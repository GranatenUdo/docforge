"""Tests for docforge.api FastAPI endpoints."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

from docforge.api import app, get_azure_scheme, get_embedder, get_pool_dep, get_settings
from tests.conftest import CapturingPool, FakePool, fake_settings


@pytest.fixture(autouse=True)
def _no_lifespan_defaults():
    """Default lifespan-populated dependencies to safe stubs for all tests in
    this module.

    Tests bypass the FastAPI lifespan (ASGITransport doesn't run it), so
    request.state is empty. These overrides prevent AttributeError when
    dependency getters try to read request.state keys that lifespan would
    normally populate.

    Individual tests replace these defaults with their own overrides as needed.
    The overrides dict is cleared fully by each test's own try/finally block;
    this fixture only ensures the module-wide defaults are in place.
    """
    from tests.conftest import FakeEmbedder

    app.dependency_overrides[get_azure_scheme] = lambda: None
    app.dependency_overrides[get_settings] = fake_settings
    app.dependency_overrides[get_pool_dep] = lambda: CapturingPool(rows=[])
    app.dependency_overrides[get_embedder] = lambda: FakeEmbedder()
    yield
    app.dependency_overrides.clear()


def _client():
    transport = ASGITransport(app=app)
    return AsyncClient(transport=transport, base_url="http://test")


class TestHealthEndpoint:
    @pytest.mark.asyncio
    async def test_health_returns_ok(self):
        async with _client() as client:
            resp = await client.get("/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"


class TestSearchEndpoint:
    @pytest.mark.asyncio
    async def test_returns_results_on_success(self):
        rows = [
            {
                "text": "Platform owns orgs.",
                "section_title": "Platform",
                "source_title": "Doc A",
                "source_url": "https://wiki/a",
                "source_tags": ["platform", "cloud"],
                "similarity": 0.95,
            }
        ]

        from tests.conftest import FakeEmbedder

        pool = CapturingPool(rows)

        app.dependency_overrides[get_embedder] = lambda: FakeEmbedder()
        app.dependency_overrides[get_pool_dep] = lambda: pool
        app.dependency_overrides[get_settings] = fake_settings
        try:
            async with _client() as client:
                resp = await client.post(
                    "/search",
                    json={
                        "query": "q",
                        "user_name": "tobias.ens",
                        "team_name": "platform",
                        "area_name": "cloud",
                        "limit": 5,
                    },
                )
        finally:
            app.dependency_overrides.clear()

        assert resp.status_code == 200
        body = resp.json()
        assert body["count"] == 1
        assert body["results"][0]["text"] == "Platform owns orgs."
        assert body["results"][0]["source_tags"] == ["platform", "cloud"]
        assert any("INSERT INTO query_log" in q for q, _ in pool.executes)

    @pytest.mark.asyncio
    async def test_returns_503_on_db_error(self):
        from tests.conftest import FakeEmbedder

        class _BrokenPool:
            def acquire(self):
                raise OSError("db down")

        app.dependency_overrides[get_embedder] = lambda: FakeEmbedder()
        app.dependency_overrides[get_pool_dep] = lambda: _BrokenPool()
        app.dependency_overrides[get_settings] = fake_settings
        try:
            async with _client() as client:
                resp = await client.post(
                    "/search",
                    json={
                        "query": "q",
                        "user_name": "u",
                        "team_name": "t",
                        "limit": 1,
                    },
                )
        finally:
            app.dependency_overrides.clear()

        assert resp.status_code == 503
        assert "Database unavailable" in resp.json()["detail"]

    @pytest.mark.asyncio
    async def test_returns_500_on_embed_error(self):
        from unittest.mock import AsyncMock

        fake_embedder = MagicMock()
        fake_embedder.aembed_query = AsyncMock(side_effect=RuntimeError("embed broken"))

        app.dependency_overrides[get_embedder] = lambda: fake_embedder
        app.dependency_overrides[get_pool_dep] = lambda: CapturingPool(rows=[])
        app.dependency_overrides[get_settings] = fake_settings
        try:
            async with _client() as client:
                resp = await client.post(
                    "/search",
                    json={
                        "query": "q",
                        "user_name": "u",
                        "team_name": "t",
                        "limit": 1,
                    },
                )
        finally:
            app.dependency_overrides.clear()

        assert resp.status_code == 500

    @pytest.mark.asyncio
    async def test_search_rejects_limit_over_max(self):
        """limit > 50 returns 422 with the limit field in the error detail."""
        async with _client() as client:
            resp = await client.post(
                "/search",
                json={
                    "query": "q",
                    "user_name": "u",
                    "team_name": "t",
                    "limit": 51,
                },
            )
        assert resp.status_code == 422
        detail = resp.json()["detail"]
        assert any(err["loc"][-1] == "limit" for err in detail)

    @pytest.mark.asyncio
    async def test_search_rejects_limit_under_min(self):
        """limit < 1 returns 422 with the limit field in the error detail."""
        async with _client() as client:
            resp = await client.post(
                "/search",
                json={
                    "query": "q",
                    "user_name": "u",
                    "team_name": "t",
                    "limit": 0,
                },
            )
        assert resp.status_code == 422
        detail = resp.json()["detail"]
        assert any(err["loc"][-1] == "limit" for err in detail)

    @pytest.mark.asyncio
    async def test_search_rejects_query_over_max_length(self):
        """query > 8000 chars returns 422 with the query field in the error detail."""
        async with _client() as client:
            resp = await client.post(
                "/search",
                json={
                    "query": "x" * 8001,
                    "user_name": "u",
                    "team_name": "t",
                    "limit": 1,
                },
            )
        assert resp.status_code == 422
        detail = resp.json()["detail"]
        assert any(err["loc"][-1] == "query" for err in detail)

    @pytest.mark.asyncio
    async def test_search_runs_embed_via_to_thread(self, monkeypatch):
        """The search handler calls aembed_query on the embedder, which
        (for in-process Embedder) wraps the sync call in asyncio.to_thread.
        This test verifies aembed_query is called with the correct query."""
        from unittest.mock import AsyncMock

        fake_embedder = MagicMock()
        fake_embedder.aembed_query = AsyncMock(return_value=[0.0] * 768)

        app.dependency_overrides[get_embedder] = lambda: fake_embedder
        app.dependency_overrides[get_pool_dep] = lambda: CapturingPool(rows=[])
        app.dependency_overrides[get_settings] = fake_settings
        try:
            async with _client() as client:
                resp = await client.post(
                    "/search",
                    json={
                        "query": "hello",
                        "user_name": "u",
                        "team_name": "t",
                        "limit": 1,
                    },
                )
            assert resp.status_code == 200
            fake_embedder.aembed_query.assert_called_once_with("hello")
        finally:
            app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_search_uses_anonymous_when_no_auth_no_user_name(self, monkeypatch):
        """POST /search without user_name and no auth → log_query receives 'anonymous'."""
        captured: dict = {}

        async def fake_log_query(pool, user_name, team_name, area_name, query, count, **kwargs):
            captured["user_name"] = user_name
            captured["team_name"] = team_name

        monkeypatch.setattr("docforge.api.log_query", fake_log_query)

        async with _client() as client:
            resp = await client.post("/search", json={"query": "hello", "limit": 5})

        assert resp.status_code == 200
        assert captured["user_name"] == "anonymous"
        assert captured["team_name"] is None

    @pytest.mark.asyncio
    async def test_search_uses_auth_subject_when_present(self, monkeypatch):
        """POST /search with auth subject → log_query receives preferred_username."""
        from types import SimpleNamespace

        from docforge.api import _auth_dependency

        captured: dict = {}

        async def fake_log_query(pool, user_name, team_name, area_name, query, count, **kwargs):
            captured["user_name"] = user_name

        monkeypatch.setattr("docforge.api.log_query", fake_log_query)

        fake_user = SimpleNamespace(preferred_username="tobias.ens", oid="abc-123")
        app.dependency_overrides[_auth_dependency] = lambda: fake_user
        try:
            async with _client() as client:
                resp = await client.post("/search", json={"query": "hello", "limit": 5})
        finally:
            del app.dependency_overrides[_auth_dependency]

        assert resp.status_code == 200
        assert captured["user_name"] == "tobias.ens"


class TestSourcesEndpoint:
    @pytest.mark.asyncio
    async def test_lists_sources(self):
        rows = [
            {
                "title": "Doc A",
                "url": "https://wiki/a",
                "status": "active",
                "last_crawled_at": datetime(2026, 4, 17, 9, 0, tzinfo=timezone.utc),
                "chunk_count": 4,
            }
        ]
        fake_pool = FakePool(rows)

        app.dependency_overrides[get_pool_dep] = lambda: fake_pool
        app.dependency_overrides[get_settings] = fake_settings
        try:
            async with _client() as client:
                resp = await client.get("/sources")
        finally:
            app.dependency_overrides.clear()

        assert resp.status_code == 200
        body = resp.json()
        assert body["count"] == 1
        assert body["sources"][0]["title"] == "Doc A"

    @pytest.mark.asyncio
    async def test_returns_503_on_db_error(self):
        class _BrokenPool:
            def acquire(self):
                raise OSError("boom")

        app.dependency_overrides[get_pool_dep] = lambda: _BrokenPool()
        app.dependency_overrides[get_settings] = fake_settings
        try:
            async with _client() as client:
                resp = await client.get("/sources")
        finally:
            app.dependency_overrides.clear()

        assert resp.status_code == 503


class TestRequestTimingInstrumentation:
    """C4.3 — the /search handler measures its own wall-clock time and
    passes request_ms into log_query."""

    @pytest.mark.asyncio
    async def test_search_writes_request_ms_to_query_log(self, monkeypatch):
        captured: dict = {}

        async def fake_log_query(*args, **kwargs):
            captured.update(kwargs)

        monkeypatch.setattr("docforge.api.log_query", fake_log_query)

        from tests.conftest import FakeEmbedder

        app.dependency_overrides[get_embedder] = lambda: FakeEmbedder()
        app.dependency_overrides[get_pool_dep] = lambda: CapturingPool(rows=[])
        app.dependency_overrides[get_settings] = fake_settings
        try:
            async with _client() as client:
                resp = await client.post(
                    "/search",
                    json={
                        "query": "test",
                        "user_name": "tobias",
                        "team_name": "platform",
                        "area_name": None,
                        "limit": 3,
                    },
                )
        finally:
            app.dependency_overrides.clear()

        assert resp.status_code == 200
        assert "request_ms" in captured
        assert isinstance(captured["request_ms"], int)
        assert captured["request_ms"] >= 0
        # Sanity: should be much less than a second for a stubbed handler.
        assert captured["request_ms"] < 1000


def test_search_request_user_name_and_team_name_optional():
    """SearchRequest validates without user_name or team_name (relaxed schema)."""
    from docforge.api import SearchRequest

    req = SearchRequest(query="hello", limit=5)
    assert req.user_name is None
    assert req.team_name is None
    assert req.area_name is None
    assert req.query == "hello"


def test_search_request_accepts_full_body_for_backwards_compat():
    """Existing clients still work when sending all identity fields."""
    from docforge.api import SearchRequest

    req = SearchRequest(
        query="hello",
        user_name="tobias.ens",
        team_name="ccl",
        area_name="cloud",
        limit=10,
    )
    assert req.user_name == "tobias.ens"
    assert req.team_name == "ccl"
    assert req.area_name == "cloud"
