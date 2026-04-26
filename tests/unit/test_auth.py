"""Tests for Entra auth integration in docforge.api."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from httpx import ASGITransport, AsyncClient

from tests.conftest import FakePool


@pytest.fixture
def stub_downstream(monkeypatch, fake_embedder):
    """Short-circuit `/search` past embedder + DB + log_query to keep tests
    focused on auth behavior. Patches names where they are bound inside
    `docforge.api` — matches the pattern used by `test_api.py`."""
    import docforge.api as api_mod

    monkeypatch.setattr(api_mod, "_embedder", fake_embedder())

    async def fake_get_pool(url):
        return FakePool(rows=[])

    monkeypatch.setattr(api_mod, "get_pool", fake_get_pool)

    monkeypatch.setattr(
        api_mod,
        "_get_settings",
        lambda: SimpleNamespace(
            database_url="postgresql://fake",
            tag_match_weight=0.1,
            org_tag_weight=0.05,
        ),
    )

    async def fake_log_query(*args, **kwargs):
        pass

    monkeypatch.setattr("docforge.query_log.log_query", fake_log_query)


@pytest.fixture
def stub_entra(monkeypatch):
    """Install a real `SingleTenantAzureAuthorizationCodeBearer` but stub the
    openid-discovery HTTP call so lifespan doesn't hit Entra."""
    from fastapi_azure_auth import SingleTenantAzureAuthorizationCodeBearer
    from fastapi_azure_auth.openid_config import OpenIdConfig

    async def fake_load(self):
        return None

    monkeypatch.setattr(OpenIdConfig, "load_config", fake_load)

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
            resp = await c.post(
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
            resp = await c.post(
                "/search",
                json={
                    "query": "test",
                    "user_name": "tobias",
                    "team_name": "platform",
                    "area_name": None,
                    "limit": 3,
                },
            )
        # fastapi-azure-auth raises 401 for missing tokens; HTTPBearer base
        # class would default to 403. Accept either — library-version dependent.
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
            claims={},
            preferred_username="tobias.ens",
            oid="abc-oid-123",
            sub="sub",
            tid="test-tenant",
            aud="api://test-app",
            access_token="mock",
            is_guest=False,
            iat=1,
            nbf=1,
            exp=99999999,
            iss="iss",
            aio="aio",
            uti="uti",
            rh="rh",
            ver="2.0",
        )

        async def fake_dep():
            return fake_user

        app.dependency_overrides[_auth_dependency] = fake_dep
        try:
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
                resp = await c.post(
                    "/search",
                    json={
                        "query": "test",
                        "user_name": "ignored-in-entra-mode",
                        "team_name": "platform",
                        "area_name": None,
                        "limit": 3,
                    },
                )
            assert resp.status_code == 200
        finally:
            app.dependency_overrides.clear()


class TestQueryLogCleanup:
    """The app-level cleanup loop deletes rows older than retention_days
    every _CLEANUP_INTERVAL_SECONDS. Verifies it runs and survives transient
    DB errors."""

    @pytest.mark.asyncio
    async def test_cleanup_loop_runs_delete_each_iteration(self, monkeypatch):
        calls: list[tuple] = []

        class _Conn:
            async def execute(self, query, *args):
                calls.append((query, args))
                return "DELETE 0"

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

        import docforge.api as api_mod

        monkeypatch.setattr(api_mod, "get_pool", fake_get_pool)
        monkeypatch.setattr(api_mod, "_CLEANUP_INTERVAL_SECONDS", 0.05)

        task = asyncio.create_task(api_mod._query_log_cleanup_loop("postgresql://fake", 180))
        await asyncio.sleep(0.12)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

        assert len(calls) >= 2
        assert "DELETE FROM query_log" in calls[0][0]
        # retention is embedded into the SQL as a literal via f-string (safe —
        # coerced to int in the production code); asyncpg's $1::interval
        # parameter binding doesn't accept strings.
        assert "interval '180 days'" in calls[0][0]
        assert calls[0][1] == ()

    @pytest.mark.asyncio
    async def test_cleanup_loop_continues_after_db_error(self, monkeypatch):
        # Poll for >=2 iterations rather than sleeping a fixed duration —
        # avoids flakes on slow CI where 0.15 s isn't enough for 2 iterations.
        iteration = {"n": 0}

        async def fake_get_pool(url):
            iteration["n"] += 1
            if iteration["n"] == 1:
                raise OSError("simulated DB hiccup")

            class _Conn:
                async def execute(self, q, *a):
                    return "DELETE 0"

            class _Ctx:
                async def __aenter__(self):
                    return _Conn()

                async def __aexit__(self, *a):
                    pass

            class _Pool:
                def acquire(self):
                    return _Ctx()

            return _Pool()

        import docforge.api as api_mod

        monkeypatch.setattr(api_mod, "get_pool", fake_get_pool)
        monkeypatch.setattr(api_mod, "_CLEANUP_INTERVAL_SECONDS", 0.02)

        task = asyncio.create_task(api_mod._query_log_cleanup_loop("postgresql://fake", 180))
        for _ in range(50):  # up to 1 s total
            await asyncio.sleep(0.02)
            if iteration["n"] >= 2:
                break
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

        assert iteration["n"] >= 2, f"loop died after first failure (reached n={iteration['n']})"
