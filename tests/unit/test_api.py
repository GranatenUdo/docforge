"""Tests for docforge.api FastAPI endpoints."""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

from docforge import api as api_module
from docforge.api import app
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


def _client():
    transport = ASGITransport(app=app)
    return AsyncClient(transport=transport, base_url="http://test")


def _settings_stub():
    return SimpleNamespace(
        database_url="postgresql://fake",
        tag_match_weight=0.1,
        org_tag_weight=0.05,
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
    async def test_returns_503_when_model_not_loaded(self):
        original = api_module._embedder
        api_module._embedder = None
        try:
            async with _client() as client:
                resp = await client.post(
                    "/search",
                    json={"query": "q", "user_name": "u", "team_name": "t", "limit": 1},
                )
            assert resp.status_code == 503
            assert "not loaded" in resp.json()["detail"]
        finally:
            api_module._embedder = original

    @pytest.mark.asyncio
    async def test_returns_results_on_success(self, monkeypatch):
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
        api_module._embedder = fake_embedder

        pool = _CapturingPool(rows)

        async def fake_get_pool(url):
            return pool

        monkeypatch.setattr(api_module, "get_pool", fake_get_pool)
        monkeypatch.setattr(api_module, "_get_settings", _settings_stub)

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
            api_module._embedder = None

        assert resp.status_code == 200
        body = resp.json()
        assert body["count"] == 1
        assert body["results"][0]["text"] == "Platform owns orgs."
        assert body["results"][0]["source_tags"] == ["platform", "cloud"]
        # query_log insert happened
        assert any("INSERT INTO query_log" in q for q, _ in pool.executes)

    @pytest.mark.asyncio
    async def test_returns_503_on_db_error(self, monkeypatch):
        fake_embedder = MagicMock()
        fake_embedder.embed_query.return_value = [0.0] * 768
        api_module._embedder = fake_embedder

        async def fake_get_pool(url):
            raise OSError("db down")

        monkeypatch.setattr(api_module, "get_pool", fake_get_pool)
        monkeypatch.setattr(api_module, "_get_settings", _settings_stub)

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
            api_module._embedder = None

        assert resp.status_code == 503
        assert "Database unavailable" in resp.json()["detail"]

    @pytest.mark.asyncio
    async def test_returns_500_on_embed_error(self, monkeypatch):
        fake_embedder = MagicMock()
        fake_embedder.embed_query.side_effect = RuntimeError("embed broken")
        api_module._embedder = fake_embedder

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
            api_module._embedder = None

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


class TestSourcesEndpoint:
    @pytest.mark.asyncio
    async def test_lists_sources(self, monkeypatch):
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

        async def fake_get_pool(url):
            return fake_pool

        monkeypatch.setattr(api_module, "get_pool", fake_get_pool)
        monkeypatch.setattr(api_module, "_get_settings", _settings_stub)

        async with _client() as client:
            resp = await client.get("/sources")

        assert resp.status_code == 200
        body = resp.json()
        assert body["count"] == 1
        assert body["sources"][0]["title"] == "Doc A"

    @pytest.mark.asyncio
    async def test_returns_503_on_db_error(self, monkeypatch):
        async def fake_get_pool(url):
            raise OSError("boom")

        monkeypatch.setattr(api_module, "get_pool", fake_get_pool)
        monkeypatch.setattr(api_module, "_get_settings", _settings_stub)

        async with _client() as client:
            resp = await client.get("/sources")

        assert resp.status_code == 503


class TestRequestTimingInstrumentation:
    """C4.3 — the /search handler measures its own wall-clock time and
    passes request_ms into log_query."""

    @pytest.mark.asyncio
    async def test_search_writes_request_ms_to_query_log(self, monkeypatch):
        captured: dict = {}

        async def fake_log_query(*args, **kwargs):
            captured.update(kwargs)

        monkeypatch.setattr("docforge.query_log.log_query", fake_log_query)
        monkeypatch.setattr(api_module, "_get_settings", _settings_stub)
        monkeypatch.setattr(api_module, "_azure_scheme", None)

        class _FakeEmbedder:
            model_name = "test"
            dimensions = 768

            def embed_query(self, q):
                return [0.0] * 768

        monkeypatch.setattr(api_module, "_embedder", _FakeEmbedder())

        async def fake_get_pool(url):
            return _CapturingPool(rows=[])

        monkeypatch.setattr(api_module, "get_pool", fake_get_pool)

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
        assert resp.status_code == 200
        assert "request_ms" in captured
        assert isinstance(captured["request_ms"], int)
        assert captured["request_ms"] >= 0
        # Sanity: should be much less than a second for a stubbed handler.
        assert captured["request_ms"] < 1000
