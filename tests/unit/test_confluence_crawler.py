"""Tests for docforge.crawlers.confluence.crawl_page.

Uses httpx.MockTransport to intercept HTTP calls without hitting Confluence.
The crawl_page function instantiates its own AsyncClient, so we monkeypatch
`docforge.crawlers.confluence.httpx.AsyncClient` to return a pre-configured
client whose transport is our mock.
"""

from __future__ import annotations

import hashlib

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
