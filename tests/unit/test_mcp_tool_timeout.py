"""Tests for the MCP server tool-level safety-net timeout and logging diagnostics.

The MCP `search_documentation` and `list_sources` tools have inner timeouts
(httpx, asyncio.wait_for for auth) but the user has observed the MCP "running
into a timeout and continuing to wait instead of terminating the request" —
i.e., an inner coro not honoring cancellation. These tests cover the outer
`asyncio.timeout(60s)` safety net that strictly bounds wall-clock time per
tool call, plus the logger breadcrumbs that identify which phase stalled.
"""

from __future__ import annotations

import asyncio
import logging
import re

import pytest


@pytest.mark.asyncio
async def test_tool_timeout_fires_on_hung_inner_call(monkeypatch):
    """If backend.search hangs past the safety-net budget, the tool wrapper
    must return a clear safety-net error string within the (shortened) budget
    rather than waiting for the inner coro to finish on its own."""
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
    assert elapsed < 1.0, f"safety-net fired too late: {elapsed:.3f}s"


@pytest.mark.asyncio
async def test_tool_completes_within_timeout(monkeypatch, caplog):
    """When the inner coro finishes quickly, the wrapper returns its result
    unchanged and emits a 'done in <ms>' log breadcrumb."""
    monkeypatch.setattr("docforge.remote_client._TOOL_TIMEOUT_S", 60.0)
    caplog.set_level(logging.INFO, logger="docforge.remote_client")

    from docforge.remote_client import _run_tool_with_timeout

    async def quick():
        return "the-actual-result"

    result = await _run_tool_with_timeout("search_documentation", quick)
    assert result == "the-actual-result"

    messages = [r.getMessage() for r in caplog.records]
    assert any("tool=search_documentation start" in m for m in messages)
    assert any(re.search(r"tool=search_documentation done in \d+ms", m) for m in messages)


@pytest.mark.asyncio
async def test_log_breadcrumbs_include_phase_markers(monkeypatch, caplog):
    """End-to-end check: an MCP tool call should emit start + done breadcrumbs
    via the logger. Captures both tool-level and request-level breadcrumbs by
    routing the call through a real RemoteBackend with a MockTransport."""
    import httpx

    monkeypatch.delenv("DOCFORGE_USER", raising=False)
    monkeypatch.delenv("DOCFORGE_TEAM", raising=False)
    monkeypatch.delenv("DOCFORGE_AREA", raising=False)
    caplog.set_level(logging.INFO, logger="docforge.remote_client")

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

    messages = [r.getMessage() for r in caplog.records]
    assert any("tool=search_documentation start" in m for m in messages)
    assert any(re.search(r"tool=search_documentation done in \d+ms", m) for m in messages)
    assert any("request POST /search start" in m for m in messages)
    assert any(re.search(r"request POST /search -> 200 in \d+ms", m) for m in messages)


# Note: auth-phase logging is exercised live during the integration suite
# (test_remote_client.py covers AzureAuth init + headers paths). A unit-test
# variant here was tried but its monkeypatch on sys.modules['azure.identity.aio']
# corrupted the test_cli.py CliRunner state in CI (Python 3.12); removed in favor
# of the live coverage.
