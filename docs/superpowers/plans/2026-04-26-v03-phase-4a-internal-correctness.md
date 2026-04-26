# docforge v0.3 Phase 4a — Internal Correctness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the FastAPI process internally correct under concurrency —
stateless replicas via lifespan + `Depends`, event-loop unblocked on
embed calls, cleanup loop coordinated across replicas via Postgres
advisory lock, and Postgres pool tunable per deploy. No new operational
component; pure refactor + correctness pass that keeps deployment
topology unchanged.

**Architecture:** Replace 5 module globals in `api.py` with a FastAPI
`lifespan` async context manager that yields a state dict; `Depends`
getters expose each resource to handlers. Cleanup loop receives a
`pool` instead of looking it up via a module-level lazy initialiser, and
gates work on `pg_try_advisory_xact_lock(0xD0CF0001)` so at most one
replica runs DELETE at a time. `Settings.pool_min_size` and
`pool_max_size` (new) replace the hardcoded `1`/`5` literals in
`db.py:get_pool`. Hot embed paths in `api.py:search` and
`mcp_server.py:search_documentation` go through `asyncio.to_thread` so
the event loop stays responsive during inference.

**Tech Stack:** Python 3.12, FastAPI 0.136, asyncpg, pytest, pytest-asyncio.

**Spec mapping:**

| Spec section | Plan task |
|---|---|
| §1 Lifespan + `Depends` refactor | Task 2 (with Task 1 prep) |
| §2 `to_thread` wrapping for embed calls | Task 3 |
| §3 Cleanup loop on advisory lock | Task 2 (cleanup loop change happens together with the lifespan refactor that supplies the `pool` argument) |
| §4 Pool config knobs | Task 1 |
| §5 Test refactor strategy | Task 2 (touches the same tests as the lifespan refactor) |
| §6 New tests added by 4a | Tasks 1, 2, 3 each ship their own |
| §7 Out of scope | (no plan task — sidecar etc. is Phase 4b) |
| Behaviour change CHANGELOG entry | Task 4 |

**Final unit-suite count target:** 164 (current) + 5 new across Tasks
1–3 (2 in Task 1, 1 in Task 2, 2 in Task 3) − 1 deleted in Task 2 →
**168** passing after 4a. Same coverage gate (60%); existing 163 stay
green throughout (the deleted one tests behaviour the new architecture
makes unreachable — see Task 2 Step 4c for rationale).

---

### Task 1: Pool config knobs + `db.py:get_pool` signature

Pure additive change. Settings get two new fields with new defaults; the
helper accepts them as kwargs (with the new defaults) so existing
callers continue to work unchanged.

**Files:**
- Modify: `src/docforge/config.py` — add `pool_min_size`, `pool_max_size` fields after `query_log_retention_days` (line 78).
- Modify: `src/docforge/db.py:16-26` — add `min_size`, `max_size` keyword-only params with the new defaults; pass them through to `asyncpg.create_pool`.
- Modify: `src/docforge/cli.py`, `src/docforge/ingest.py`, `src/docforge/mcp_server.py` — call sites that invoke `get_pool(settings.database_url)` now pass the new pool params explicitly.
- Modify: `tests/unit/test_config.py` — add 2 tests for the new Settings fields.

- [ ] **Step 1: Write the failing tests for the new Settings fields**

Append to `tests/unit/test_config.py`, after the existing `TestQueryLogRetention` class (around line 199):

```python
class TestPoolSettings:
    def test_default_pool_sizes(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        from docforge.config import Settings

        s = Settings()
        assert s.pool_min_size == 5
        assert s.pool_max_size == 25

    def test_pool_sizes_overridable_in_yml(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        (tmp_path / "docforge.yml").write_text(
            "pool_min_size: 2\npool_max_size: 10\n",
            encoding="utf-8",
        )
        from docforge.config import Settings

        s = Settings()
        assert s.pool_min_size == 2
        assert s.pool_max_size == 10
```

- [ ] **Step 2: Run, verify they fail**

```bash
python -m pytest tests/unit/test_config.py::TestPoolSettings -v --tb=short 2>&1 | tail -10
```

Expected: `AttributeError: 'Settings' object has no attribute 'pool_min_size'`.

- [ ] **Step 3: Add the new Settings fields**

In `src/docforge/config.py`, after line 78 (`query_log_retention_days: int = 180`) and before the `def __init__(self, **kwargs)` block, insert:

