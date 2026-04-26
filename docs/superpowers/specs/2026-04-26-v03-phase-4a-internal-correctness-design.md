# docforge v0.3 Phase 4a — Internal Correctness — design

**Status:** Approved 2026-04-26
**Author:** Tobias Ens
**Scope:** First half of v0.3 Phase 4 per the umbrella spec at
`docs/superpowers/specs/2026-04-25-v03-hardening-design.md`. The umbrella
Phase 4 is split into **4a (internal correctness — this doc)** and **4b
(embedding sidecar + feature flag — separate spec later)**. Each lands as
its own PR; 4a is purely a refactor + correctness pass with no operational
component.

## Goal

Make the FastAPI process internally correct under concurrency:

- Replicas are stateless — no module globals holding shared resources.
- The event loop is no longer blocked by synchronous embedder calls on the
  hot paths (API + MCP `/search`).
- The hourly `query_log` cleanup runs in exactly one replica per interval,
  not once per replica.
- The Postgres connection pool is tunable per deployment instead of
  hardcoded `max_size=5`.

After 4a, a multi-replica deploy on the existing in-process embedder
behaves correctly under burst from AI-assistant traffic. Phase 4b will then
move the embedder out of the API process entirely.

## Context

The v0.2.1 critical review's Finding 1 ("sync embedder blocks the event
loop") and Finding 8 ("hardcoded pool / cleanup-loop runs per worker") both
land here. The umbrella Phase 4 design spec covers them as a single block;
this 4a spec carves out the parts that don't require new operational
components, so they can land before the sidecar work in 4b.

Current state in `src/docforge/api.py`:

- 5 module-level globals: `_pool`, `_embedder`, `_settings`, `_azure_scheme`,
  `_cleanup_task`.
- Cleanup loop runs hourly on every worker (via per-process `lifespan`),
  redundantly deleting the same rows.
- `_embedder.embed_query(req.query)` is awaited from `async def search`,
  but `embed_query` itself is synchronous — the event loop blocks during
  inference.
- Tests across `test_api.py` and `test_auth.py` reach into the module and
  monkey-patch these globals directly.

In `src/docforge/db.py`:

- Pool is created with hardcoded `min_size=1, max_size=5`.

In `src/docforge/mcp_server.py`:

- Same blocking pattern: `embedder.embed_query(query)` from `async def
  search_documentation`.

## Detailed design

### 1. Lifespan + `Depends` refactor

Replace module globals with a FastAPI `lifespan` async context manager that
yields a state dict. FastAPI auto-populates `request.state.<key>` from the
yielded dict. A small set of `Depends` getters expose each resource to
handlers; tests override via `app.dependency_overrides`.

Shape:

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
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
        azure_scheme = _build_auth_scheme(settings)
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


def get_settings(request: Request) -> Settings:
    return request.state.settings


def get_pool_dep(request: Request) -> asyncpg.Pool:
    return request.state.pool


def get_embedder(request: Request) -> Embedder:
    return request.state.embedder


def get_azure_scheme(request: Request):
    return request.state.azure_scheme


@app.post("/search")
async def search(
    req: SearchRequest,
    settings: Settings = Depends(get_settings),
    pool: asyncpg.Pool = Depends(get_pool_dep),
    embedder: Embedder = Depends(get_embedder),
    user=Depends(_auth_dependency),
) -> SearchResponse:
    ...
```

Notes on the lifespan:

- `_cleanup_task` no longer lives in the yielded dict — it's an internal
  resource managed by lifespan startup/shutdown only. Tests don't need to
  see it.
- `_auth_dependency` continues to exist; it now reads `azure_scheme` via
  `Depends(get_azure_scheme)` rather than a module global.
- The nested `try/finally` structure ensures `pool.close()` runs even if
  `Embedder.from_settings(settings)` raises (Phase 1's dimension guard
  fires). The outer `finally` covers from pool creation onward; the inner
  `finally` covers from cleanup-task creation onward.
- Verified behaviour: FastAPI 0.136.1 + Starlette 1.0.0 do auto-populate
  `request.state.<key>` from the lifespan-yielded dict (probed during spec
  authoring).

### 2. `to_thread` wrapping for embed calls

`Embedder.embed_query` is synchronous and CPU-bound. Wrap each call site on
the multi-client paths with `asyncio.to_thread`:

```python
# api.py:search
query_vector = await asyncio.to_thread(embedder.embed_query, req.query)

