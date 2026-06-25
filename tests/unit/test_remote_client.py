"""Tests for the remote-API MCP client mode."""

from __future__ import annotations

import json
import sys

import httpx
import pytest


@pytest.fixture(autouse=True)
def _no_backoff_sleep(monkeypatch):
    """Replace asyncio.sleep with a no-op for every test in this file.

    The retry logic added in Task 2 (remote_client._request) calls
    asyncio.sleep(2.0) between attempts on 5xx. Real sleeps in unit tests
    just slow CI down. Tests that explicitly want to assert backoff
    behavior can still inspect call_count on the MockTransport handler.
    """

    async def _fast(_delay):
        return None

    monkeypatch.setattr("docforge.remote_client.asyncio.sleep", _fast)


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


def test_azure_auth_raises_when_audience_unset(monkeypatch):
    monkeypatch.delenv("DOCFORGE_AUDIENCE", raising=False)
    from docforge.remote_client import AzureAuth

    with pytest.raises(RuntimeError, match="DOCFORGE_AUDIENCE"):
        AzureAuth()


def test_azure_auth_raises_when_extra_not_installed(monkeypatch):
    """If azure.identity.aio isn't importable, AzureAuth raises ImportError."""
    monkeypatch.setenv("DOCFORGE_AUDIENCE", "api://test-audience")
    monkeypatch.setitem(sys.modules, "azure.identity.aio", None)
    from docforge.remote_client import AzureAuth

    with pytest.raises(ImportError, match=r"\[azure\]"):
        AzureAuth()


@pytest.mark.asyncio
async def test_azure_auth_returns_bearer_from_credential(monkeypatch):
    monkeypatch.setenv("DOCFORGE_AUDIENCE", "api://test-audience")

    from unittest.mock import AsyncMock, MagicMock

    fake_token = MagicMock(token="fake-jwt-token")
    fake_credential = MagicMock()
    fake_credential.get_token = AsyncMock(return_value=fake_token)

    fake_aio_module = MagicMock()
    fake_aio_module.DefaultAzureCredential = MagicMock(return_value=fake_credential)
    monkeypatch.setitem(sys.modules, "azure.identity.aio", fake_aio_module)

    from docforge.remote_client import AzureAuth

    auth = AzureAuth()
    headers = await auth.headers()
    assert headers == {"Authorization": "Bearer fake-jwt-token"}
    fake_credential.get_token.assert_awaited_once_with("api://test-audience/.default")


def test_make_auth_provider_none():
    from docforge.remote_client import NoneAuth, make_auth_provider

    p = make_auth_provider("none")
    assert isinstance(p, NoneAuth)


def test_make_auth_provider_bearer(monkeypatch):
    monkeypatch.setenv("DOCFORGE_API_TOKEN", "x")
    from docforge.remote_client import BearerAuth, make_auth_provider

    p = make_auth_provider("bearer")
    assert isinstance(p, BearerAuth)


def test_make_auth_provider_unknown_raises():
    from docforge.remote_client import make_auth_provider

    with pytest.raises(ValueError, match="Unknown auth provider"):
        make_auth_provider("oauth")


@pytest.mark.asyncio
async def test_remote_backend_search_happy_path(monkeypatch):
    """search() POSTs to /search and formats the response as Markdown."""
    monkeypatch.delenv("DOCFORGE_USER", raising=False)
    monkeypatch.delenv("DOCFORGE_TEAM", raising=False)
    monkeypatch.delenv("DOCFORGE_AREA", raising=False)

    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "results": [
                    {
                        "text": "Hello world",
                        "section_title": "Intro",
                        "source_title": "Test Page",
                        "source_url": "https://example.com/page",
                        "source_tags": ["org"],
                        "similarity": 0.85,
                    },
                ],
                "query": "hello",
                "count": 1,
            },
        )

    transport = httpx.MockTransport(handler)
    from docforge.remote_client import NoneAuth, RemoteBackend

    backend = RemoteBackend(
        url="https://api.example.com",
        auth=NoneAuth(),
        transport=transport,
    )
    result = await backend.search(query="hello", limit=5)

    assert "Test Page" in result
    assert "**Result 1**" in result
    assert "**Result 1** -- Test Page" in result
    assert "Tags: org" in result
    assert captured["url"] == "https://api.example.com/search"
    assert captured["body"] == {"query": "hello", "limit": 5}


