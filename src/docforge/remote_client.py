"""MCP server that proxies tool calls to a remote docforge search-api.

Used by `docforge serve --remote-api $URL --auth ...`. See the
2026-05-08-docforge-remote-api-mode-design.md spec for the full design.
"""

from __future__ import annotations

import asyncio  # noqa: F401  # used by Tasks 2 & 3 (retry, token-mint timeout)
import os
from enum import Enum
from typing import Protocol

import httpx
from fastmcp import FastMCP


class AuthName(str, Enum):
    """Selectable auth providers for the --remote-api mode."""

    none = "none"
    bearer = "bearer"
    azure = "azure"


class AuthProvider(Protocol):
    """Async source of HTTP headers attached to each remote request."""

    async def headers(self) -> dict[str, str]: ...


class NoneAuth:
    """No-op auth provider. Returns no headers."""

    async def headers(self) -> dict[str, str]:
        return {}


class BearerAuth:
    """Static Bearer token from DOCFORGE_API_TOKEN env var."""

    def __init__(self) -> None:
        token = os.environ.get("DOCFORGE_API_TOKEN", "").strip()
        if not token:
            raise RuntimeError("BearerAuth requires DOCFORGE_API_TOKEN env var to be set.")
        self._token = token

    async def headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._token}"}


class AzureAuth:
    """Entra Bearer token via DefaultAzureCredential.

    Requires `pip install docforge-cli[azure]`. Reads target audience
    from DOCFORGE_AUDIENCE env var.
    """

    def __init__(self) -> None:
        try:
            from azure.identity.aio import DefaultAzureCredential
        except ImportError as e:
            raise ImportError("Azure auth requires `pip install docforge-cli[azure]`.") from e

        audience = os.environ.get("DOCFORGE_AUDIENCE", "").strip()
        if not audience:
            raise RuntimeError("AzureAuth requires DOCFORGE_AUDIENCE env var to be set.")
        self._audience = audience
        self._credential = DefaultAzureCredential()

    async def headers(self) -> dict[str, str]:
        token = await self._credential.get_token(f"{self._audience}/.default")
        return {"Authorization": f"Bearer {token.token}"}


def make_auth_provider(name: AuthName | str) -> AuthProvider:
    """Return an AuthProvider instance for the given name."""
    try:
        name = AuthName(name) if isinstance(name, str) else name
    except ValueError as e:
        raise ValueError(f"Unknown auth provider: {name!r}. Valid: none, bearer, azure.") from e
    if name is AuthName.none:
        return NoneAuth()
    if name is AuthName.bearer:
        return BearerAuth()
    if name is AuthName.azure:
        return AzureAuth()
    raise ValueError(f"Unknown auth provider: {name!r}.")


class RemoteBackend:
    """Proxy to a remote docforge search-api over HTTP."""

    def __init__(
        self,
        *,
        url: str,
        auth: AuthProvider,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._url = url.rstrip("/")
        self._auth = auth
        self._transport = transport
        self._client: httpx.AsyncClient | None = None

    async def _ensure_client(self) -> httpx.AsyncClient:
        if self._client is None:
            # Split timeouts let a connect stall (DNS, TCP, TLS) fail at 10s
            # without consuming the 30s read budget — needed because Azure
            # Container Apps cold-start can take ~22s of read time once
            # connected. Without this split, a hung connect would burn the
            # entire 30s window before the user sees an error.
            self._client = httpx.AsyncClient(
                transport=self._transport,
                timeout=httpx.Timeout(connect=10.0, read=30.0, write=10.0, pool=5.0),
            )
        return self._client

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    def _identity_body(self) -> dict[str, str]:
        out: dict[str, str] = {}
        for env_var, body_key in (
            ("DOCFORGE_USER", "user_name"),
            ("DOCFORGE_TEAM", "team_name"),
            ("DOCFORGE_AREA", "area_name"),
        ):
            val = os.environ.get(env_var, "").strip()
            if val:
                out[body_key] = val
        return out

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json: dict[str, object] | None = None,
    ) -> httpx.Response | str:
        """Perform an HTTP request with auth and uniform error handling.

        Returns the Response on 2xx; an already-formatted error string otherwise.
        """
        try:
            headers = await self._auth.headers()
        except Exception as e:
            return f"Auth provider error: {e}"

        client = await self._ensure_client()
        try:
            resp = await client.request(method, f"{self._url}{path}", json=json, headers=headers)
        except httpx.ConnectError:
            return f"Could not reach remote API at {self._url}."
        except httpx.HTTPError as e:
            return f"Remote API error: {e}"

        if resp.status_code == 401:
            return "Auth failed (401). Check DOCFORGE_API_URL and the --auth provider."
        if 500 <= resp.status_code < 600:
            return f"Remote API error ({resp.status_code}). Try again in a moment."
        if resp.status_code != 200:
            return f"Remote API returned {resp.status_code}: {resp.text[:200]}"
        return resp

    async def search(self, *, query: str, limit: int = 5) -> str:
        """Search the remote API and return Markdown-formatted results."""
        body: dict[str, object] = {"query": query, "limit": limit}
        body.update(self._identity_body())
        result = await self._request("POST", "/search", json=body)
        if isinstance(result, str):
            return result

        from docforge.mcp_server import format_search_results_markdown

        data = result.json()
        return format_search_results_markdown(data.get("results", []))

    async def list_sources(self) -> str:
        """List indexed sources from the remote API."""
        result = await self._request("GET", "/sources")
        if isinstance(result, str):
            return result

        data = result.json()
        sources = data.get("sources", [])
        if not sources:
            return "No sources indexed."

        lines = [f"**{data.get('count', len(sources))} indexed sources:**\n"]
        for s in sources:
            lines.append(f"- **{s['title']}** ({s['chunk_count']} chunks, {s['status']})")
        return "\n".join(lines)


INSTRUCTIONS = (
    "Search across your team's indexed documentation including team responsibilities, "
    "coding guidelines, architecture standards, and cross-team interfaces. "
    "Use the search_documentation tool when you need information about other teams, "
    "shared coding practices, or organizational knowledge."
)


def run_remote_mcp(*, url: str, auth_name: AuthName | str = AuthName.none) -> None:
    """Run an MCP server proxying tool calls to a remote docforge search-api."""
    auth = make_auth_provider(auth_name)
    backend = RemoteBackend(url=url, auth=auth)
    mcp = FastMCP("docforge", instructions=INSTRUCTIONS)

    @mcp.tool()
    async def search_documentation(query: str, limit: int = 5) -> str:
        """Search across indexed documentation from Confluence pages and git repos."""
        return await backend.search(query=query, limit=limit)

    @mcp.tool()
    async def list_sources() -> str:
        """List all documentation sources currently indexed."""
        return await backend.list_sources()

    mcp.run()
