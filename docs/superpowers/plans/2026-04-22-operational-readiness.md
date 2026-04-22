# Operational Readiness (Spec C4) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship six operational-readiness deliverables (C4.1 – C4.6) that close Phase 4's Operational, Scale, and Sustainability gaps at L3 "Hardened at single site". After this lands, the 14-day Spec D soak clock starts.

**Architecture:** Single docforge PR carries all code + CONTRIBUTING. Knowledge-hub prose docs (runbook, load-profile) land direct-to-master staggered: runbook after the PITR dry-run, load-profile after several days of `request_ms` data have accumulated. Orphan-purge is a new flag on `docforge ingest` (default dry-run; `--confirm` to mutate). Request timing is measured inside handlers via `perf_counter()` — no middleware (the middleware approach was considered and rejected in spec review because a middleware can't publish its measurement in time for the handler that calls `log_query`).

**Tech Stack:** Python 3.12+, FastAPI, asyncpg + pgvector, Azure Postgres Flexible Server (Standard_B1ms, 7-day PITR), Azure Container Apps, `testcontainers.postgres` for integration tests, ruff (lint + format), pytest (+pytest-asyncio).

**Spec:** `docs/superpowers/specs/2026-04-22-operational-readiness-design.md`

---

## File Structure

**docforge repo (single PR):**
- `docforge/cli.py` — MODIFY. Two new flags on `ingest`: `--purge-orphans`, `--confirm`.
- `docforge/ingest.py` — MODIFY. New `_purge_orphans(pool, current_identifiers, confirm)` helper; called from `ingest_all` when flag set.
- `docforge/api.py` — MODIFY. In-handler `perf_counter()` timing on `/search` and `/sources`; pass `request_ms` to `log_query`.
- `docforge/query_log.py` — MODIFY. `log_query()` gains `request_ms: int | None = None` kwarg.
- `docforge/sql/migrations/006_add_query_log_request_ms.sql` — NEW. Additive.
- `docforge/scripts/latency_report.py` — NEW. CLI rollup of P50/P95/P99 from `query_log.request_ms`.
- `docforge/CONTRIBUTING.md` — NEW. One page.
- `docforge/tests/unit/test_query_log.py` — MODIFY. 2 tests for `request_ms`.
- `docforge/tests/unit/test_api.py` — MODIFY. 1 test asserting `log_query` receives non-None `request_ms`.
- `docforge/tests/unit/test_latency_report.py` — NEW. Pure-function unit tests.
- `docforge/tests/integration/test_purge_orphans.py` — NEW. 3 integration tests against pgvector.

**knowledge-hub repo (direct-push, staggered):**
- `knowledge-hub/rag/docs/runbook.md` — NEW. ~3–4 pages. Populated post-PITR-drill.
- `knowledge-hub/rag/docs/load-profile.md` — NEW. ~1–2 pages. Populated after several days of `request_ms` data.

---

## Phase 0 — Branch setup

### Task 1: Create feature branch for docforge

**Files:** None (git-only).

- [ ] **Step 1: Confirm clean state on master**

Run:
```bash
cd /e/docforge && git status
```
Expected: `On branch master, nothing to commit, working tree clean`.

- [ ] **Step 2: Create + push the feature branch**

Run:
```bash
cd /e/docforge && git checkout -b phase-4-spec-c4 && git push -u origin phase-4-spec-c4
```
Expected: branch created, remote tracking set up.

No commit.

---

## Phase 1 — C4.2 Orphan-purge

### Task 2: Add the `_purge_orphans` helper to `ingest.py`

**Files:**
- Modify: `E:/docforge/docforge/ingest.py`

- [ ] **Step 1: Review existing identifier conventions**

`_ingest_confluence_source` uses `source.page_id` (stored as `confluence_page_id`). `_ingest_git_source` computes `identifier = f"git:{source.repo_path}:{file.file_path}"` (stored as `source_identifier`). The purge helper builds the "current identifiers" set the same way, then diffs against what's in the `sources` table.

- [ ] **Step 2: Add the helper at the bottom of `ingest.py`**

Append this to `docforge/ingest.py`:

```python
async def _purge_orphans(
    pool: asyncpg.Pool,
    current_identifiers: set[str],
    confirm: bool,
) -> tuple[int, int]:
    """Find `sources` rows whose identifier is not in the current sources.yml,
    report them, and (if confirm=True) delete them along with their chunks.

    Identifier format:
        - Confluence: the page_id string (e.g., "5108006937")
        - Git:        f"git:{repo_path}:{file_path}"

    Returns (orphan_source_count, orphan_chunk_count). When confirm=False,
    returns the counts of what WOULD be deleted and leaves the DB untouched.

    chunks.source_id has ON DELETE CASCADE, so deleting from sources
    cascades to chunks automatically.
    """
    async with pool.acquire() as conn:
        # All known identifiers in the DB (both columns are populated
        # exclusively — confluence or source_identifier, never both).
        rows = await conn.fetch(
            """
            SELECT id,
                   title,
                   COALESCE(confluence_page_id, source_identifier) AS identifier
              FROM sources
             WHERE COALESCE(confluence_page_id, source_identifier) IS NOT NULL
            """
        )
        db_identifiers = {r["identifier"]: r for r in rows}
        orphan_ids = [r["id"] for ident, r in db_identifiers.items() if ident not in current_identifiers]

        if not orphan_ids:
            logger.info("No orphan sources detected.")
            return (0, 0)

        chunk_count = await conn.fetchval(
            "SELECT count(*) FROM chunks WHERE source_id = ANY($1::uuid[])",
            orphan_ids,
        )

        logger.info(
            "Orphans detected: %d sources / %d chunks not in current sources.yml",
            len(orphan_ids),
            chunk_count,
        )
        for ident, r in db_identifiers.items():
            if ident not in current_identifiers:
                logger.info("  orphan: %s  (%s)", r["title"], ident)

        if not confirm:
            logger.info(
                "Would delete %d orphan sources (%d chunks). "
                "Re-run with --confirm to execute.",
                len(orphan_ids),
                chunk_count,
            )
            return (len(orphan_ids), chunk_count)

        async with conn.transaction():
            await conn.execute(
                "DELETE FROM sources WHERE id = ANY($1::uuid[])",
                orphan_ids,
            )
        logger.info(
            "Purged %d orphan sources (%d chunks).",
            len(orphan_ids),
            chunk_count,
        )
        return (len(orphan_ids), chunk_count)
```

- [ ] **Step 3: Commit the helper (no caller yet)**

Run:
```bash
cd /e/docforge && git add docforge/ingest.py && git -c commit.gpgsign=false commit -m "Add _purge_orphans helper to ingest (not yet wired to CLI)"
```
Expected: commit created on `phase-4-spec-c4`.

---

### Task 3: Write the three integration tests for `_purge_orphans`

**Files:**
- Create: `E:/docforge/tests/integration/test_purge_orphans.py`

- [ ] **Step 1: Review the existing integration conftest pattern**

`tests/integration/conftest.py:28` spins up a `pgvector/pgvector:pg16` testcontainer; the `pg_url` fixture provides a per-test truncated DB URL. Auto-marks with `@pytest.mark.integration` via the path-check at line 18. Don't add your own marker — it's auto-applied.

- [ ] **Step 2: Write the three failing tests**

Create `tests/integration/test_purge_orphans.py`:

```python
"""Integration tests for docforge.ingest._purge_orphans against pgvector."""

from __future__ import annotations

import asyncpg
import pytest
from datetime import datetime, timezone

from docforge.ingest import _purge_orphans


async def _insert_source(conn, identifier: str, title: str, is_git: bool = True) -> str:
    """Insert a sources row with either source_identifier (git) or
    confluence_page_id (confluence). Returns the inserted id."""
    if is_git:
        return await conn.fetchval(
            """
            INSERT INTO sources (type, url, title, source_identifier,
                                 last_crawled_at, content_hash, status)
            VALUES ('git_repo', $1, $2, $3, $4, 'hash', 'active')
            RETURNING id
            """,
            f"file://fake/{identifier}",
            title,
            identifier,
            datetime.now(timezone.utc),
        )
    return await conn.fetchval(
        """
        INSERT INTO sources (type, url, title, confluence_page_id,
                             last_crawled_at, content_hash, status)
        VALUES ('confluence', $1, $2, $3, $4, 'hash', 'active')
        RETURNING id
        """,
        f"https://fake/{identifier}",
        title,
        identifier,
        datetime.now(timezone.utc),
    )


@pytest.mark.asyncio
async def test_purge_orphans_dry_run_reports_but_does_not_delete(pg_url):
    pool = await asyncpg.create_pool(pg_url)
    try:
        async with pool.acquire() as conn:
            await _insert_source(conn, "git:/repo:current.md", "current")
            await _insert_source(conn, "git:/repo:orphan.md", "orphan")

        # Current sources.yml contains only the first identifier.
        current = {"git:/repo:current.md"}
        sources_deleted, chunks_deleted = await _purge_orphans(pool, current, confirm=False)

        assert sources_deleted == 1
        assert chunks_deleted == 0  # no chunks were inserted above

        async with pool.acquire() as conn:
            n = await conn.fetchval("SELECT count(*) FROM sources")
        assert n == 2, "dry-run must not delete"
    finally:
        await pool.close()


@pytest.mark.asyncio
async def test_purge_orphans_with_confirm_deletes(pg_url):
    pool = await asyncpg.create_pool(pg_url)
    try:
        async with pool.acquire() as conn:
            kept_id = await _insert_source(conn, "git:/repo:current.md", "current")
            orphan_id = await _insert_source(conn, "git:/repo:orphan.md", "orphan")

            # Give the orphan a chunk to verify cascade.
            await conn.execute(
                """
                INSERT INTO chunks (source_id, chunk_index, text, embedding, content_hash)
                VALUES ($1, 0, 'body', array_fill(0.0::real, ARRAY[768])::vector(768), 'h')
                """,
                orphan_id,
            )

        current = {"git:/repo:current.md"}
        sources_deleted, chunks_deleted = await _purge_orphans(pool, current, confirm=True)

        assert sources_deleted == 1
        assert chunks_deleted == 1

        async with pool.acquire() as conn:
            remaining = await conn.fetch(
                "SELECT id, source_identifier FROM sources ORDER BY source_identifier"
            )
            chunks = await conn.fetchval("SELECT count(*) FROM chunks")

        assert [r["source_identifier"] for r in remaining] == ["git:/repo:current.md"]
        assert remaining[0]["id"] == kept_id
        assert chunks == 0, "chunks should cascade-delete with the source"
    finally:
        await pool.close()


@pytest.mark.asyncio
async def test_purge_orphans_confluence_identifier(pg_url):
    pool = await asyncpg.create_pool(pg_url)
    try:
        async with pool.acquire() as conn:
            await _insert_source(conn, "111", "confluence-kept", is_git=False)
            await _insert_source(conn, "222", "confluence-orphan", is_git=False)

        current = {"111"}
        sources_deleted, _ = await _purge_orphans(pool, current, confirm=True)

        assert sources_deleted == 1
        async with pool.acquire() as conn:
            remaining = await conn.fetchval(
                "SELECT confluence_page_id FROM sources"
            )
        assert remaining == "111"
    finally:
        await pool.close()
```

Note the `array_fill(0.0::real, ARRAY[768])::vector(768)` pattern creates a valid 768-dim embedding without needing the real embedder. The `chunks` table's `embedding` column is `vector(768) NOT NULL`.

- [ ] **Step 3: Run tests to verify they pass**

Run:
```bash
cd /e/docforge && /e/docforge/.venv/Scripts/python.exe -m pytest tests/integration/test_purge_orphans.py -v --no-cov
```
Expected: all 3 pass (the helper from Task 2 already exists). First run takes ~10s for the testcontainer to spin up.

If a test fails with "column does not exist": the schema differs from what the test assumes. Check `docforge/sql/schema.sql` for the actual `sources` / `chunks` column names and adjust.

- [ ] **Step 4: Commit**

```bash
cd /e/docforge && git add tests/integration/test_purge_orphans.py && git -c commit.gpgsign=false commit -m "Add integration tests for _purge_orphans"
```

---

### Task 4: Wire `--purge-orphans` + `--confirm` into the CLI

**Files:**
- Modify: `E:/docforge/docforge/cli.py`
- Modify: `E:/docforge/docforge/ingest.py` (extend `ingest_all` to accept and pass the flag)

- [ ] **Step 1: Extend `ingest_all` signature**

In `docforge/ingest.py`, find `async def ingest_all(settings: Settings) -> None:` and change the signature + final block:

Before:
```python
async def ingest_all(settings: Settings) -> None:
    """Run the full ingest pipeline for all configured sources."""
    sources = load_sources(settings.sources_file)
    ...
    # existing loop; nothing after the loop
```

After:
```python
async def ingest_all(
    settings: Settings,
    *,
    purge_orphans: bool = False,
    confirm: bool = False,
) -> None:
    """Run the full ingest pipeline for all configured sources.

    When purge_orphans=True, after all sources have been ingested, any
    `sources` rows whose identifier is not in the current sources.yml are
    reported (and — if confirm=True — deleted). See _purge_orphans."""
    sources = load_sources(settings.sources_file)
    ...
    # existing loop unchanged ...

    if purge_orphans:
        current_identifiers: set[str] = set()
        for source in sources:
            if isinstance(source, ConfluenceSourceConfig):
                current_identifiers.add(source.page_id)
            elif isinstance(source, GitRepoSourceConfig):
                from docforge.crawlers.git import crawl_repo
                files = crawl_repo(source.repo_path, source.include_patterns)
                for f in files:
                    current_identifiers.add(f"git:{source.repo_path}:{f.file_path}")
        await _purge_orphans(pool, current_identifiers, confirm=confirm)
```

Note: the git branch re-crawls locally to build the identifier set. This is the same `crawl_repo` call the ingest loop makes, so it's cache-hot and fast.

- [ ] **Step 2: Extend the CLI command**

In `docforge/cli.py`, find the existing `ingest` command. Currently:

```python
@app.command()
def ingest():
    """Crawl all sources, embed, and store in PostgreSQL."""
    _setup_logging()
    asyncio.run(_ingest())
```

Replace with:

```python
@app.command()
def ingest(
    purge_orphans: bool = typer.Option(
        False,
        "--purge-orphans",
        help="After ingest, report sources in the DB but not in current sources.yml. Default dry-run; pass --confirm to delete.",
    ),
    confirm: bool = typer.Option(
        False,
        "--confirm",
        help="Required alongside --purge-orphans to actually delete orphans.",
    ),
):
    """Crawl all sources, embed, and store in PostgreSQL."""
    _setup_logging()
    if confirm and not purge_orphans:
        typer.echo("Error: --confirm only applies to --purge-orphans", err=True)
        raise typer.Exit(1)
    asyncio.run(_ingest(purge_orphans=purge_orphans, confirm=confirm))
```

Update the `_ingest` helper:

```python
async def _ingest(purge_orphans: bool = False, confirm: bool = False):
    from docforge.config import Settings
    from docforge.db import close_pool
    from docforge.ingest import ingest_all

    settings = Settings()
    try:
        await ingest_all(settings, purge_orphans=purge_orphans, confirm=confirm)
    except OSError as e:
        typer.echo(
            f"Error: Cannot connect to database. Is PostgreSQL running?\n{e}",
            err=True,
        )
        raise typer.Exit(1)
    except RuntimeError as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(1)
    except Exception as e:
        typer.echo(f"Error during ingest: {e}", err=True)
        raise typer.Exit(1)
    finally:
        await close_pool()
```

- [ ] **Step 3: Smoke-test `--help`**

Run:
```bash
cd /e/docforge && /e/docforge/.venv/Scripts/python.exe -m docforge ingest --help 2>&1 | tail -15
```
Expected: both `--purge-orphans` and `--confirm` appear in the options listing.

- [ ] **Step 4: Quick unit-level sanity on the CLI wiring**

Run:
```bash
cd /e/docforge && /e/docforge/.venv/Scripts/python.exe -m pytest tests/unit/test_cli.py -q --no-cov
```
Expected: existing CLI tests still pass.

- [ ] **Step 5: Commit**

```bash
cd /e/docforge && git add docforge/cli.py docforge/ingest.py && git -c commit.gpgsign=false commit -m "Wire --purge-orphans + --confirm flags into docforge ingest CLI"
```

---

## Phase 2 — C4.5 CONTRIBUTING.md

### Task 5: Write `docforge/CONTRIBUTING.md`

**Files:**
- Create: `E:/docforge/CONTRIBUTING.md`

- [ ] **Step 1: Write the doc**

Create `CONTRIBUTING.md` at the repo root:

```markdown
# Contributing to docforge

Thanks for your interest in contributing. This project is maintained by a single engineer at the time of writing; PRs are welcome but expect short feedback loops rather than fast review turnaround.

## Quickstart

```bash
git clone https://github.com/GranatenUdo/docforge
cd docforge
python -m venv .venv
.venv\Scripts\activate          # Windows
source .venv/bin/activate        # Linux / macOS
pip install -e ".[dev,entra]"
pytest -m "not integration"      # unit tests only; fast (<30s)
pytest -m integration            # integration tests; slower (~2min, spins up pgvector container)
```

For deeper architectural context, read `CLAUDE.md` at the repo root.

## PR requirements

Branch protection on `master` requires the two CI checks to pass before merge:

- **`lint`** — `ruff check docforge tests` + `ruff format --check docforge tests`
- **`test`** — `pytest -m "not integration"` with a ≥60% coverage gate

If you add a new Python file, running `pytest --cov` locally first avoids surprise CI failures.

### Migration files

SQL migrations live under `docforge/sql/migrations/` and are numbered sequentially: `NNN_description.sql`. The next free number is easy to see with `ls docforge/sql/migrations/ | tail -1`. Migrations are applied automatically by `docforge init-db` on fresh installs; existing deployments need the migration applied manually (see runbook).

### Schema changes to `query_log`

The `query_log` table is governed by `knowledge-hub/rag/docs/log-privacy.md`. Any change to its schema (new column, retention semantics, identity-handling) requires updating that doc in the same PR (or a follow-up PR merged before the schema change reaches production).

## Branch flow

- Branch per PR against `master`.
- Direct push to `master` is blocked by branch protection.
- Squash-merge is the default; feature-branch names follow `phase-N-spec-Y` or `feature/<short-name>`.

## Code style

- `ruff format` + `ruff check` are authoritative; CI rejects unformatted code.
- Python type hints on all function signatures.
- Pydantic v2 for data models; pydantic-settings for configuration.
- `async def` for endpoints and DB ops; sync is fine everywhere else.
- No type-checker in CI (deliberately — signal-over-ritual at solo-maintainer scale). Revisit if the team grows.

## Optional extras

- `docforge[dev]` — test + lint tooling.
- `docforge[entra]` — `fastapi-azure-auth` + `azure-identity` + `aiohttp`, required when `auth.mode: entra` in `docforge.yml`. For first-time Entra setup in a new tenant, see `deploy/azure/bootstrap-entra.sh` (one-shot script that creates the app registration, exposes the `search` scope, and grants tenant-wide consent).

## Where to ask

Open an issue at https://github.com/GranatenUdo/docforge/issues or email the maintainer (tobias.ens@docuware.com).
```

- [ ] **Step 2: Commit**

```bash
cd /e/docforge && git add CONTRIBUTING.md && git -c commit.gpgsign=false commit -m "Add CONTRIBUTING.md"
```

---

## Phase 3 — C4.3 Request-timing instrumentation

### Task 6: Write migration 006

**Files:**
- Create: `E:/docforge/docforge/sql/migrations/006_add_query_log_request_ms.sql`

- [ ] **Step 1: Write the migration**

Create `docforge/sql/migrations/006_add_query_log_request_ms.sql`:

```sql
ALTER TABLE query_log ADD COLUMN IF NOT EXISTS request_ms INT;
```

No index: `query_log` stays small (180-day retention; single-team volume) and the latency report's percentile queries are infrequent operational reads, not user-facing queries.

- [ ] **Step 2: Commit**

```bash
cd /e/docforge && git add docforge/sql/migrations/006_add_query_log_request_ms.sql && git -c commit.gpgsign=false commit -m "Add migration 006: query_log.request_ms column"
```

Production application happens in Phase 5 (Task 16).

---

### Task 7: Extend `log_query()` with `request_ms` (TDD)

**Files:**
- Modify: `E:/docforge/docforge/query_log.py`
- Modify: `E:/docforge/tests/unit/test_query_log.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_query_log.py`:

```python
@pytest.mark.asyncio
async def test_log_query_accepts_request_ms():
    conn = _ConnCapture()
    pool = _FakePool(conn)
    await log_query(
        pool=pool,
        user_name="tobias.ens",
        team_name="ccl",
        area_name="cloud",
        query="q",
        result_count=3,
        user_oid="oid-1",
        request_ms=42,
    )
    _, args = conn.executed[0]
    # args is now (user_name, team_name, area_name, query, result_count,
    # user_oid, request_ms) — request_ms is the 7th/last positional.
    assert args[-1] == 42


@pytest.mark.asyncio
async def test_log_query_request_ms_defaults_to_none():
    conn = _ConnCapture()
    pool = _FakePool(conn)
    await log_query(
        pool=pool,
        user_name="a",
        team_name="b",
        area_name=None,
        query="q",
        result_count=0,
    )
    _, args = conn.executed[0]
    assert args[-1] is None
```

- [ ] **Step 2: Also update the existing `test_log_query_inserts_row` to match the new arg count**

Find the assertion on line ~55 in `tests/unit/test_query_log.py`:

```python
assert args == ("tobias.ens", "ccl", "cloud", "retry policy", 3, None)
```

Change to:

```python
assert args == ("tobias.ens", "ccl", "cloud", "retry policy", 3, None, None)
```

(user_oid defaults to None; request_ms also defaults to None.)

- [ ] **Step 3: Run tests to verify they fail**

Run:
```bash
cd /e/docforge && /e/docforge/.venv/Scripts/python.exe -m pytest tests/unit/test_query_log.py -v --no-cov
```
Expected: 3 tests fail (2 new, plus the updated `test_log_query_inserts_row`).

- [ ] **Step 4: Update `log_query()` in `docforge/query_log.py`**

Current signature (from C3.5):
```python
async def log_query(
    pool: asyncpg.Pool,
    user_name: str,
    team_name: str,
    area_name: str | None,
    query: str,
    result_count: int,
    user_oid: str | None = None,
) -> None:
```

Change to:

```python
async def log_query(
    pool: asyncpg.Pool,
    user_name: str,
    team_name: str,
    area_name: str | None,
    query: str,
    result_count: int,
    user_oid: str | None = None,
    request_ms: int | None = None,
) -> None:
    """Record a search request. user_oid is the Entra object ID (post-auth)
    or None (pre-auth rows). request_ms is the handler's wall-clock time in
    milliseconds (post-C4.3) or None (pre-C4.3 rows). Never raises."""
    try:
        async with pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO query_log
                    (user_name, team_name, area_name, query, result_count, user_oid, request_ms)
                VALUES ($1, $2, $3, $4, $5, $6, $7)
                """,
                user_name,
                team_name,
                area_name,
                query,
                result_count,
                user_oid,
                request_ms,
            )
    except Exception as e:
        logger.warning("query_log insert failed: %s", e)
```

- [ ] **Step 5: Run tests to verify they pass**

Run:
```bash
cd /e/docforge && /e/docforge/.venv/Scripts/python.exe -m pytest tests/unit/test_query_log.py -v --no-cov
```
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
cd /e/docforge && git add docforge/query_log.py tests/unit/test_query_log.py && git -c commit.gpgsign=false commit -m "Extend log_query() with optional request_ms parameter"
```

---

### Task 8: Time the `/search` handler + write the assertion test

**Files:**
- Modify: `E:/docforge/docforge/api.py`
- Modify: `E:/docforge/tests/unit/test_api.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/test_api.py` at the bottom of the file:

```python
class TestRequestTimingInstrumentation:
    """C4.3 — the /search handler measures its own wall-clock time and
    passes request_ms into log_query."""

    @pytest.mark.asyncio
    async def test_search_writes_request_ms_to_query_log(self, monkeypatch):
        captured: dict = {}

        async def fake_log_query(*args, **kwargs):
            captured.update(kwargs)

        monkeypatch.setattr("docforge.query_log.log_query", fake_log_query)
        monkeypatch.setattr(api_module, "_get_settings", _settings_stub)
        monkeypatch.setattr(api_module, "_azure_scheme", None)

        class _FakeEmbedder:
            model_name = "test"
            dimensions = 768

            def embed_query(self, q):
                return [0.0] * 768

        monkeypatch.setattr(api_module, "_embedder", _FakeEmbedder())

        async def fake_get_pool(url):
            return _CapturingPool(rows=[])

        monkeypatch.setattr(api_module, "get_pool", fake_get_pool)

        async with _client() as client:
            resp = await client.post(
                "/search",
                json={
                    "query": "test",
                    "user_name": "tobias",
                    "team_name": "ccl",
                    "area_name": None,
                    "limit": 3,
                },
            )
        assert resp.status_code == 200
        assert "request_ms" in captured
        assert isinstance(captured["request_ms"], int)
        assert captured["request_ms"] >= 0
        # Sanity: should be much less than a second for a stubbed handler.
        assert captured["request_ms"] < 1000
```

- [ ] **Step 2: Run the test to verify it fails**

Run:
```bash
cd /e/docforge && /e/docforge/.venv/Scripts/python.exe -m pytest tests/unit/test_api.py::TestRequestTimingInstrumentation -v --no-cov
```
Expected: fails — current `/search` handler doesn't pass `request_ms` to `log_query`.

- [ ] **Step 3: Add timing to the `/search` handler in `api.py`**

Find `async def search(req: SearchRequest, user=Depends(_auth_dependency)) -> SearchResponse:` in `docforge/api.py`. It already imports `asyncio` at the top. Add `import time` at the top with the other stdlib imports if not present — grep first:

```bash
grep -n "^import time" /e/docforge/docforge/api.py
```

If no hit, add it at the top of the stdlib import block.

Modify the handler so timing wraps the work:

```python
@app.post("/search", response_model=SearchResponse)
async def search(req: SearchRequest, user=Depends(_auth_dependency)) -> SearchResponse:
    """Search indexed documentation by semantic similarity."""
    start = time.perf_counter()

    if not _embedder:
        raise HTTPException(status_code=503, detail="Embedding model not loaded yet")

    # ... existing embedder + DB query logic (unchanged) ...

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
    return SearchResponse(
        results=results, query=req.query, count=len(results)
    )
```

Notes:
- `start` at the top captures entry time — including the `_embedder is None` short-circuit error case (where `log_query` isn't called anyway).
- The measurement includes embedding + DB query. That's the right window; model is already loaded so the cost is inference + vector search.
- Apply the **same** pattern to `list_sources` too:

```python
@app.get("/sources")
async def list_sources(user=Depends(_auth_dependency)) -> dict[str, Any]:
    """List all indexed documentation sources."""
    start = time.perf_counter()
    # ... existing query ...
    # After the query, if /sources doesn't write to query_log today, skip
    # the log_query call — we only time endpoints that already log. The
    # request_ms field is specifically for search-query latency.
```

**Decision:** /sources does NOT write to `query_log` today (it's a sources listing, not a search). Leave it untimed to keep `query_log` focused on search latency. Revert the `/sources` change after adding it — the spec's "timing on /search + /sources" was ambitious; only `/search` has a meaningful log row.

If you've already added timing to `/sources`, remove it.

- [ ] **Step 4: Run the test to verify it passes**

Run:
```bash
cd /e/docforge && /e/docforge/.venv/Scripts/python.exe -m pytest tests/unit/test_api.py -v --no-cov
```
Expected: all pass (new + existing).

- [ ] **Step 5: Also ensure `cli.py` and `mcp_server.py` callers of `log_query` still compile**

These callers don't pass `request_ms` — it defaults to None. No changes needed, but a quick check:

```bash
grep -n "log_query(" /e/docforge/docforge/cli.py /e/docforge/docforge/mcp_server.py
```
Expected: both pass without `request_ms` (which is fine; it defaults).

- [ ] **Step 6: Commit**

```bash
cd /e/docforge && git add docforge/api.py tests/unit/test_api.py && git -c commit.gpgsign=false commit -m "Time /search handler; write request_ms into query_log"
```

---

### Task 9: Write `docforge/scripts/latency_report.py`

**Files:**
- Create: `E:/docforge/docforge/scripts/latency_report.py`
- Create: `E:/docforge/tests/unit/test_latency_report.py`

- [ ] **Step 1: Write the script**

Create `docforge/scripts/latency_report.py`:

```python
"""Compute P50 / P95 / P99 latency over recent query_log entries.

Usage:
    python -m docforge.scripts.latency_report --since '7 days' [--database-url ...]

Reads DATABASE_URL from the environment (or --database-url flag) so it can
run against prod with the admin connection string from Key Vault.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from dataclasses import dataclass

import asyncpg


@dataclass(frozen=True)
class LatencySummary:
    n: int
    p50_ms: float | None
    p95_ms: float | None
    p99_ms: float | None
    earliest_request_ms_at: str | None  # ISO timestamp of first post-C4.3 row


async def compute_summary(database_url: str, since: str) -> LatencySummary:
    """Query query_log.request_ms within the given interval. Returns
    percentiles + row count + the earliest-seen request_ms timestamp (the
    effective C4.3 cutover date for this DB)."""
    conn = await asyncpg.connect(database_url)
    try:
        row = await conn.fetchrow(
            """
            SELECT
                percentile_cont(0.50) WITHIN GROUP (ORDER BY request_ms) AS p50,
                percentile_cont(0.95) WITHIN GROUP (ORDER BY request_ms) AS p95,
                percentile_cont(0.99) WITHIN GROUP (ORDER BY request_ms) AS p99,
                count(*)                                                 AS n
              FROM query_log
             WHERE request_ms IS NOT NULL
               AND created_at > now() - $1::interval
            """,
            since,
        )
        earliest = await conn.fetchval(
            "SELECT min(created_at) FROM query_log WHERE request_ms IS NOT NULL"
        )
        return LatencySummary(
            n=int(row["n"]),
            p50_ms=float(row["p50"]) if row["p50"] is not None else None,
            p95_ms=float(row["p95"]) if row["p95"] is not None else None,
            p99_ms=float(row["p99"]) if row["p99"] is not None else None,
            earliest_request_ms_at=earliest.isoformat() if earliest is not None else None,
        )
    finally:
        await conn.close()


def format_summary(summary: LatencySummary, since: str) -> str:
    """Human-readable stdout report."""
    lines = [
        f"Window:                 last {since}",
        f"Queries with timing:    {summary.n}",
    ]
    if summary.n == 0:
        lines.append("No rows with request_ms in the window — has the C4.3 migration been applied and the /search handler redeployed?")
        return "\n".join(lines)
    lines.extend([
        f"P50:                    {summary.p50_ms:.0f} ms",
        f"P95:                    {summary.p95_ms:.0f} ms",
        f"P99:                    {summary.p99_ms:.0f} ms",
    ])
    if summary.earliest_request_ms_at is not None:
        lines.append(f"request_ms cutover at:  {summary.earliest_request_ms_at}")
    lines.append("")
    lines.append("Note: the earliest ~1-2 rows after each revision deployment include")
    lines.append("the 15-30 s embedding-model warm-up cost; this is kept in the data as")
    lines.append("honest signal. P95 therefore reflects warm-up+steady-state.")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--since",
        default="7 days",
        help="Postgres interval string (e.g., '7 days', '24 hours'). Default: 7 days.",
    )
    parser.add_argument(
        "--database-url",
        default=None,
        help="Postgres URL. Falls back to DATABASE_URL env var.",
    )
    args = parser.parse_args()

    db_url = args.database_url or os.environ.get("DATABASE_URL")
    if not db_url:
        print("Error: DATABASE_URL not set (and --database-url not provided)", file=sys.stderr)
        return 1

    summary = asyncio.run(compute_summary(db_url, args.since))
    print(format_summary(summary, args.since))
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: Write pure-function unit tests**

Create `tests/unit/test_latency_report.py`:

```python
"""Pure-function unit tests for docforge.scripts.latency_report."""

from __future__ import annotations

from docforge.scripts.latency_report import LatencySummary, format_summary


def test_format_summary_empty_window():
    s = LatencySummary(n=0, p50_ms=None, p95_ms=None, p99_ms=None, earliest_request_ms_at=None)
    out = format_summary(s, "7 days")
    assert "No rows with request_ms" in out
    assert "Queries with timing:    0" in out


def test_format_summary_with_data():
    s = LatencySummary(
        n=1234,
        p50_ms=87.5,
        p95_ms=412.0,
        p99_ms=1830.3,
        earliest_request_ms_at="2026-04-22T19:00:00+00:00",
    )
    out = format_summary(s, "7 days")
    assert "Queries with timing:    1234" in out
    assert "P50:                    88 ms" in out  # %.0f rounds 87.5 to 88
    assert "P95:                    412 ms" in out
    assert "P99:                    1830 ms" in out
    assert "warm-up+steady-state" in out
    assert "cutover at:             2026-04-22T19:00:00+00:00" in out


def test_format_summary_rounding():
    """%.0f uses banker's rounding for .5 values — just smoke-test it doesn't crash."""
    s = LatencySummary(n=1, p50_ms=0.4, p95_ms=0.6, p99_ms=999.99, earliest_request_ms_at=None)
    out = format_summary(s, "1 hour")
    assert "P50:" in out
    assert "P99:                    1000 ms" in out  # 999.99 rounds up


def test_format_summary_argparse_help_unaffected():
    """Sanity: the module imports cleanly (i.e., argparse declarations valid)."""
    from docforge.scripts import latency_report
    assert latency_report.main is not None
```

Also a smoke-test on `--help` (no unit test for `compute_summary` — that's a live-DB operation covered by the Phase 5 live run):

```bash
cd /e/docforge && /e/docforge/.venv/Scripts/python.exe -m docforge.scripts.latency_report --help | head -3
```
Expected: argparse help prints without error.

- [ ] **Step 3: Run the tests to verify they pass**

Run:
```bash
cd /e/docforge && /e/docforge/.venv/Scripts/python.exe -m pytest tests/unit/test_latency_report.py -v --no-cov
```
Expected: all pass.

- [ ] **Step 4: Commit**

```bash
cd /e/docforge && git add docforge/scripts/latency_report.py tests/unit/test_latency_report.py && git -c commit.gpgsign=false commit -m "Add docforge.scripts.latency_report (P50/P95/P99 over query_log.request_ms)"
```

---

## Phase 4 — Open the docforge PR

### Task 10: Full-suite check + ruff + open PR

**Files:** None new.

- [ ] **Step 1: Full unit suite + ruff**

Run:
```bash
cd /e/docforge && /e/docforge/.venv/Scripts/python.exe -m pytest tests/unit/ -q
```
Expected: all pass; coverage ≥60%.

Run:
```bash
cd /e/docforge && /e/docforge/.venv/Scripts/python.exe -m ruff format --check . && /e/docforge/.venv/Scripts/python.exe -m ruff check .
```
Expected: both exit 0. If format-check fails:
```bash
cd /e/docforge && /e/docforge/.venv/Scripts/python.exe -m ruff format . && git add -u && git -c commit.gpgsign=false commit -m "style: ruff format sweep"
```

- [ ] **Step 2: Push**

Run:
```bash
cd /e/docforge && git push origin phase-4-spec-c4
```

- [ ] **Step 3: Open the PR**

Run:
```bash
cd /e/docforge && gh pr create --title "Phase 4 Spec C4: operational readiness (orphan-purge, request-timing, latency-report, CONTRIBUTING)" --body "$(cat <<'EOF'
## Summary

Implements Spec C4 (docs/superpowers/specs/2026-04-22-operational-readiness-design.md). Ships the operational-readiness deliverables derived from Spec D §4; after merge + load-profile commit, the 14-day Spec D soak clock starts.

## Deliverables (this PR)

- **C4.2** — `docforge ingest --purge-orphans` (default dry-run; `--confirm` to delete). Cleans up DB rows whose identifier is not in current sources.yml. Real operational issue: DB has ~140 rows vs 72 current sources; roughly half the index is stale.
- **C4.3** — in-handler `perf_counter()` timing on `/search`; writes `request_ms` into `query_log`. Migration 006 adds the column (applied to prod as a separate step).
- **C4.5** — `CONTRIBUTING.md` at repo root.
- Plus `docforge/scripts/latency_report.py` for P50/P95/P99 rollups.

## Deliverables in knowledge-hub (land on master after this PR merges)

- **C4.1** — `knowledge-hub/rag/docs/runbook.md` (populated from C4.6 PITR drill).
- **C4.4** — `knowledge-hub/rag/docs/load-profile.md` (populated after several days of request_ms data).
- **C4.6** — PITR dry-run executed against a throwaway server; results land in the runbook.

## Test plan

- [x] 3 new integration tests for `_purge_orphans` (testcontainers pgvector, per-test truncate)
- [x] Unit tests for request_ms kwarg on log_query + handler assertion via ASGITransport
- [x] Unit tests for latency_report pure functions
- [x] Full unit suite passes; coverage gate ≥60%
- [x] ruff format + check clean

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

- [ ] **Step 4: Wait for CI to go green**

Run:
```bash
for i in 1 2 3 4 5 6 7 8 9 10 11 12; do
  sleep 30
  state=$(gh pr view --json statusCheckRollup --jq '.statusCheckRollup | map(.name + ":" + .conclusion) | join(" ")' 2>&1)
  echo "t=$((i*30))s $state"
  if echo "$state" | grep -qE "FAILURE|lint:SUCCESS test:SUCCESS|test:SUCCESS lint:SUCCESS"; then
    break
  fi
done
```
Expected: eventually `lint:SUCCESS test:SUCCESS`.

- [ ] **Step 5: No commit (PR-level task)**

---

### Task 11: User-review + merge

**Files:** None (human gate).

- [ ] **Step 1: Present the PR URL + summary to the user for review**

Print the PR URL:
```bash
gh pr view --json url --jq .url
```

Ask the user to review and approve/merge.

- [ ] **Step 2: Once user approves, squash-merge**

Run (once approved):
```bash
gh pr merge --squash --delete-branch
```

- [ ] **Step 3: Reset local state**

```bash
cd /e/docforge && git checkout master && git fetch --prune origin && git reset --hard origin/master
```

---

## Phase 5 — Production deploy + migration 006

### Task 12: Rebuild + redeploy the container image

**Files:** None (Azure tasks).

- [ ] **Step 1: Rebuild the container (remote source — proxy-tolerant)**

Run:
```bash
cd /e/docforge && az acr build -r dwdocforgeacr -t docforge:latest . --no-logs 2>&1 | tail -3
```

- [ ] **Step 2: Wait for the build to complete**

Run:
```bash
for i in 1 2 3 4 5 6 7 8 9 10 11 12; do
  sleep 30
  status=$(az acr task list-runs -r dwdocforgeacr --top 1 --query "[0].status" -o tsv 2>&1)
  echo "t=$((i*30))s $status"
  if [ "$status" = "Succeeded" ] || [ "$status" = "Failed" ]; then break; fi
done
```
Expected: `Succeeded`.

- [ ] **Step 3: Apply migration 006 to the production DB**

Migration 006 must land BEFORE the new code runs, otherwise the `/search` handler's `INSERT INTO query_log (..., request_ms) VALUES (..., $7)` will fail on a column that doesn't exist. Same pattern as C3.5.

Run:
```bash
set -a
source /e/knowledge-hub/rag/infrastructure/secrets.env
set +a

/e/docforge/.venv/Scripts/python.exe <<'EOF'
import asyncio, asyncpg, os
async def apply():
    conn = await asyncpg.connect(
        host="docforge-pg.postgres.database.azure.com", user="dfadmin",
        password=os.environ['POSTGRES_ADMIN_PASSWORD'], database="docforge",
        port=5432, ssl='require',
    )
    with open(r'E:\docforge\docforge\sql\migrations\006_add_query_log_request_ms.sql') as f:
        sql = f.read()
    await conn.execute(sql)
    cols = await conn.fetch(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_name='query_log' ORDER BY ordinal_position"
    )
    print('query_log columns:', [c['column_name'] for c in cols])
    await conn.close()
asyncio.run(apply())
EOF
```
Expected: output includes `request_ms` in the column list (alongside existing columns).

- [ ] **Step 4: Deploy the new revision**

Run:
```bash
az containerapp update --name docforge-search-api --resource-group docforge-test \
  --image "dwdocforgeacr.azurecr.io/docforge:latest" \
  --revision-suffix "c4-$(date +%s)" 2>&1 | tail -3
```

- [ ] **Step 5: Wait for new revision to become healthy**

Run:
```bash
for i in 1 2 3 4 5 6 7 8 9 10 11 12; do
  sleep 20
  health=$(curl -sS -o /dev/null -w "%{http_code}" --max-time 5 https://docforge-search-api.ashyhill-c79f3b95.westeurope.azurecontainerapps.io/health 2>&1)
  echo "t=$((i*20))s /health=$health"
  [ "$health" = "200" ] && break
done
```

- [ ] **Step 6: No commit (infra task)**

---

### Task 13: Live smoke test — confirm `request_ms` is populated

**Files:** None (live verification).

- [ ] **Step 1: Fire a live authenticated query and confirm the DB captures request_ms**

Run:
```bash
/e/docforge/.venv/Scripts/python.exe <<'EOF'
import asyncio, json, base64
from azure.identity.aio import DefaultAzureCredential
import httpx

async def run():
    cred = DefaultAzureCredential()
    token = await cred.get_token("api://a94315d8-b023-4280-9d8d-cfa080fce4d1/.default")
    await cred.close()
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.post(
            "https://docforge-search-api.ashyhill-c79f3b95.westeurope.azurecontainerapps.io/search",
            headers={"Authorization": f"Bearer {token.token}"},
            json={"query": "smoke test c4", "user_name": "tobias.ens", "team_name": "ccl", "area_name": "cloud", "limit": 2},
        )
    print("HTTP:", r.status_code)
    print("count:", r.json().get("count"))

asyncio.run(run())
EOF
```
Expected: HTTP 200; count ≥ 0.

- [ ] **Step 2: Check the latest `query_log` row has a populated `request_ms`**

Run:
```bash
set -a; source /e/knowledge-hub/rag/infrastructure/secrets.env; set +a
/e/docforge/.venv/Scripts/python.exe <<'EOF'
import asyncio, asyncpg, os
async def check():
    conn = await asyncpg.connect(
        host="docforge-pg.postgres.database.azure.com", user="dfadmin",
        password=os.environ['POSTGRES_ADMIN_PASSWORD'], database="docforge",
        port=5432, ssl='require',
    )
    row = await conn.fetchrow(
        "SELECT user_name, request_ms, query, created_at "
        "FROM query_log ORDER BY created_at DESC LIMIT 1"
    )
    print(dict(row))
    await conn.close()
asyncio.run(check())
EOF
```
Expected: `request_ms` is a non-None integer (probably 50-500 ms); `user_name` is an Entra UPN; `query` is "smoke test c4".

- [ ] **Step 3: Run the latency-report script live**

Run:
```bash
set -a; source /e/knowledge-hub/rag/infrastructure/secrets.env; set +a
export DATABASE_URL="postgresql://dfadmin:${POSTGRES_ADMIN_PASSWORD}@docforge-pg.postgres.database.azure.com:5432/docforge?sslmode=require"

/e/docforge/.venv/Scripts/python.exe -m docforge.scripts.latency_report --since '1 hour'
```
Expected: a summary with non-None percentiles and `n >= 1`.

- [ ] **Step 4: No commit (live verification)**

If any step fails: check container logs (`az containerapp logs show --name docforge-search-api --resource-group docforge-test --tail 50`) for migration-not-applied errors and re-apply migration 006.

---

## Phase 6 — C4.6 PITR dry-run

### Task 14: Initiate PITR restore to a throwaway server

**Files:** None (Azure task). Will capture commands + output for the runbook in Task 16.

- [ ] **Step 1: Record baseline counts before the drill**

Run:
```bash
set -a; source /e/knowledge-hub/rag/infrastructure/secrets.env; set +a
/e/docforge/.venv/Scripts/python.exe <<'EOF'
import asyncio, asyncpg, os
async def run():
    conn = await asyncpg.connect(
        host="docforge-pg.postgres.database.azure.com", user="dfadmin",
        password=os.environ['POSTGRES_ADMIN_PASSWORD'], database="docforge",
        port=5432, ssl='require',
    )
    for table in ("sources", "chunks", "query_log"):
        n = await conn.fetchval(f"SELECT count(*) FROM {table}")
        print(f"baseline {table}: {n}")
    await conn.close()
asyncio.run(run())
EOF
```
Record the output — you'll compare after restore in Task 15.

- [ ] **Step 2: Note the current UTC time and compute a restore point 30 minutes in the past**

```bash
NOW=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
RESTORE_POINT=$(date -u -d "30 minutes ago" +"%Y-%m-%dT%H:%M:%SZ")
echo "current UTC:   $NOW"
echo "restore point: $RESTORE_POINT"
```

- [ ] **Step 3: Fire the restore**

Azure uses `az postgres flexible-server restore` with `--restore-time` to create a new server restored to the given timestamp.

```bash
RESTORE_POINT=$(date -u -d "30 minutes ago" +"%Y-%m-%dT%H:%M:%SZ")

az postgres flexible-server restore \
  --resource-group docforge-test \
  --name docforge-pg-pitr-test \
  --source-server docforge-pg \
  --restore-time "$RESTORE_POINT" \
  --location westeurope \
  2>&1 | tee /tmp/pitr-restore.log | tail -3
```

Expected: command returns a JSON resource description (restore takes 10-15 min, but the CLI returns once the background operation is accepted).

Record the exact command + output for the runbook.

- [ ] **Step 4: Poll for the restore to complete**

```bash
for i in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17 18; do
  sleep 60
  state=$(az postgres flexible-server show --resource-group docforge-test --name docforge-pg-pitr-test --query "state" -o tsv 2>&1)
  echo "t=$((i*60))s state=$state"
  [ "$state" = "Ready" ] && break
done
```
Expected: `state=Ready` within ~10-15 min.

Record the end-to-end restore duration.

---

### Task 15: Verify the restore + capture counts

**Files:** None.

- [ ] **Step 1: Query the throwaway server and compare to baseline**

```bash
set -a; source /e/knowledge-hub/rag/infrastructure/secrets.env; set +a
/e/docforge/.venv/Scripts/python.exe <<'EOF'
import asyncio, asyncpg, os
async def run():
    conn = await asyncpg.connect(
        host="docforge-pg-pitr-test.postgres.database.azure.com", user="dfadmin",
        password=os.environ['POSTGRES_ADMIN_PASSWORD'], database="docforge",
        port=5432, ssl='require',
    )
    for table in ("sources", "chunks", "query_log"):
        n = await conn.fetchval(f"SELECT count(*) FROM {table}")
        print(f"restored {table}: {n}")
    latest_log = await conn.fetchval("SELECT max(created_at) FROM query_log")
    print(f"latest query_log entry:  {latest_log}")
    await conn.close()
asyncio.run(run())
EOF
```

Expected: counts are close to baseline (may be slightly lower — the restore point is 30 min in the past; anything written in the interim isn't present). `latest query_log entry` should be ≤ the restore point.

Record the output.

- [ ] **Step 2: Delete the throwaway server**

```bash
az postgres flexible-server delete \
  --resource-group docforge-test \
  --name docforge-pg-pitr-test \
  --yes 2>&1 | tail -3
```
Expected: deletion accepted. Confirm with:
```bash
az postgres flexible-server show --resource-group docforge-test --name docforge-pg-pitr-test 2>&1 | head -3
```
Expected: `(ResourceNotFound)` error — server gone.

- [ ] **Step 3: No commit (infra task; notes used in Task 16)**

---

## Phase 7 — C4.1 Runbook

### Task 16: Write `knowledge-hub/rag/docs/runbook.md`

**Files:**
- Create: `E:/knowledge-hub/rag/docs/runbook.md`

- [ ] **Step 1: Write the runbook**

Use the outline from Spec C4 §C4.1 plus the real commands and timings captured in Phase 6. The runbook has a `Last verified: YYYY-MM-DD` stamp at the top that you bump on each verification pass.

Create `knowledge-hub/rag/docs/runbook.md`:

```markdown
# docforge incident runbook — DocuWare CCL deployment

**Last verified:** 2026-04-22

Playbook for the CCL deployment at `docforge-search-api.ashyhill-c79f3b95.westeurope.azurecontainerapps.io`. Reader: the current on-call engineer (= maintainer; bus-factor-1 is named plainly in Spec D). Assumes Azure subscription access + DB admin creds in Key Vault.

## How to reach the system

| Resource | Name | Notes |
|---|---|---|
| Azure subscription | `CloudCL-Test` | `az account set --subscription CloudCL-Test` |
| Resource group | `docforge-test` | Both compute + data |
| Container App | `docforge-search-api` | Public ingress (`external: true`), Entra-protected |
| Postgres | `docforge-pg` (`docforge-pg.postgres.database.azure.com`) | Standard_B1ms, 7-day PITR |
| Key Vault | `docforge-kv` | Container App managed identity is the only `get-secret` principal |
| Container Registry | `dwdocforgeacr` | Stores `docforge:latest` |
| Entra tenant | DocuWare (`c901724f-...`) | See `deployment.md` §DocuWare deployment context |
| Entra app registration | `docforge-search-api` (`a94315d8-...`) | See `docs/threat-model.md` |

## Container App failure modes

### Startup probe failing / 503 on /health

**Symptom:** `/health` returns 503; container logs show "Application startup failed."
**Diagnosis:** 
- Check: `az containerapp logs show --name docforge-search-api -g docforge-test --tail 200 | grep -iE "error|exception"`
- Common causes: (a) Key Vault secret sync broken, (b) embedding-model download failed, (c) Entra `openid_config.load_config` failed.
**Fix:**
- (a) Secret sync: `az containerapp identity show --name docforge-search-api -g docforge-test` → verify principalId has `Key Vault Secrets User` on `docforge-kv`. Restart revision.
- (b) Model download: check HF_TOKEN validity. Regenerate + update Key Vault secret.
- (c) Entra unreachable: usually transient. Restart revision (`az containerapp revision restart`).

### Image pull failure

**Symptom:** Revision shows `Failed` state; logs: `failed to pull image`.
**Diagnosis:** `az containerapp revision show --name docforge-search-api -g docforge-test --revision <rev-name>` → check `properties.runningState`.
**Fix:** The Container App's managed identity needs `AcrPull` on the registry. Re-run `deploy.sh` to re-apply RBAC.

### Key Vault secret sync failure

**Symptom:** Container boots; DB connection fails with auth error.
**Diagnosis:** Container env has `secretRef: database-url` but Key Vault didn't resolve it.
**Fix:** Manually fetch: `az keyvault secret show --vault-name docforge-kv --name database-url`. If missing, recreate from `secrets.env`.

### Revision rollout stuck (two revisions active)

**Symptom:** `/search` requests return inconsistent behavior (old-revision + new-revision mix).
**Diagnosis:** `az containerapp revision list --name docforge-search-api -g docforge-test --query "[?properties.active].{name:name, trafficWeight:properties.trafficWeight}" -o table`
**Fix:** `az containerapp revision deactivate --name docforge-search-api -g docforge-test --revision <old-rev-name>`. Traffic routing is "latestRevision: true" so the new revision takes 100%.

### Entra `openid_config.load_config` failure at startup

**Symptom:** Startup log contains `Entra auth enabled ...` but first requests return 503. Eventually 401s succeed.
**Diagnosis:** The OpenID discovery fetch is retried; initial requests hit before it completes.
**Fix:** Wait 60 s and retry. If persistent, check tenant URL reachability from the container subnet.

### Entra 401 on a valid-looking token

**Symptom:** User has a fresh `az login`, token looks valid, but `/search` returns 401 "invalid_token" or "invalid claims".
**Diagnosis (decision tree):**
1. Token `ver` claim: must be `2.0`. If `1.0`, the app registration's `api.requestedAccessTokenVersion` is 1 — fix with `./deploy/azure/bootstrap-entra.sh --name docforge-search-api` (idempotent; step 7 sets v2).
2. Token `aud`: must be the client ID GUID (v2 format). If it's `api://<guid>` (v1 format), same fix as above.
3. Admin consent missing: `az rest --method GET --url "https://graph.microsoft.com/v1.0/oauth2PermissionGrants?\$filter=clientId eq '<user-tenant-sp-id>'"` — expect a row for `scope: search, resourceId: <docforge-sp-id>`.

## Database failure modes

### Connection refused / timeout

**Symptom:** Container logs: `Database error during search: password authentication failed` or connection timeouts.
**Diagnosis:** 
- Firewall: `az postgres flexible-server firewall-rule list --resource-group docforge-test --name docforge-pg -o table` — verify `AllowAzureServices` (0.0.0.0-0.0.0.0) and your admin IPs if ingesting locally.
- Auto-stop: `az postgres flexible-server show --resource-group docforge-test --name docforge-pg --query state -o tsv` — expected `Ready`.
**Fix:** Restore firewall rule; start server if stopped (`az postgres flexible-server start`).

### Point-in-time restore (verified 2026-04-22)

Verified exercise: restore the production DB to a throwaway server, confirm row counts, delete. Total time: ~10-15 min. Cost: ~$1-3 for the throwaway-server-hour.

```bash
# 1. Compute restore point (30 minutes in the past here; adjust as needed).
RESTORE_POINT=$(date -u -d "30 minutes ago" +"%Y-%m-%dT%H:%M:%SZ")

# 2. Initiate the restore.
az postgres flexible-server restore \
  --resource-group docforge-test \
  --name docforge-pg-pitr-test \
  --source-server docforge-pg \
  --restore-time "$RESTORE_POINT" \
  --location westeurope

# 3. Poll until Ready (~10-15 min).
for i in $(seq 1 18); do
  sleep 60
  state=$(az postgres flexible-server show --resource-group docforge-test --name docforge-pg-pitr-test --query state -o tsv)
  echo "t=$((i*60))s state=$state"
  [ "$state" = "Ready" ] && break
done

# 4. Connect + verify counts (expect close to source; may be slightly lower).
#    See compare block in phase-6 of the 2026-04-22-operational-readiness plan.

# 5. Delete the throwaway.
az postgres flexible-server delete \
  --resource-group docforge-test \
  --name docforge-pg-pitr-test \
  --yes
```

**Recovery window:** 7 days (set by `backupRetentionDays: 7` on `Standard_B1ms` in `main.bicep`). Data older than 7 days is not recoverable via PITR.

### `query_log` cleanup loop silent failure

**Symptom:** `query_log` row count grows unbounded past the 180-day retention.
**Diagnosis:** Tail container logs — the cleanup loop logs `query_log cleanup: DELETE <n>` hourly. Absent lines → loop failed.
**Fix:** Restart the revision (`az containerapp revision restart`). The lifespan restarts the cleanup task. If still failing, check for asyncpg exceptions in the container log.

## Ingest failure modes

### HF token expired

**Symptom:** `docforge ingest` fails at the embedding step with 401 from huggingface.co.
**Fix:** Regenerate token at https://huggingface.co/settings/tokens. Update `secrets.env` AND the `hf-token` Key Vault secret: `az keyvault secret set --vault-name docforge-kv --name hf-token --value "<new-token>"`. Restart container revision.

### Confluence rate-limited (429) or token expired

**Symptom:** `docforge ingest` logs `429 Too Many Requests` or `401` from atlassian URLs.
**Fix:** 
- 429: backoff is not implemented — wait 15 min and retry. If persistent, reduce ingest batch by filtering `sources.yml`.
- 401: regenerate at https://id.atlassian.com/manage-profile/security/api-tokens. Update `.env` + Key Vault + container restart.

### Orphan accumulation

**Symptom:** `SELECT count(*) FROM sources` shows significantly more rows than `sources.yml` lists.
**Fix:** `docforge ingest --purge-orphans` (dry-run; reports what would be deleted). Verify the list is correct, then `docforge ingest --purge-orphans --confirm` to execute.

## Auth failure modes

See `docforge/docs/threat-model.md` for the full picture. Quick diagnostic: follow the "Entra 401 on a valid-looking token" decision tree above.

## Historical / resolved items

- **"1/72 ingest failure" (from earlier Spec D draft).** No longer reproduces — a fresh ingest run on 2026-04-22 reported 72/72 succeeded, 0 failures. Leaving the entry for context.
```

Make sure to populate the PITR section with the REAL timings + counts observed in Phase 6 Tasks 14-15.

- [ ] **Step 2: Commit (knowledge-hub)**

```bash
cd /e/knowledge-hub && git add rag/docs/runbook.md && git -c commit.gpgsign=false commit -m "Add rag/docs/runbook.md (C4.1)" && git push origin master
```

---

## Phase 8 — C4.4 Load profile (after soak data accumulates)

### Task 17: Wait for sufficient `request_ms` data

**Files:** None.

- [ ] **Step 1: Wait ~7 days of real-use traffic**

The load profile cites P50/P95/P99. These numbers are most informative after several days of real colleague-driven search traffic has landed in `query_log`. Anything less risks sample-size-of-one timings skewed by synthetic smoke tests.

Periodically check:
```bash
set -a; source /e/knowledge-hub/rag/infrastructure/secrets.env; set +a
export DATABASE_URL="postgresql://dfadmin:${POSTGRES_ADMIN_PASSWORD}@docforge-pg.postgres.database.azure.com:5432/docforge?sslmode=require"

/e/docforge/.venv/Scripts/python.exe -m docforge.scripts.latency_report --since '7 days'
```

Proceed to Task 18 when the reported `n` is at least a few dozen (ideally 100+).

**No wait is strictly required** — you can commit the load profile earlier with smaller `n`, but then re-run the report and re-commit once more data accumulates.

---

### Task 18: Write `knowledge-hub/rag/docs/load-profile.md`

**Files:**
- Create: `E:/knowledge-hub/rag/docs/load-profile.md`

- [ ] **Step 1: Capture current volumes**

```bash
set -a; source /e/knowledge-hub/rag/infrastructure/secrets.env; set +a
/e/docforge/.venv/Scripts/python.exe <<'EOF'
import asyncio, asyncpg, os
async def run():
    conn = await asyncpg.connect(
        host="docforge-pg.postgres.database.azure.com", user="dfadmin",
        password=os.environ['POSTGRES_ADMIN_PASSWORD'], database="docforge",
        port=5432, ssl='require',
    )
    for label, q in [
        ("total sources",      "SELECT count(*) FROM sources"),
        ("confluence sources", "SELECT count(*) FROM sources WHERE type='confluence'"),
        ("git sources",        "SELECT count(*) FROM sources WHERE type='git_repo'"),
        ("chunks",             "SELECT count(*) FROM chunks"),
        ("queries (7d)",       "SELECT count(*) FROM query_log WHERE created_at > now() - interval '7 days'"),
        ("queries-with-ms (7d)", "SELECT count(*) FROM query_log WHERE created_at > now() - interval '7 days' AND request_ms IS NOT NULL"),
        ("distinct users (7d)", "SELECT count(DISTINCT user_oid) FROM query_log WHERE user_oid IS NOT NULL AND created_at > now() - interval '7 days'"),
        ("distinct teams (7d)", "SELECT count(DISTINCT team_name) FROM query_log WHERE created_at > now() - interval '7 days'"),
    ]:
        n = await conn.fetchval(q)
        print(f"{label}: {n}")
    await conn.close()
asyncio.run(run())
EOF
```
Record all values.

- [ ] **Step 2: Capture the latency report**

```bash
/e/docforge/.venv/Scripts/python.exe -m docforge.scripts.latency_report --since '7 days'
```
Record P50 / P95 / P99 / n.

- [ ] **Step 3: Write the load profile**

Create `knowledge-hub/rag/docs/load-profile.md` with the REAL numbers from Steps 1-2 (no placeholders):

```markdown
# docforge load profile — DocuWare CCL deployment

**Generated:** <YYYY-MM-DD>  
**Window:** last 7 days

## Index volumes

| Dimension | Value |
|---|---|
| Total sources | <N> |
|  ...of which Confluence | <N> |
|  ...of which git repo files | <N> |
| Chunks | <N> |
| Embedding dimension | 768 (EmbeddingGemma-300M) |

Query producing the above: see `knowledge-hub/rag/docs/runbook.md` §Database failure modes.

## Query volume

| Dimension | Value |
|---|---|
| `/search` calls in the last 7 days | <N> |
| ...of which have timing (post-C4.3) | <N> |
| Distinct users (by Entra oid) | <N> |
| Distinct teams | <N> |

Suppression note: the ≥3-user minimum-cell guard in `log-privacy.md` applies to any per-team breakdown published externally. The aggregate totals above are fine to share.

## Latency

Measured via `docforge/scripts/latency_report.py` over the same 7-day window:

| Percentile | ms |
|---|---|
| P50 | <X> |
| P95 | <Y> |
| P99 | <Z> |

**Post-deployment warm-up:** every new Container App revision triggers a 15-30 s embedding-model load. The first 1-2 queries after each deployment include that cost. `minReplicas: 1` eliminates scale-to-zero cold starts during normal operation. The P95/P99 numbers above therefore reflect steady-state traffic plus one-time warm-ups after each deploy in the window — not a "cold start every idle period" pattern.

## HNSW parameter rationale

pgvector defaults are used: `m=16, ef_construction=64`. At ~1,770 chunks (roughly one index worth of build work), the defaults keep index build time under 5 seconds and recall well above 95% at common query-time `ef_search` settings. See [pgvector tuning docs](https://github.com/pgvector/pgvector#index-options) for the rationale.

**Re-evaluate if:** chunk count grows past ~20,000 (2-3 orders of magnitude from today). Beyond that, `m=32, ef_construction=128` becomes worth benchmarking.

## Regeneration

All numbers above are re-generatable by anyone with admin DB access:

```
# Volumes
/e/docforge/.venv/Scripts/python.exe <<'EOF'
# (see Step 1 of load-profile authoring task for the full Python block)
EOF

# Latency
python -m docforge.scripts.latency_report --since '7 days'
```

Update this document when re-generated, or when volumes shift by >10%.
```

- [ ] **Step 4: Commit + push (knowledge-hub, direct-to-master)**

```bash
cd /e/knowledge-hub && git add rag/docs/load-profile.md && git -c commit.gpgsign=false commit -m "Add rag/docs/load-profile.md (C4.4)" && git push origin master
```

- [ ] **Step 5: Mark soak-clock start**

At this point, the 14-day Spec D soak clock begins. Record the knowledge-hub load-profile commit timestamp:

```bash
cd /e/knowledge-hub && git log -1 --format='%cI rag/docs/load-profile.md' -- rag/docs/load-profile.md
```

Soak ends 14 days after this timestamp. When it ends, Spec D artifact writing can begin.

---

## Final verification

### Task 19: End-to-end verification

- [ ] **Step 1: docforge repo is healthy**

```bash
cd /e/docforge && /e/docforge/.venv/Scripts/python.exe -m pytest tests/unit/ -q && /e/docforge/.venv/Scripts/python.exe -m ruff format --check . && /e/docforge/.venv/Scripts/python.exe -m ruff check .
```
Expected: all green.

- [ ] **Step 2: knowledge-hub master is clean**

```bash
cd /e/knowledge-hub && git status
```
Expected: `nothing to commit, working tree clean`, on master.

- [ ] **Step 3: Live API still works authenticated**

```bash
/e/docforge/.venv/Scripts/python.exe <<'EOF'
import asyncio
from azure.identity.aio import DefaultAzureCredential
import httpx
async def run():
    cred = DefaultAzureCredential()
    token = await cred.get_token("api://a94315d8-b023-4280-9d8d-cfa080fce4d1/.default")
    await cred.close()
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.post(
            "https://docforge-search-api.ashyhill-c79f3b95.westeurope.azurecontainerapps.io/search",
            headers={"Authorization": f"Bearer {token.token}"},
            json={"query": "final verification", "user_name": "tobias.ens", "team_name": "ccl", "area_name": "cloud", "limit": 1},
        )
    print("HTTP:", r.status_code, "count:", r.json().get("count"))
asyncio.run(run())
EOF
```
Expected: HTTP 200, count ≥ 0.

- [ ] **Step 4: Eval harness — baseline behavior**

Run:
```bash
cd /e/docforge && /e/docforge/.venv/Scripts/python.exe -m docforge.scripts.eval_search \
  --api-url https://docforge-search-api.ashyhill-c79f3b95.westeurope.azurecontainerapps.io \
  --ground-truth /e/knowledge-hub/rag/eval/ground_truth.yml \
  --user tobias.ens --team ccl --area cloud \
  --audience api://a94315d8-b023-4280-9d8d-cfa080fce4d1 \
  --k 5 2>&1 | tail -6
```

If you have run `--purge-orphans --confirm` since the C2 baseline, numbers may differ. Inspect whether the delta reflects orphan removal (by spot-checking returned titles) vs. a retrieval regression. For the CCL ground-truth, all 25 expected titles are substrings of current `sources.yml` titles, so the baseline (recall@1 40%, recall@5 76%, MRR 0.533) should still reproduce.

---

## Success criteria recap (from spec)

- [x] `docforge ingest --purge-orphans` without `--confirm` prints would-be-deleted and exits without mutating. (Tasks 2-4)
- [x] `docforge ingest --purge-orphans --confirm` deletes orphans; subsequent `SELECT count(*) FROM sources` matches current sources.yml. (Tasks 2-4; Phase 5 verification)
- [x] `query_log.request_ms` exists; populated non-NULL on post-migration `/search`; pre-migration rows have NULL. (Tasks 6, 7, 12, 13)
- [x] `python -m docforge.scripts.latency_report` prints P50/P95/P99. (Task 9; Task 13 live run; Task 18 in load profile)
- [x] `knowledge-hub/rag/docs/runbook.md` committed; all failure-mode sub-sections have concrete text; `Last verified:` stamp present. (Task 16)
- [x] `knowledge-hub/rag/docs/load-profile.md` committed with real numbers from C4.3. (Task 18)
- [x] `docforge/CONTRIBUTING.md` committed. (Task 5)
- [x] PITR dry-run: throwaway created, restore succeeded, commands + timing in runbook, throwaway deleted. (Tasks 14-16)
- [x] All new unit tests pass; coverage ≥60%. (Task 10, Task 19)
- [x] CI green on both repos. (Task 10)
- [x] Eval rerun: if metrics change, confirmed due to orphan removal not regression. (Task 19 Step 4)
