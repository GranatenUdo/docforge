"""Tests for the MCP server tool-level safety-net timeout and stderr diagnostics.

The MCP `search_documentation` and `list_sources` tools have inner timeouts
(httpx, asyncio.wait_for for auth) but the user has observed the MCP "running
into a timeout and continuing to wait instead of terminating the request" —
i.e., an inner coro not honoring cancellation. These tests cover the outer
`asyncio.timeout(60s)` safety net that strictly bounds wall-clock time per
tool call, plus the stderr breadcrumbs that identify which phase stalled.
"""

from __future__ import annotations

import asyncio
import re

import pytest


@pytest.fixture(autouse=True)
def _no_backoff_sleep(monkeypatch):
    """Replace asyncio.sleep with a no-op (mirrors test_remote_client.py)."""

    async def _fast(_delay):
        return None

    monkeypatch.setattr("docforge.remote_client.asyncio.sleep", _fast)


@pytest.mark.asyncio
async def test_tool_timeout_fires_on_hung_inner_call(monkeypatch, capsys):
    """If backend.search hangs past the safety-net budget, the tool wrapper
    must return a clear safety-net error string within the (shortened) budget
    rather than waiting for the inner coro to finish on its own."""
    # Shrink the safety-net budget so the test runs in well under a second.
    monkeypatch.setattr("docforge.remote_client._TOOL_TIMEOUT_S", 0.1)

    from docforge.remote_client import _run_tool_with_timeout

    async def hangs_forever():
        await asyncio.Future()  # never resolves
        return "never-returned"

    start = asyncio.get_event_loop().time()
    result = await _run_tool_with_timeout("search_documentation", hangs_forever)
    elapsed = asyncio.get_event_loop().time() - start

    assert isinstance(result, str)
    assert "safety-net timeout" in result
    assert "search_documentation" in result
    # The wrapper must NOT wait longer than ~2x the budget (some scheduler slop).
    assert elapsed < 1.0, f"safety-net fired too late: {elapsed:.3f}s"


@pytest.mark.asyncio
async def test_tool_completes_within_timeout(monkeypatch, capsys):
    """When the inner coro finishes quickly, the wrapper returns its result
    unchanged and emits a 'done in <ms>' stderr breadcrumb."""
    monkeypatch.setattr("docforge.remote_client._TOOL_TIMEOUT_S", 60.0)

    from docforge.remote_client import _run_tool_with_timeout

    async def quick():
        return "the-actual-result"

    result = await _run_tool_with_timeout("search_documentation", quick)
    assert result == "the-actual-result"

    err = capsys.readouterr().err
    assert "tool=search_documentation start" in err
    assert re.search(r"tool=search_documentation done in \d+ms", err)


@pytest.mark.asyncio
async def test_stderr_logs_include_phase_markers(monkeypatch, capsys):
    """End-to-end check: an MCP tool call should emit start + done breadcrumbs
    on stderr. Captures both tool-level and request-level breadcrumbs by
    routing the call through a real RemoteBackend with a MockTransport."""
    import httpx

    monkeypatch.delenv("DOCFORGE_USER", raising=False)
    monkeypatch.delenv("DOCFORGE_TEAM", raising=False)
    monkeypatch.delenv("DOCFORGE_AREA", raising=False)

    from docforge.remote_client import NoneAuth, RemoteBackend, _run_tool_with_timeout

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"results": [], "query": "x", "count": 0})

    transport = httpx.MockTransport(handler)
    backend = RemoteBackend(url="https://api.example.com", auth=NoneAuth(), transport=transport)
    try:
        await _run_tool_with_timeout(
            "search_documentation",
            lambda: backend.search(query="x", limit=5),
        )
    finally:
        await backend.aclose()

    err = capsys.readouterr().err
    # Tool-level breadcrumbs.
    assert "tool=search_documentation start" in err
    assert re.search(r"tool=search_documentation done in \d+ms", err)
    # Request-level breadcrumbs.
    assert "request POST /search start" in err
    assert re.search(r"request POST /search -> 200 in \d+ms", err)


@pytest.mark.asyncio
async def test_auth_logs_token_acquisition(monkeypatch, capsys):
    """AzureAuth.headers() emits before/after breadcrumbs with elapsed time."""
    import sys
    from unittest.mock import AsyncMock, MagicMock

    monkeypatch.setenv("DOCFORGE_AUDIENCE", "api://test-audience")

    fake_token = MagicMock(token="fake-jwt")
    fake_credential = MagicMock()
    fake_credential.get_token = AsyncMock(return_value=fake_token)

    fake_aio_module = MagicMock()
    fake_aio_module.DefaultAzureCredential = MagicMock(return_value=fake_credential)
    monkeypatch.setitem(sys.modules, "azure.identity.aio", fake_aio_module)

    from docforge.remote_client import AzureAuth

    auth = AzureAuth()
    await auth.headers()

    err = capsys.readouterr().err
    assert "auth requesting token" in err
    assert re.search(r"auth token acquired in \d+ms", err)
