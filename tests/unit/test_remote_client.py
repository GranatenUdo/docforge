"""Tests for the remote-API MCP client mode."""
from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_none_auth_returns_empty_headers():
    from docforge.remote_client import NoneAuth
    auth = NoneAuth()
    headers = await auth.headers()
    assert headers == {}