# mcp_server.py:search_documentation
query_vector = await asyncio.to_thread(embedder.embed_query, query)
```

Scope: only the API and MCP handlers. `cli.py` and `ingest.py` are
single-process orchestrators with no concurrent requesters; wrapping their
calls adds threading overhead for no benefit.

### 3. Cleanup loop on advisory lock

Move from "every replica runs the cleanup loop hourly" to "the replica that
wins a transaction-scoped advisory lock runs DELETE; the rest skip."

```python
CLEANUP_LOCK_ID = 0xD0CF0001  # arbitrary stable 32-bit; identifies the cleanup-loop lock


async def _query_log_cleanup_loop(pool: asyncpg.Pool, retention_days: int) -> None:
    """Each iteration takes a transaction-scoped advisory lock. A replica
    that can't acquire it skips this iteration. The lock auto-releases at
    COMMIT/ROLLBACK (no manual unlock needed) and on connection drop."""
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
```

Properties:

- **Non-blocking lock:** `pg_try_advisory_xact_lock` returns immediately.
  Replicas that don't get the lock log at debug level and move on; they
  don't queue.
- **Transaction-scoped lock:** held for the duration of the surrounding
  asyncpg transaction. `async with conn.transaction()` commits on
  successful exit (releasing the lock) and rolls back on exception (also
  releasing the lock). No manual `pg_advisory_unlock` needed; no leak risk
  from a failed unlock call.
- **Lock ID stable across replicas:** hardcoded constant `0xD0CF0001`
  (decimal 3,503,226,881). Specific to this cleanup loop; no collision
  risk unless another part of docforge claims the same number (it doesn't).
- **Mutual-exclusion guarantee:** at any moment, at most one replica is
  running the DELETE — the lock prevents simultaneous concurrent runs.
  Replicas whose loops are out of phase may each acquire the lock briefly
  during their own iteration, run a DELETE that finds no rows (because an
  earlier replica already cleaned), and release. The redundant DELETEs
  are no-ops — wasteful but not incorrect.
- **Loop frequency:** unchanged at `_CLEANUP_INTERVAL_SECONDS = 3600`.
  Worst case after 4a: cleanup misses one interval if the lock-holder
  crashes mid-iteration; the transaction rolls back and the next replica's
  hourly tick re-tries.

The signature change matters: the loop now takes `pool: asyncpg.Pool`
instead of `database_url: str`. Callers (just `lifespan` in api.py) pass
the lifespan's pool directly. The two `TestQueryLogCleanup` tests in
`tests/unit/test_auth.py` are updated to construct a fake pool and pass it
in, instead of patching `get_pool`.

### 4. Pool config knobs

Add two new fields to `Settings`:

```python
# config.py
pool_min_size: int = 5    # was hardcoded 1
pool_max_size: int = 25   # was hardcoded 5
```

Two consumers of pool state, two paths:

- **The FastAPI app's `lifespan`** calls `asyncpg.create_pool` directly,
  reading `settings.pool_min_size` and `settings.pool_max_size`. The pool
  is yielded into `request.state` and accessed via `Depends(get_pool_dep)`.
  No call to `db.py:get_pool` from the API layer after the refactor.
- **The non-FastAPI callers** (`mcp_server.py`, `cli.py`, `ingest.py`)
  still need the lazy-init `get_pool` helper. Update its signature to
  `async def get_pool(database_url: str, *, min_size: int = 5, max_size: int = 25)`;
  callers pass `settings.pool_min_size, settings.pool_max_size` explicitly
  on first call. The helper's existing module-level `_pool` cache is kept
  (these processes are single-process; one pool per process is correct).

Defaults raised to 5/25: at 30 teams / 500 engineers / AI-assistant burst
traffic, the prior `max_size=5` was the next bottleneck after the embedder.
Smaller deployments tune down via env (`POOL_MIN_SIZE`, `POOL_MAX_SIZE`).

### 5. Test refactor strategy

The existing test patterns reach into module globals:

```python
# Before
api_module._embedder = fake_embedder
monkeypatch.setattr(api_module, "_get_settings", _settings_stub)
monkeypatch.setattr(api_module, "get_pool", fake_get_pool)
```

After 4a, all of those are replaced by `app.dependency_overrides`:

```python
# After
from docforge.api import app, get_embedder, get_pool_dep, get_settings

