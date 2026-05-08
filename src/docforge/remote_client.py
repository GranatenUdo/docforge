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
