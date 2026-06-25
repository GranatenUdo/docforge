"""MCP server that proxies tool calls to a remote docforge search-api.

Used by `docforge serve --remote-api $URL --auth ...`. See the
2026-05-08-docforge-remote-api-mode-design.md spec for the full design.
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
import time
from collections.abc import Awaitable, Callable
from enum import Enum
from typing import Protocol

import httpx
from fastmcp import FastMCP

from docforge.formatters import format_search_results_markdown

logger = logging.getLogger(__name__)


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
        # DefaultAzureCredential walks several credential providers (env,
        # managed identity, CLI, VS Code, etc.); if any one stalls — e.g.,
        # a corrupted CLI token cache or a network glitch during MSAL
        # discovery — the get_token coroutine can hang indefinitely. 15s
        # is well past the cold-network worst case (~3s for CLI cache load)
        # but short enough that the user sees a clear error instead of
        # an apparently-hung MCP session.
        t0 = time.perf_counter()
        logger.info("auth requesting token")
        try:
            token = await asyncio.wait_for(
                self._credential.get_token(f"{self._audience}/.default"),
                timeout=15.0,
            )
        except asyncio.TimeoutError:
            logger.warning("auth TIMEOUT after %dms", int((time.perf_counter() - t0) * 1000))
            raise
        except Exception as e:
            logger.warning(
                "auth FAILED after %dms: %s",
                int((time.perf_counter() - t0) * 1000),
                type(e).__name__,
            )
            raise
        logger.info("auth token acquired in %dms", int((time.perf_counter() - t0) * 1000))
        return {"Authorization": f"Bearer {token.token}"}


class _StartupFailedAuth:
    """Substitute auth provider used when the real provider can't be constructed
    (missing `[azure]` extra, unset DOCFORGE_AUDIENCE/DOCFORGE_API_TOKEN, etc.).

    Lets `serve --remote-api` finish the MCP `initialize` handshake so `/mcp`
    shows the server as connected instead of dying with an opaque -32000 process
    crash. The real, actionable error is surfaced as a tool RESULT on the first
    search/list call: RemoteBackend._request awaits headers(), catches the
    exception, and returns it as `"Auth provider error: …"`.
    """

    def __init__(self, auth_name: object, error: Exception) -> None:
        self._message = (
            f"docforge could not initialize '{auth_name}' authentication: {error} "
            "Fix the above, then restart Claude Code (or run /mcp -> Reconnect)."
        )

    async def headers(self) -> dict[str, str]:
        raise RuntimeError(self._message)


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


# Read timeout (seconds) for remote /search calls. Long enough to cover an
# Azure Container Apps cold start (~22s observed); short enough that a stuck
# upstream surfaces a clear error instead of hanging the MCP session.
_READ_TIMEOUT_S = 30.0


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
                timeout=httpx.Timeout(connect=10.0, read=_READ_TIMEOUT_S, write=10.0, pool=5.0),
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

        Retries once on 5xx with a 2-second backoff — cold-start 502/503 from
        Azure Container Apps ingress is the dominant transient failure. 4xx
        responses and timeouts are NOT retried: 4xx is caller-fault, and a
        timeout has already burned the configured budget.

        Returns the Response on 2xx; an already-formatted error string otherwise.
        """
        try:
            headers = await self._auth.headers()
        except Exception as e:
            return f"Auth provider error: {e}"

        client = await self._ensure_client()

        async def _attempt() -> httpx.Response | str:
            t0 = time.perf_counter()
            logger.info("request %s %s start", method, path)
            try:
                resp = await client.request(
                    method, f"{self._url}{path}", json=json, headers=headers
                )
            except httpx.ConnectError:
                logger.warning(
                    "request %s %s CONNECT_ERROR after %dms",
                    method,
                    path,
                    int((time.perf_counter() - t0) * 1000),
                )
                return f"Could not reach remote API at {self._url}."
            except httpx.ReadTimeout:
                logger.warning(
                    "request %s %s READ_TIMEOUT after %dms",
                    method,
                    path,
                    int((time.perf_counter() - t0) * 1000),
                )
                return (
                    f"DocForge /search timed out after {int(_READ_TIMEOUT_S)}s "
                    f"(Container App may be cold-starting; retry in 30s)."
                )
            except httpx.HTTPError as e:
                logger.warning(
                    "request %s %s HTTP_ERROR after %dms: %s",
                    method,
                    path,
                    int((time.perf_counter() - t0) * 1000),
                    type(e).__name__,
                )
                return f"Remote API error: {e}"

            logger.info(
                "request %s %s -> %d in %dms",
                method,
                path,
                resp.status_code,
                int((time.perf_counter() - t0) * 1000),
            )
            if resp.status_code == 401:
                return "Auth failed (401). Check DOCFORGE_API_URL and the --auth provider."
            if 500 <= resp.status_code < 600:
                return resp  # caller decides: retry or surface
            if resp.status_code != 200:
                return f"Remote API returned {resp.status_code}: {resp.text[:200]}"
            return resp

        first = await _attempt()
        if isinstance(first, httpx.Response) and first.status_code == 200:
            return first
        if isinstance(first, httpx.Response) and 500 <= first.status_code < 600:
            # 5xx: backoff briefly, then retry once
            await asyncio.sleep(2.0)
            second = await _attempt()
            if isinstance(second, httpx.Response) and second.status_code == 200:
                return second
            if isinstance(second, httpx.Response):
                return f"Remote API error ({second.status_code}). Try again in a moment."
            return second  # already-formatted error string
        # _attempt only returns Response for 200 or 5xx; both handled above.
        # Anything else is already a formatted error string.
        return first

    async def search(self, *, query: str, limit: int = 10) -> str:
        """Search the remote API and return Markdown-formatted results."""
        body: dict[str, object] = {"query": query, "limit": limit}
        body.update(self._identity_body())
        logger.info("search: about to call _request")
        result = await self._request("POST", "/search", json=body)
        logger.info("search: _request returned (type=%s)", type(result).__name__)
        if isinstance(result, str):
            return result

        data = result.json()
        results = data.get("results", [])
        logger.info("search: JSON parsed (%d results), formatting", len(results))
        out = format_search_results_markdown(results)
        logger.info("search: formatted markdown (%d chars), returning", len(out))
        return out

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
DEFAULT_TOOL_DESCRIPTION = (
    "Search across indexed documentation from Confluence pages and git repos."
)


