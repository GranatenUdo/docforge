"""Tests for docforge.reranker_api FastAPI service (reranker sidecar)."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from httpx import ASGITransport, AsyncClient


def _settings_with_token(token: str = "secret-tok"):
    return SimpleNamespace(
        reranker_token=SimpleNamespace(get_secret_value=lambda: token),
        rerank_model="test/reranker",
        reranker_url="",
    )


@pytest.fixture(autouse=True)
def _stub_lifespan_resources(monkeypatch):
    """Override the reranker-app lifespan dependencies with stubs so tests
    don't load the real model."""
    from docforge.reranker_api import app, get_reranker, get_settings

    fake_reranker = MagicMock()
    fake_reranker.score = MagicMock(return_value=[0.9, 0.1])
    fake_reranker.model_name = "test/reranker"

    app.dependency_overrides[get_reranker] = lambda: fake_reranker
    app.dependency_overrides[get_settings] = _settings_with_token
    yield
    app.dependency_overrides.clear()


def _client(app):
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


class TestHealth:
    @pytest.mark.asyncio
    async def test_health_returns_model(self):
        from docforge.reranker_api import app

        async with _client(app) as c:
            resp = await c.get("/health")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "ok"
        assert body["model"] == "test/reranker"


class TestRerankAuth:
    @pytest.mark.asyncio
    async def test_missing_token_returns_401(self):
        from docforge.reranker_api import app

        async with _client(app) as c:
            resp = await c.post("/rerank", json={"query": "q", "texts": ["a", "b"]})
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_wrong_token_returns_401(self):
        from docforge.reranker_api import app

        async with _client(app) as c:
            resp = await c.post(
                "/rerank",
                json={"query": "q", "texts": ["a", "b"]},
                headers={"Authorization": "Bearer wrong-token"},
            )
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_correct_token_returns_200_with_scores(self):
        from docforge.reranker_api import app

        async with _client(app) as c:
            resp = await c.post(
                "/rerank",
                json={"query": "q", "texts": ["a", "b"]},
                headers={"Authorization": "Bearer secret-tok"},
            )
        assert resp.status_code == 200
        body = resp.json()
        assert body["scores"] == [0.9, 0.1]


class TestRerankValidation:
    @pytest.mark.asyncio
    async def test_empty_texts_returns_422(self):
        from docforge.reranker_api import app

        async with _client(app) as c:
            resp = await c.post(
                "/rerank",
                json={"query": "q", "texts": []},
                headers={"Authorization": "Bearer secret-tok"},
            )
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_oversized_texts_returns_422(self):
        # A batch larger than MAX_RERANK_BATCH is rejected at the API layer
        # (parity with the embedder) before it can OOM the GPU.
        from docforge.config import MAX_RERANK_BATCH
        from docforge.reranker_api import app

        async with _client(app) as c:
            resp = await c.post(
                "/rerank",
                json={"query": "q", "texts": ["t"] * (MAX_RERANK_BATCH + 1)},
                headers={"Authorization": "Bearer secret-tok"},
            )
        assert resp.status_code == 422


class TestLifespanGuard:
    @pytest.mark.asyncio
    async def test_lifespan_refuses_empty_token(self, monkeypatch):
        """The reranker service refuses to start with an empty RERANKER_TOKEN.
        Direct unit test of the lifespan."""
        from fastapi import FastAPI

        from docforge.reranker_api import lifespan

        app = FastAPI()

        # Patch the module-level Settings binding so the lifespan body's
        # `Settings()` call returns the stub instead of reading real env.
        monkeypatch.setattr(
            "docforge.reranker_api.Settings",
            lambda: SimpleNamespace(
                reranker_token=SimpleNamespace(get_secret_value=lambda: ""),
                rerank_model="test/reranker",
                reranker_url="",
            ),
        )

        with pytest.raises(RuntimeError, match="RERANKER_TOKEN"):
            async with lifespan(app):
                pass
