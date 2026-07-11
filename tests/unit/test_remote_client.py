"""Tests for the remote-API MCP client mode."""

from __future__ import annotations

import json
import sys

import httpx
import pytest


@pytest.fixture(autouse=True)
def _isolated_prefs(monkeypatch, tmp_path):
    """Redirect the user-prefs store to tmp_path and clear DOCFORGE_TEAM_IDS.

    Without this, a developer machine's real prefs.json (or a configured
    DOCFORGE_TEAM_IDS) would leak a team_name into request bodies and flip
    nudge behavior, breaking the byte-exact body assertions below.
    """
    import docforge.user_prefs as up

    monkeypatch.setattr(up, "prefs_path", lambda: tmp_path / "prefs.json")
    monkeypatch.delenv("DOCFORGE_TEAM_IDS", raising=False)


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


# --- team fallback, first-query nudge, set_team ------------------------------


def _search_transport(captured: dict | None = None, results: list | None = None):
    """MockTransport returning a canned 200 /search response."""

    def handler(request: httpx.Request) -> httpx.Response:
        if captured is not None:
            captured["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "results": results
                if results is not None
                else [
                    {
                        "text": "Hello world",
                        "section_title": "Intro",
                        "source_title": "Test Page",
                        "source_url": "https://example.com/page",
                        "source_tags": ["org"],
                        "similarity": 0.85,
                    }
                ],
                "query": "q",
                "count": 1,
            },
        )

    return httpx.MockTransport(handler)


def _backend(transport):
    from docforge.remote_client import NoneAuth, RemoteBackend

    return RemoteBackend(url="https://api.example.com", auth=NoneAuth(), transport=transport)


@pytest.fixture()
def _no_env_identity(monkeypatch):
    for var in ("DOCFORGE_USER", "DOCFORGE_TEAM", "DOCFORGE_AREA"):
        monkeypatch.delenv(var, raising=False)


@pytest.mark.asyncio
async def test_nudge_appended_after_results_when_team_unresolved(monkeypatch, _no_env_identity):
    monkeypatch.setenv("DOCFORGE_TEAM_IDS", "ccl,cis")
    backend = _backend(_search_transport())

    out = await backend.search(query="q", limit=5)
    assert "note to the assistant" in out
    assert "Valid team ids: ccl, cis" in out
    # results come first, nudge strictly after
    assert out.index("Test Page") < out.index("note to the assistant")


@pytest.mark.asyncio
async def test_nudge_emitted_once_per_process(monkeypatch, _no_env_identity):
    monkeypatch.setenv("DOCFORGE_TEAM_IDS", "ccl,cis")
    backend = _backend(_search_transport())

    first = await backend.search(query="q", limit=5)
    second = await backend.search(query="q", limit=5)
    assert "note to the assistant" in first
    assert "note to the assistant" not in second


@pytest.mark.asyncio
async def test_no_nudge_when_env_team_set(monkeypatch, _no_env_identity):
    monkeypatch.setenv("DOCFORGE_TEAM", "ccl")
    monkeypatch.setenv("DOCFORGE_TEAM_IDS", "ccl,cis")
    backend = _backend(_search_transport())

    assert "note to the assistant" not in await backend.search(query="q", limit=5)


@pytest.mark.asyncio
async def test_no_nudge_when_team_ids_unset(monkeypatch, _no_env_identity):
    """Org-generic deployments (no DOCFORGE_TEAM_IDS) never see the nudge."""
    backend = _backend(_search_transport())

    assert "note to the assistant" not in await backend.search(query="q", limit=5)


@pytest.mark.asyncio
async def test_no_nudge_when_prefs_team_set_and_team_sent(monkeypatch, tmp_path, _no_env_identity):
    from docforge.user_prefs import UserPrefs, save_prefs

    monkeypatch.setenv("DOCFORGE_TEAM_IDS", "ccl,cis")
    save_prefs(UserPrefs(team="cis"), tmp_path / "prefs.json")

    captured: dict = {}
    backend = _backend(_search_transport(captured))
    out = await backend.search(query="q", limit=5)

    assert "note to the assistant" not in out
    assert captured["body"]["team_name"] == "cis"


@pytest.mark.asyncio
async def test_env_team_beats_prefs_team(monkeypatch, tmp_path, _no_env_identity):
    from docforge.user_prefs import UserPrefs, save_prefs

    monkeypatch.setenv("DOCFORGE_TEAM", "ccl")
    save_prefs(UserPrefs(team="cis"), tmp_path / "prefs.json")

    captured: dict = {}
    backend = _backend(_search_transport(captured))
    await backend.search(query="q", limit=5)
    assert captured["body"]["team_name"] == "ccl"


