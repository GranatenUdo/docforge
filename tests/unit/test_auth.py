"""Tests for Entra auth integration in docforge.api."""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient


@pytest.fixture
def stub_downstream(monkeypatch):
    """Stub embedder, DB pool, settings, and log_query so /search reaches its
    return path without touching real infra. Patches names as they're bound
    inside docforge.api (matches the test_api.py pattern)."""
    from types import SimpleNamespace

    class FakeEmbedder:
        model_name = "test"
        dimensions = 768

        def embed_query(self, q):
            return [0.0] * 768

    import docforge.api as api_mod
    monkeypatch.setattr(api_mod, "_embedder", FakeEmbedder())

    class _Conn:
        async def fetch(self, *a, **k):
            return []

        async def execute(self, *a, **k):
            pass

    class _Ctx:
        async def __aenter__(self):
            return _Conn()

        async def __aexit__(self, *a):
            pass

    class _Pool:
        def acquire(self):
            return _Ctx()

    async def fake_get_pool(url):
        return _Pool()

    monkeypatch.setattr(api_mod, "get_pool", fake_get_pool)

    def fake_settings():
        return SimpleNamespace(
            database_url="postgresql://fake",
            tag_match_weight=0.1,
            org_tag_weight=0.05,
        )

    monkeypatch.setattr(api_mod, "_get_settings", fake_settings)

    async def fake_log_query(*args, **kwargs):
        pass

    monkeypatch.setattr("docforge.query_log.log_query", fake_log_query)


@pytest.fixture
def stub_entra(monkeypatch):
    """Install a stub SingleTenantAzureAuthorizationCodeBearer so lifespan
    doesn't hit real Entra URLs. Returns the installed stub scheme."""
    from fastapi_azure_auth import SingleTenantAzureAuthorizationCodeBearer
    from fastapi_azure_auth.openid_config import OpenIdConfig

    async def fake_load(self):
        return None

    monkeypatch.setattr(OpenIdConfig, "load_config", fake_load)

    # Force mode=entra at settings load.
    import docforge.api as api_mod
    monkeypatch.setenv("AUTH__MODE", "entra")
    monkeypatch.setenv("AUTH__TENANT_ID", "test-tenant")
    monkeypatch.setenv("AUTH__AUDIENCE", "api://test-app")
    monkeypatch.setattr(api_mod, "_settings", None)

    scheme = SingleTenantAzureAuthorizationCodeBearer(
        app_client_id="test-app",
        tenant_id="test-tenant",
        scopes={"api://test-app/search": "Search docforge"},
    )
    monkeypatch.setattr(api_mod, "_azure_scheme", scheme)
    return scheme


class TestAuthModeNone:
    """Default auth.mode=none keeps existing behavior."""

    @pytest.mark.asyncio
    async def test_search_accepts_unauthenticated(self, monkeypatch, stub_downstream):
        import docforge.api as api_mod
        monkeypatch.setattr(api_mod, "_azure_scheme", None)

        from docforge.api import app
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.post("/search", json={
                "query": "test", "user_name": "tobias",
                "team_name": "ccl", "area_name": None, "limit": 3,
            })
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_health_always_unauthenticated(self):
        from docforge.api import app
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.get("/health")
        assert resp.status_code == 200


class TestAuthModeEntra:
    """auth.mode=entra gates /search and /sources, leaves /health open."""

    @pytest.mark.asyncio
    async def test_search_rejects_missing_bearer_token(self, stub_entra, stub_downstream):
        from docforge.api import app
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.post("/search", json={
                "query": "test", "user_name": "tobias",
                "team_name": "ccl", "area_name": None, "limit": 3,
            })
        # fastapi-azure-auth raises 401 for missing tokens; HTTPBearer base class
        # would default to 403. Accept either — library-version dependent.
        assert resp.status_code in (401, 403)

    @pytest.mark.asyncio
    async def test_health_still_unauthenticated_under_entra(self, stub_entra):
        from docforge.api import app
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.get("/health")
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_search_accepts_with_mock_user(self, stub_entra, stub_downstream):
        from fastapi_azure_auth.user import User

        from docforge.api import _auth_dependency, app

        fake_user = User(
            claims={}, preferred_username="tobias.ens", oid="abc-oid-123",
            sub="sub", tid="test-tenant", aud="api://test-app",
            access_token="mock", is_guest=False,
            iat=1, nbf=1, exp=99999999,
            iss="iss", aio="aio", uti="uti", rh="rh", ver="2.0",
        )

        async def fake_dep():
            return fake_user

        app.dependency_overrides[_auth_dependency] = fake_dep
        try:
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
                resp = await c.post("/search", json={
                    "query": "test", "user_name": "ignored-in-entra-mode",
                    "team_name": "ccl", "area_name": None, "limit": 3,
                })
            assert resp.status_code == 200
        finally:
            app.dependency_overrides.clear()