```python
    # asyncpg pool sizing — defaults match the operating profile (multi-replica,
    # bursty AI-assistant traffic). Smaller deploys can lower these via
    # POOL_MIN_SIZE / POOL_MAX_SIZE env vars.
    pool_min_size: int = 5
    pool_max_size: int = 25
```

- [ ] **Step 4: Run the new Settings tests, verify they pass**

```bash
python -m pytest tests/unit/test_config.py::TestPoolSettings -v --tb=short 2>&1 | tail -10
```

Expected: 2 passed.

- [ ] **Step 5: Update `db.py:get_pool` signature**

Replace the entire body of `src/docforge/db.py:16-26` with:

```python
async def get_pool(
    database_url: str,
    *,
    min_size: int = 5,
    max_size: int = 25,
) -> asyncpg.Pool:
    """Return the module-level asyncpg pool, creating it on first call.

    Note: the cache is first-call-wins. min_size/max_size on subsequent calls
    are ignored — these helpers serve single-process callers (mcp_server,
    cli, ingest). The FastAPI app creates its pool directly inside the
    lifespan and does not go through this helper.
    """
    global _pool
    if _pool is None:
        _pool = await asyncpg.create_pool(
            database_url,
            min_size=min_size,
            max_size=max_size,
            init=_init_connection,
        )
    return _pool
```

- [ ] **Step 6: Update non-API callers to pass the new kwargs**

Three call sites need the new arguments. Find them:

```bash
git grep -n "get_pool(" -- 'src/docforge/*.py'
```

Expected hits (from a clean Phase 3 master):
- `src/docforge/cli.py` — one caller in `_search`, one in `_status`, etc.
- `src/docforge/ingest.py` — one caller
- `src/docforge/mcp_server.py` — one caller

For each caller, change `await get_pool(settings.database_url)` to:

```python
await get_pool(
    settings.database_url,
    min_size=settings.pool_min_size,
    max_size=settings.pool_max_size,
)
```

(Note: `cli.py` may have multiple call sites; update each. `api.py` is
out of scope for Task 1 — Task 2 removes its call to `get_pool`
entirely.)

- [ ] **Step 7: Run the full unit suite — verify 166 passing**

```bash
python -m pytest -m "not integration" -q --no-header --tb=line 2>&1 | tail -5
```

Expected: `166 passed, 12 deselected` (164 pre-existing + 2 new pool
tests). No regressions.

- [ ] **Step 8: Lint**

```bash
python -m ruff check src/docforge tests && python -m ruff format --check src/docforge tests
```

Expected: clean.

- [ ] **Step 9: Commit**

```bash
git add src/docforge/config.py src/docforge/db.py src/docforge/cli.py src/docforge/ingest.py src/docforge/mcp_server.py tests/unit/test_config.py
git commit -m "$(cat <<'EOF'
feat(config,db): tunable asyncpg pool size via Settings

Adds Settings.pool_min_size (default 5) and pool_max_size (default 25)
fields. db.py:get_pool now accepts these as keyword-only kwargs;
callers in cli.py, ingest.py, and mcp_server.py thread the values
through. The defaults raise from the prior hardcoded 1/5 — at the
operating profile (multi-replica, AI-assistant burst traffic) the
old max_size=5 was the next bottleneck after the embedder.

api.py is unchanged here; Phase 4a Task 2 refactors it to use
lifespan + Depends and creates the pool directly with the new
settings, no longer going through db.py:get_pool.

Operators on smaller Postgres tiers can lower the values via
POOL_MIN_SIZE / POOL_MAX_SIZE env vars.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 2: api.py lifespan refactor + cleanup loop on advisory lock + test refactor

The breaking change. Module globals replaced by lifespan-yielded state;
handlers receive resources via `Depends`; cleanup loop receives the pool
as an argument and gates work on a transaction-scoped advisory lock.
Affected tests rewritten to use `app.dependency_overrides` instead of
monkey-patching globals.

**Files:**
- Modify: `src/docforge/api.py` — wholesale refactor of module globals, lifespan, `_auth_dependency`, handlers, and the cleanup loop.
- Modify: `tests/unit/test_api.py` — refactor `TestSearchEndpoint` (8 tests; 5 need real refactor, 3 boundary tests pass through unchanged), `TestSourcesEndpoint` (2 tests), `TestRequestTimingInstrumentation` (1 test).
- Modify: `tests/unit/test_auth.py` — refactor `stub_downstream` and `stub_entra` fixtures + 5 test methods that use them; refactor `TestQueryLogCleanup` (2 tests) for the cleanup-loop signature change; add 1 new test for the advisory-lock skip path.

- [ ] **Step 1: Write the new test for advisory-lock skip behaviour**

In `tests/unit/test_auth.py`, append a new test method to the
`TestQueryLogCleanup` class:

```python
    @pytest.mark.asyncio
    async def test_cleanup_loop_skips_when_lock_held_by_another_replica(self, monkeypatch):
        """When pg_try_advisory_xact_lock returns False (another replica holds
        the lock), the loop logs a debug line and skips the DELETE."""
        delete_calls: list[tuple] = []

        class _Conn:
            async def fetchval(self, query, *args):
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

        # No DELETE should fire because the lock was unavailable
        assert delete_calls == []