@pytest.mark.asyncio
async def test_remote_backend_search_includes_set_identity(monkeypatch):
    monkeypatch.setenv("DOCFORGE_USER", "tobias.ens")
    monkeypatch.setenv("DOCFORGE_TEAM", "ccl")
    monkeypatch.setenv("DOCFORGE_AREA", "cloud")

    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json={"results": [], "query": "x", "count": 0})

    transport = httpx.MockTransport(handler)
    from docforge.remote_client import NoneAuth, RemoteBackend

    backend = RemoteBackend(url="https://api.example.com", auth=NoneAuth(), transport=transport)
    await backend.search(query="x", limit=5)

    assert captured["body"] == {
        "query": "x",
        "limit": 5,
        "user_name": "tobias.ens",
        "team_name": "ccl",
        "area_name": "cloud",
    }


@pytest.mark.asyncio
async def test_remote_backend_search_empty_results_no_ingest_hint(monkeypatch):
    """Empty-result message must not say 'run docforge ingest' — remote users can't."""
    monkeypatch.delenv("DOCFORGE_USER", raising=False)
    monkeypatch.delenv("DOCFORGE_TEAM", raising=False)
    monkeypatch.delenv("DOCFORGE_AREA", raising=False)

    transport = httpx.MockTransport(
        lambda req: httpx.Response(200, json={"results": [], "query": "x", "count": 0})
    )
    from docforge.remote_client import NoneAuth, RemoteBackend

    backend = RemoteBackend(url="https://api.example.com", auth=NoneAuth(), transport=transport)
    result = await backend.search(query="x", limit=5)

    assert "No documentation found" in result
    assert "ingest" not in result.lower()


@pytest.mark.asyncio
async def test_remote_backend_search_401_returns_friendly_error(monkeypatch):
    monkeypatch.delenv("DOCFORGE_USER", raising=False)
    transport = httpx.MockTransport(
        lambda req: httpx.Response(401, json={"detail": "Unauthorized"})
    )
    from docforge.remote_client import NoneAuth, RemoteBackend

    backend = RemoteBackend(url="https://api.example.com", auth=NoneAuth(), transport=transport)
    result = await backend.search(query="x", limit=5)
    assert "Auth failed" in result
    assert "401" in result


@pytest.mark.asyncio
async def test_remote_backend_search_500_returns_friendly_error(monkeypatch):
    monkeypatch.delenv("DOCFORGE_USER", raising=False)
    transport = httpx.MockTransport(
        lambda req: httpx.Response(500, json={"detail": "Server error"})
    )
    from docforge.remote_client import NoneAuth, RemoteBackend

    backend = RemoteBackend(url="https://api.example.com", auth=NoneAuth(), transport=transport)
    result = await backend.search(query="x", limit=5)
    assert "Remote API error" in result
    assert "(500)" in result


@pytest.mark.asyncio
async def test_remote_backend_search_network_error_returns_friendly_error(monkeypatch):
    monkeypatch.delenv("DOCFORGE_USER", raising=False)

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    transport = httpx.MockTransport(handler)
    from docforge.remote_client import NoneAuth, RemoteBackend

    backend = RemoteBackend(url="https://api.example.com", auth=NoneAuth(), transport=transport)
    result = await backend.search(query="x", limit=5)
    assert "Could not reach" in result
    assert "https://api.example.com" in result


@pytest.mark.asyncio
async def test_remote_backend_list_sources_happy_path(monkeypatch):
    monkeypatch.setenv("DOCFORGE_USER", "tobias.ens")  # should NOT appear in body

    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["method"] = request.method
        captured["body"] = request.content
        return httpx.Response(
            200,
            json={
                "sources": [
                    {"title": "Test Page", "chunk_count": 5, "status": "active"},
                ],
                "count": 1,
            },
        )

    transport = httpx.MockTransport(handler)
    from docforge.remote_client import NoneAuth, RemoteBackend

    backend = RemoteBackend(url="https://api.example.com", auth=NoneAuth(), transport=transport)
    result = await backend.list_sources()

    assert "1 indexed sources" in result
    assert "Test Page" in result
    assert "5 chunks" in result
    assert captured["url"] == "https://api.example.com/sources"
    assert captured["method"] == "GET"
    assert captured["body"] == b""


def test_run_remote_mcp_constructs_components(monkeypatch):
    """run_remote_mcp wires AuthProvider, RemoteBackend, FastMCP without crashing."""
    monkeypatch.delenv("DOCFORGE_API_TOKEN", raising=False)

    constructed = {}

    class FakeMCP:
        def __init__(self, name: str, instructions: str = "") -> None:
            constructed["name"] = name
            constructed["tools"] = []

        def tool(self, **kwargs):
            def deco(fn):
                constructed["tools"].append(fn.__name__)
                return fn

            return deco

        def run(self) -> None:
            constructed["ran"] = True

    monkeypatch.setattr("docforge.remote_client.FastMCP", FakeMCP)

    from docforge.remote_client import run_remote_mcp

    run_remote_mcp(url="https://api.example.com", auth_name="none")

    assert constructed["name"] == "docforge"
    assert "search_documentation" in constructed["tools"]
    assert "list_sources" in constructed["tools"]
    assert constructed["ran"] is True


