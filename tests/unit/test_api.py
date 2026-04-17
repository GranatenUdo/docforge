import pytest
from httpx import ASGITransport, AsyncClient

from docforge.api import app


class TestHealthEndpoint:
    @pytest.mark.asyncio
    async def test_health_returns_ok(self):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"


class TestSearchEndpoint:
    @pytest.mark.asyncio
    async def test_search_returns_503_when_model_not_loaded(self):
        import docforge.api as api_module

        original = api_module._embedder
        api_module._embedder = None
        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.post(
                    "/search",
                    json={"query": "test", "limit": 1},
                )
            assert resp.status_code == 503
            assert "not loaded" in resp.json()["detail"]
        finally:
            api_module._embedder = original