```

(The two existing `TestQueryLogCleanup` tests will be updated in Step
3b below, but this new test goes in alongside them now since it also
needs to be present at red phase.)

- [ ] **Step 2: Run new test, verify it fails**

```bash
python -m pytest tests/unit/test_auth.py::TestQueryLogCleanup::test_cleanup_loop_skips_when_lock_held_by_another_replica -v --tb=short 2>&1 | tail -10
```

Expected: fails on `assert len(fetchval_calls) >= 1`. With the OLD
loop body, no `pg_try_advisory_xact_lock` call happens — the loop
goes straight from `pool = await get_pool(database_url)` to the
DELETE. (Python doesn't enforce type hints at runtime, so passing
the `_Pool` mock as the `database_url` arg doesn't TypeError; it
errors deep inside `get_pool` → caught by the loop's `except`
→ silent retry → never calls `fetchval`.) The assertion that
`fetchval_calls` is non-empty is what makes the test red on old
code and green on new.

- [ ] **Step 3: Refactor `src/docforge/api.py`**

This is the meat of Task 2. Replace the file's contents from line 22
onward (preserve the docstring and imports up to line 21) with the
following structure. Three things change: module globals removed,
lifespan rewritten, cleanup loop body uses `pg_try_advisory_xact_lock`,
and handlers receive resources via `Depends`.

Step 3a: replace lines 26-119 (module globals through `_auth_dependency`) with this:

```python
logger = logging.getLogger(__name__)

_CLEANUP_INTERVAL_SECONDS = 3600  # one hour — overridable in tests
CLEANUP_LOCK_ID = 0xD0CF0001  # decimal 3,503,226,881 — stable across replicas