@pytest.mark.asyncio
async def test_ensure_client_uses_split_timeouts():
    """RemoteBackend should configure connect/read/write/pool timeouts separately
    so a connect stall fails fast at 10s without blocking the 30s read budget."""
    from docforge.remote_client import NoneAuth, RemoteBackend

    backend = RemoteBackend(url="https://example.test", auth=NoneAuth())
    client = await backend._ensure_client()
    try:
        timeout = client.timeout
        assert timeout.connect == 10.0
        assert timeout.read == 30.0
        assert timeout.write == 10.0
        assert timeout.pool == 5.0
    finally:
        await backend.aclose()


@pytest.mark.asyncio
async def test_request_retries_once_on_5xx_then_succeeds():
    """A transient 503 from a cold-starting Container App should be retried
    exactly once with a short backoff. Second response succeeds → caller gets
    the success response, not the 503 error string."""
    from docforge.remote_client import NoneAuth, RemoteBackend

    call_count = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        call_count["n"] += 1
        if call_count["n"] == 1:
            return httpx.Response(503, text="cold start in progress")
        return httpx.Response(200, json={"results": [], "query": "q", "count": 0})

    transport = httpx.MockTransport(handler)
    backend = RemoteBackend(url="https://example.test", auth=NoneAuth(), transport=transport)

    try:
        result = await backend._request("POST", "/search", json={"query": "q"})
    finally:
        await backend.aclose()

    assert call_count["n"] == 2, f"expected exactly 2 calls (1 retry), got {call_count['n']}"
    assert isinstance(result, httpx.Response), (
        f"expected Response, got {type(result).__name__}: {result}"
    )
    assert result.status_code == 200


@pytest.mark.asyncio
async def test_request_does_not_retry_on_5xx_when_second_call_also_fails():
    """If both attempts fail, return the error string after the second attempt
    (do not retry indefinitely)."""
    from docforge.remote_client import NoneAuth, RemoteBackend

    call_count = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        call_count["n"] += 1
        return httpx.Response(502, text="bad gateway")

    transport = httpx.MockTransport(handler)
    backend = RemoteBackend(url="https://example.test", auth=NoneAuth(), transport=transport)

    try:
        result = await backend._request("POST", "/search", json={"query": "q"})
    finally:
        await backend.aclose()

    assert call_count["n"] == 2, f"expected exactly 2 calls (1 retry), got {call_count['n']}"
    assert isinstance(result, str)
    assert "502" in result


@pytest.mark.asyncio
async def test_request_does_not_retry_on_4xx():
    """4xx errors are caller-fault — auth, validation, etc. — and must fail
    immediately. Retrying is wasted work and would double the latency for
    every misconfigured client."""
    from docforge.remote_client import NoneAuth, RemoteBackend

    call_count = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        call_count["n"] += 1
        return httpx.Response(401, text="unauthorized")

    transport = httpx.MockTransport(handler)
    backend = RemoteBackend(url="https://example.test", auth=NoneAuth(), transport=transport)

    try:
        result = await backend._request("POST", "/search", json={"query": "q"})
    finally:
        await backend.aclose()

    assert call_count["n"] == 1, "401 must not be retried"
    assert isinstance(result, str)
    assert "Auth failed" in result


@pytest.mark.asyncio
async def test_build_remote_mcp_injects_instructions_and_description():
    from fastmcp.client import Client

    from docforge.remote_client import AuthName, build_remote_mcp

    mcp = build_remote_mcp(
        url="https://example",
        auth_name=AuthName.none,
        instructions="CUSTOM INSTRUCTIONS",
        tool_description="CUSTOM TOOL DESC",
    )
    assert mcp.instructions == "CUSTOM INSTRUCTIONS"
    async with Client(mcp) as client:
        tools = await client.list_tools()
        sd = next(t for t in tools if t.name == "search_documentation")
        assert sd.description == "CUSTOM TOOL DESC"


@pytest.mark.asyncio
async def test_build_remote_mcp_uses_builtin_defaults_when_none():
    from fastmcp.client import Client

    from docforge.remote_client import (
        DEFAULT_TOOL_DESCRIPTION,
        INSTRUCTIONS,
        AuthName,
        build_remote_mcp,
    )

    mcp = build_remote_mcp(url="https://example", auth_name=AuthName.none)
    assert mcp.instructions == INSTRUCTIONS
    async with Client(mcp) as client:
        tools = await client.list_tools()
        sd = next(t for t in tools if t.name == "search_documentation")
        assert sd.description == DEFAULT_TOOL_DESCRIPTION