# Hard outer bound on a single MCP tool call, in seconds. Sized to comfortably
# cover the worst inner budget — Azure token mint (15s) + first httpx read
# (30s) + retry backoff (2s) + second httpx read (30s) ≈ 77s but in practice
# only one of token / read can hit its full budget. 60s leaves headroom for
# scheduler slop while still guaranteeing the caller gets a clear error well
# inside any client-side MCP timeout. If any inner coro fails to honor
# cancellation (Azure SDK token refresh, FastMCP stdio, httpx pool), this
# outer asyncio.timeout still fires and returns a diagnostic string.
_TOOL_TIMEOUT_S = 60.0


async def _run_tool_with_timeout(name: str, coro_fn: Callable[[], Awaitable[str]]) -> str:
    """Wrap an MCP tool body in a hard outer timeout + log breadcrumbs.

    `coro_fn` is a no-arg callable that returns a fresh coroutine each call.
    We deliberately accept a factory (not an already-awaited coroutine) so
    `asyncio.timeout()` can cancel a freshly-started task — passing an
    already-created coroutine would mean we couldn't restart it on retry
    and could leak references on cancellation.

    On timeout the inner task is cancelled and we return a clear diagnostic
    string instead of raising, since FastMCP tool handlers are expected to
    return strings.
    """
    t0 = time.perf_counter()
    logger.info("tool=%s start", name)
    try:
        async with asyncio.timeout(_TOOL_TIMEOUT_S):
            result = await coro_fn()
        logger.info("tool=%s done in %dms", name, int((time.perf_counter() - t0) * 1000))
        return result
    except asyncio.TimeoutError:
        logger.warning(
            "tool=%s HIT SAFETY-NET TIMEOUT after %dms",
            name,
            int((time.perf_counter() - t0) * 1000),
        )
        return (
            f"docforge tool '{name}' hit the {int(_TOOL_TIMEOUT_S)}s safety-net timeout. "
            "An inner call hung without honoring cancellation. "
            "Check the MCP server stderr logs for the LAST PHASE REACHED. "
            "Common causes: Azure auth credential cache corruption, "
            "Container App cold start during 5xx retry, FastMCP stdio deadlock."
        )


def build_remote_mcp(
    *,
    url: str,
    auth_name: AuthName | str = AuthName.none,
    instructions: str | None = None,
    tool_description: str | None = None,
) -> FastMCP:
    """Construct (but do not run) the remote-backed MCP server.

    `instructions` and `tool_description` default to the engine's built-in
    generic text when None; deployments inject their own via Settings.
    Returned without running so the wiring is unit-testable."""
    try:
        auth = make_auth_provider(auth_name)
    except Exception as e:  # noqa: BLE001 — any construction failure must degrade
        # to a connected-but-degraded server, not a startup crash (-32000).
        logger.warning("auth provider %r could not be constructed: %s", auth_name, e)
        auth = _StartupFailedAuth(auth_name, e)
    backend = RemoteBackend(url=url, auth=auth)
    mcp = FastMCP("docforge", instructions=instructions or INSTRUCTIONS)

    @mcp.tool(description=tool_description or DEFAULT_TOOL_DESCRIPTION)
    async def search_documentation(query: str, limit: int = 10) -> str:
        return await _run_tool_with_timeout(
            "search_documentation",
            lambda: backend.search(query=query, limit=limit),
        )

    @mcp.tool()
    async def list_sources() -> str:
        """List all documentation sources currently indexed."""
        return await _run_tool_with_timeout(
            "list_sources",
            lambda: backend.list_sources(),
        )

    return mcp


def run_remote_mcp(
    *,
    url: str,
    auth_name: AuthName | str = AuthName.none,
    instructions: str | None = None,
    tool_description: str | None = None,
) -> None:
    """Run an MCP server proxying tool calls to a remote docforge search-api."""
    try:
        mcp = build_remote_mcp(
            url=url,
            auth_name=auth_name,
            instructions=instructions,
            tool_description=tool_description,
        )
    except Exception as e:  # noqa: BLE001 — surface a clear diagnostic, then re-raise
        print(
            f"docforge serve failed to start: {type(e).__name__}: {e}\n"
            "This usually means a bad docforge.yml/.env or a packaging problem. "
            "Verify `docforge --version`, then reinstall: "
            'pip install --upgrade "docforge-cli[azure]".',
            file=sys.stderr,
        )
        raise
    mcp.run()