async def _query_log_cleanup_loop(pool: asyncpg.Pool, retention_days: int) -> None:
    """Each iteration takes a transaction-scoped advisory lock. A replica
    that can't acquire it skips this iteration. The lock auto-releases at
    COMMIT/ROLLBACK and on connection drop — no manual unlock to forget."""
    days = int(retention_days)
    while True:
        try:
            async with pool.acquire() as conn:
                async with conn.transaction():
                    got_lock = await conn.fetchval(
                        "SELECT pg_try_advisory_xact_lock($1)", CLEANUP_LOCK_ID
                    )
                    if got_lock:
                        result = await conn.execute(
                            f"DELETE FROM query_log "
                            f"WHERE created_at < now() - interval '{days} days'"
                        )
                        logger.info("query_log cleanup: %s", result)
                    else:
                        logger.debug("query_log cleanup: another replica holds the lock")
        except Exception as e:
            logger.exception("query_log cleanup failed: %s", e)
        await asyncio.sleep(_CLEANUP_INTERVAL_SECONDS)


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


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Build per-process resources at startup; tear them down on shutdown.

    Yields a dict whose entries flow into request.state for handler access
    via the Depends getters below."""
    settings = Settings()
    pool = await asyncpg.create_pool(
        settings.database_url,
        min_size=settings.pool_min_size,
        max_size=settings.pool_max_size,
        init=_init_connection,
    )
    try:
        # Embedder construction can raise (Phase 1 dimension guard); the
        # outer finally still closes the pool in that case.
        embedder = Embedder.from_settings(settings)
        logger.info("Model loaded: %s (%dd)", embedder.model_name, embedder.dimensions)

        azure_scheme = _build_auth_scheme(settings)
        if azure_scheme is not None:
            await azure_scheme.openid_config.load_config()
            logger.info(
                "Entra auth enabled (tenant=%s, audience=%s)",
                settings.auth.tenant_id,
                settings.auth.audience,
            )

        cleanup_task = asyncio.create_task(
            _query_log_cleanup_loop(pool, settings.query_log_retention_days)
        )
        try:
            yield {
                "settings": settings,
                "pool": pool,
                "embedder": embedder,
                "azure_scheme": azure_scheme,
            }
        finally:
            cleanup_task.cancel()
            try:
                await cleanup_task
            except asyncio.CancelledError:
                pass
    finally:
        await pool.close()


app = FastAPI(title="docforge", lifespan=lifespan)


def get_settings(request: Request) -> Settings:
    return request.state.settings


def get_pool_dep(request: Request) -> asyncpg.Pool:
    return request.state.pool


def get_embedder(request: Request) -> Embedder:
    return request.state.embedder


def get_azure_scheme(request: Request):
    return request.state.azure_scheme


async def _auth_dependency(
    request: Request,
    azure_scheme=Depends(get_azure_scheme),
):
    """Return the authenticated User under auth.mode=entra, None otherwise."""
    if azure_scheme is None:
        return None
    return await azure_scheme(request, SecurityScopes())
```

Step 3b: update the imports at the top of `api.py` — replace the existing import block (lines 9-24) with:

```python
from __future__ import annotations

import asyncio
import logging
import time
from contextlib import asynccontextmanager
from typing import Any

import asyncpg
import numpy as np
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.security import SecurityScopes
from pydantic import BaseModel, Field

from docforge.config import Settings
from docforge.db import _init_connection
from docforge.processors.embedder import Embedder
```

Two things changed: `close_pool, get_pool` removed from `db` import (no
longer used; the lifespan creates pool directly); `_init_connection`
imported instead (for the pgvector registration). `asyncpg` added.

Step 3c: update the `search` handler signature and body. Replace
lines 153-233 (the `@app.post("/search")` block) with:

```python
@app.post("/search", response_model=SearchResponse)
async def search(
    req: SearchRequest,
    settings: Settings = Depends(get_settings),
    pool: asyncpg.Pool = Depends(get_pool_dep),
    embedder: Embedder = Depends(get_embedder),
    user=Depends(_auth_dependency),
) -> SearchResponse:
    """Search indexed documentation by semantic similarity."""
    start = time.perf_counter()

    try:
        query_vector = embedder.embed_query(req.query)
    except Exception as e:
        logger.error("Embedding failed: %s", e)
        raise HTTPException(status_code=500, detail="Failed to embed query")

    user_tags = [req.team_name] + ([req.area_name] if req.area_name else [])

    try:
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT
                    c.text,
                    c.section_title,
                    s.title AS source_title,
                    s.url AS source_url,
                    s.tags AS source_tags,
                    1 - (c.embedding <=> $1::vector) AS similarity,
                    (1 - (c.embedding <=> $1::vector)) *
                        (1
                         + $2::float * cardinality(
                             ARRAY(SELECT unnest(s.tags) INTERSECT SELECT unnest($3::text[]))
                           )
                         + $4::float * (CASE WHEN 'org' = ANY(s.tags) THEN 1 ELSE 0 END)
                        ) AS boosted_score
                FROM chunks c
                JOIN sources s ON c.source_id = s.id
                WHERE s.status = 'active'
                ORDER BY boosted_score DESC
                LIMIT $5
                """,
                np.array(query_vector, dtype=np.float32),
                settings.tag_match_weight,
                user_tags,
                settings.org_tag_weight,
                req.limit,
            )
    except Exception as e:
        logger.error("Database error during search: %s", e)
        raise HTTPException(status_code=503, detail="Database unavailable")

    from docforge.query_log import log_query

    request_ms = int((time.perf_counter() - start) * 1000)

    await log_query(
        pool,
        user.preferred_username if user else req.user_name,
        req.team_name,
        req.area_name,
        req.query,
        len(rows),
        user_oid=user.oid if user else None,
        request_ms=request_ms,
    )

    results = [
        SearchResult(
            text=row["text"],
            section_title=row["section_title"],
            source_title=row["source_title"],
            source_url=row["source_url"],
            source_tags=list(row["source_tags"] or []),
            similarity=float(row["similarity"]),
        )
        for row in rows
    ]

    return SearchResponse(results=results, query=req.query, count=len(results))