@pytest.mark.asyncio
async def test_azure_auth_token_mint_times_out_after_15s(monkeypatch):
    """If DefaultAzureCredential.get_token hangs (corrupted cache, network
    stall during MSAL discovery, etc.), AzureAuth.headers() must raise a
    TimeoutError after 15 seconds rather than hanging the entire MCP
    session indefinitely."""
    import asyncio
    import sys
    from unittest.mock import MagicMock

    monkeypatch.setenv("DOCFORGE_AUDIENCE", "api://test-audience")

    async def hangs_forever(_scope: str):
        await asyncio.Future()  # never resolves; wait_for will time it out
        return MagicMock(token="never-returned")

    fake_credential = MagicMock()
    fake_credential.get_token = hangs_forever

    fake_aio_module = MagicMock()
    fake_aio_module.DefaultAzureCredential = MagicMock(return_value=fake_credential)
    monkeypatch.setitem(sys.modules, "azure.identity.aio", fake_aio_module)

    # Speed up the test — patch wait_for so the 15s budget becomes ~0.05s
    original_wait_for = asyncio.wait_for

    async def fast_wait_for(awaitable, timeout):
        return await original_wait_for(awaitable, timeout=0.05)

    monkeypatch.setattr("docforge.remote_client.asyncio.wait_for", fast_wait_for)

    from docforge.remote_client import AzureAuth

    auth = AzureAuth()
    with pytest.raises(asyncio.TimeoutError):
        await auth.headers()


# --- graceful startup: server must connect even when auth can't be constructed ---


@pytest.mark.asyncio
async def test_startup_failed_auth_headers_raises_actionable():
    """The substitute provider defers the construction error to first use, with
    an actionable message (names the fix + tells the user to restart)."""
    from docforge.remote_client import _StartupFailedAuth

    auth = _StartupFailedAuth(
        "azure", ImportError("Azure auth requires `pip install docforge-cli[azure]`.")
    )
    with pytest.raises(RuntimeError) as ei:
        await auth.headers()
    msg = str(ei.value)
    assert "[azure]" in msg
    assert "restart" in msg.lower()


def test_build_remote_mcp_does_not_raise_when_azure_extra_missing(monkeypatch):
    """Missing [azure] extra must NOT crash server construction (was the -32000)."""
    monkeypatch.setenv("DOCFORGE_AUDIENCE", "api://test-audience")
    monkeypatch.setitem(sys.modules, "azure.identity.aio", None)  # force ImportError
    from docforge.remote_client import AuthName, build_remote_mcp

    mcp = build_remote_mcp(url="https://example", auth_name=AuthName.azure)
    assert mcp is not None  # would have raised ImportError before the fix


@pytest.mark.asyncio
async def test_search_surfaces_setup_error_as_tool_result_when_auth_unconstructable(monkeypatch):
    """End-to-end surface: a misconfigured auth provider yields an actionable
    tool RESULT (not a crash). headers() raises before any HTTP call, so no
    transport is needed."""
    monkeypatch.setenv("DOCFORGE_AUDIENCE", "api://test-audience")
    monkeypatch.setitem(sys.modules, "azure.identity.aio", None)
    from docforge.remote_client import RemoteBackend, _StartupFailedAuth, make_auth_provider

    try:
        make_auth_provider("azure")
        raised: Exception | None = None
    except Exception as e:  # noqa: BLE001
        raised = e
    assert raised is not None

    backend = RemoteBackend(url="https://api.example.com", auth=_StartupFailedAuth("azure", raised))
    result = await backend.search(query="x", limit=5)
    assert "Auth provider error" in result
    assert "[azure]" in result


def test_run_remote_mcp_prints_actionable_stderr_on_startup_error(monkeypatch, capsys):
    """If building the server raises, print a diagnostic to stderr and re-raise
    (so the process still exits non-zero for Claude Code's --debug logs)."""
    from docforge import remote_client

    def boom(**kwargs):
        raise RuntimeError("kaboom")

    monkeypatch.setattr(remote_client, "build_remote_mcp", boom)
    with pytest.raises(RuntimeError, match="kaboom"):
        remote_client.run_remote_mcp(url="https://example", auth_name="none")
    err = capsys.readouterr().err
    assert "docforge" in err.lower()
    assert "failed to start" in err.lower()
