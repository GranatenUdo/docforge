"""Tests for Entra auth integration in docforge.api."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from httpx import ASGITransport, AsyncClient

from tests.conftest import FakePool


@pytest.fixture
def stub_downstream(fake_embedder):
    """Short-circuit /search past embedder + DB + log_query so auth tests
    can focus on auth behaviour."""
    from docforge.api import app, get_embedder, get_pool_dep, get_settings

    fake_pool = FakePool(rows=[])
    settings_stub = lambda: SimpleNamespace(  # noqa: E731
        database_url="postgresql://fake",
        tag_match_weight=0.1,
        org_tag_weight=0.05,
        pool_min_size=5,
        pool_max_size=25,
        query_log_retention_days=180,
    )

    app.dependency_overrides[get_embedder] = lambda: fake_embedder()
    app.dependency_overrides[get_pool_dep] = lambda: fake_pool
    app.dependency_overrides[get_settings] = settings_stub

    yield

    app.dependency_overrides.clear()


@pytest.fixture
def stub_entra(monkeypatch):
    """Install a real SingleTenantAzureAuthorizationCodeBearer but stub the
    openid-discovery HTTP call. Override `get_azure_scheme` to return it."""
    from fastapi_azure_auth import SingleTenantAzureAuthorizationCodeBearer
    from fastapi_azure_auth.openid_config import OpenIdConfig

    from docforge.api import app, get_azure_scheme

    async def fake_load(self):
        return None

    monkeypatch.setattr(OpenIdConfig, "load_config", fake_load)

    scheme = SingleTenantAzureAuthorizationCodeBearer(
        app_client_id="test-app",
        tenant_id="test-tenant",
        scopes={"api://test-app/search": "Search docforge"},
    )
    app.dependency_overrides[get_azure_scheme] = lambda: scheme

    yield scheme

    app.dependency_overrides.pop(get_azure_scheme, None)


class TestAuthModeNone:
    """Default auth.mode=none keeps existing behavior."""

    @pytest.mark.asyncio
    async def test_search_accepts_unauthenticated(self, stub_downstream):
        from docforge.api import app, get_azure_scheme

        app.dependency_overrides[get_azure_scheme] = lambda: None
        try:
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
        finally:
            app.dependency_overrides.pop(get_azure_scheme, None)

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
            async def fetchval(self, query, *args):
                # Lock acquired
                return True

            async def execute(self, query, *args):
                calls.append((query, args))
                return "DELETE 0"

            def transaction(self):
                return _Tx()

        class _Tx:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                pass

        class _Ctx:
            async def __aenter__(self):
                return _Conn()

            async def __aexit__(self, *a):
                pass

        class _Pool:
            def acquire(self):
                return _Ctx()

        import docforge.api as api_mod

        monkeypatch.setattr(api_mod, "_CLEANUP_INTERVAL_SECONDS", 0.05)

        task = asyncio.create_task(api_mod._query_log_cleanup_loop(_Pool(), 60))
        await asyncio.sleep(0.12)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

        # At least 2 iterations ran the DELETE (lock was always available)
        delete_calls = [c for c in calls if "DELETE FROM query_log" in c[0]]
        assert len(delete_calls) >= 2
        assert "interval '60 days'" in delete_calls[0][0]

    @pytest.mark.asyncio
    async def test_cleanup_loop_continues_after_db_error(self, monkeypatch):
        iteration = {"n": 0}

        class _Conn:
            async def fetchval(self, q, *a):
                return True

            async def execute(self, q, *a):
                return "DELETE 0"

            def transaction(self):
                return _Tx()

        class _Tx:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                pass

        class _Ctx:
            async def __aenter__(self):
                iteration["n"] += 1
                if iteration["n"] == 1:
                    raise OSError("simulated DB hiccup")
                return _Conn()

            async def __aexit__(self, *a):
                pass

        class _Pool:
            def acquire(self):
                return _Ctx()

        import docforge.api as api_mod

        monkeypatch.setattr(api_mod, "_CLEANUP_INTERVAL_SECONDS", 0.02)

        task = asyncio.create_task(api_mod._query_log_cleanup_loop(_Pool(), 60))
        for _ in range(50):
            await asyncio.sleep(0.02)
            if iteration["n"] >= 2:
                break
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

        assert iteration["n"] >= 2, f"loop died after first failure (reached n={iteration['n']})"

    @pytest.mark.asyncio
    async def test_cleanup_loop_skips_when_lock_held_by_another_replica(self, monkeypatch):
        """When pg_try_advisory_xact_lock returns False (another replica holds
        the lock), the loop logs a debug line and skips the DELETE."""
        fetchval_calls: list[tuple] = []
        delete_calls: list[tuple] = []

        class _Conn:
            async def fetchval(self, query, *args):
                fetchval_calls.append((query, args))
                # Simulate "lock unavailable" — another replica has it
                return False

            async def execute(self, query, *args):
                delete_calls.append((query, args))
                return "DELETE 0"

            def transaction(self):
                return _Tx()

        class _Tx:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                pass

        class _Ctx:
            async def __aenter__(self):
                return _Conn()

            async def __aexit__(self, *a):
                pass

        class _Pool:
            def acquire(self):
                return _Ctx()

        import docforge.api as api_mod

        monkeypatch.setattr(api_mod, "_CLEANUP_INTERVAL_SECONDS", 0.05)

        task = asyncio.create_task(api_mod._query_log_cleanup_loop(_Pool(), 60))
        await asyncio.sleep(0.12)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

        # The loop ran ≥1 iteration: at least one fetchval (lock probe) happened
        assert len(fetchval_calls) >= 1
        assert "pg_try_advisory_xact_lock" in fetchval_calls[0][0]
        # No DELETE should fire because the lock was unavailable
        assert delete_calls == []