app.dependency_overrides[get_embedder] = lambda: fake_embedder
app.dependency_overrides[get_settings] = lambda: settings_stub
app.dependency_overrides[get_pool_dep] = lambda: fake_pool
# (cleanup is automatic at end of test via pytest fixture teardown that
# clears app.dependency_overrides)
```

Affected tests, by file:

- `tests/unit/test_api.py` — `TestSearchEndpoint` (8 tests, including the
  3 boundary tests added in Phase 3 — though only 5 of those need
  refactor; the 3 boundary tests trigger 422 from Pydantic before any
  handler dependency runs and don't touch globals), `TestSourcesEndpoint`
  (2 tests), `TestRequestTimingInstrumentation` (1 test). About 8 tests
  with setup that needs rewriting.
- `tests/unit/test_auth.py` — `stub_downstream` fixture, `stub_entra`
  fixture, and the 5 test methods that use them; plus 2 tests in
  `TestQueryLogCleanup` that exercise `_query_log_cleanup_loop` directly
  and need to adapt to the new signature (passes `pool: asyncpg.Pool`,
  not `database_url: str`).
- `tests/conftest.py` — `FakePool` and `FakeEmbedder` unchanged; they're
  consumed via `app.dependency_overrides` instead of being monkey-patched
  in.

Total: ~15 tests touched + 2 fixture rewrites. The refactor itself adds
zero tests (counts preserved for the affected tests); §6 below adds 5-7
new tests for the new behaviour.

### 6. New tests added by 4a

- `tests/unit/test_db.py` (new file or new tests in existing file): pool
  reads `Settings.pool_min_size` and `Settings.pool_max_size` correctly
  (~2 tests).
- `tests/unit/test_auth.py::TestQueryLogCleanup`: cleanup loop with
  advisory lock — verify that when a second concurrent loop runs against
  the same database, only one performs the DELETE per interval (existing
  test scenario expanded with an "other replica holds lock" case via
  pg_try_advisory_xact_lock returning false, ~1-2 tests).
- `tests/unit/test_api.py` and `tests/unit/test_mcp_server.py`: `to_thread`
  wrapping — verify the API/MCP handlers run the embed call off the event
  loop (~2 tests, one per handler, asserting the embed call happens on a
  different thread or via `asyncio.to_thread` mock).

Estimate: 5-7 new tests; total unit suite ~169-171 passing after 4a.

## Risks & mitigations

- **Test refactor is the bulk of the diff.** Risk: state leaks across tests
  if `app.dependency_overrides` isn't cleared. Mitigation: use a
  pytest-fixture-managed override pattern (`monkeypatch.setattr` on
  `app.dependency_overrides`, or explicit teardown at fixture exit). Already
  the standard FastAPI testing pattern.

- **Lifespan startup error blocks pool close.** Mitigation: nested
  `try/finally` in lifespan — outer `finally` covers `pool.close()` from
  pool creation onward, inner covers cleanup-task cancellation around the
  `yield`. A startup error in `Embedder.from_settings` (Phase 1 dimension
  guard) still releases the pool.

- **Advisory-lock leak.** Mitigated by design: `pg_try_advisory_xact_lock`
  is bound to the surrounding asyncpg transaction, so it auto-releases at
  COMMIT/ROLLBACK whether the DELETE succeeded, raised, or the connection
  dropped. No manual unlock to forget; no leak path.

- **Pool default change (5→25 max) might exhaust Postgres connections on
  small deploys.** Mitigation: defaults match the operating profile (30
  teams / 500 engineers); operators on smaller Postgres tiers tune down
  via env. CHANGELOG entry calls this out under "Behavior change."

- **`to_thread` thread-pool default size.** Python's default executor has
  `min(32, os.cpu_count() + 4)` threads; on a small Container App
  instance with 1 vCPU, that's 5 threads. Embeddings run in those; if 5+
  concurrent embeds happen the 6th queues. Acceptable for in-process
  embedder; Phase 4b's sidecar removes this constraint.

## Out of scope

Acknowledging explicitly so the spec doesn't drift:

- Embedding sidecar service (Phase 4b)
- `DOCFORGE_EMBEDDER_URL` env var / feature flag (Phase 4b)
- Bicep changes for second Container App (Phase 4b)
- Async methods on `Embedder` class itself (Phase 4b can introduce if the
  sidecar benefits)
- `to_thread` wrapping for `cli.py` and `ingest.py` (single-process
  orchestrators)
- Cleanup-loop frequency tuning (still 3600s)
- Per-tenant or per-user retention policy (Phase 5)
- DB role separation (`docforge_app`, `docforge_log_reader` per
  log-privacy.md — Phase 5)

## Success criteria

- All pre-existing unit + integration tests pass after the refactor.
- New behaviour tests cover: pool config knobs, advisory-lock cleanup
  skipping when not lock-holder, `to_thread` wrapping on API + MCP
  handlers.
- Multi-replica deploy: cleanup loop runs DELETE in exactly one replica
  per hour (verified via Postgres logs or the application's `INFO` line).
- Manual canary on the live deployment: under burst load, 95th-percentile
  latency on `/search` doesn't degrade vs. pre-4a baseline (the `to_thread`
  wrapping keeps the event loop responsive).

## Implementation plan

Drafted next via the `superpowers:writing-plans` skill. Saved to
`docs/superpowers/plans/2026-04-26-v03-phase-4a-internal-correctness.md`.
