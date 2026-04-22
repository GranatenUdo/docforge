# Security + Privacy (Spec C3) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship Entra ID authentication on `/search` + `/sources` (delegated-user flow, hard-enforced when `auth.mode == entra`), add `user_oid` to `query_log` as an additive migration, and publish the threat model + log-privacy supporting documents.

**Architecture:** Auth is opt-in via config. Engine default stays `auth.mode: none` (local dev + other consumers unaffected). When `auth.mode == entra`, FastAPI validates JWTs via `fastapi-azure-auth` against DocuWare's tenant; client-side uses `azure-identity.DefaultAzureCredential` for silent token acquisition. The `query_log` migration is additive — `user_oid TEXT NULL` added; pre-Entra rows keep NULL. `/health` stays open for Container Apps probes; `/search` and `/sources` are gated. 180-day retention enforced by a background asyncio task in FastAPI's `lifespan` (idempotent hourly DELETE; multi-replica-safe).

**Tech Stack:** Python 3.12+, FastAPI, `fastapi-azure-auth>=5.0` (new optional dep), `azure-identity>=1.19` (new optional dep), pydantic-settings, asyncpg + pgvector, Azure Container Apps + Bicep IaC.

**Spec:** `docs/superpowers/specs/2026-04-21-security-privacy-design.md`

**Status during development:** `master` stays deployable throughout. `auth.mode` defaults to `none`; tests cover both `none` and `entra` paths. The live cutover to `auth.mode: entra` happens in Phase 7 after all tests pass and the Entra app registration is in place.

---

## File Structure

**docforge repo:**
- `docforge/config.py` — MODIFY. Add `AuthSettings` pydantic model; add `auth: AuthSettings` field to `Settings`; pass `auth` key through from yml.
- `docforge/api.py` — MODIFY. Conditionally build `azure_scheme`; register `/search` + `/sources` with `Security(azure_scheme)` when `mode == entra`; pass JWT claims into `log_query`.
- `docforge/query_log.py` — MODIFY. Add `user_oid` param; write to new column.
- `docforge/sql/migrations/005_add_query_log_user_oid.sql` — NEW. Additive migration.
- `docforge/pyproject.toml` — MODIFY. `[project.optional-dependencies] entra = [...]`.
- `docforge/deploy/azure/main.bicep` — MODIFY. 3 new auth params + env vars. (pg_cron considered and rejected during plan review — app-level cleanup instead.)
- `docforge/scripts/eval_search.py` — MODIFY. `DefaultAzureCredential` + `--audience` flag.
- `docforge/scripts/README.md` — MODIFY. Document `--audience` + `az login` prereq.
- `docforge/docs/threat-model.md` — NEW. Per spec §3 outline.
- `docforge/tests/unit/test_config.py` — MODIFY. Tests for AuthSettings loading.
- `docforge/tests/unit/test_query_log.py` — MODIFY. Tests for `user_oid` param.
- `docforge/tests/unit/test_auth.py` — NEW. Tests for auth flow (mode=none, mode=entra with mock JWT, /health carve-out).
- `docforge/tests/unit/test_api.py` — MODIFY. Keep existing path under `mode=none`.

**knowledge-hub repo:**
- `knowledge-hub/rag/mcp_client.py` — MODIFY. `DefaultAzureCredential` + auth header.
- `knowledge-hub/rag/docforge.yml` — MODIFY. Set `auth.mode: entra` + tenant_id + audience.
- `knowledge-hub/rag/infrastructure/docforge.bicepparam` — MODIFY. Populate auth params.
- `knowledge-hub/rag/docs/deployment.md` — MODIFY. Append "DocuWare deployment context for threat modelling" section.
- `knowledge-hub/rag/docs/log-privacy.md` — NEW. Per spec §4 outline.
- `knowledge-hub/rag/docs/team-setup-azure.md` — MODIFY. Add `az login` step; correct stale "scales to zero".
- `knowledge-hub/rag/docs/team-setup.md` — MODIFY. Same.

---

## Phase 0 — External prerequisite

### Task 1: Entra app registration (external, manual)

**Files:** None (Azure portal task by the user).

- [ ] **Step 1: Create the app registration**

In the Azure portal, navigate to **Microsoft Entra ID → App registrations → New registration**. Use:
- Name: `docforge-search-api`
- Supported account types: **Single tenant** (DocuWare only)
- Redirect URI: leave blank (this is a protected API, not a client)

After creation, note the **Application (client) ID** and **Directory (tenant) ID** from the overview page.

- [ ] **Step 2: Expose an API with a user-delegated scope**

Under the new app registration → **Expose an API** → **Add a scope**:
- **Application ID URI:** Accept the default `api://<client-id>` (or set explicitly).
- **Scope name:** `search`
- **Who can consent:** Admins and users
- **Admin consent display name:** "Search docforge"
- **Admin consent description:** "Allows the signed-in user to search indexed documentation."
- **State:** Enabled

The full scope identifier becomes `api://<client-id>/search`.

- [ ] **Step 3: Grant admin consent for the `search` scope**

Without this, every first-use surfaces a consent popup. As tenant admin:

- Go to **API permissions** (still on the app-registration blade).
- Click **Add a permission** → **My APIs** → select the `docforge-search-api` app you just registered → **Delegated permissions** → check `search`.
- Click **Grant admin consent for DocuWare** (top of the permissions grid).

Verify: the `search` row now shows "Granted for DocuWare" in green.

- [ ] **Step 4: Record identifiers in a local note (not committed)**

Capture these values — they are **not secrets** but are needed for Task 16 (populate `knowledge-hub/rag/docforge.yml`) and Task 17 (deploy):

```
AZURE_TENANT_ID = <tenant guid>
AZURE_AUDIENCE  = api://<client-id>
```

- [ ] **Step 5: No commit — external task only**

No code change yet. Proceed to Phase 1.

---

## Phase 1 — Database migration (additive, no behavior change)

### Task 2: Write migration 005

**Files:**
- Create: `E:/docforge/docforge/sql/migrations/005_add_query_log_user_oid.sql`

- [ ] **Step 1: Create the migration file**

Write `docforge/sql/migrations/005_add_query_log_user_oid.sql`:

```sql
ALTER TABLE query_log ADD COLUMN IF NOT EXISTS user_oid TEXT;
CREATE INDEX IF NOT EXISTS query_log_user_oid_idx ON query_log (user_oid);
```

- [ ] **Step 2: Apply to local DB**

Ensure local Postgres is running (from `knowledge-hub/rag/docker-compose.yml` or equivalent). Apply:

```bash
cd /e/docforge && /e/docforge/.venv/Scripts/python.exe -c "
import asyncio, asyncpg, os
from pathlib import Path
async def apply():
    url = os.environ.get('LOCAL_DB_URL', 'postgresql://docforge:localdev@localhost:5432/docforge')
    conn = await asyncpg.connect(url)
    sql = Path('docforge/sql/migrations/005_add_query_log_user_oid.sql').read_text()
    await conn.execute(sql)
    await conn.close()
    print('Migration 005 applied')
asyncio.run(apply())
"
```

Expected: prints `Migration 005 applied`. If local DB isn't up, that's OK — this task only creates the file; live application is Phase 7.

- [ ] **Step 3: Commit**

```bash
cd /e/docforge && git add docforge/sql/migrations/005_add_query_log_user_oid.sql && git -c commit.gpgsign=false commit -m "Add migration 005: query_log.user_oid column"
```

---

### Task 3: Extend `query_log.log_query()` to accept `user_oid`

**Files:**
- Modify: `E:/docforge/docforge/query_log.py`
- Modify: `E:/docforge/tests/unit/test_query_log.py`

- [ ] **Step 1: Write the failing tests**

Read the current `tests/unit/test_query_log.py` first to match the existing fixture style. Then append to it:

```python
class TestLogQueryUserOid:
    @pytest.mark.asyncio
    async def test_log_query_accepts_user_oid(self, fake_pool):
        # fake_pool is the fixture already used in existing tests.
        await log_query(
            fake_pool,
            user_name="tobias.ens",
            team_name="ccl",
            area_name="cloud",
            query="test query",
            result_count=3,
            user_oid="abc-123-oid",
        )
        # Inspect the captured INSERT statement parameters.
        assert fake_pool.last_insert_params[-1] == "abc-123-oid"

    @pytest.mark.asyncio
    async def test_log_query_user_oid_defaults_to_none(self, fake_pool):
        await log_query(
            fake_pool,
            user_name="tobias.ens",
            team_name="ccl",
            area_name=None,
            query="q",
            result_count=0,
        )
        # Default must be None so pre-Entra rows have NULL in the DB.
        assert fake_pool.last_insert_params[-1] is None
```

If the existing test file doesn't have a `fake_pool` fixture matching this shape, use the same mock pattern already used by existing tests in that file (they all mock asyncpg somehow).

- [ ] **Step 2: Run the tests and verify they fail**

Run:
```bash
cd /e/docforge && /e/docforge/.venv/Scripts/python.exe -m pytest tests/unit/test_query_log.py::TestLogQueryUserOid -v --no-cov
```
Expected: both tests fail — either with `TypeError: unexpected keyword argument 'user_oid'` or an assertion failure on the captured SQL params.