@pytest.mark.asyncio
async def test_no_nudge_after_decline(monkeypatch, tmp_path, _no_env_identity):
    from docforge.user_prefs import UserPrefs, save_prefs

    monkeypatch.setenv("DOCFORGE_TEAM_IDS", "ccl,cis")
    save_prefs(UserPrefs(declined=True), tmp_path / "prefs.json")

    backend = _backend(_search_transport())
    assert "note to the assistant" not in await backend.search(query="q", limit=5)


@pytest.mark.asyncio
async def test_no_nudge_after_lifetime_cap(monkeypatch, tmp_path, _no_env_identity):
    from docforge.user_prefs import UserPrefs, save_prefs

    monkeypatch.setenv("DOCFORGE_TEAM_IDS", "ccl,cis")
    save_prefs(UserPrefs(nudge_count=3), tmp_path / "prefs.json")

    backend = _backend(_search_transport())
    assert "note to the assistant" not in await backend.search(query="q", limit=5)


@pytest.mark.asyncio
async def test_nudge_increments_persisted_count(monkeypatch, tmp_path, _no_env_identity):
    from docforge.user_prefs import load_prefs

    monkeypatch.setenv("DOCFORGE_TEAM_IDS", "ccl,cis")
    backend = _backend(_search_transport())
    await backend.search(query="q", limit=5)

    assert load_prefs(tmp_path / "prefs.json").nudge_count == 1


@pytest.mark.asyncio
async def test_no_nudge_on_error_results(monkeypatch, _no_env_identity):
    """Error strings (401 here) must never carry the nudge."""
    monkeypatch.setenv("DOCFORGE_TEAM_IDS", "ccl,cis")
    transport = httpx.MockTransport(lambda req: httpx.Response(401, json={"detail": "no"}))
    backend = _backend(transport)

    out = await backend.search(query="q", limit=5)
    assert "Auth failed" in out
    assert "note to the assistant" not in out


@pytest.mark.asyncio
async def test_unsubstituted_placeholder_env_values_ignored(monkeypatch, _no_env_identity):
    """A literal ${user_config.team} (unsubstituted plugin template) must not
    be sent as a team_name."""
    monkeypatch.setenv("DOCFORGE_TEAM", "${user_config.team}")

    captured: dict = {}
    backend = _backend(_search_transport(captured))
    await backend.search(query="q", limit=5)
    assert "team_name" not in captured["body"]


@pytest.mark.asyncio
async def test_search_survives_prefs_load_crash(monkeypatch, _no_env_identity):
    """C2: identity/prefs failures must never break a search."""
    import docforge.user_prefs as up

    monkeypatch.setenv("DOCFORGE_TEAM_IDS", "ccl,cis")

    def boom():
        raise RuntimeError("disk exploded")

    monkeypatch.setattr(up, "prefs_path", boom)
    backend = _backend(_search_transport())

    out = await backend.search(query="q", limit=5)
    assert "Test Page" in out


# --- apply_set_team ----------------------------------------------------------


def test_apply_set_team_valid_id_persists(monkeypatch, tmp_path):
    monkeypatch.setenv("DOCFORGE_TEAM_IDS", "ccl,cis")
    monkeypatch.delenv("DOCFORGE_TEAM", raising=False)
    from docforge.remote_client import apply_set_team
    from docforge.user_prefs import load_prefs

    backend = _backend(_search_transport())
    msg = apply_set_team(backend, team=" CCL ")
    assert "Team set to 'ccl'" in msg
    assert load_prefs(tmp_path / "prefs.json").team == "ccl"


def test_apply_set_team_unknown_id_rejected_file_untouched(monkeypatch, tmp_path):
    monkeypatch.setenv("DOCFORGE_TEAM_IDS", "ccl,cis")
    from docforge.remote_client import apply_set_team
    from docforge.user_prefs import UserPrefs, load_prefs

    backend = _backend(_search_transport())
    msg = apply_set_team(backend, team="bogus")
    assert "not a recognized team id" in msg
    assert "ccl, cis" in msg
    assert load_prefs(tmp_path / "prefs.json") == UserPrefs()


