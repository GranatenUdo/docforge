"""Tests for docforge.api FastAPI endpoints."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

from docforge.api import app, get_azure_scheme, get_embedder, get_pool_dep, get_settings
from tests.conftest import FakePool


class _CapturingConn:
    """Returns rows for SELECT; captures query_log INSERTs via execute."""

    def __init__(self, rows, executes):
        self._rows = rows
        self._executes = executes

    async def fetch(self, query, *args):
        return self._rows

    async def execute(self, query, *args):
        self._executes.append((query, args))


class _CapturingCtx:
    def __init__(self, conn):
        self._conn = conn

    async def __aenter__(self):
        return self._conn

    async def __aexit__(self, *a):
        return None


class _CapturingPool:
    def __init__(self, rows):
        self.rows = rows
        self.executes = []

    def acquire(self):
        return _CapturingCtx(_CapturingConn(self.rows, self.executes))


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
    _fake_embedder = MagicMock()
    _fake_embedder.embed_query.return_value = [0.0] * 768
    _fake_embedder.model_name = "test"

    app.dependency_overrides[get_azure_scheme] = lambda: None
    app.dependency_overrides[get_settings] = _settings_stub
    app.dependency_overrides[get_pool_dep] = lambda: _CapturingPool(rows=[])
    app.dependency_overrides[get_embedder] = lambda: _fake_embedder
    yield
    app.dependency_overrides.clear()


def _client():
    transport = ASGITransport(app=app)
    return AsyncClient(transport=transport, base_url="http://test")


def _settings_stub():
    return SimpleNamespace(
        database_url="postgresql://fake",
        tag_match_weight=0.1,
        org_tag_weight=0.05,
        pool_min_size=5,
        pool_max_size=25,
        query_log_retention_days=180,
    )


class TestHealthEndpoint:
    @pytest.mark.asyncio
    async def test_health_returns_ok(self):
        async with _client() as client:
            resp = await client.get("/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"


class TestSearchEndpoint:
    @pytest.mark.asyncio
    async def test_rejects_missing_required_identity_fields(self):
        async with _client() as client:
            resp = await client.post("/search", json={"query": "q", "limit": 1})
        assert resp.status_code == 422

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

        fake_embedder = MagicMock()
        fake_embedder.embed_query.return_value = [0.0] * 768
        fake_embedder.model_name = "fake"

        pool = _CapturingPool(rows)

        app.dependency_overrides[get_embedder] = lambda: fake_embedder
        app.dependency_overrides[get_pool_dep] = lambda: pool
        app.dependency_overrides[get_settings] = _settings_stub
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
        fake_embedder = MagicMock()
        fake_embedder.embed_query.return_value = [0.0] * 768

        class _BrokenPool:
            def acquire(self):
                raise OSError("db down")

        app.dependency_overrides[get_embedder] = lambda: fake_embedder
        app.dependency_overrides[get_pool_dep] = lambda: _BrokenPool()
        app.dependency_overrides[get_settings] = _settings_stub
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
        fake_embedder = MagicMock()
        fake_embedder.embed_query.side_effect = RuntimeError("embed broken")

        app.dependency_overrides[get_embedder] = lambda: fake_embedder
        app.dependency_overrides[get_pool_dep] = lambda: _CapturingPool(rows=[])
        app.dependency_overrides[get_settings] = _settings_stub
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
        """The synchronous embed_query call goes through asyncio.to_thread
        so the event loop is not blocked during inference."""
        captured: dict = {"args": None}

        original_to_thread = asyncio.to_thread

        async def spy_to_thread(func, *args, **kwargs):
            captured["args"] = (func, args, kwargs)
            return await original_to_thread(func, *args, **kwargs)

        monkeypatch.setattr(asyncio, "to_thread", spy_to_thread)

        fake_embedder = MagicMock()
        fake_embedder.embed_query.return_value = [0.0] * 768

        app.dependency_overrides[get_embedder] = lambda: fake_embedder
        app.dependency_overrides[get_pool_dep] = lambda: _CapturingPool(rows=[])
        app.dependency_overrides[get_settings] = _settings_stub
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
            assert captured["args"] is not None, "embed_query was not run via asyncio.to_thread"
            assert captured["args"][0] == fake_embedder.embed_query
            assert captured["args"][1] == ("hello",)
        finally:
            app.dependency_overrides.clear()


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
        app.dependency_overrides[get_settings] = _settings_stub
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
        app.dependency_overrides[get_settings] = _settings_stub
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

        class _FakeEmbedder:
            model_name = "test"
            dimensions = 768

            def embed_query(self, q):
                return [0.0] * 768

        from docforge.api import get_azure_scheme

        app.dependency_overrides[get_embedder] = lambda: _FakeEmbedder()
        app.dependency_overrides[get_pool_dep] = lambda: _CapturingPool(rows=[])
        app.dependency_overrides[get_settings] = _settings_stub
        app.dependency_overrides[get_azure_scheme] = lambda: None
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
