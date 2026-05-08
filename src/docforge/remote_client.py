"""MCP server that proxies tool calls to a remote docforge search-api.

Used by `docforge serve --remote-api $URL --auth ...`. See the
2026-05-08-docforge-remote-api-mode-design.md spec for the full design.
"""
from __future__ import annotations

import os
from typing import Protocol


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
            raise RuntimeError(
                "BearerAuth requires DOCFORGE_API_TOKEN env var to be set."
            )
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
            raise ImportError(
                "Azure auth requires `pip install docforge-cli[azure]`."
            ) from e

        audience = os.environ.get("DOCFORGE_AUDIENCE", "").strip()
        if not audience:
            raise RuntimeError(
                "AzureAuth requires DOCFORGE_AUDIENCE env var to be set."
            )
        self._audience = audience
        self._credential = DefaultAzureCredential()

    async def headers(self) -> dict[str, str]:
        token = await self._credential.get_token(f"{self._audience}/.default")
        return {"Authorization": f"Bearer {token.token}"}


def make_auth_provider(name: str) -> AuthProvider:
    """Return an AuthProvider instance for the given name."""
    if name == "none":
        return NoneAuth()
    if name == "bearer":
        return BearerAuth()
    if name == "azure":
        return AzureAuth()
    raise ValueError(
        f"Unknown auth provider: {name!r}. Valid: none, bearer, azure."
    )