def test_apply_set_team_freeform_when_no_ids(monkeypatch, tmp_path):
    monkeypatch.delenv("DOCFORGE_TEAM_IDS", raising=False)
    monkeypatch.delenv("DOCFORGE_TEAM", raising=False)
    from docforge.remote_client import apply_set_team
    from docforge.user_prefs import load_prefs

    backend = _backend(_search_transport())
    assert "Team set to 'platform-docs'" in apply_set_team(backend, team="platform-docs")
    assert load_prefs(tmp_path / "prefs.json").team == "platform-docs"
    assert "not a valid team id" in apply_set_team(backend, team="bad id with spaces")


def test_apply_set_team_empty_call_is_noop(monkeypatch, tmp_path):
    from docforge.remote_client import apply_set_team
    from docforge.user_prefs import UserPrefs, load_prefs

    backend = _backend(_search_transport())
    msg = apply_set_team(backend)
    assert "Nothing to do" in msg
    assert load_prefs(tmp_path / "prefs.json") == UserPrefs()


def test_apply_set_team_decline_persists(monkeypatch, tmp_path):
    from docforge.remote_client import apply_set_team
    from docforge.user_prefs import load_prefs

    backend = _backend(_search_transport())
    msg = apply_set_team(backend, never_ask_again=True)
    assert "will not be raised again" in msg
    assert load_prefs(tmp_path / "prefs.json").declined is True


def test_apply_set_team_explicit_team_beats_decline(monkeypatch, tmp_path):
    """LLMs sometimes set both ('I'm on ccl, stop asking'): the stated team wins
    and clears any previous decline."""
    monkeypatch.setenv("DOCFORGE_TEAM_IDS", "ccl,cis")
    monkeypatch.delenv("DOCFORGE_TEAM", raising=False)
    from docforge.remote_client import apply_set_team
    from docforge.user_prefs import UserPrefs, load_prefs, save_prefs

    save_prefs(UserPrefs(declined=True), tmp_path / "prefs.json")
    backend = _backend(_search_transport())
    msg = apply_set_team(backend, team="ccl", never_ask_again=True)
    assert "Team set to 'ccl'" in msg
    prefs = load_prefs(tmp_path / "prefs.json")
    assert prefs.team == "ccl"
    assert prefs.declined is False


def test_apply_set_team_notes_env_precedence(monkeypatch, tmp_path):
    monkeypatch.setenv("DOCFORGE_TEAM_IDS", "ccl,cis")
    monkeypatch.setenv("DOCFORGE_TEAM", "cis")
    from docforge.remote_client import apply_set_team

    backend = _backend(_search_transport())
    msg = apply_set_team(backend, team="ccl")
    assert "takes precedence" in msg
    assert "'cis'" in msg


@pytest.mark.asyncio
async def test_apply_set_team_save_failure_falls_back_to_session(
    monkeypatch, tmp_path, _no_env_identity
):
    """Disk-write failure keeps the answer for this session: the message says
    session-only and subsequent searches still carry the team."""
    import docforge.user_prefs as up

    monkeypatch.setenv("DOCFORGE_TEAM_IDS", "ccl,cis")
    monkeypatch.setattr(up, "save_prefs", lambda prefs, path=None: False)
    from docforge.remote_client import apply_set_team

    captured: dict = {}
    backend = _backend(_search_transport(captured))
    msg = apply_set_team(backend, team="ccl")
    assert "this session only" in msg

    await backend.search(query="q", limit=5)
    assert captured["body"]["team_name"] == "ccl"


@pytest.mark.asyncio
async def test_set_team_tool_registered_and_writes_file(monkeypatch, tmp_path):
    from fastmcp.client import Client

    from docforge.remote_client import SET_TEAM_DESCRIPTION, AuthName, build_remote_mcp
    from docforge.user_prefs import load_prefs

    monkeypatch.setenv("DOCFORGE_TEAM_IDS", "ccl,cis")
    monkeypatch.delenv("DOCFORGE_TEAM", raising=False)

    mcp = build_remote_mcp(url="https://example", auth_name=AuthName.none)
    async with Client(mcp) as client:
        tools = await client.list_tools()
        st = next(t for t in tools if t.name == "set_team")
        assert st.description == SET_TEAM_DESCRIPTION

        result = await client.call_tool("set_team", {"team": "ccl"})
        assert "Team set to 'ccl'" in result.content[0].text

    assert load_prefs(tmp_path / "prefs.json").team == "ccl"


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
    assert constructed["tools"] == ["search_documentation", "list_sources", "set_team"]
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
