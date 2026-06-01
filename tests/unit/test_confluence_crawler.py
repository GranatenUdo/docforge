"""Tests for docforge.crawlers.confluence.crawl_page.

Uses httpx.MockTransport to intercept HTTP calls without hitting Confluence.
The crawl_page function instantiates its own AsyncClient, so we monkeypatch
`docforge.crawlers.confluence.httpx.AsyncClient` to return a pre-configured
client whose transport is our mock.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from docforge.crawlers.confluence import crawl_page


@pytest.fixture
def mock_confluence(monkeypatch):
    """Return an installer: `mock_confluence(handler_fn)` patches httpx."""
    # Capture real AsyncClient before patching; the monkeypatch setattr on
    # `docforge.crawlers.confluence.httpx.AsyncClient` mutates the httpx
    # module globally, so the factory cannot refer to httpx.AsyncClient
    # without infinite recursion.
    real_async_client = httpx.AsyncClient

    def _install(handler):
        def client_factory(**kwargs):
            return real_async_client(transport=httpx.MockTransport(handler))

        monkeypatch.setattr("docforge.crawlers.confluence.httpx.AsyncClient", client_factory)

    return _install


@pytest.mark.asyncio
async def test_successful_fetch(mock_confluence):
    def handler(request):
        assert "pages/42" in str(request.url)
        return httpx.Response(
            200,
            json={
                "title": "Team Responsibilities",
                "version": {"number": 7},
                "spaceId": "ORG",
                "body": {"storage": {"value": "<h2>Platform</h2><p>Owns X</p>"}},
            },
        )

    mock_confluence(handler)

    page = await crawl_page(
        "42",
        base_url="https://example.atlassian.net",
        email="a@b.c",
        api_token="tok",
    )

    assert page.page_id == "42"
    assert page.title == "Team Responsibilities"
    assert page.version == 7
    assert page.html_content == "<h2>Platform</h2><p>Owns X</p>"
    expected_hash = hashlib.sha256(page.html_content.encode()).hexdigest()
    assert page.content_hash == expected_hash
    assert page.url == "https://example.atlassian.net/wiki/spaces/ORG/pages/42"


@pytest.mark.asyncio
async def test_missing_body_returns_empty_html(mock_confluence):
    def handler(request):
        return httpx.Response(200, json={"title": "Empty"})

    mock_confluence(handler)

    page = await crawl_page("1", base_url="https://x", email="a", api_token="t")
    assert page.html_content == ""


@pytest.mark.asyncio
async def test_auth_error_raises(mock_confluence):
    def handler(request):
        return httpx.Response(401, json={"message": "unauthorized"})

    mock_confluence(handler)

    with pytest.raises(httpx.HTTPStatusError):
        await crawl_page("1", base_url="https://x", email="a", api_token="bad")


@pytest.mark.asyncio
async def test_not_found_raises(mock_confluence):
    def handler(request):
        return httpx.Response(404, json={"message": "not found"})

    mock_confluence(handler)

    with pytest.raises(httpx.HTTPStatusError):
        await crawl_page("missing", base_url="https://x", email="a", api_token="t")


@pytest.mark.asyncio
async def test_retries_on_transient_then_succeeds(mock_confluence, monkeypatch):
    async def _noop_sleep(_):
        return None

    monkeypatch.setattr("asyncio.sleep", _noop_sleep)

    call_count = {"n": 0}

    def handler(request):
        call_count["n"] += 1
        if call_count["n"] == 1:
            return httpx.Response(503, headers={"Retry-After": "0"})
        return httpx.Response(
            200,
            json={
                "title": "OK",
                "version": {"number": 1},
                "spaceId": "SP",
                "body": {"storage": {"value": "<p>Ok</p>"}},
            },
        )

    mock_confluence(handler)

    page = await crawl_page("1", base_url="https://x", email="a", api_token="t")
    assert page.title == "OK"
    assert call_count["n"] == 2


@pytest.mark.asyncio
async def test_max_retries_exceeded_raises(mock_confluence, monkeypatch):
    async def _noop_sleep(_):
        return None

    monkeypatch.setattr("asyncio.sleep", _noop_sleep)

    def handler(request):
        return httpx.Response(503, headers={"Retry-After": "0"})

    mock_confluence(handler)

    with pytest.raises(httpx.HTTPStatusError):
        await crawl_page("1", base_url="https://x", email="a", api_token="t")


@pytest.mark.asyncio
async def test_retries_on_timeout(mock_confluence, monkeypatch):
    async def _noop_sleep(_):
        return None

    monkeypatch.setattr("asyncio.sleep", _noop_sleep)

    call_count = {"n": 0}

    def handler(request):
        call_count["n"] += 1
        if call_count["n"] == 1:
            raise httpx.TimeoutException("slow")
        return httpx.Response(
            200,
            json={
                "title": "OK",
                "version": {"number": 1},
                "spaceId": "SP",
                "body": {"storage": {"value": "<p>Ok</p>"}},
            },
        )

    mock_confluence(handler)

    page = await crawl_page("1", base_url="https://x", email="a", api_token="t")
    assert page.title == "OK"
    assert call_count["n"] == 2


@pytest.mark.asyncio
async def test_last_modified_parsed_from_version_created_at(mock_confluence):
    def handler(request):
        return httpx.Response(
            200,
            json={
                "title": "Stale Page",
                "version": {"number": 3, "createdAt": "2022-01-15T10:30:00Z"},
                "spaceId": "ORG",
                "body": {"storage": {"value": "<p>old</p>"}},
            },
        )

    mock_confluence(handler)

    page = await crawl_page("1", base_url="https://x", email="a", api_token="t")

    assert page.last_modified == datetime(2022, 1, 15, 10, 30, 0, tzinfo=timezone.utc)


@pytest.mark.asyncio
async def test_missing_version_created_at_defaults_to_now(mock_confluence):
    """If the API response omits version.createdAt, treat the page as fresh (now)
    so the [STALE] rule never fires for it."""

    def handler(request):
        return httpx.Response(
            200,
            json={
                "title": "Versionless",
                "version": {"number": 1},
                "spaceId": "ORG",
                "body": {"storage": {"value": "<p>ok</p>"}},
            },
        )

    mock_confluence(handler)

    before = datetime.now(timezone.utc)
    page = await crawl_page("1", base_url="https://x", email="a", api_token="t")
    after = datetime.now(timezone.utc)

    # last_modified falls in [before, after] since the fallback used now()
    assert before <= page.last_modified <= after


@pytest.mark.asyncio
async def test_stale_prefix_applied_when_old(mock_confluence):
    def handler(request):
        return httpx.Response(
            200,
            json={
                "title": "Departments in Product Development",
                "version": {"number": 3, "createdAt": "2022-01-15T10:30:00Z"},
                "spaceId": "ORG",
                "body": {"storage": {"value": "<p>old</p>"}},
            },
        )

    mock_confluence(handler)
    page = await crawl_page(
        "1",
        base_url="https://x",
        email="a",
        api_token="t",
        stale_threshold_months=36,
    )
    assert page.title == "[STALE 2022] Departments in Product Development"


@pytest.mark.asyncio
async def test_stale_prefix_not_applied_when_fresh(mock_confluence):
    fresh_iso = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat().replace("+00:00", "Z")

    def handler(request):
        return httpx.Response(
            200,
            json={
                "title": "Fresh Page",
                "version": {"number": 1, "createdAt": fresh_iso},
                "spaceId": "ORG",
                "body": {"storage": {"value": "<p>new</p>"}},
            },
        )

    mock_confluence(handler)
    page = await crawl_page(
        "1",
        base_url="https://x",
        email="a",
        api_token="t",
        stale_threshold_months=36,
    )
    assert not page.title.startswith("[STALE")
    assert page.title == "Fresh Page"


@pytest.mark.asyncio
async def test_stale_prefix_disabled_via_none(mock_confluence):
    def handler(request):
        return httpx.Response(
            200,
            json={
                "title": "Ancient Page",
                "version": {"number": 1, "createdAt": "1999-01-01T00:00:00Z"},
                "spaceId": "ORG",
                "body": {"storage": {"value": "<p>old</p>"}},
            },
        )

    mock_confluence(handler)
    page = await crawl_page(
        "1",
        base_url="https://x",
        email="a",
        api_token="t",
        stale_threshold_months=None,
    )
    assert page.title == "Ancient Page"


from docforge.crawlers.confluence import enumerate_tree_page_ids


@pytest.mark.asyncio
async def test_enumerate_single_page_no_pagination(mock_confluence):
    captured = {}

    def handler(request):
        # request.url.params decodes the query string, so we assert on the exact
        # CQL the function built — not its percent-encoded form.
        captured["cql"] = request.url.params.get("cql")
        return httpx.Response(
            200,
            json={"results": [{"id": "111", "type": "page", "title": "A"}], "_links": {}},
        )

    mock_confluence(handler)
    ids = await enumerate_tree_page_ids(
        "999", base_url="https://x", email="a", api_token="t"
    )
    assert ids == ["111"]
    # Default 24-month staleness with UPPERCASE M (months). Lowercase m means
    # MINUTES in CQL and would silently match almost nothing.
    assert captured["cql"] == 'ancestor=999 and type=page and lastmodified >= now("-24M")'


@pytest.mark.asyncio
async def test_enumerate_follows_links_next_prepending_base(mock_confluence):
    calls = {"n": 0, "second_url": None}

    def handler(request):
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(
                200,
                json={
                    "results": [{"id": "1"}, {"id": "2"}],
                    # next omits the /wiki context path; base carries it
                    "_links": {
                        "base": "https://x/wiki",
                        "next": "/rest/api/content/search?cursor=ABC",
                    },
                },
            )
        calls["second_url"] = str(request.url)
        return httpx.Response(200, json={"results": [{"id": "3"}], "_links": {}})

    mock_confluence(handler)
    ids = await enumerate_tree_page_ids(
        "999", base_url="https://x", email="a", api_token="t"
    )
    assert ids == ["1", "2", "3"]
    assert calls["second_url"].startswith("https://x/wiki/rest/api/content/search")
    assert "cursor=ABC" in calls["second_url"]


@pytest.mark.asyncio
async def test_enumerate_omits_staleness_clause_when_none(mock_confluence):
    captured = {}

    def handler(request):
        captured["cql"] = request.url.params.get("cql")
        return httpx.Response(200, json={"results": [], "_links": {}})

    mock_confluence(handler)
    await enumerate_tree_page_ids(
        "999", base_url="https://x", email="a", api_token="t", stale_months=None
    )
    assert captured["cql"] == "ancestor=999 and type=page"


@pytest.mark.asyncio
async def test_enumerate_custom_stale_months(mock_confluence):
    captured = {}

    def handler(request):
        captured["cql"] = request.url.params.get("cql")
        return httpx.Response(200, json={"results": [], "_links": {}})

    mock_confluence(handler)
    await enumerate_tree_page_ids(
        "999", base_url="https://x", email="a", api_token="t", stale_months=12
    )
    assert 'now("-12M")' in captured["cql"]
