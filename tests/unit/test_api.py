"""Tests for docforge.api FastAPI endpoints."""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

from docforge import api as api_module
from docforge.api import app


class _FakeConn:
    def __init__(self, rows):
        self._rows = rows

    async def fetch(self, query, *args):
        return self._rows


class _AcquireCtx:
    def __init__(self, rows):
        self._rows = rows

    async def __aenter__(self):
        return _FakeConn(self._rows)

    async def __aexit__(self, *a):
        return None


class FakePool:
    def __init__(self, rows):
        self._rows = rows

    def acquire(self):
        return _AcquireCtx(self._rows)


async def _client():
    transport = ASGITransport(app=app)
    return AsyncClient(transport=transport, base_url="http://test")


class TestHealthEndpoint:
    @pytest.mark.asyncio
    async def test_health_returns_ok(self):
        async with await _client() as client:
            resp = await client.get("/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"


class TestSearchEndpoint:
    @pytest.mark.asyncio
    async def test_returns_503_when_model_not_loaded(self):
        original = api_module._embedder
        api_module._embedder = None
        try:
            async with await _client() as client:
                resp = await client.post("/search", json={"query": "q", "limit": 1})
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
                "similarity": 0.95,
            }
        ]

        fake_embedder = MagicMock()
        fake_embedder.embed_query.return_value = [0.0] * 768
        fake_embedder.model_name = "fake"
        api_module._embedder = fake_embedder

        fake_pool = FakePool(rows)

        async def fake_get_pool(url):
            return fake_pool

        monkeypatch.setattr(api_module, "get_pool", fake_get_pool)
        monkeypatch.setattr(
            api_module,
            "_get_settings",
            lambda: SimpleNamespace(database_url="postgresql://fake"),
        )

        try:
            async with await _client() as client:
                resp = await client.post("/search", json={"query": "q", "limit": 5})
        finally:
            api_module._embedder = None

        assert resp.status_code == 200
        body = resp.json()
        assert body["count"] == 1
        assert body["results"][0]["text"] == "Platform owns orgs."
        assert body["results"][0]["similarity"] == pytest.approx(0.95)

    @pytest.mark.asyncio
    async def test_returns_503_on_db_error(self, monkeypatch):
        fake_embedder = MagicMock()
        fake_embedder.embed_query.return_value = [0.0] * 768
        api_module._embedder = fake_embedder

        async def fake_get_pool(url):
            raise OSError("db down")

        monkeypatch.setattr(api_module, "get_pool", fake_get_pool)
        monkeypatch.setattr(
            api_module,
            "_get_settings",
            lambda: SimpleNamespace(database_url="postgresql://fake"),
        )

        try:
            async with await _client() as client:
                resp = await client.post("/search", json={"query": "q", "limit": 1})
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
            async with await _client() as client:
                resp = await client.post("/search", json={"query": "q", "limit": 1})
        finally:
            api_module._embedder = None

        assert resp.status_code == 500
        assert "embed" in resp.json()["detail"].lower()


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
        monkeypatch.setattr(
            api_module,
            "_get_settings",
            lambda: SimpleNamespace(database_url="postgresql://fake"),
        )

        async with await _client() as client:
            resp = await client.get("/sources")

        assert resp.status_code == 200
        body = resp.json()
        assert body["count"] == 1
        assert body["sources"][0]["title"] == "Doc A"
        assert body["sources"][0]["chunk_count"] == 4

    @pytest.mark.asyncio
    async def test_returns_503_on_db_error(self, monkeypatch):
        async def fake_get_pool(url):
            raise OSError("boom")

        monkeypatch.setattr(api_module, "get_pool", fake_get_pool)
        monkeypatch.setattr(
            api_module,
            "_get_settings",
            lambda: SimpleNamespace(database_url="postgresql://fake"),
        )

        async with await _client() as client:
            resp = await client.get("/sources")

        assert resp.status_code == 503
