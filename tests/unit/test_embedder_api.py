"""Tests for docforge.embedder_api FastAPI service (Phase 4b)."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from httpx import ASGITransport, AsyncClient


def _settings_with_token(token: str = "secret-tok"):
    return SimpleNamespace(
        embedder_token=SimpleNamespace(get_secret_value=lambda: token),
        embedding_model="test/model",
        embedding_dimensions=768,
        hf_token=SimpleNamespace(get_secret_value=lambda: ""),
        embedder_url="",
    )


@pytest.fixture(autouse=True)
def _stub_lifespan_resources(monkeypatch):
    """Override the embedder-app lifespan dependencies with stubs so tests
    don't load the real model."""
    from docforge.embedder_api import app, get_embedder, get_settings

    fake_embedder = MagicMock()
    fake_embedder.embed.return_value = [[0.1] * 768]
    fake_embedder.model_name = "test/model"
    fake_embedder.dimensions = 768

    app.dependency_overrides[get_embedder] = lambda: fake_embedder
    app.dependency_overrides[get_settings] = _settings_with_token
    yield
    app.dependency_overrides.clear()


def _client(app):
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


class TestHealth:
    @pytest.mark.asyncio
    async def test_health_returns_model_and_dimensions(self):
        from docforge.embedder_api import app

        async with _client(app) as c:
            resp = await c.get("/health")
        assert resp.status_code == 200
        body = resp.json()
        assert body["model"] == "test/model"
        assert body["dimensions"] == 768


class TestEmbedAuth:
    @pytest.mark.asyncio
    async def test_missing_token_returns_401(self):
        from docforge.embedder_api import app

        async with _client(app) as c:
            resp = await c.post("/embed", json={"texts": ["hello"]})
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_wrong_token_returns_401(self):
        from docforge.embedder_api import app

        async with _client(app) as c:
            resp = await c.post(
                "/embed",
                json={"texts": ["hello"]},
                headers={"Authorization": "Bearer wrong-token"},
            )
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_correct_token_returns_200(self):
        from docforge.embedder_api import app

        async with _client(app) as c:
            resp = await c.post(
                "/embed",
                json={"texts": ["hello"]},
                headers={"Authorization": "Bearer secret-tok"},
            )
        assert resp.status_code == 200
        body = resp.json()
        assert body["dimensions"] == 768
        assert len(body["vectors"]) == 1


class TestEmbedValidation:
    @pytest.mark.asyncio
    async def test_empty_texts_returns_422(self):
        from docforge.embedder_api import app

        async with _client(app) as c:
            resp = await c.post(
                "/embed",
                json={"texts": []},
                headers={"Authorization": "Bearer secret-tok"},
            )
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_oversized_batch_returns_422(self):
        from docforge.embedder_api import app

        async with _client(app) as c:
            resp = await c.post(
                "/embed",
                json={"texts": ["x"] * 257},  # MAX_BATCH_SIZE + 1
                headers={"Authorization": "Bearer secret-tok"},
            )
        assert resp.status_code == 422


class TestLifespanGuard:
    @pytest.mark.asyncio
    async def test_lifespan_refuses_empty_token(self, monkeypatch):
        """Phase 4b: the embedder service refuses to start with empty
        EMBEDDER_TOKEN. Direct unit test of the lifespan."""
        from fastapi import FastAPI

        from docforge.embedder_api import lifespan

        app = FastAPI()

        # Patch the module-level Settings binding so the lifespan body's
        # `Settings()` call returns the stub instead of reading real env.
        monkeypatch.setattr(
            "docforge.embedder_api.Settings",
            lambda: SimpleNamespace(
                embedder_token=SimpleNamespace(get_secret_value=lambda: ""),
                embedding_model="test",
                embedding_dimensions=768,
                hf_token=SimpleNamespace(get_secret_value=lambda: ""),
                embedder_url="",
            ),
        )

        with pytest.raises(RuntimeError, match="EMBEDDER_TOKEN"):
            async with lifespan(app):
                pass
