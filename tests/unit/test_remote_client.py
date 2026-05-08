"""Tests for the remote-API MCP client mode."""
from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_none_auth_returns_empty_headers():
    from docforge.remote_client import NoneAuth
    auth = NoneAuth()
    headers = await auth.headers()
    assert headers == {}


@pytest.mark.asyncio
async def test_bearer_auth_returns_authorization_header(monkeypatch):
    monkeypatch.setenv("DOCFORGE_API_TOKEN", "abc123")
    from docforge.remote_client import BearerAuth
    auth = BearerAuth()
    headers = await auth.headers()
    assert headers == {"Authorization": "Bearer abc123"}


def test_bearer_auth_raises_when_token_unset(monkeypatch):
    monkeypatch.delenv("DOCFORGE_API_TOKEN", raising=False)
    from docforge.remote_client import BearerAuth
    with pytest.raises(RuntimeError, match="DOCFORGE_API_TOKEN"):
        BearerAuth()