- [ ] **Step 3: Update `log_query()` in `docforge/query_log.py`**

Current `query_log.py` has this shape (verified via Grep earlier):

```python
async def log_query(
    pool,
    user_name: str,
    team_name: str,
    area_name: str | None,
    query: str,
    result_count: int,
) -> None:
    ...
    await conn.execute(
        """
        INSERT INTO query_log
            (user_name, team_name, area_name, query, result_count)
        VALUES ($1, $2, $3, $4, $5)
        """,
        user_name, team_name, area_name, query, result_count,
    )
```

Change to:

```python
async def log_query(
    pool,
    user_name: str,
    team_name: str,
    area_name: str | None,
    query: str,
    result_count: int,
    user_oid: str | None = None,
) -> None:
    """Record a /search call. user_oid is the Entra object ID (post-auth)
    or None (pre-auth rows)."""
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO query_log
                (user_name, team_name, area_name, query, result_count, user_oid)
            VALUES ($1, $2, $3, $4, $5, $6)
            """,
            user_name, team_name, area_name, query, result_count, user_oid,
        )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run:
```bash
cd /e/docforge && /e/docforge/.venv/Scripts/python.exe -m pytest tests/unit/test_query_log.py -v --no-cov
```
Expected: all tests pass (existing tests still pass because `user_oid` has a default).

- [ ] **Step 5: Commit**

```bash
cd /e/docforge && git add docforge/query_log.py tests/unit/test_query_log.py && git -c commit.gpgsign=false commit -m "Extend log_query() with optional user_oid parameter"
```

---

### Task 4: Update `api.py` caller of `log_query` to forward `user_oid=None`

**Files:**
- Modify: `E:/docforge/docforge/api.py:135`
- Modify: `E:/docforge/docforge/cli.py:222` (CLI's `_search` helper also calls `log_query`)

- [ ] **Step 1: Update callers to explicitly pass `user_oid=None`**

In `docforge/api.py`, find the `log_query` call (around line 135) and change from:

```python
await log_query(pool, req.user_name, req.team_name, req.area_name, req.query, len(rows))
```

to:

```python
await log_query(
    pool,
    req.user_name,
    req.team_name,
    req.area_name,
    req.query,
    len(rows),
    user_oid=None,  # Populated from JWT in Task 10; None for auth.mode=none.
)
```

In `docforge/cli.py`, find the `log_query` call (around line 222) and make the same change.

- [ ] **Step 2: Run full test suite**

Run:
```bash
cd /e/docforge && /e/docforge/.venv/Scripts/python.exe -m pytest tests/unit/ -q
```
Expected: all tests pass; coverage ≥60%.

- [ ] **Step 3: Commit**

```bash
cd /e/docforge && git add docforge/api.py docforge/cli.py && git -c commit.gpgsign=false commit -m "Thread user_oid=None through existing log_query callers"
```

---

## Phase 2 — Config + optional dependency

### Task 5: Add `entra` optional extra to `pyproject.toml`

**Files:**
- Modify: `E:/docforge/pyproject.toml`

- [ ] **Step 1: Add the optional extra**

Read `pyproject.toml` to locate the existing `[project.optional-dependencies]` block (there is one for `dev`). Add an `entra` extra:

```toml
[project.optional-dependencies]
dev = [ ... existing list ... ]
entra = [
    "fastapi-azure-auth>=5.0",
    "azure-identity>=1.19",
]
```

- [ ] **Step 2: Install the extra in the local venv**

Run:
```bash
cd /e/docforge && /e/docforge/.venv/Scripts/python.exe -m pip install -e ".[dev,entra]"
```
Expected: installs `fastapi-azure-auth`, `azure-identity`, and their transitive deps. No errors.

- [ ] **Step 3: Smoke-test imports**

Run:
```bash
/e/docforge/.venv/Scripts/python.exe -c "from fastapi_azure_auth import SingleTenantAzureAuthorizationCodeBearer; from azure.identity.aio import DefaultAzureCredential; print('OK')"
```
Expected: prints `OK`.

- [ ] **Step 4: Commit**

```bash
cd /e/docforge && git add pyproject.toml && git -c commit.gpgsign=false commit -m "Add docforge[entra] optional dependencies"
```

---

### Task 6: Add `AuthSettings` to `docforge/config.py` (TDD)

**Files:**
- Modify: `E:/docforge/docforge/config.py`
- Modify: `E:/docforge/tests/unit/test_config.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_config.py`:

```python
class TestAuthSettings:
    def test_default_mode_is_none(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        from docforge.config import Settings
        s = Settings()
        assert s.auth.mode == "none"
        assert s.auth.tenant_id == ""
        assert s.auth.audience == ""

    def test_loads_auth_from_yml(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        (tmp_path / "docforge.yml").write_text(
            "auth:\n"
            "  mode: entra\n"
            "  tenant_id: t-123\n"
            "  audience: api://a-456\n",
            encoding="utf-8",
        )
        from docforge.config import Settings
        s = Settings()
        assert s.auth.mode == "entra"
        assert s.auth.tenant_id == "t-123"
        assert s.auth.audience == "api://a-456"

    def test_env_overrides_yml(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        (tmp_path / "docforge.yml").write_text(
            "auth:\n  mode: entra\n  tenant_id: t-from-yml\n  audience: api://yml\n",
            encoding="utf-8",
        )
        monkeypatch.setenv("DOCFORGE_AUTH__TENANT_ID", "t-from-env")
        from docforge.config import Settings
        s = Settings()
        assert s.auth.tenant_id == "t-from-env"

    def test_entra_mode_requires_tenant_and_audience(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        (tmp_path / "docforge.yml").write_text(
            "auth:\n  mode: entra\n  tenant_id: ''\n  audience: ''\n",
            encoding="utf-8",
        )
        from docforge.config import Settings
        import pytest as pt
        with pt.raises(ValueError, match="tenant_id"):
            Settings()
```

- [ ] **Step 2: Run the tests and verify they fail**

Run:
```bash
cd /e/docforge && /e/docforge/.venv/Scripts/python.exe -m pytest tests/unit/test_config.py::TestAuthSettings -v --no-cov
```
Expected: all 4 tests fail (`AttributeError: 'Settings' object has no attribute 'auth'` or similar).

- [ ] **Step 3: Add `AuthSettings` to `docforge/config.py`**

Read the current `docforge/config.py` to find the `Settings` class structure and the custom `__init__` that flattens embedding config. Add at the top of the file (after existing imports, before `class Settings`):

```python
from typing import Literal
from pydantic import BaseModel, model_validator


class AuthSettings(BaseModel):
    mode: Literal["none", "entra"] = "none"
    tenant_id: str = ""
    audience: str = ""

    @model_validator(mode="after")
    def _validate_entra_fields(self):
        if self.mode == "entra":
            if not self.tenant_id:
                raise ValueError(
                    "auth.mode=entra requires auth.tenant_id to be set "
                    "(via docforge.yml or DOCFORGE_AUTH__TENANT_ID env var)"
                )
            if not self.audience:
                raise ValueError(
                    "auth.mode=entra requires auth.audience to be set "
                    "(via docforge.yml or DOCFORGE_AUTH__AUDIENCE env var)"
                )
        return self
```

Add `auth: AuthSettings = AuthSettings()` as a field on `Settings` (place it near the other nested groupings, after the identity defaults block).

Also update `Settings.model_config` to enable nested-delimiter env support:

```python
model_config = SettingsConfigDict(
    env_file=".env",
    env_file_encoding="utf-8",
    env_nested_delimiter="__",
)
```

In the custom `__init__` that loads yml, ensure the `auth` nested dict passes through. The current `__init__` flattens `embedding` — add an equivalent passthrough for `auth`:

```python
# In __init__, after the embedding flattening block:
if "auth" in yml:
    yml_values["auth"] = yml.pop("auth")
```

- [ ] **Step 4: Run the tests to verify they pass**

Run:
```bash
cd /e/docforge && /e/docforge/.venv/Scripts/python.exe -m pytest tests/unit/test_config.py -v --no-cov
```
Expected: all tests (existing + new) pass.

- [ ] **Step 5: Commit**

```bash
cd /e/docforge && git add docforge/config.py tests/unit/test_config.py && git -c commit.gpgsign=false commit -m "Add AuthSettings to config with validation"
```

---

## Phase 3 — Server-side auth

### Task 7: Auth dependency scaffold in `api.py` — `mode=none` still works

**Files:**
- Modify: `E:/docforge/docforge/api.py`

This task adds the conditional auth plumbing but keeps `/search` + `/sources` unauthenticated (matching `mode=none` default). No tests fail; existing behavior is preserved.

- [ ] **Step 1: Add the conditional auth scheme setup**

Read `docforge/api.py`. At module level, after the existing imports and `_settings`/`_embedder` globals, add:

```python
_azure_scheme = None  # Set in lifespan if auth.mode == "entra"


def _build_auth_scheme(settings: Settings):
    """Return a SingleTenantAzureAuthorizationCodeBearer if mode==entra, else None."""
    if settings.auth.mode != "entra":
        return None
    from fastapi_azure_auth import SingleTenantAzureAuthorizationCodeBearer

    app_client_id = settings.auth.audience.removeprefix("api://")
    return SingleTenantAzureAuthorizationCodeBearer(
        app_client_id=app_client_id,
        tenant_id=settings.auth.tenant_id,
        scopes={f"{settings.auth.audience}/search": "Search docforge"},
    )
```

Update the `lifespan` function to construct the scheme at startup:

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    global _embedder, _azure_scheme
    settings = _get_settings()
    _azure_scheme = _build_auth_scheme(settings)
    if _azure_scheme is not None:
        await _azure_scheme.openid_config.load_config()
    logger.info("Loading embedding model...")
    _embedder = Embedder(settings.embedding_model, hf_token=settings.hf_token.get_secret_value())
    logger.info("Model loaded: %s (%dd)", _embedder.model_name, _embedder.dimensions)
    yield
    await close_pool()
```

Do not change endpoint decorators yet. Only the scheme is wired; endpoints remain unauthenticated.

- [ ] **Step 2: Run the full suite**

Run:
```bash
cd /e/docforge && /e/docforge/.venv/Scripts/python.exe -m pytest tests/unit/ -q
```
Expected: all tests pass. Existing `/search` and `/sources` tests still use `mode=none` defaults, so `_azure_scheme` stays None.

- [ ] **Step 3: Commit**

```bash
cd /e/docforge && git add docforge/api.py && git -c commit.gpgsign=false commit -m "Add conditional Entra auth scheme to api.py lifespan"
```

---

### Task 8: Gate `/search` and `/sources` on auth when `mode == entra` (TDD)

**Files:**
- Create: `E:/docforge/tests/unit/test_auth.py`
- Modify: `E:/docforge/docforge/api.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_auth.py`. Uses the same `AsyncClient(transport=ASGITransport(app=app))` pattern as the existing `tests/unit/test_api.py`:

```python
"""Tests for Entra auth integration in docforge.api."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from httpx import ASGITransport, AsyncClient


@pytest.fixture
def stub_downstream(monkeypatch):
    """Stub out embedder, DB pool, and log_query so /search reaches its return path
    without touching real infra."""
    class FakeEmbedder:
        model_name = "test"
        dimensions = 768
        def embed_query(self, q): return [0.0] * 768

    import docforge.api as api_mod
    monkeypatch.setattr(api_mod, "_embedder", FakeEmbedder())

    class _Conn:
        async def fetch(self, *a, **k): return []
        async def execute(self, *a, **k): pass

    class _Ctx:
        async def __aenter__(self): return _Conn()
        async def __aexit__(self, *a): pass

    class _Pool:
        def acquire(self): return _Ctx()

    async def fake_get_pool(url): return _Pool()
    monkeypatch.setattr("docforge.db.get_pool", fake_get_pool)

    async def fake_log_query(*args, **kwargs): pass
    monkeypatch.setattr("docforge.query_log.log_query", fake_log_query)


@pytest.fixture
def stub_entra(monkeypatch):
    """Install a stub SingleTenantAzureAuthorizationCodeBearer so lifespan doesn't
    hit real Entra URLs. Returns the installed stub scheme so tests can override
    the dependency."""
    import docforge.api as api_mod
    from fastapi_azure_auth.openid_config import OpenIdConfig

    # Stop openid discovery from hitting the real Entra tenant.
    async def fake_load(self): return None
    monkeypatch.setattr(OpenIdConfig, "load_config", fake_load)

    # Force mode=entra at settings load.
    monkeypatch.setenv("DOCFORGE_AUTH__MODE", "entra")
    monkeypatch.setenv("DOCFORGE_AUTH__TENANT_ID", "test-tenant")
    monkeypatch.setenv("DOCFORGE_AUTH__AUDIENCE", "api://test-app")
    monkeypatch.setattr(api_mod, "_settings", None)

    # Build the scheme manually and install it in place of lifespan wiring.
    from fastapi_azure_auth import SingleTenantAzureAuthorizationCodeBearer
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
        monkeypatch.setattr(api_mod, "_azure_scheme", None)  # mode=none

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
        # No Authorization header -> fastapi-azure-auth's HTTPBearer base raises.
        from docforge.api import app
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.post("/search", json={
                "query": "test", "user_name": "tobias",
                "team_name": "ccl", "area_name": None, "limit": 3,
            })
        # fastapi-azure-auth raises 401 for missing/invalid tokens. HTTPBearer
        # base-class default would be 403; the library overrides to 401.
        assert resp.status_code in (401, 403)  # accept either — library version dependent
        assert resp.status_code != 200

    @pytest.mark.asyncio
    async def test_health_still_unauthenticated_under_entra(self, stub_entra):
        from docforge.api import app
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.get("/health")
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_search_accepts_with_mock_user(self, stub_entra, stub_downstream):
        from fastapi_azure_auth.user import User
        from docforge.api import app, _auth_dependency

        fake_user = User(
            claims={}, preferred_username="tobias.ens", oid="abc-oid-123",
            sub="sub", tid="test-tenant", aud="api://test-app",
            access_token="mock", is_guest=False, iat=1, nbf=1, exp=99999999,
            iss="iss", aio="aio", uti="uti", rh="rh", ver="2.0",
        )

        # Override the wrapper dependency to skip real JWT validation.
        async def fake_dep(): return fake_user
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
```

- [ ] **Step 2: Run the tests and verify they fail**

Run:
```bash
cd /e/docforge && /e/docforge/.venv/Scripts/python.exe -m pytest tests/unit/test_auth.py -v --no-cov
```
Expected: `TestAuthModeNone` tests pass (behavior unchanged); `TestAuthModeEntra::test_search_requires_bearer_token` and `test_search_accepts_with_mock_user` FAIL because `/search` doesn't require auth yet.

- [ ] **Step 3: Gate `/search` and `/sources` in `api.py`**

In `docforge/api.py`, update the `search` and `list_sources` endpoint handlers. FastAPI doesn't support conditional `Security(...)` decorators cleanly, so we use a single dependency function that either returns the auth result or returns None:

```python
from fastapi import Security

async def _auth_dependency(request: Request):
    """Resolve the current user from the auth scheme when auth.mode==entra.
    Returns None when auth.mode==none (so /search handlers can still read
    req.user_name for the legacy path)."""
    if _azure_scheme is None:
        return None
    # fastapi-azure-auth's scheme is a callable dependency;
    # invoke it manually so we can call it conditionally.
    return await _azure_scheme(request)


@app.post("/search", response_model=SearchResponse)
async def search(req: SearchRequest, user=Depends(_auth_dependency)) -> SearchResponse:
    ...
    # When user is not None (auth.mode==entra), prefer token claims:
    effective_user_name = user.preferred_username if user else req.user_name
    effective_user_oid = user.oid if user else None

    # ... (existing embedder + DB code) ...

    await log_query(
        pool,
        effective_user_name,
        req.team_name,
        req.area_name,
        req.query,
        len(rows),
        user_oid=effective_user_oid,
    )
    return SearchResponse(...)
```

Apply the same pattern to `list_sources`:

```python
@app.get("/sources")
async def list_sources(user=Depends(_auth_dependency)) -> dict[str, Any]:
    # user is None when auth.mode==none, authenticated User when entra.
    ...
```

Note: `/health` is unchanged (no `Depends`). Container Apps probes continue to reach it.

- [ ] **Step 4: Run the tests and verify they pass**

Run:
```bash
cd /e/docforge && /e/docforge/.venv/Scripts/python.exe -m pytest tests/unit/test_auth.py -v --no-cov
```
Expected: all 5 tests pass.

- [ ] **Step 5: Run the full suite**

Run:
```bash
cd /e/docforge && /e/docforge/.venv/Scripts/python.exe -m pytest tests/unit/ -q
```
Expected: all tests pass; coverage ≥60%.

- [ ] **Step 6: Commit**

```bash
cd /e/docforge && git add docforge/api.py tests/unit/test_auth.py && git -c commit.gpgsign=false commit -m "Gate /search and /sources on Entra auth when auth.mode==entra"
```

---

## Phase 4 — Client-side integration

### Task 9: Update MCP client to attach Entra tokens

**Files:**
- Modify: `E:/knowledge-hub/rag/mcp_client.py`

- [ ] **Step 1: Add credential + header-building helper**

Edit `knowledge-hub/rag/mcp_client.py`. After the existing imports:

```python
from azure.identity.aio import DefaultAzureCredential

AUDIENCE = os.environ.get("KNOWLEDGE_HUB_AUDIENCE", "").strip()
_credential: DefaultAzureCredential | None = None


async def _auth_header() -> dict[str, str]:
    """Return Authorization header when KNOWLEDGE_HUB_AUDIENCE is set.
    Empty dict otherwise (auth.mode==none path)."""
    global _credential
    if not AUDIENCE:
        return {}
    if _credential is None:
        _credential = DefaultAzureCredential()
    token = await _credential.get_token(f"{AUDIENCE}/.default")
    return {"Authorization": f"Bearer {token.token}"}
```

- [ ] **Step 2: Thread the header into both HTTP calls**

In `search_documentation`, change:

```python
async with httpx.AsyncClient(timeout=30.0) as client:
    resp = await client.post(
        f"{API_URL}/search",
        json={...},
    )
```

to:

```python
headers = await _auth_header()
async with httpx.AsyncClient(timeout=30.0) as client:
    resp = await client.post(
        f"{API_URL}/search",
        headers=headers,
        json={...},
    )
```

Apply the same change to `list_sources` (the GET call).

- [ ] **Step 3: Smoke-test the module imports**

Run:
```bash
/e/docforge/.venv/Scripts/python.exe -c "
import sys
sys.path.insert(0, '/e/knowledge-hub/rag')
import os
os.environ['KNOWLEDGE_HUB_USER'] = 'x'
os.environ['KNOWLEDGE_HUB_TEAM'] = 'x'
import mcp_client
print('OK')
"
```
Expected: prints `OK` with no import errors.

- [ ] **Step 4: Commit (in knowledge-hub)**

```bash
cd /e/knowledge-hub && git add rag/mcp_client.py && git -c commit.gpgsign=false commit -m "MCP client: attach Entra bearer token when KNOWLEDGE_HUB_AUDIENCE is set"
```

---

### Task 10: Update eval harness with `--audience` flag

**Files:**
- Modify: `E:/docforge/docforge/scripts/eval_search.py`
- Modify: `E:/docforge/docforge/scripts/README.md`

- [ ] **Step 1: Add `--audience` flag and token-building helper**

In `docforge/scripts/eval_search.py`, add argparse flag. Update the argparser block in `main()`:

```python
parser.add_argument(
    "--audience",
    default=None,
    help="Entra API audience (e.g., api://<app-id>). Enables Entra auth on outbound calls.",
)
```

Thread `args.audience` into `run_queries`:

```python
results = asyncio.run(
    run_queries(
        api_url=args.api_url.rstrip("/"),
        ground_truth=ground_truth,
        user_name=args.user,
        team_name=args.team,
        area_name=args.area,
        k=args.k,
        audience=args.audience,
    )
)
```

Update `run_queries` signature + body:

```python
async def run_queries(
    api_url: str,
    ground_truth: list[dict],
    user_name: str,
    team_name: str,
    area_name: str | None,
    k: int,
    audience: str | None = None,
) -> list[QueryResult]:
    results: list[QueryResult] = []
    credential = None
    if audience:
        from azure.identity.aio import DefaultAzureCredential
        credential = DefaultAzureCredential()

    async with httpx.AsyncClient(timeout=30.0) as client:
        for entry in ground_truth:
            q: str = entry["q"]
            expected: str = entry["expected_title_contains"]
            headers: dict[str, str] = {}
            if credential is not None:
                token = await credential.get_token(f"{audience}/.default")
                headers["Authorization"] = f"Bearer {token.token}"
            try:
                resp = await client.post(
                    f"{api_url}/search",
                    headers=headers,
                    json={
                        "query": q,
                        "user_name": user_name,
                        "team_name": team_name,
                        "area_name": area_name,
                        "limit": k,
                    },
                )
                resp.raise_for_status()
                payload = resp.json()
                hits = payload.get("results", [])
            except (httpx.HTTPError, ValueError) as e:
                print(f"  Query failed ({q!r}): {e}", file=sys.stderr)
                hits = []
            titles = [h.get("source_title", "") for h in hits]
            scores = [float(h.get("similarity", 0.0)) for h in hits]
            results.append(
                QueryResult(
                    query=q,
                    expected_substring=expected,
                    returned_titles=titles,
                    returned_scores=scores,
                    match_rank=score_query(titles, expected),
                )
            )
    if credential is not None:
        await credential.close()
    return results
```

- [ ] **Step 2: Smoke-test `--help`**

Run:
```bash
cd /e/docforge && /e/docforge/.venv/Scripts/python.exe -m docforge.scripts.eval_search --help 2>&1 | head -15
```
Expected: `--audience` appears in the argument list.

- [ ] **Step 3: Update `docforge/scripts/README.md`**

Read the current `docforge/scripts/README.md`. Append under the "Run against the live Azure deployment" example:

```markdown
### Running against an Entra-protected deployment

If the target API has `auth.mode: entra` enabled, pass `--audience`:

    az login --tenant <DocuWare-tenant-id>
    python -m docforge.scripts.eval_search \
      --api-url https://... \
      --ground-truth .../ground_truth.yml \
      --user your.name --team your-team --area your-area \
      --audience api://<app-id> \
      --k 5

`DefaultAzureCredential` silently picks up the `az login` token and attaches it as a Bearer header on each request.
```

- [ ] **Step 4: Commit**

```bash
cd /e/docforge && git add docforge/scripts/eval_search.py docforge/scripts/README.md && git -c commit.gpgsign=false commit -m "eval_search: add --audience flag for Entra-protected endpoints"
```

---

## Phase 5 — Bicep updates (auth params)

### Task 11: Add auth params + env vars to `main.bicep`

**Files:**
- Modify: `E:/docforge/deploy/azure/main.bicep`

- [ ] **Step 1: Add parameters**

Near the top of `main.bicep` (where `postgresSku`, `minReplicas`, etc. are declared), add:

```bicep
@description('Auth mode: "none" or "entra".')
param authMode string = 'none'

@description('Entra tenant ID (required when authMode=entra).')
param authTenantId string = ''

@description('Entra API audience, e.g., api://<app-id> (required when authMode=entra).')
param authAudience string = ''
```

- [ ] **Step 2: Add env vars to the container app template**

Find `realContainerEnv` (the existing env var array for when `hasRealImage` is true). Add these three entries:

```bicep
{
  name: 'DOCFORGE_AUTH__MODE'
  value: authMode
}
{
  name: 'DOCFORGE_AUTH__TENANT_ID'
  value: authTenantId
}
{
  name: 'DOCFORGE_AUTH__AUDIENCE'
  value: authAudience
}
```

- [ ] **Step 3: Validate the Bicep compiles**

Run:
```bash
cd /e/docforge && az bicep build --file deploy/azure/main.bicep --stdout 2>&1 | head -5
```
Expected: no errors; the ARM template JSON is emitted. (If `az` is not installed locally, skip this step — the next deploy in Task 17 will surface any errors.)

- [ ] **Step 4: Commit**

```bash
cd /e/docforge && git add deploy/azure/main.bicep && git -c commit.gpgsign=false commit -m "Bicep: add authMode/authTenantId/authAudience params + env vars"
```

---

### Task 12: App-level `query_log` cleanup loop in FastAPI lifespan

**Files:**
- Modify: `E:/docforge/docforge/config.py`
- Modify: `E:/docforge/docforge/api.py`
- Modify: `E:/docforge/tests/unit/test_config.py`
- Modify: `E:/docforge/tests/unit/test_auth.py` (extend)

Post-review change: rather than pg_cron on Azure Flexible Server (which requires `shared_preload_libraries` + `CREATE EXTENSION` in the `postgres` database + `cron.schedule_in_database` for cross-db scheduling), the cleanup runs as an asyncio task from FastAPI's `lifespan`. Idempotent, works regardless of replica count, no Azure-specific setup.

- [ ] **Step 1: Add `query_log_retention_days` setting (TDD)**

Append to `tests/unit/test_config.py`:

```python
class TestQueryLogRetention:
    def test_default_retention_days(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        from docforge.config import Settings
        s = Settings()
        assert s.query_log_retention_days == 180

    def test_retention_overridable_in_yml(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        (tmp_path / "docforge.yml").write_text(
            "query_log_retention_days: 90\n", encoding="utf-8",
        )
        from docforge.config import Settings
        s = Settings()
        assert s.query_log_retention_days == 90
```

Run:
```bash
cd /e/docforge && /e/docforge/.venv/Scripts/python.exe -m pytest tests/unit/test_config.py::TestQueryLogRetention -v --no-cov
```
Expected: both fail.

- [ ] **Step 2: Add the field to `Settings`**

In `docforge/config.py`, add alongside the other flat settings:

```python
query_log_retention_days: int = 180
```

Run the tests again — both pass.

- [ ] **Step 3: Add the cleanup loop to `api.py`**

In `docforge/api.py`, at module level, add:

```python
import asyncio

_cleanup_task: asyncio.Task | None = None

_CLEANUP_INTERVAL_SECONDS = 3600  # one hour


async def _query_log_cleanup_loop(database_url: str, retention_days: int) -> None:
    """Runs hourly. Deletes query_log rows older than retention_days.
    Idempotent: no-op when nothing to delete, so multi-replica is safe."""
    from docforge.db import get_pool
    while True:
        try:
            pool = await get_pool(database_url)
            async with pool.acquire() as conn:
                result = await conn.execute(
                    "DELETE FROM query_log WHERE created_at < now() - $1::interval",
                    f"{retention_days} days",
                )
            logger.info("query_log cleanup: %s", result)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            # Never let the loop die on a transient failure — just log and retry.
            logger.exception("query_log cleanup failed: %s", e)
        try:
            await asyncio.sleep(_CLEANUP_INTERVAL_SECONDS)
        except asyncio.CancelledError:
            raise
```

Update `lifespan`:

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    global _embedder, _azure_scheme, _cleanup_task
    settings = _get_settings()
    _azure_scheme = _build_auth_scheme(settings)
    if _azure_scheme is not None:
        await _azure_scheme.openid_config.load_config()
    logger.info("Loading embedding model...")
    _embedder = Embedder(settings.embedding_model, hf_token=settings.hf_token.get_secret_value())
    logger.info("Model loaded: %s (%dd)", _embedder.model_name, _embedder.dimensions)

    _cleanup_task = asyncio.create_task(
        _query_log_cleanup_loop(settings.database_url, settings.query_log_retention_days)
    )

    yield

    if _cleanup_task is not None:
        _cleanup_task.cancel()
        try:
            await _cleanup_task
        except asyncio.CancelledError:
            pass
    await close_pool()
```

- [ ] **Step 4: Unit test the loop logic**

Append to `tests/unit/test_auth.py` (the test module already imports `asyncio`):

```python
class TestQueryLogCleanup:
    @pytest.mark.asyncio
    async def test_cleanup_loop_runs_delete_once_per_iteration(self, monkeypatch):
        calls = []

        class _Conn:
            async def execute(self, query, *args):
                calls.append((query, args))
                return "DELETE 0"

        class _Ctx:
            async def __aenter__(self): return _Conn()
            async def __aexit__(self, *a): pass

        class _Pool:
            def acquire(self): return _Ctx()

        async def fake_get_pool(url): return _Pool()
        monkeypatch.setattr("docforge.db.get_pool", fake_get_pool)

        # Shrink the sleep so we can assert without waiting an hour.
        import docforge.api as api_mod
        monkeypatch.setattr(api_mod, "_CLEANUP_INTERVAL_SECONDS", 0.05)

        task = asyncio.create_task(
            api_mod._query_log_cleanup_loop("postgresql://fake", 180)
        )
        await asyncio.sleep(0.12)  # time for at least 2 iterations
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

        assert len(calls) >= 2
        # Verify the DELETE query and the retention interval argument.
        assert "DELETE FROM query_log" in calls[0][0]
        assert calls[0][1] == ("180 days",)

    @pytest.mark.asyncio
    async def test_cleanup_loop_continues_after_db_error(self, monkeypatch):
        iteration = {"n": 0}

        async def fake_get_pool(url):
            iteration["n"] += 1
            if iteration["n"] == 1:
                raise OSError("simulated DB hiccup")
            class _Conn:
                async def execute(self, q, *a): return "DELETE 0"
            class _Ctx:
                async def __aenter__(self): return _Conn()
                async def __aexit__(self, *a): pass
            class _Pool:
                def acquire(self): return _Ctx()
            return _Pool()

        monkeypatch.setattr("docforge.db.get_pool", fake_get_pool)

        import docforge.api as api_mod
        monkeypatch.setattr(api_mod, "_CLEANUP_INTERVAL_SECONDS", 0.05)

        task = asyncio.create_task(
            api_mod._query_log_cleanup_loop("postgresql://fake", 180)
        )
        await asyncio.sleep(0.15)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

        # We expect iteration to have advanced past the failing first try.
        assert iteration["n"] >= 2
```

- [ ] **Step 5: Run the tests**

```bash
cd /e/docforge && /e/docforge/.venv/Scripts/python.exe -m pytest tests/unit/test_config.py tests/unit/test_auth.py -v --no-cov
```
Expected: all pass.

- [ ] **Step 6: Run the full suite**

```bash
cd /e/docforge && /e/docforge/.venv/Scripts/python.exe -m pytest tests/unit/ -q
```
Expected: all pass; coverage ≥60%.

- [ ] **Step 7: Commit**

```bash
cd /e/docforge && git add docforge/config.py docforge/api.py tests/unit/test_config.py tests/unit/test_auth.py && git -c commit.gpgsign=false commit -m "Add query_log cleanup loop in FastAPI lifespan (180-day retention)"
```

---

## Phase 6 — Supporting documents

### Task 13: Write `docforge/docs/threat-model.md`

**Files:**
- Create: `E:/docforge/docs/threat-model.md`

- [ ] **Step 1: Write the doc per spec §3 outline**

Create `docforge/docs/threat-model.md`:

```markdown
# docforge threat model

**Scope:** This document threat-models the docforge engine code and the reference Azure deployment described in `docforge/deploy/azure/main.bicep`. It does NOT cover consumer-specific Azure subscription governance or tenant-level policies — those are consumer concerns (see `knowledge-hub/rag/docs/deployment.md` for DocuWare's specifics).

**Reader:** Someone evaluating docforge for adoption, or an engineer reviewing the deployed DocuWare system.

## Trust model

- **Single-company, single-tenant.** No cross-tenant isolation; no customer data segregation.
- **Indexed content is non-sensitive corporate documentation.** The `sources` and `chunks` tables hold Confluence pages and git-repo markdown that the operator's organization has already classified as internal-engineering-sharing-appropriate. No PII, no customer data, no secrets.
- **`query_log` is the only semi-sensitive datum.** Per-user query history. Governed by the consumer's log-privacy policy (DocuWare deployment: `knowledge-hub/rag/docs/log-privacy.md`).
- **Authenticated users are trusted.** An engineer with a valid Entra token is trusted to query any source. Auth is access control; there is no authorization layer beyond it — no per-source ACLs.
- **The operator is trusted.** Whoever has Azure subscription admin rights is trusted to not tamper with the deployment.

## Assets

| Asset | Location | Sensitivity |
|---|---|---|
| Indexed docs (sources + chunks) | Postgres Flexible Server | Internal (org-classified) |
| `query_log` rows | Postgres Flexible Server | Semi-sensitive (per-user history) |
| HuggingFace API token | Azure Key Vault | Secret |
| Confluence API token | Azure Key Vault | Secret |
| DB connection string | Azure Key Vault | Secret |
| Container image | Azure Container Registry | Non-secret (distribution-controlled) |

## Threat surfaces and mitigations

| Surface | Threats considered | Mitigations shipped |
|---|---|---|
| Public HTTPS `/search` + `/sources` | Unauthenticated query; credential stuffing against self-declared `user_name`; enumeration | Entra ID delegated auth required (`docforge/api.py`, `auth.mode == entra`); `user_oid` from JWT replaces self-declared identity in `query_log` (migration `005_add_query_log_user_oid.sql`); only `/health` is unauthenticated and returns no index content |
| `/health` open endpoint | Endpoint fingerprinting; DoS amplification | Returns static JSON (`{"status": "ok", ...}`); no DB access; rate-limited by Container Apps default ingress |
| FastAPI app code | JWT validation bypass; injection in query text | `fastapi-azure-auth` validates against Entra OpenID config loaded at startup; query text is parameterised (asyncpg bind params); no SQL string concatenation |
| MCP client (`knowledge-hub/rag/mcp_client.py`) | Token exfiltration; stale token reuse | `DefaultAzureCredential` keeps tokens in-memory only; token refresh is library-handled; no token logging |
| Ingest pipeline | Poisoned Confluence/git content injecting prompt-injection payloads into search results | Out of scope for this iteration; documented as residual risk below |
| Azure Key Vault | Secret exfiltration via misconfigured RBAC | System-assigned managed identity only; no human accounts granted `get-secret` in `main.bicep` |
| Postgres Flexible Server | DB compromise via connection-string leak | Connection string held in Key Vault; retrieved only at container boot; container runs as UID 1000 with no write access to logs that would contain it |
| Container image | Supply-chain attack via base image or Python deps | Dependabot updates weekly (`.github/dependabot.yml`); base image pinned to `python:3.12-slim-bookworm`; no untrusted build steps |
| Dependency CVEs | Known vulnerabilities in runtime deps | Dependabot opens PRs on CVE disclosure; merged against master under branch protection |

## Risks accepted

- **Bus factor of 1.** Single maintainer. Loss-of-availability risk, not loss-of-confidentiality. Named plainly; mitigation requires a second maintainer, which is outside C3's scope.
- **HuggingFace-gated embedding model.** EmbeddingGemma-300M requires a HuggingFace token. Model-provider compromise or gating policy change would block re-ingest. Accepted; re-ingestable from a different provider if the need arises.
- **DB backup window = 7 days.** `Standard_B1ms` default on Postgres Flexible Server. Data older than 7 days cannot be restored via point-in-time recovery. Accepted as cost-appropriate for current scale.
- **Prompt-injection via indexed content.** Malicious content in an indexed source (Confluence page, README) could attempt to manipulate the LLM that consumes search results. Mitigation is operational (source-review discipline by the owning team), not code-level in this iteration.
- **No per-source ACLs.** Any authenticated user can query any indexed source. Appropriate for a single-company tool with org-classified content; not a multi-tenant assumption.

## Out of scope

- Multi-tenant isolation (the tool is single-tenant by design).
- Consumer-specific Entra tenant policies (MFA, conditional access). These are tenant-admin configuration, not docforge code. See `knowledge-hub/rag/docs/deployment.md` for DocuWare's specifics.
- Azure subscription governance (who has owner/contributor rights, break-glass accounts). Consumer-specific.
- Physical security of the Postgres data.

## Review cadence

This threat model is reviewed on major docforge version changes, on changes to the deployment topology (`main.bicep`), and at least annually.
```

- [ ] **Step 2: Audit for banned vague terms**

Run:
```bash
cd /e/docforge && grep -inE "robust|scalable|enterprise-grade|production-ready|secure[^s]" docs/threat-model.md | head
```
Expected: no matches, or only in acceptable contexts (e.g., "secrets" is fine).

- [ ] **Step 3: Commit**

```bash
cd /e/docforge && git add docs/threat-model.md && git -c commit.gpgsign=false commit -m "Add docforge/docs/threat-model.md (C3.3)"
```

---

### Task 14: Append DocuWare deployment context to `knowledge-hub/rag/docs/deployment.md`

**Files:**
- Modify: `E:/knowledge-hub/rag/docs/deployment.md`

- [ ] **Step 1: Append the new section**

Read the current `knowledge-hub/rag/docs/deployment.md`. At the bottom, append:

```markdown
## DocuWare deployment context for threat modelling

This section supplements `docforge/docs/threat-model.md` with DocuWare-specific facts the generic threat model deliberately omits.

- **Azure subscription:** `CloudCL-Test`
- **Resource group:** `cloudcl-test-docforge-rg`
- **Entra tenant:** DocuWare (populate real tenant ID at write time)
- **Tenant-level policies relevant to docforge:** MFA enforced for all Entra logins (DocuWare-wide); conditional-access rules inherited from tenant defaults
- **Runtime Key Vault:** populate real Key Vault name at write time
- **Postgres Flexible Server SKU:** `Standard_B1ms` with 7-day backup retention (override in `rag/infrastructure/docforge.bicepparam` if changed)
- **Repos governed by branch protection + required CI:**
  - `docforge` (GitHub, private; 2 CI checks required before merge)
  - `knowledge-hub` (ADO `dwcr`; ADO pipeline `config-validation.yml` gates YAML changes)
- **Who can merge to `docforge` master:** GranatenUdo (until repo goes public and wider permissions are configured)
- **Who can merge to `knowledge-hub` master:** CCL team (approver list in ADO policy)
```

- [ ] **Step 2: Commit (in knowledge-hub)**

```bash
cd /e/knowledge-hub && git add rag/docs/deployment.md && git -c commit.gpgsign=false commit -m "Append DocuWare deployment context for threat modelling (C3.3)"
```

---

### Task 15: Write `knowledge-hub/rag/docs/log-privacy.md`

**Files:**
- Create: `E:/knowledge-hub/rag/docs/log-privacy.md`

- [ ] **Step 1: Write the doc per spec §4 outline**

Create `knowledge-hub/rag/docs/log-privacy.md`:

```markdown
# query_log privacy policy — DocuWare CCL deployment

## Purpose and scope

`query_log` is an append-only record of `/search` calls against the docforge search API. This policy defines retention, access, aggregation, and purpose-of-use rules for `query_log` in the DocuWare CCL deployment at `docforge-search-api.ashyhill-c79f3b95.westeurope.azurecontainerapps.io`. Other consumers of docforge write their own policies.

## What `query_log` contains

| Column | Type | Source | Sensitivity |
|---|---|---|---|
| `id` | UUID | generated | non-sensitive |
| `user_name` | TEXT NOT NULL | pre-Entra: self-declared; post-Entra: JWT `preferred_username` claim | semi-sensitive (identity) |
| `user_oid` | TEXT NULL | JWT `oid` claim (post-Entra); NULL for pre-Entra rows | semi-sensitive (canonical identity) |
| `team_name` | TEXT NOT NULL | client-supplied routing hint | non-sensitive |
| `area_name` | TEXT NULL | client-supplied routing hint | non-sensitive |
| `query` | TEXT NOT NULL | user-typed query string | semi-sensitive (could reveal intent) |
| `result_count` | INT NOT NULL | server-computed | non-sensitive |
| `created_at` | TIMESTAMPTZ NOT NULL | server time | non-sensitive |

**Sensitivity definition:** "Semi-sensitive" = internal-to-DocuWare use only; not to be shared outside DocuWare; not exported in aggregate form that would allow outsiders to correlate individuals to query patterns.

## Retention

**180 days rolling.** Rows with `created_at < now() - interval '180 days'` are deleted by an automated job.

**Cleanup mechanism:** the docforge API process runs this DELETE hourly from its FastAPI lifespan background task:

```sql
DELETE FROM query_log WHERE created_at < now() - interval '180 days';
```

The query is idempotent (no-op when nothing to delete), so multi-replica deployments run it in parallel safely — Postgres serializes.

**Cutover date:** The Entra authentication rollout completed on `<POPULATE-AT-TASK-21>`. Rows with `created_at < <cutover-date>` have `user_oid = NULL`; rows from the cutover onward have a populated `user_oid`. Reports that require trustworthy identity filter `WHERE user_oid IS NOT NULL` or `created_at >= '<cutover-date>'`.

**Rationale for 180 days:** operational window for multi-quarter adoption-trend analysis. Not longer because the data is not needed for year-over-year comparisons given single-team scope. Not shorter because adoption signals emerge over multi-sprint cycles.

**Why not pg_cron:** the original spec considered pg_cron. Azure Flexible Server setup (allowlist + `shared_preload_libraries` + `CREATE EXTENSION` in the `postgres` database + `cron.schedule_in_database` for cross-DB jobs) is more infrastructure than the idempotent cleanup query warrants. Revisit if the cleanup ever grows beyond a single DELETE.

## Access

- **Read:** Tobias Ens (current maintainer) via `psql` connection using the admin connection string held in Azure Key Vault.
- **Write:** only the running FastAPI app, via the app's managed-identity-granted DB connection.
- **Cannot read:** end users, colleagues, anyone without Key Vault `get-secret` access.
- **Audit:** Key Vault logs secret-retrieval events; Postgres Flexible Server logs connections. Review on incident; not proactive.

## Aggregation and reporting

Reports derived from `query_log` for the Spec D readiness assessment and for operational adoption tracking:

- Aggregate by `team_name` / `area_name` / month; do NOT expose individual queries.
- **Minimum cell size: 3 distinct users.** Any aggregate group with fewer than 3 distinct users is suppressed in reports (standard anti-reidentification guard).
- **Query text:** aggregate reports never include raw query strings. Counts, timestamps, distinct-users-per-team are permitted. Raw queries remain in the database and are accessible only per "Access" above.

## Purpose limitation

`query_log` is used for:
1. Operational debugging ("did this user's search fail, and why?")
2. Adoption evidence ("is the team using docforge? how frequently?")
3. Spec D readiness-assessment metrics

`query_log` is NOT used for:
- Individual performance evaluation
- Identifying "heavy users" by name
- Any purpose that correlates query content to individuals beyond operational debugging

## Deletion on request

Any DocuWare engineer can request deletion of their rows by Entra object ID (OID) or `preferred_username`.

- **Request path:** email to the current maintainer with the engineer's Entra OID (or `preferred_username`, for pre-Entra rows).
- **SLA:** processed within 5 business days.
- **Pre-Entra rows** (`user_oid IS NULL`) are identified by `user_name` only; the requester confirms their `user_name` at request time.

## GDPR posture

- **Data controller:** DocuWare.
- **Lawful basis:** legitimate interests — internal-engineering-tool operational telemetry.
- **Data subjects:** DocuWare engineers who opt into using the MCP client.
- **Cross-border transfer:** all data remains in Azure West Europe region.
- **Processor:** DocuWare internal; no external sub-processors.

This policy is the tool-specific addendum to DocuWare's internal GDPR framework.

## Appendix — example reporting queries

### Distinct users in the last 30 days (with ≥3-user minimum-cell guard)

```sql
WITH raw AS (
    SELECT DATE_TRUNC('week', created_at) AS week,
           COUNT(DISTINCT user_oid) AS distinct_users,
           COUNT(*) AS queries
    FROM query_log
    WHERE user_oid IS NOT NULL
      AND created_at >= now() - interval '30 days'
    GROUP BY week
)
SELECT week,
       CASE WHEN distinct_users >= 3 THEN distinct_users END AS distinct_users_visible,
       CASE WHEN distinct_users >= 3 THEN queries END AS queries_visible
FROM raw
ORDER BY week;
```

### Adoption by team (post-Entra only)

```sql
SELECT team_name,
       COUNT(DISTINCT user_oid) AS distinct_users,
       COUNT(*) AS queries
FROM query_log
WHERE user_oid IS NOT NULL
  AND created_at >= now() - interval '90 days'
GROUP BY team_name
HAVING COUNT(DISTINCT user_oid) >= 3
ORDER BY distinct_users DESC;
```

### Find a user's history (for deletion request)

```sql
-- By OID (post-Entra)
SELECT id, created_at, query, result_count
FROM query_log
WHERE user_oid = '<oid>'
ORDER BY created_at;

-- By user_name (pre-Entra only)
SELECT id, created_at, query, result_count
FROM query_log
WHERE user_oid IS NULL
  AND user_name = '<preferred_username>'
ORDER BY created_at;
```
```

- [ ] **Step 2: Commit (in knowledge-hub)**

```bash
cd /e/knowledge-hub && git add rag/docs/log-privacy.md && git -c commit.gpgsign=false commit -m "Add rag/docs/log-privacy.md (C3.4)"
```

---

## Phase 7 — Deploy and live validation

### Task 16: Update `knowledge-hub` config to enable Entra

**Files:**
- Modify: `E:/knowledge-hub/rag/docforge.yml`
- Modify: `E:/knowledge-hub/rag/infrastructure/docforge.bicepparam`

- [ ] **Step 1: Set auth values in `knowledge-hub/rag/docforge.yml`**

Read the current `knowledge-hub/rag/docforge.yml`. Append (or add a new `auth` block if one doesn't exist):

```yaml
auth:
  mode: entra
  tenant_id: <AZURE_TENANT_ID from Task 1 Step 3>
  audience: api://<AZURE_AUDIENCE client-id portion from Task 1 Step 3>
```

Use the actual tenant and audience values recorded in Task 1 Step 3.

- [ ] **Step 2: Set auth params in `knowledge-hub/rag/infrastructure/docforge.bicepparam`**

Read the current `docforge.bicepparam`. Add:

```bicep
param authMode = 'entra'
param authTenantId = '<AZURE_TENANT_ID>'
param authAudience = 'api://<AZURE_AUDIENCE client-id portion>'
```

- [ ] **Step 3: Commit (in knowledge-hub)**

```bash
cd /e/knowledge-hub && git add rag/docforge.yml rag/infrastructure/docforge.bicepparam && git -c commit.gpgsign=false commit -m "Enable Entra auth in CCL docforge deployment"
```

---

### Task 17: Deploy to Azure

**Files:** None (Azure task).

- [ ] **Step 1: Rebuild the docforge container image**

From the existing deploy flow — using `az acr build` so the image is built in Azure (proxy-free):

```bash
cd /e/docforge && az acr build \
  --registry dwdocforgeacr \
  --image docforge:c3-entra \
  --source .
```

Expected: successful build; image tag `c3-entra` appears in the registry.

- [ ] **Step 2: Deploy via the existing deploy script**

From `knowledge-hub/rag/infrastructure/`:

```bash
cd /e/knowledge-hub/rag/infrastructure && ./deploy.sh
```

(Or whichever deploy command the existing pipeline uses — the script wraps `az deployment group create` against `main.bicep` with `docforge.bicepparam`.)

Expected: deployment completes; new revision of the container app comes up; probes pass within the 10-minute startup window.

- [ ] **Step 3: Check the app started cleanly**

Run:
```bash
az containerapp logs show --name docforge-search-api --resource-group cloudcl-test-docforge-rg --tail 50 | tail -30
```
Expected logs include "Model loaded" and no auth-related errors. If `openid_config.load_config` fails, the logs will say so; fix the tenant_id or audience and redeploy.

- [ ] **Step 4: Smoke-test `/health` (unauthenticated)**

Run:
```bash
curl -sf https://docforge-search-api.ashyhill-c79f3b95.westeurope.azurecontainerapps.io/health
```
Expected: HTTP 200 JSON response.

- [ ] **Step 5: Smoke-test `/search` without auth (expect 401)**

Run:
```bash
curl -si -X POST -H "Content-Type: application/json" \
  -d '{"query":"test","user_name":"x","team_name":"x","limit":1}' \
  https://docforge-search-api.ashyhill-c79f3b95.westeurope.azurecontainerapps.io/search \
  | head -10
```
Expected: HTTP 401.

- [ ] **Step 6: No commit (infra task)**

---

### Task 18: End-to-end validation from a real MCP client invocation

**Files:** None (validation task).

- [ ] **Step 1: `az login` against DocuWare tenant**

Run:
```bash
az login --tenant <DocuWare-tenant-id>
```
Complete the browser flow. Expected: signed into DocuWare tenant with your engineering account.

- [ ] **Step 2: Export `KNOWLEDGE_HUB_AUDIENCE` and re-register the MCP client**

The existing MCP registration in `~/.claude.json` (or its knowledge-hub subcommand equivalent) was set up in a prior phase without the audience env var. Update the env block to include:

```
KNOWLEDGE_HUB_AUDIENCE=api://<client-id>
```

If the MCP client was registered via `claude mcp add`, re-register with the extra `-e` flag. Alternatively edit `~/.claude.json` directly.

- [ ] **Step 3: Restart Claude Code and verify MCP connection**

Exit and reopen Claude Code. Run `/mcp`. Expected: `knowledge-hub: Connected`.

- [ ] **Step 4: Perform a real search query**

In a Claude Code conversation, ask: "Which team is responsible for Organization Lifecycle?"

Expected: Claude calls the `search_documentation` MCP tool; results come back; no 401 errors in the MCP logs.

If there's a 401, check (in order): `az login` was against the right tenant; `KNOWLEDGE_HUB_AUDIENCE` matches the deployed `authAudience`; the Entra app registration's scope is `api://<id>/search` not `api://<id>`.

- [ ] **Step 5: Verify `query_log.user_oid` is populated for the new query**

Run (with admin DB credentials):
```bash
/e/docforge/.venv/Scripts/python.exe -c "
import asyncio, asyncpg, os
async def check():
    conn = await asyncpg.connect(os.environ['ADMIN_DB_URL'])
    row = await conn.fetchrow(
        'SELECT user_name, user_oid, created_at FROM query_log ORDER BY created_at DESC LIMIT 1'
    )
    print(dict(row) if row else 'no rows')
    await conn.close()
asyncio.run(check())
"
```
Expected: the latest row has a non-NULL `user_oid` and a `user_name` matching your `preferred_username`.

- [ ] **Step 6: Re-run eval harness against authenticated endpoint**

Run:
```bash
cd /e/docforge && /e/docforge/.venv/Scripts/python.exe -m docforge.scripts.eval_search \
  --api-url https://docforge-search-api.ashyhill-c79f3b95.westeurope.azurecontainerapps.io \
  --ground-truth /e/knowledge-hub/rag/eval/ground_truth.yml \
  --user tobias.ens --team ccl --area cloud \
  --audience api://<client-id> \
  --k 5 2>&1 | tail -6
```
Expected: summary shows `recall@1: 10/25 (40%)`, `recall@5: 19/25 (76%)`, `mrr: 0.533` — identical to the pre-Entra baseline (retrieval logic unchanged).

- [ ] **Step 7: No commit (validation task)**

If any of the above fails, stop and diagnose before proceeding. Record the Entra go-live date (this task's completion date) — it's the cutover date used in Task 21.

---

## Phase 8 — Cleanup verification in production

### Task 19: Verify the app-level cleanup runs end-to-end against the deployed API

**Files:** None (validation task against the live Azure deployment).

The cleanup loop is wired into the lifespan in Task 12 and ships with the deployment in Task 17. This task confirms the deployed container actually runs it.

- [ ] **Step 1: Confirm the cleanup loop started at container boot**

```bash
az containerapp logs show --name docforge-search-api --resource-group cloudcl-test-docforge-rg --tail 200 2>&1 | grep -E "query_log cleanup|Loading embedding"
```
Expected: at least one `query_log cleanup: DELETE <n>` log line from the most recent container start. `<n>` will usually be 0 on a fresh deployment.

- [ ] **Step 2: Insert a synthetic row dated >180 days ago**

```bash
/e/docforge/.venv/Scripts/python.exe -c "
import asyncio, asyncpg, os, uuid
async def ins():
    conn = await asyncpg.connect(os.environ['ADMIN_DB_URL'])
    row_id = str(uuid.uuid4())
    await conn.execute(\"\"\"
        INSERT INTO query_log (id, user_name, team_name, query, result_count, created_at)
        VALUES (\$1, 'synthetic-cleanup-test', 'ccl', 'dummy', 0, now() - interval '181 days')
    \"\"\", row_id)
    print(f'Inserted {row_id}')
    await conn.close()
asyncio.run(ins())
"
```

- [ ] **Step 3: Trigger a container restart to force the lifespan cleanup to run within seconds (instead of waiting up to an hour)**

```bash
az containerapp revision restart --name docforge-search-api --resource-group cloudcl-test-docforge-rg --revision $(az containerapp revision list --name docforge-search-api --resource-group cloudcl-test-docforge-rg --query "[0].name" -o tsv)
```

Wait ~30 seconds for the new container to boot past the embedding-model-load warm-up.

- [ ] **Step 4: Confirm the synthetic row was deleted**

```bash
/e/docforge/.venv/Scripts/python.exe -c "
import asyncio, asyncpg, os
async def check():
    conn = await asyncpg.connect(os.environ['ADMIN_DB_URL'])
    row = await conn.fetchrow(\"SELECT * FROM query_log WHERE user_name = 'synthetic-cleanup-test'\")
    print('still present — cleanup did not run' if row else 'deleted as expected')
    await conn.close()
asyncio.run(check())
"
```
Expected: `deleted as expected`. If `still present`, check the container logs (Step 1) — if there's no "query_log cleanup" line, the container hasn't booted yet; wait longer. If there IS a line but the row survived, the DELETE query has a bug — compare to the SQL in Task 12 Step 3.

- [ ] **Step 5: No commit (validation task)**

---

## Phase 9 — Team-setup docs + cutover annotation

### Task 20: Update `team-setup-azure.md` and `team-setup.md`

**Files:**
- Modify: `E:/knowledge-hub/rag/docs/team-setup-azure.md`
- Modify: `E:/knowledge-hub/rag/docs/team-setup.md`

- [ ] **Step 1: Update `team-setup-azure.md`**

Read the current `team-setup-azure.md`. Make three edits:

1. **Prerequisites section** — add `az login` to the list:

```markdown
## Prerequisites

- Python 3.12+ (`python --version`)
- Claude Code installed
- Azure CLI installed + signed into DocuWare tenant: `az login --tenant <DocuWare-tenant-id>`
```

2. **Environment section** — add `KNOWLEDGE_HUB_AUDIENCE`:

Under the existing `KNOWLEDGE_HUB_USER`/`KNOWLEDGE_HUB_TEAM`/`KNOWLEDGE_HUB_AREA` env-var block, append:

```
KNOWLEDGE_HUB_AUDIENCE=api://<client-id>    # required for Entra auth; same for everyone
```

3. **`claude mcp add` command** — add the `-e KNOWLEDGE_HUB_AUDIENCE=...` flag:

Find the existing `claude mcp add` block and add the audience flag so it becomes:

```bash
claude mcp add -s user \
  -e KNOWLEDGE_HUB_API_URL="<API_URL>" \
  -e KNOWLEDGE_HUB_USER="your.name" \
  -e KNOWLEDGE_HUB_TEAM="your-team-tag" \
  -e KNOWLEDGE_HUB_AREA="your-area-tag" \
  -e KNOWLEDGE_HUB_AUDIENCE="api://<client-id>" \
  knowledge-hub -- python <FULL_PATH_TO>/mcp_client.py
```

4. **Fix stale "scales to zero" paragraph** — currently `team-setup-azure.md:99` says "scales to zero when idle. First request after idle may take ~30 seconds." Replace with:

```markdown
### No results returned

The search API may be warming up after a recent deployment (it loads the 300 MB embedding model on startup — typically 15–30 s). Wait a moment and try again.
```

- [ ] **Step 2: Apply the same changes to `team-setup.md`**

`team-setup.md` is the original (non-Azure) team-setup doc. Mirror the three edits from Step 1 into it, adjusting for any structural differences.

- [ ] **Step 3: Commit (in knowledge-hub)**

```bash
cd /e/knowledge-hub && git add rag/docs/team-setup-azure.md rag/docs/team-setup.md && git -c commit.gpgsign=false commit -m "Team-setup: add az login + KNOWLEDGE_HUB_AUDIENCE; fix stale scales-to-zero note"
```

---

### Task 21: Record the Entra cutover date in `log-privacy.md`

**Files:**
- Modify: `E:/knowledge-hub/rag/docs/log-privacy.md`

- [ ] **Step 1: Replace the placeholder cutover date**

The doc created in Task 15 has `<POPULATE-AT-TASK-21>` as a placeholder. Replace it with the actual date from Task 18 (the first successful authenticated query). Format: `YYYY-MM-DD`.

- [ ] **Step 2: Commit (in knowledge-hub)**

```bash
cd /e/knowledge-hub && git add rag/docs/log-privacy.md && git -c commit.gpgsign=false commit -m "log-privacy: record actual Entra cutover date"
```

---

## Final verification

### Task 22: End-to-end verification pass

- [ ] **Step 1: Unit tests green on docforge**

```bash
cd /e/docforge && /e/docforge/.venv/Scripts/python.exe -m pytest tests/unit/ -q
```
Expected: all tests pass, coverage ≥60%.

- [ ] **Step 2: Ruff clean**

```bash
cd /e/docforge && /e/docforge/.venv/Scripts/python.exe -m ruff format --check . && /e/docforge/.venv/Scripts/python.exe -m ruff check .
```
Expected: both exit 0. If format check fails, run `ruff format .` and commit with `style: ruff format sweep`.

- [ ] **Step 3: Re-confirm production behavior**

```bash
# /health open
curl -sf https://docforge-search-api.ashyhill-c79f3b95.westeurope.azurecontainerapps.io/health

# /search without auth -> 401
curl -si -X POST -H "Content-Type: application/json" \
  -d '{"query":"x","user_name":"x","team_name":"x","limit":1}' \
  https://docforge-search-api.ashyhill-c79f3b95.westeurope.azurecontainerapps.io/search \
  | head -1
```
Expected: `/health` returns 200; `/search` returns 401.

- [ ] **Step 4: Confirm both repos are pushable**

```bash
cd /e/docforge && git status && git log --oneline origin/master..HEAD
cd /e/knowledge-hub && git status && git log --oneline origin/master..HEAD
```
Note: `docforge` commits likely go through a PR (branch protection); `knowledge-hub` can push directly to master.

- [ ] **Step 5: Push (or open PR for docforge)**

For docforge (branch protection → PR flow, following Spec C2 precedent):

```bash
cd /e/docforge && git checkout -b phase-4-spec-c3 && git push -u origin phase-4-spec-c3
gh pr create --title "Phase 4 Spec C3: security + privacy (Entra auth, threat model, log privacy)" --body "$(cat <<'EOF'
## Summary

Implements Spec C3 (spec at docs/superpowers/specs/2026-04-21-security-privacy-design.md). Closes the headline Security gap identified in Spec D §5 by adding Entra ID authentication on the public /search + /sources endpoints, introducing a trustworthy per-user identity in query_log, and shipping the supporting threat model + log-privacy documents.

## Deliverables

- C3.1 Entra ID auth on /search + /sources (fastapi-azure-auth server-side; azure-identity DefaultAzureCredential clients in mcp_client.py + eval_search.py)
- C3.2 Entra app registration (DocuWare tenant; tobias holds admin rights)
- C3.3 docforge/docs/threat-model.md + DocuWare deployment context section appended to knowledge-hub deployment.md
- C3.4 knowledge-hub/rag/docs/log-privacy.md with 180-day retention + app-level cleanup loop in FastAPI lifespan
- C3.5 Additive query_log.user_oid migration (pre-Entra rows keep NULL)

## Test plan

- [x] Unit tests pass (auth mode=none + mode=entra with mock JWT; /health carve-out)
- [x] Coverage ≥60% preserved
- [x] Ruff clean
- [x] Live deployment: /health open (200), /search without auth (401), /search with Entra token (200)
- [x] query_log.user_oid populated on post-cutover rows
- [x] Eval harness reproduces baseline (recall@1 40%, recall@5 76%, MRR 0.533) with auth enabled
- [x] App-level cleanup loop verified against deployed API with dated test row

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

For knowledge-hub (direct to master is established pattern):

```bash
cd /e/knowledge-hub && git push origin master
```

---

## Success criteria recap (from spec)

- [x] `docforge[entra]` extra installs `fastapi-azure-auth` + `azure-identity`; plain install does not. (Task 5)
- [x] `auth.mode=none` default: unauthenticated requests accepted (backward-compatible). (Task 8 tests)
- [x] `auth.mode=entra`: `/search` + `/sources` return 401 on missing/invalid JWT. (Task 8 tests + Task 17 Step 5)
- [x] `auth.mode=entra`: `/health` accepts unauthenticated. (Task 8 tests + Task 17 Step 4)
- [x] App fails fast if `auth.mode=entra` without tenant_id or audience. (Task 6 tests)
- [x] `query_log.user_oid` exists; pre-Entra NULL; post-Entra populated. (Tasks 2, 3, 18 Step 5)
- [x] MCP client + eval harness authenticate; live end-to-end query succeeds. (Task 18)
- [x] Bicep ships auth params + env vars. (Tasks 11, 16, 17)
- [x] App-level cleanup runs hourly in FastAPI lifespan; unit-tested and verified against the deployed API with a dated synthetic row. (Tasks 12, 19)
- [x] `docforge/docs/threat-model.md` committed per outline. (Task 13)
- [x] `knowledge-hub/rag/docs/log-privacy.md` committed per outline. (Task 15)
- [x] `knowledge-hub/rag/docs/deployment.md` has DocuWare-context section. (Task 14)
- [x] Team-setup docs updated: `az login` added; "scales to zero" corrected. (Task 20)
- [x] Unit suite passes; coverage ≥60%. (Task 22)
- [x] Baseline reproduces with auth. (Task 18 Step 6)
- [x] CI green on both repos. (Task 22 Step 5)