```

Three things changed in the handler: dependency-injected
`settings`, `pool`, `embedder`; the `if not _embedder` guard is gone
(lifespan startup either succeeds — embedder is set — or raises); and
the inline `_get_settings()` and `await get_pool(...)` calls are gone.
Note the embed_query call is still synchronous here — Task 3 wraps it
in `to_thread`.

Step 3d: update the `list_sources` handler. Replace lines 236-266 with:

```python
@app.get("/sources")
async def list_sources(
    pool: asyncpg.Pool = Depends(get_pool_dep),
    user=Depends(_auth_dependency),
) -> dict[str, Any]:
    """List all indexed documentation sources."""
    try:
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT title, url, status, last_crawled_at,
                       (SELECT count(*) FROM chunks WHERE source_id = s.id) AS chunk_count
                FROM sources s
                ORDER BY title
                """
            )
    except Exception as e:
        logger.error("Database error listing sources: %s", e)
        raise HTTPException(status_code=503, detail="Database unavailable")

    return {
        "count": len(rows),
        "sources": [
            {
                "title": row["title"],
                "url": row["url"],
                "status": row["status"],
                "chunk_count": row["chunk_count"],
            }
            for row in rows
        ],
    }
```

Step 3e: update the `health` endpoint at line 144-150. Replace:

```python
@app.get("/health")
async def health() -> dict[str, Any]:
    """Health check endpoint."""
    return {
        "status": "ok",
        "model": _embedder.model_name if _embedder else "not loaded",
    }
```

with:

```python
@app.get("/health")
async def health(request: Request) -> dict[str, Any]:
    """Health check endpoint."""
    embedder = getattr(request.state, "embedder", None)
    return {
        "status": "ok",
        "model": embedder.model_name if embedder else "not loaded",
    }
```

The `getattr(..., "embedder", None)` guard handles the case where
`/health` is hit before lifespan finishes startup (relevant only in
extreme cold-start scenarios but correct).

- [ ] **Step 4: Refactor `tests/unit/test_api.py`**

The pattern across all affected tests: replace `monkeypatch.setattr(api_module, "_get_settings", ...)`, `monkeypatch.setattr(api_module, "get_pool", ...)`, and `api_module._embedder = ...` with `app.dependency_overrides[get_X] = ...`. Imports add the getter functions.

Step 4a: update the imports at the top of `tests/unit/test_api.py`:

```python
from docforge import api as api_module
from docforge.api import app, get_embedder, get_pool_dep, get_settings
```

Step 4b: update `_settings_stub` to also include `pool_min_size`, `pool_max_size`, and `query_log_retention_days` so it doesn't trip dependency code paths that read them later:

```python
def _settings_stub():
    return SimpleNamespace(
        database_url="postgresql://fake",
        tag_match_weight=0.1,
        org_tag_weight=0.05,
        pool_min_size=5,
        pool_max_size=25,
        query_log_retention_days=180,
    )
```

Step 4c: rewrite each test that previously monkey-patched globals. The pattern is consistent — show one example here; apply to all affected tests.

`TestSearchEndpoint::test_returns_results_on_success` — current shape uses `api_module._embedder = fake_embedder; monkeypatch.setattr(api_module, "get_pool", fake_get_pool); monkeypatch.setattr(api_module, "_get_settings", _settings_stub)`. Rewrite as:

```python
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
```

Apply the same pattern to:

**`test_returns_503_when_model_not_loaded` — DELETE this test.** The new
architecture guarantees the embedder is loaded before any request
handler runs (lifespan startup either succeeds or raises — there's no
state where a request reaches a handler with `embedder = None`). The
test asserts unreachable behaviour. Remove the entire `async def
test_returns_503_when_model_not_loaded(...)` method from
`TestSearchEndpoint`. Note the deletion in the commit message.

**`test_returns_503_on_db_error`** — rewrite as:

```python
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
```

**`test_returns_500_on_embed_error`** — rewrite as:

```python
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
```

**The 3 boundary tests added in Phase 3** (`test_search_rejects_limit_over_max`,
`test_search_rejects_query_over_max_length`, `test_search_rejects_limit_under_min`)
need NO refactor — they trigger 422 from Pydantic before any handler
dependency resolves, so they don't touch globals or overrides.

`TestSourcesEndpoint::test_lists_sources` and `test_returns_503_on_db_error` — same pattern (override `get_pool_dep`, `get_settings`).

`TestRequestTimingInstrumentation::test_search_writes_request_ms_to_query_log` — apply the same pattern (override embedder, pool, settings); the `monkeypatch.setattr("docforge.query_log.log_query", fake_log_query)` line stays as-is (it's not an `app.dependency_overrides`-managed dependency).

Step 4d: ensure cleanup. After each test that uses `app.dependency_overrides`, the `try/finally` with `app.dependency_overrides.clear()` is required. This is the standard FastAPI test pattern. Pytest fixtures could centralise this; for now keep it inline (matches the pattern in the existing `test_auth.py`).

- [ ] **Step 5: Refactor `tests/unit/test_auth.py`**

Step 5a: rewrite `stub_downstream` fixture (currently monkey-patches `_embedder`, `get_pool`, `_get_settings`, `log_query`) to use `app.dependency_overrides`:

```python
@pytest.fixture
def stub_downstream(fake_embedder):
    """Short-circuit /search past embedder + DB + log_query so auth tests
    can focus on auth behaviour."""
    from docforge.api import app, get_embedder, get_pool_dep, get_settings

    fake_pool = FakePool(rows=[])
    settings_stub = lambda: SimpleNamespace(
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
```

Step 5b: rewrite `stub_entra` fixture. Currently monkey-patches `_settings`, `_azure_scheme`. Replace with:

```python
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
```

Step 5c: update `TestAuthModeNone::test_search_accepts_unauthenticated`. The current test sets `api_mod._azure_scheme = None`; the new pattern just doesn't override `get_azure_scheme` (the default return from request.state.azure_scheme is None when auth.mode != entra). Simplify:

```python
    @pytest.mark.asyncio
    async def test_search_accepts_unauthenticated(self, stub_downstream):
        # No stub_entra fixture used → request.state.azure_scheme is None →
        # _auth_dependency returns None → handler accepts.
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
```

Note: this test is special — it doesn't go through the `stub_entra` fixture, so `request.state.azure_scheme` needs to exist for the handler. Since the test bypasses lifespan (ASGITransport doesn't trigger lifespan), we need to add an override that explicitly sets `azure_scheme = None`. Update:

```python
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
```

Apply the same pattern to other auth-mode-none tests.

Step 5d: rewrite `TestAuthModeEntra::test_search_accepts_with_mock_user`. The current test uses `app.dependency_overrides[_auth_dependency] = fake_dep` already, so the test body stays — only the fixture-managed setup changes. After Step 5b, `stub_entra` is the right shape.

Step 5e: rewrite the two `TestQueryLogCleanup` tests for the new signature.

`test_cleanup_loop_runs_delete_each_iteration` — currently passes `database_url="postgresql://fake"`. Update to construct a fake pool and pass it:

```python
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
```

`test_cleanup_loop_continues_after_db_error` — apply the same shape but with a pool whose `acquire` raises on the first call:

```python
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
```

- [ ] **Step 6: Run all tests, verify pass**

```bash
python -m pytest -m "not integration" -q --no-header --tb=short 2>&1 | tail -10
```

Expected: `166 passed, 12 deselected`. The math: 166 from Task 1 + 1 new advisory-lock-skip test from Step 1 − 1 deleted (`test_returns_503_when_model_not_loaded` in Step 4c) = 166. The two cleanup-loop tests rewritten in Step 5e stay at count 2 (signature change, not count change).

If failing: re-read the affected tests carefully. Likely culprits are missing `app.dependency_overrides.clear()` (test pollution) or stub `Settings`-namespace fields the new handler reads (`pool_min_size`, etc.).

- [ ] **Step 7: Lint**

```bash
python -m ruff check src/docforge tests && python -m ruff format --check src/docforge tests
```

Expected: clean. If `ruff format --check` complains about the new lifespan formatting, run `ruff format src/docforge`.

- [ ] **Step 8: Commit**

```bash
git add src/docforge/api.py tests/unit/test_api.py tests/unit/test_auth.py
git commit -m "$(cat <<'EOF'
refactor(api): lifespan + Depends + advisory-lock cleanup

Phase 4a's structural change. The API process is now stateless:
no module globals for pool / embedder / settings / azure_scheme;
all four come from a FastAPI lifespan that yields a state dict, with
Depends getters exposing each to handlers.

The query_log cleanup loop receives a pool argument (was: looked up
via the module-level lazy initialiser) and gates work on a
transaction-scoped advisory lock (pg_try_advisory_xact_lock with
LOCK_ID = 0xD0CF0001). Multiple replicas can run the loop on the
same hourly cadence; the lock guarantees at most one of them runs
DELETE at a time.

Tests rewritten from monkey-patched module globals to
app.dependency_overrides. The TestQueryLogCleanup tests adapt to
the cleanup loop's new (pool, retention_days) signature, and one new
test covers the "another replica holds the lock" skip path.

The test_returns_503_when_model_not_loaded test is removed —
the new architecture guarantees the embedder is loaded before any
request handler runs (lifespan startup either succeeds or raises).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 3: `to_thread` wrapping for embed calls

Wrap the synchronous `embed_query` calls on the API and MCP hot paths
in `asyncio.to_thread` so the event loop stays responsive during model
inference. Skip CLI and ingest (single-process orchestrators with no
concurrent requesters).

**Files:**
- Modify: `src/docforge/api.py:search` — wrap `embedder.embed_query(req.query)` call.
- Modify: `src/docforge/mcp_server.py:search_documentation` — wrap `embedder.embed_query(query)` call.
- Modify: `tests/unit/test_api.py` — add 1 test verifying the wrap.
- Modify: `tests/unit/test_mcp_server.py` — add 1 test verifying the wrap.

- [ ] **Step 1: Write the failing tests**

In `tests/unit/test_api.py`, append to `TestSearchEndpoint`:

```python
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
```

In `tests/unit/test_mcp_server.py`, append a new test (outside any class — match the existing flat-function pattern):

```python
@pytest.mark.asyncio
async def test_search_documentation_runs_embed_via_to_thread(monkeypatch, patch_mcp_deps):
    """The synchronous embed_query call goes through asyncio.to_thread
    so the event loop is not blocked during inference."""
    import asyncio as _asyncio

    captured: dict = {"args": None}
    original_to_thread = _asyncio.to_thread

    async def spy_to_thread(func, *args, **kwargs):
        captured["args"] = (func, args, kwargs)
        return await original_to_thread(func, *args, **kwargs)

    monkeypatch.setattr(_asyncio, "to_thread", spy_to_thread)

    rows = [
        {
            "text": "x",
            "section_title": None,
            "source_title": "S",
            "source_url": "https://x",
            "source_tags": [],
            "similarity": 0.9,
        },
    ]
    pool, fake_embedder = patch_mcp_deps(rows)

    from docforge.mcp_server import search_documentation

    await search_documentation("hello", user_name="u", team_name="t")

    assert captured["args"] is not None, "embed_query was not run via asyncio.to_thread"
    assert captured["args"][0] == fake_embedder.embed_query
    assert captured["args"][1] == ("hello",)
```

- [ ] **Step 2: Run, verify they fail**

```bash
python -m pytest tests/unit/test_api.py::TestSearchEndpoint::test_search_runs_embed_via_to_thread tests/unit/test_mcp_server.py::test_search_documentation_runs_embed_via_to_thread -v --tb=short 2>&1 | tail -10
```

Expected: both fail with `AssertionError: embed_query was not run via asyncio.to_thread` because the current handlers call `embedder.embed_query(...)` directly.

- [ ] **Step 3: Wrap embed call in `api.py:search`**

Find the line in `src/docforge/api.py:search` (post-Task-2 state):

```python
    try:
        query_vector = embedder.embed_query(req.query)
    except Exception as e:
```

Replace with:

```python
    try:
        query_vector = await asyncio.to_thread(embedder.embed_query, req.query)
    except Exception as e:
```

- [ ] **Step 4: Wrap embed call in `mcp_server.py:search_documentation`**

Find in `src/docforge/mcp_server.py`:

```python
    query_vector = embedder.embed_query(query)
```

Replace with:

```python
    query_vector = await asyncio.to_thread(embedder.embed_query, query)
```

Add an `import asyncio` at the top of `mcp_server.py` if it's not already imported. (It is — `asyncio` is part of the existing imports.)

- [ ] **Step 5: Run targeted tests, verify pass**

```bash
python -m pytest tests/unit/test_api.py::TestSearchEndpoint::test_search_runs_embed_via_to_thread tests/unit/test_mcp_server.py::test_search_documentation_runs_embed_via_to_thread -v --tb=short 2>&1 | tail -10
```

Expected: 2 passed.

- [ ] **Step 6: Run full unit suite**

```bash
python -m pytest -m "not integration" -q --no-header --tb=line 2>&1 | tail -5
```

Expected: `168 passed, 12 deselected` (166 from Task 2 + 2 new to_thread tests).

- [ ] **Step 7: Lint**

```bash
python -m ruff check src/docforge tests && python -m ruff format --check src/docforge tests
```

Expected: clean.

- [ ] **Step 8: Commit**

```bash
git add src/docforge/api.py src/docforge/mcp_server.py tests/unit/test_api.py tests/unit/test_mcp_server.py
git commit -m "$(cat <<'EOF'
perf(api,mcp): unblock event loop during embed via asyncio.to_thread

Embedder.embed_query is sync and CPU-bound. Calling it directly from
async handlers blocks the event loop until inference completes — at
the operating profile (multi-replica, AI-assistant burst traffic)
that's the hot-path concurrency bug from Finding 1 of the v0.2.1
review. Wrapping in asyncio.to_thread runs the call on the default
ThreadPoolExecutor, freeing the loop to accept other connections.

Scope: the multi-client paths (api.py:search, mcp_server.py:
search_documentation). cli.py and ingest.py are single-process
orchestrators with no concurrent requesters; threading them adds
overhead for no benefit.

Two new tests verify the wrap by spying on asyncio.to_thread and
asserting the embed_query call lands on it.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 4: CHANGELOG entries

**Files:**
- Modify: `CHANGELOG.md` — append bullets to the existing `[Unreleased]` section.

- [ ] **Step 1: Append the Phase 4a bullets**

Find the existing `### Changed` block under `## [Unreleased]`. Append after the existing bullets:

```markdown
- API process is now stateless — module globals replaced by a FastAPI lifespan that yields settings, pool, embedder, and azure_scheme into per-request `request.state`; handlers access them via `Depends` getters. **Behavior change for tests:** consumers that monkey-patched `api._embedder`, `api._get_settings`, or `api.get_pool` need to switch to `app.dependency_overrides`. No deployer-facing change.
- Asyncpg pool sizing is tunable per deployment via the new `Settings.pool_min_size` and `pool_max_size` fields (env: `POOL_MIN_SIZE`, `POOL_MAX_SIZE`). Defaults raised from `1`/`5` to `5`/`25` to match the operating profile. Operators on smaller Postgres tiers should lower these explicitly.
- `query_log` cleanup loop now coordinates across replicas via a transaction-scoped Postgres advisory lock (`pg_try_advisory_xact_lock(0xD0CF0001)`). At most one replica runs DELETE per interval; the others log a debug line and skip. Replaces the prior "every replica deletes once per hour" pattern (which was idempotent but wasteful).
- `api.py:search` and `mcp_server.py:search_documentation` now wrap the synchronous `Embedder.embed_query` call in `asyncio.to_thread`. The event loop remains responsive during embedding inference. Closes the original Finding 1 from the v0.2.1 critical review.
```

- [ ] **Step 2: Verify**

```bash
python -c "
import pathlib
content = pathlib.Path('CHANGELOG.md').read_text(encoding='utf-8')
unreleased = content.split('## [Unreleased]')[1].split('## [0.2.1]')[0]
for fragment in ['stateless', 'pool_min_size', 'advisory lock', 'asyncio.to_thread']:
    assert fragment in unreleased, f'CHANGELOG missing: {fragment}'
print('OK')
"
```

Expected: prints `OK`.

- [ ] **Step 3: Commit**

```bash
git add CHANGELOG.md
git commit -m "$(cat <<'EOF'
docs(changelog): add unreleased entries for v0.3 phase 4a

Four user/operator-facing changes from Phase 4a — internal
correctness pass:

- Stateless API replicas via lifespan + Depends. Test-facing
  behaviour change for consumers that monkey-patched module globals.
- Tunable asyncpg pool size via Settings.pool_{min,max}_size; defaults
  raised from 1/5 to 5/25.
- Cleanup loop coordinates across replicas via transaction-scoped
  pg_try_advisory_xact_lock. At most one replica runs DELETE per hour.
- Hot embed paths run via asyncio.to_thread. Event loop responsive
  during inference (closes Finding 1 of the v0.2.1 review).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Post-merge actions

None additional. Phase 4a's changes ship in the PR; no infrastructure
or branch-protection edits required. Phase 4b will introduce the
embedding sidecar, which IS a deployment-topology change.

## Out of scope for this plan

Phase 4b territory:
- Embedding sidecar service (separate FastAPI process)
- `DOCFORGE_EMBEDDER_URL` feature flag
- Bicep changes for second Container App
- Async methods on the `Embedder` class itself

Each will get its own brainstorm + spec + plan once 4a is in production.
