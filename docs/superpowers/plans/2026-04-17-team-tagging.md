# Team Tagging + MCP user/team/area Parameters — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add tag-based scoping to docforge. Sources gain a `TEXT[]` tags column; MCP tool, `/search` API, and CLI `search` command accept required `user_name`+`team_name` and optional `area_name`; ranking applies a small multiplicative boost when source tags overlap the caller's scope. Query metadata logged to a new `query_log` table. Knowledge-hub/rag gains a canonical `teams.yml`, tagged sources, updated MCP client, and updated setup docs.

**Architecture:** Schema-first change (migrations add column + log table). Pure Python ranking helper mirrors the SQL formula for unit-testability. MCP tool, API, and CLI all converge on the same `(user_name, team_name, area_name)` identity triple. Failures at config boundaries surface as errors (422 / typer exit / pydantic validation), not silent fallbacks. Knowledge-hub/rag is updated in lockstep — existing MCP client configs without the new env vars will fail loudly (one-time migration for ~8-10 users).

**Tech Stack:** PostgreSQL + pgvector, asyncpg, pydantic v2, Typer, FastMCP 3.x, FastAPI, pytest + testcontainers.

---

## File Structure

**docforge repo — create:**
- `docforge/docforge/sql/migrations/003_add_source_tags.sql`
- `docforge/docforge/sql/migrations/004_add_query_log.sql`
- `docforge/docforge/ranking.py` — pure `compute_boosted_score` function
- `docforge/docforge/query_log.py` — async `log_query` helper
- `docforge/tests/unit/test_ranking.py`
- `docforge/tests/unit/test_query_log.py`
- `docforge/tests/integration/test_ranking_integration.py`

**docforge repo — modify:**
- `docforge/docforge/sources.py` — add `tags` to both source configs
- `docforge/docforge/ingest.py` — propagate `tags` into `INSERT INTO sources`
- `docforge/docforge/config.py` — add weights + default identity settings
- `docforge/docforge/mcp_server.py` — new tool signature, new SQL, response format, logging
- `docforge/docforge/api.py` — new `SearchRequest` fields, new SQL, logging
- `docforge/docforge/cli.py` — new flags, Settings defaults
- `docforge/tests/unit/test_api.py`
- `docforge/tests/unit/test_mcp_server.py`
- `docforge/tests/unit/test_cli.py`
- `docforge/tests/unit/test_ingest.py`
- `docforge/tests/integration/test_db_schema.py`
- `docforge/tests/integration/test_ingest_git_integration.py`

**knowledge-hub/rag — create:**
- `knowledge-hub/rag/teams.yml`

**knowledge-hub/rag — modify:**
- `knowledge-hub/rag/sources.yml` — tag all 72 entries
- `knowledge-hub/rag/generate_sources.py` — emit `tags: [ccl]` for auto-discovered CCL git repos
- `knowledge-hub/rag/mcp_client.py` — pass new env vars; fail hard if missing
- `knowledge-hub/rag/docs/team-setup-azure.md` — add identity-setup step

---

## Task 1: Add migration 003 — `sources.tags` column

**Files:**
- Create: `docforge/docforge/sql/migrations/003_add_source_tags.sql`

- [ ] **Step 1: Create the migration file**

```sql
ALTER TABLE sources
    ADD COLUMN IF NOT EXISTS tags TEXT[] NOT NULL DEFAULT '{}';

CREATE INDEX IF NOT EXISTS sources_tags_idx ON sources USING gin (tags);
```

- [ ] **Step 2: Verify migration applies cleanly against a fresh pgvector container**

Run:
```bash
cd /e/docforge
source .venv/Scripts/activate
pytest tests/integration/test_db_schema.py -v -m integration --no-cov
```
Expected: existing schema test passes (migration runs as part of `init_db`).

- [ ] **Step 3: Commit**

```bash
cd /e/docforge
git add docforge/sql/migrations/003_add_source_tags.sql
git commit -m "migrate: add tags column to sources"
```

---

## Task 2: Add migration 004 — `query_log` table

**Files:**
- Create: `docforge/docforge/sql/migrations/004_add_query_log.sql`

- [ ] **Step 1: Create the migration file**

```sql
CREATE TABLE IF NOT EXISTS query_log (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_name TEXT NOT NULL,
    team_name TEXT NOT NULL,
    area_name TEXT,
    query TEXT NOT NULL,
    result_count INT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS query_log_created_at_idx ON query_log (created_at);
```

- [ ] **Step 2: Verify against container**

```bash
cd /e/docforge
source .venv/Scripts/activate
pytest tests/integration/test_db_schema.py -v -m integration --no-cov
```
Expected: passes.

- [ ] **Step 3: Commit**

```bash
cd /e/docforge
git add docforge/sql/migrations/004_add_query_log.sql
git commit -m "migrate: add query_log table"
```

---

## Task 3: Extend integration schema test to verify new structures

**Files:**
- Modify: `docforge/tests/integration/test_db_schema.py`

- [ ] **Step 1: Add assertions for tags column, query_log table, and GIN index**

Append the following test after the existing `test_init_db_creates_schema_and_pgvector`:

```python
@pytest.mark.asyncio
async def test_sources_has_tags_column(pg_url):
    conn = await asyncpg.connect(pg_url)
    try:
        col = await conn.fetchrow(
            """
            SELECT column_name, data_type, is_nullable, column_default
            FROM information_schema.columns
            WHERE table_name = 'sources' AND column_name = 'tags'
            """
        )
        assert col is not None
        assert col["data_type"] == "ARRAY"
        assert col["is_nullable"] == "NO"
        assert "{}" in (col["column_default"] or "")

        idx = await conn.fetchval(
            """
            SELECT indexname FROM pg_indexes
            WHERE tablename = 'sources' AND indexname = 'sources_tags_idx'
            """
        )
        assert idx == "sources_tags_idx"
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_query_log_table_exists(pg_url):
    conn = await asyncpg.connect(pg_url)
    try:
        cols = await conn.fetch(
            """
            SELECT column_name FROM information_schema.columns
            WHERE table_name = 'query_log'
            ORDER BY ordinal_position
            """
        )
        names = [row["column_name"] for row in cols]
        assert names == [
            "id", "user_name", "team_name", "area_name",
            "query", "result_count", "created_at",
        ]
    finally:
        await conn.close()
```

- [ ] **Step 2: Run the new tests**

```bash
cd /e/docforge
source .venv/Scripts/activate
pytest tests/integration/test_db_schema.py -v -m integration --no-cov
```
Expected: 3 tests pass.

- [ ] **Step 3: Commit**

```bash
cd /e/docforge
git add tests/integration/test_db_schema.py
git commit -m "test(integration): verify new tags column and query_log table"
```

---

## Task 4: Add `ranking.py` — pure boost calculation

**Files:**
- Create: `docforge/docforge/ranking.py`
- Create: `docforge/tests/unit/test_ranking.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_ranking.py`:

```python
"""Tests for docforge.ranking.compute_boosted_score."""

from __future__ import annotations

import pytest

from docforge.ranking import compute_boosted_score


class TestComputeBoostedScore:
    def test_no_overlap_no_org_is_identity(self):
        assert compute_boosted_score(
            similarity=0.8, source_tags=["other"], user_tags=["ccl"],
            tag_weight=0.1, org_weight=0.05,
        ) == pytest.approx(0.8)

    def test_one_overlap_no_org(self):
        assert compute_boosted_score(
            similarity=0.8, source_tags=["ccl"], user_tags=["ccl"],
            tag_weight=0.1, org_weight=0.05,
        ) == pytest.approx(0.8 * 1.1)

    def test_two_overlap_no_org(self):
        assert compute_boosted_score(
            similarity=0.8, source_tags=["ccl", "cloud"], user_tags=["ccl", "cloud"],
            tag_weight=0.1, org_weight=0.05,
        ) == pytest.approx(0.8 * 1.2)

    def test_zero_overlap_has_org(self):
        assert compute_boosted_score(
            similarity=0.8, source_tags=["org"], user_tags=["ccl"],
            tag_weight=0.1, org_weight=0.05,
        ) == pytest.approx(0.8 * 1.05)

    def test_one_overlap_plus_org(self):
        assert compute_boosted_score(
            similarity=0.8, source_tags=["ccl", "org"], user_tags=["ccl"],
            tag_weight=0.1, org_weight=0.05,
        ) == pytest.approx(0.8 * 1.15)

    def test_configurable_weights_honored(self):
        assert compute_boosted_score(
            similarity=1.0, source_tags=["ccl"], user_tags=["ccl"],
            tag_weight=0.5, org_weight=0.0,
        ) == pytest.approx(1.5)

    def test_duplicate_tags_counted_once(self):
        # Set intersection, not list count — duplicates in either list don't double-count
        assert compute_boosted_score(
            similarity=1.0, source_tags=["ccl", "ccl"], user_tags=["ccl"],
            tag_weight=0.1, org_weight=0.0,
        ) == pytest.approx(1.1)

    def test_empty_tags_is_identity(self):
        assert compute_boosted_score(
            similarity=0.9, source_tags=[], user_tags=[],
            tag_weight=0.1, org_weight=0.05,
        ) == pytest.approx(0.9)
```

- [ ] **Step 2: Run to verify failure**

```bash
cd /e/docforge
source .venv/Scripts/activate
pytest tests/unit/test_ranking.py -v --no-cov
```
Expected: FAIL with `ModuleNotFoundError: No module named 'docforge.ranking'`.

- [ ] **Step 3: Create `docforge/ranking.py`**

```python
"""Ranking helpers — pure Python mirror of the boost formula in search SQL."""

from __future__ import annotations


def compute_boosted_score(
    similarity: float,
    source_tags: list[str],
    user_tags: list[str],
    tag_weight: float,
    org_weight: float,
) -> float:
    """Apply tag-overlap + org-tag boost to a similarity score.

    Formula mirrors the SQL used in mcp_server.py and api.py search queries.
    Kept in a pure function so the ranking math is unit-testable without SQL.
    """
    overlap = len(set(source_tags) & set(user_tags))
    has_org = "org" in source_tags
    return similarity * (1 + tag_weight * overlap + org_weight * (1 if has_org else 0))
```

- [ ] **Step 4: Run to verify pass**

```bash
cd /e/docforge
source .venv/Scripts/activate
pytest tests/unit/test_ranking.py -v --no-cov
```
Expected: 8 tests PASS.

- [ ] **Step 5: Commit**

```bash
cd /e/docforge
git add docforge/ranking.py tests/unit/test_ranking.py
git commit -m "feat: add ranking.compute_boosted_score with full test coverage"
```

---

## Task 5: Add `query_log.py` — async log helper

**Files:**
- Create: `docforge/docforge/query_log.py`
- Create: `docforge/tests/unit/test_query_log.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_query_log.py`:

```python
"""Tests for docforge.query_log.log_query."""

from __future__ import annotations

import pytest

from docforge.query_log import log_query


class _ConnCapture:
    def __init__(self, raise_on_execute: bool = False):
        self.raise_on_execute = raise_on_execute
        self.executed = []

    async def execute(self, query, *args):
        if self.raise_on_execute:
            raise RuntimeError("boom")
        self.executed.append((query, args))


class _AcquireCtx:
    def __init__(self, conn):
        self._conn = conn

    async def __aenter__(self):
        return self._conn

    async def __aexit__(self, *a):
        return None


class _FakePool:
    def __init__(self, conn):
        self._conn = conn

    def acquire(self):
        return _AcquireCtx(self._conn)


@pytest.mark.asyncio
async def test_log_query_inserts_row():
    conn = _ConnCapture()
    pool = _FakePool(conn)
    await log_query(
        pool=pool,
        user_name="tobias.ens",
        team_name="ccl",
        area_name="cloud",
        query="retry policy",
        result_count=3,
    )
    assert len(conn.executed) == 1
    query, args = conn.executed[0]
    assert "INSERT INTO query_log" in query
    assert args == ("tobias.ens", "ccl", "cloud", "retry policy", 3)


@pytest.mark.asyncio
async def test_log_query_accepts_null_area():
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
    assert args[2] is None


@pytest.mark.asyncio
async def test_log_query_swallows_failures():
    conn = _ConnCapture(raise_on_execute=True)
    pool = _FakePool(conn)
    # Must not raise
    await log_query(
        pool=pool, user_name="a", team_name="b", area_name=None,
        query="q", result_count=0,
    )
```

- [ ] **Step 2: Run to verify failure**

```bash
cd /e/docforge
source .venv/Scripts/activate
pytest tests/unit/test_query_log.py -v --no-cov
```
Expected: FAIL with `ModuleNotFoundError: No module named 'docforge.query_log'`.

- [ ] **Step 3: Create `docforge/query_log.py`**

```python
"""Async helper for inserting rows into query_log.

Failures are logged and swallowed — query logging must never break a search.
"""

from __future__ import annotations

import logging

import asyncpg

logger = logging.getLogger(__name__)


async def log_query(
    pool: asyncpg.Pool,
    user_name: str,
    team_name: str,
    area_name: str | None,
    query: str,
    result_count: int,
) -> None:
    """Record a search request to the query_log table. Never raises."""
    try:
        async with pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO query_log
                    (user_name, team_name, area_name, query, result_count)
                VALUES ($1, $2, $3, $4, $5)
                """,
                user_name, team_name, area_name, query, result_count,
            )
    except Exception as e:
        logger.warning("query_log insert failed: %s", e)
```

- [ ] **Step 4: Run to verify pass**

```bash
cd /e/docforge
source .venv/Scripts/activate
pytest tests/unit/test_query_log.py -v --no-cov
```
Expected: 3 tests PASS.

- [ ] **Step 5: Commit**

```bash
cd /e/docforge
git add docforge/query_log.py tests/unit/test_query_log.py
git commit -m "feat: add query_log.log_query async helper"
```

---

## Task 6: Add `tags` to source config models

**Files:**
- Modify: `docforge/docforge/sources.py`
- Modify: `docforge/tests/unit/test_sources.py`

- [ ] **Step 1: Update sources.py**

Replace the two model classes in `docforge/sources.py`:

```python
class ConfluenceSourceConfig(BaseModel):
    type: Literal["confluence_page"]
    page_id: str
    space_key: str
    title: str
    tags: list[str] = []


class GitRepoSourceConfig(BaseModel):
    type: Literal["git_repo"]
    repo_path: str
    include_patterns: list[str] = ["README.md", "CLAUDE.md", "docs/**/*.md"]
    title: str
    tags: list[str] = []
```

- [ ] **Step 2: Add tests for the `tags` field**

Append to `tests/unit/test_sources.py`:

```python
class TestTags:
    def test_tags_default_to_empty(self, tmp_path):
        yml = tmp_path / "sources.yml"
        yml.write_text(
            "sources:\n"
            "  - type: confluence_page\n"
            '    page_id: "1"\n'
            "    space_key: HEL\n"
            '    title: "Page"\n'
        )
        sources = load_sources(yml)
        assert sources[0].tags == []

    def test_tags_parsed_from_yaml(self, tmp_path):
        yml = tmp_path / "sources.yml"
        yml.write_text(
            "sources:\n"
            "  - type: confluence_page\n"
            '    page_id: "1"\n'
            "    space_key: HEL\n"
            '    title: "Page"\n'
            "    tags: [ccl, cloud]\n"
            "  - type: git_repo\n"
            '    repo_path: "E:/repo"\n'
            "    include_patterns: [README.md]\n"
            '    title: "R"\n'
            "    tags: [org]\n"
        )
        sources = load_sources(yml)
        assert sources[0].tags == ["ccl", "cloud"]
        assert sources[1].tags == ["org"]
```

- [ ] **Step 3: Run tests**

```bash
cd /e/docforge
source .venv/Scripts/activate
pytest tests/unit/test_sources.py -v --no-cov
```
Expected: existing 3 tests + 2 new tests all pass.

- [ ] **Step 4: Commit**

```bash
cd /e/docforge
git add docforge/sources.py tests/unit/test_sources.py
git commit -m "feat: add tags field to source config models"
```

---

## Task 7: Propagate tags through ingest

**Files:**
- Modify: `docforge/docforge/ingest.py`
- Modify: `docforge/tests/unit/test_ingest.py`
- Modify: `docforge/tests/integration/test_ingest_git_integration.py`

- [ ] **Step 1: Update ingest.py to pass tags through to SQL**

In `docforge/ingest.py::_ingest_confluence_source`, modify the `INSERT INTO sources` query and arguments so `tags` is included. Replace the INSERT block:

```python
            source_id = await conn.fetchval(
                """
                INSERT INTO sources (type, url, title, confluence_page_id,
                                     confluence_space_key, last_crawled_at,
                                     content_hash, status, tags)
                VALUES ($1, $2, $3, $4, $5, $6, $7, 'active', $8)
                ON CONFLICT (confluence_page_id)
                DO UPDATE SET
                    title = EXCLUDED.title,
                    url = EXCLUDED.url,
                    last_crawled_at = EXCLUDED.last_crawled_at,
                    content_hash = EXCLUDED.content_hash,
                    status = 'active',
                    tags = EXCLUDED.tags
                RETURNING id
                """,
                source.type,
                page.url,
                page.title,
                source.page_id,
                source.space_key,
                datetime.now(timezone.utc),
                page.content_hash,
                source.tags,
            )
```

In `_ingest_git_source`, same pattern. Replace the INSERT block:

```python
                source_id = await conn.fetchval(
                    """
                    INSERT INTO sources (type, url, title, source_identifier,
                                         last_crawled_at, content_hash, status, tags)
                    VALUES ($1, $2, $3, $4, $5, $6, 'active', $7)
                    ON CONFLICT (source_identifier)
                        WHERE source_identifier IS NOT NULL
                    DO UPDATE SET
                        title = EXCLUDED.title,
                        last_crawled_at = EXCLUDED.last_crawled_at,
                        content_hash = EXCLUDED.content_hash,
                        status = 'active',
                        tags = EXCLUDED.tags
                    RETURNING id
                    """,
                    "git_repo",
                    url,
                    f"{source.title}/{file.title}",
                    identifier,
                    datetime.now(timezone.utc),
                    file.content_hash,
                    source.tags,
                )
```

- [ ] **Step 2: Extend `tests/unit/test_ingest.py::test_ingest_git_source_inserts_chunks` to assert tags**

Replace the test `test_ingest_git_source_inserts_chunks` with:

```python
@pytest.mark.asyncio
async def test_ingest_git_source_inserts_chunks(
    tmp_path, monkeypatch, fake_embedder
):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "README.md").write_text("# Title\n\nContent one.\n\n## Sub\n\nContent two.")

    sources_file = tmp_path / "sources.yml"
    sources_file.write_text(
        "sources:\n"
        "  - type: git_repo\n"
        f'    repo_path: "{repo.as_posix()}"\n'
        "    include_patterns: [\"README.md\"]\n"
        "    title: \"RepoX\"\n"
        "    tags: [ccl]\n"
    )

    conn = _Conn(existing_hash=None)

    async def fake_get_pool(url):
        return _FakePool(conn)

    monkeypatch.setattr(ingest_mod, "get_pool", fake_get_pool)

    from docforge.config import Settings

    settings = Settings(sources_file=str(sources_file))

    await ingest_all(settings)

    assert len(conn.inserted_sources) == 1
    assert len(conn.inserted_chunks) >= 1
    # Tags are the last positional arg to fetchval in the INSERT call
    assert conn.inserted_sources[0][-1] == ["ccl"]
```

- [ ] **Step 3: Run unit tests**

```bash
cd /e/docforge
source .venv/Scripts/activate
pytest tests/unit/test_ingest.py -v --no-cov
```
Expected: all pass.

- [ ] **Step 4: Extend `tests/integration/test_ingest_git_integration.py` to verify tags land on the row**

Modify the `sources.yml` content within `test_end_to_end_ingest_and_search` to include tags. Replace the `sources_file.write_text(...)` block with:

```python
    sources_file.write_text(
        "sources:\n"
        "  - type: git_repo\n"
        f'    repo_path: "{repo.as_posix()}"\n'
        "    include_patterns: [\"README.md\", \"CLAUDE.md\"]\n"
        "    title: \"TestRepo\"\n"
        "    tags: [ccl, cloud]\n"
    )
```

Add the following assertion block after the existing `assert chunk_count >= 2` but before the relevance query:

```python
        tags_rows = await conn.fetch("SELECT tags FROM sources")
        for row in tags_rows:
            assert row["tags"] == ["ccl", "cloud"]
```

- [ ] **Step 5: Run integration tests**

```bash
cd /e/docforge
source .venv/Scripts/activate
pytest tests/integration/test_ingest_git_integration.py -v -m integration --no-cov
```
Expected: passes.

- [ ] **Step 6: Commit**

```bash
cd /e/docforge
git add docforge/ingest.py tests/unit/test_ingest.py tests/integration/test_ingest_git_integration.py
git commit -m "feat(ingest): propagate tags into sources INSERT"
```

---

## Task 8: Add ranking weights + default-identity settings

**Files:**
- Modify: `docforge/docforge/config.py`
- Modify: `docforge/tests/unit/test_config.py`

- [ ] **Step 1: Add fields to Settings**

In `docforge/config.py`, add inside the `Settings` class body (after existing fields):

```python
    # Ranking weights (see docforge.ranking.compute_boosted_score)
    tag_match_weight: float = 0.1
    org_tag_weight: float = 0.05

    # Default identity (used as CLI flag defaults when set via env/yml)
    default_user_name: str = ""
    default_team_name: str = ""
    default_area_name: str = ""
```

- [ ] **Step 2: Add tests**

Append to `tests/unit/test_config.py::TestSettingsDefaults::test_defaults_when_no_yml_or_env` the following assertions:

```python
        assert s.tag_match_weight == pytest.approx(0.1)
        assert s.org_tag_weight == pytest.approx(0.05)
        assert s.default_user_name == ""
        assert s.default_team_name == ""
        assert s.default_area_name == ""
```

Also ensure `pytest` is imported at the top of the file if not already (it is).

- [ ] **Step 3: Run**

```bash
cd /e/docforge
source .venv/Scripts/activate
pytest tests/unit/test_config.py -v --no-cov
```
Expected: 8 tests pass.

- [ ] **Step 4: Commit**

```bash
cd /e/docforge
git add docforge/config.py tests/unit/test_config.py
git commit -m "feat(config): add ranking weights and default identity settings"
```

---

## Task 9: Update API — SearchRequest fields, SQL, logging

**Files:**
- Modify: `docforge/docforge/api.py`
- Modify: `docforge/tests/unit/test_api.py`

- [ ] **Step 1: Update `docforge/api.py`**

Replace `SearchRequest` and `SearchResult`:

```python
class SearchRequest(BaseModel):
    query: str
    user_name: str
    team_name: str
    area_name: str | None = None
    limit: int = 5


class SearchResult(BaseModel):
    text: str
    section_title: str | None
    source_title: str
    source_url: str
    source_tags: list[str]
    similarity: float
```

Replace the `search` endpoint body (the entire `@app.post("/search", ...)` function). New body:

```python
@app.post("/search", response_model=SearchResponse)
async def search(req: SearchRequest) -> SearchResponse:
    """Search indexed documentation by semantic similarity."""
    if not _embedder:
        raise HTTPException(status_code=503, detail="Embedding model not loaded yet")

    try:
        query_vector = _embedder.embed_query(req.query)
    except Exception as e:
        logger.error("Embedding failed: %s", e)
        raise HTTPException(status_code=500, detail="Failed to embed query")

    settings = _get_settings()
    user_tags = [req.team_name] + ([req.area_name] if req.area_name else [])

    try:
        pool = await get_pool(settings.database_url)
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
    await log_query(
        pool, req.user_name, req.team_name, req.area_name, req.query, len(rows)
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

- [ ] **Step 2: Update `tests/unit/test_api.py`**

Four tests need changes. Replace the full file contents with:

```python
"""Tests for docforge.api FastAPI endpoints."""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

from docforge import api as api_module
from docforge.api import app
from tests.conftest import FakePool


class _CapturingConn:
    """Returns rows for SELECT; captures query_log INSERTs via execute."""

    def __init__(self, rows, executes):
        self._rows = rows
        self._executes = executes

    async def fetch(self, query, *args):
        return self._rows

    async def execute(self, query, *args):
        self._executes.append((query, args))


class _CapturingCtx:
    def __init__(self, conn):
        self._conn = conn

    async def __aenter__(self):
        return self._conn

    async def __aexit__(self, *a):
        return None


class _CapturingPool:
    def __init__(self, rows):
        self.rows = rows
        self.executes = []

    def acquire(self):
        return _CapturingCtx(_CapturingConn(self.rows, self.executes))


def _client():
    transport = ASGITransport(app=app)
    return AsyncClient(transport=transport, base_url="http://test")


def _settings_stub():
    return SimpleNamespace(
        database_url="postgresql://fake",
        tag_match_weight=0.1,
        org_tag_weight=0.05,
    )


class TestHealthEndpoint:
    @pytest.mark.asyncio
    async def test_health_returns_ok(self):
        async with _client() as client:
            resp = await client.get("/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"


class TestSearchEndpoint:
    @pytest.mark.asyncio
    async def test_rejects_missing_required_identity_fields(self):
        async with _client() as client:
            resp = await client.post("/search", json={"query": "q", "limit": 1})
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_returns_503_when_model_not_loaded(self):
        original = api_module._embedder
        api_module._embedder = None
        try:
            async with _client() as client:
                resp = await client.post(
                    "/search",
                    json={"query": "q", "user_name": "u", "team_name": "t", "limit": 1},
                )
            assert resp.status_code == 503
            assert "not loaded" in resp.json()["detail"]
        finally:
            api_module._embedder = original

    @pytest.mark.asyncio
    async def test_returns_results_on_success(self, monkeypatch):
        rows = [
            {
                "text": "Platform owns orgs.",
                "section_title": "Platform",
                "source_title": "Doc A",
                "source_url": "https://wiki/a",
                "source_tags": ["ccl", "cloud"],
                "similarity": 0.95,
            }
        ]

        fake_embedder = MagicMock()
        fake_embedder.embed_query.return_value = [0.0] * 768
        fake_embedder.model_name = "fake"
        api_module._embedder = fake_embedder

        pool = _CapturingPool(rows)

        async def fake_get_pool(url):
            return pool

        monkeypatch.setattr(api_module, "get_pool", fake_get_pool)
        monkeypatch.setattr(api_module, "_get_settings", _settings_stub)

        try:
            async with _client() as client:
                resp = await client.post(
                    "/search",
                    json={
                        "query": "q",
                        "user_name": "tobias.ens",
                        "team_name": "ccl",
                        "area_name": "cloud",
                        "limit": 5,
                    },
                )
        finally:
            api_module._embedder = None

        assert resp.status_code == 200
        body = resp.json()
        assert body["count"] == 1
        assert body["results"][0]["text"] == "Platform owns orgs."
        assert body["results"][0]["source_tags"] == ["ccl", "cloud"]
        # query_log insert happened
        assert any(
            "INSERT INTO query_log" in q for q, _ in pool.executes
        )

    @pytest.mark.asyncio
    async def test_returns_503_on_db_error(self, monkeypatch):
        fake_embedder = MagicMock()
        fake_embedder.embed_query.return_value = [0.0] * 768
        api_module._embedder = fake_embedder

        async def fake_get_pool(url):
            raise OSError("db down")

        monkeypatch.setattr(api_module, "get_pool", fake_get_pool)
        monkeypatch.setattr(api_module, "_get_settings", _settings_stub)

        try:
            async with _client() as client:
                resp = await client.post(
                    "/search",
                    json={
                        "query": "q", "user_name": "u", "team_name": "t", "limit": 1,
                    },
                )
        finally:
            api_module._embedder = None

        assert resp.status_code == 503
        assert "Database unavailable" in resp.json()["detail"]

    @pytest.mark.asyncio
    async def test_returns_500_on_embed_error(self, monkeypatch):
        fake_embedder = MagicMock()
        fake_embedder.embed_query.side_effect = RuntimeError("embed broken")
        api_module._embedder = fake_embedder

        try:
            async with _client() as client:
                resp = await client.post(
                    "/search",
                    json={
                        "query": "q", "user_name": "u", "team_name": "t", "limit": 1,
                    },
                )
        finally:
            api_module._embedder = None

        assert resp.status_code == 500


class TestSourcesEndpoint:
    @pytest.mark.asyncio
    async def test_lists_sources(self, monkeypatch):
        rows = [
            {
                "title": "Doc A",
                "url": "https://wiki/a",
                "status": "active",
                "last_crawled_at": datetime(2026, 4, 17, 9, 0, tzinfo=timezone.utc),
                "chunk_count": 4,
            }
        ]
        fake_pool = FakePool(rows)

        async def fake_get_pool(url):
            return fake_pool

        monkeypatch.setattr(api_module, "get_pool", fake_get_pool)
        monkeypatch.setattr(api_module, "_get_settings", _settings_stub)

        async with _client() as client:
            resp = await client.get("/sources")

        assert resp.status_code == 200
        body = resp.json()
        assert body["count"] == 1
        assert body["sources"][0]["title"] == "Doc A"

    @pytest.mark.asyncio
    async def test_returns_503_on_db_error(self, monkeypatch):
        async def fake_get_pool(url):
            raise OSError("boom")

        monkeypatch.setattr(api_module, "get_pool", fake_get_pool)
        monkeypatch.setattr(api_module, "_get_settings", _settings_stub)

        async with _client() as client:
            resp = await client.get("/sources")

        assert resp.status_code == 503
```

- [ ] **Step 3: Run API tests**

```bash
cd /e/docforge
source .venv/Scripts/activate
pytest tests/unit/test_api.py -v --no-cov
```
Expected: all pass.

- [ ] **Step 4: Commit**

```bash
cd /e/docforge
git add docforge/api.py tests/unit/test_api.py
git commit -m "feat(api): add user/team/area params, tag-aware SQL, query logging"
```

---

## Task 10: Update MCP server — tool signature, SQL, response, logging

**Files:**
- Modify: `docforge/docforge/mcp_server.py`
- Modify: `docforge/tests/unit/test_mcp_server.py`

- [ ] **Step 1: Update `docforge/mcp_server.py::search_documentation`**

Replace the entire `search_documentation` function:

```python
@mcp.tool()
async def search_documentation(
    query: str,
    user_name: str,
    team_name: str,
    area_name: str | None = None,
    limit: int = 5,
) -> str:
    """Search across indexed documentation from Confluence pages and git repos.

    Returns relevant documentation chunks with source attribution. Use this to find
    information about team ownership, coding guidelines, architecture decisions,
    and cross-team interfaces.

    Args:
        query: Natural language search query.
        user_name: Your name (e.g., "tobias.ens"). Used for usage telemetry.
        team_name: Your team tag (e.g., "ccl"). Boosts team-tagged docs.
        area_name: Your area tag (e.g., "cloud"). Optional; boosts area-tagged docs.
        limit: Maximum number of results to return (default 5).
    """
    settings = _get_settings()
    embedder = _get_embedder()

    query_vector = embedder.embed_query(query)
    user_tags = [team_name] + ([area_name] if area_name else [])

    pool = await get_pool(settings.database_url)
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
            limit,
        )

    from docforge.query_log import log_query
    await log_query(pool, user_name, team_name, area_name, query, len(rows))

    if not rows:
        return (
            "No documentation found matching your query. "
            "The index may be empty -- run `python -m docforge ingest` to populate it."
        )

    parts: list[str] = []
    for i, row in enumerate(rows, 1):
        similarity = row["similarity"]
        source = row["source_title"]
        url = row["source_url"]
        section = row["section_title"]
        text = row["text"]
        tags = list(row["source_tags"] or [])

        header = f"**Result {i}** (relevance: {similarity:.2f}) — {source}"
        if section:
            header += f" > {section}"
        header += f"\nSource: {url}"
        if tags:
            header += f"\nTags: {', '.join(tags)}"

        parts.append(f"{header}\n\n{text}")

    return "\n\n---\n\n".join(parts)
```

- [ ] **Step 2: Update `tests/unit/test_mcp_server.py`**

Replace the fixture and tests. Full new file content:

```python
"""Tests for docforge.mcp_server — search_documentation and list_sources."""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from tests.conftest import FakePool


class _CapturingConn:
    def __init__(self, rows, executes):
        self._rows = rows
        self._executes = executes

    async def fetch(self, query, *args):
        return self._rows

    async def execute(self, query, *args):
        self._executes.append((query, args))


class _CapturingCtx:
    def __init__(self, conn):
        self._conn = conn

    async def __aenter__(self):
        return self._conn

    async def __aexit__(self, *a):
        return None


class _CapturingPool:
    def __init__(self, rows):
        self.rows = rows
        self.executes = []

    def acquire(self):
        return _CapturingCtx(_CapturingConn(self.rows, self.executes))


@pytest.fixture
def patch_mcp_deps(monkeypatch):
    def _install(rows):
        from docforge import mcp_server as mod

        pool = _CapturingPool(rows)

        async def fake_get_pool(url):
            return pool

        fake_embedder = MagicMock()
        fake_embedder.embed_query.return_value = [0.0] * 768

        monkeypatch.setattr(mod, "get_pool", fake_get_pool)
        monkeypatch.setattr(mod, "_get_embedder", lambda: fake_embedder)
        monkeypatch.setattr(
            mod, "_get_settings",
            lambda: SimpleNamespace(
                database_url="postgresql://fake",
                tag_match_weight=0.1,
                org_tag_weight=0.05,
            ),
        )
        return pool, fake_embedder

    return _install


@pytest.mark.asyncio
async def test_search_documentation_formats_results(patch_mcp_deps):
    rows = [
        {
            "text": "Platform team owns orgs.",
            "section_title": "Platform",
            "source_title": "Team Responsibilities",
            "source_url": "https://wiki/page/1",
            "source_tags": ["ccl", "cloud"],
            "similarity": 0.92,
        },
    ]
    pool, fake_embedder = patch_mcp_deps(rows)

    from docforge.mcp_server import search_documentation

    result = await search_documentation(
        "who owns orgs", user_name="tobias.ens", team_name="ccl", area_name="cloud", limit=5,
    )

    assert "Platform team owns orgs." in result
    assert "0.92" in result
    assert "Tags: ccl, cloud" in result
    fake_embedder.embed_query.assert_called_once_with("who owns orgs")
    # query_log insert fired
    assert any("INSERT INTO query_log" in q for q, _ in pool.executes)


@pytest.mark.asyncio
async def test_search_documentation_no_tags_no_tag_line(patch_mcp_deps):
    rows = [
        {
            "text": "some text",
            "section_title": None,
            "source_title": "Doc",
            "source_url": "https://x",
            "source_tags": [],
            "similarity": 0.7,
        },
    ]
    patch_mcp_deps(rows)

    from docforge.mcp_server import search_documentation

    result = await search_documentation(
        "q", user_name="u", team_name="t",
    )
    assert "Tags:" not in result


@pytest.mark.asyncio
async def test_search_documentation_empty_returns_hint(patch_mcp_deps):
    patch_mcp_deps([])

    from docforge.mcp_server import search_documentation

    result = await search_documentation("q", user_name="u", team_name="t")
    assert "No documentation found" in result


@pytest.mark.asyncio
async def test_list_sources_formats_entries(patch_mcp_deps):
    rows = [
        {
            "title": "Doc A",
            "url": "https://wiki/a",
            "status": "active",
            "last_crawled_at": datetime(2026, 4, 17, 9, 30, tzinfo=timezone.utc),
            "chunk_count": 12,
        },
    ]
    patch_mcp_deps(rows)

    from docforge.mcp_server import list_sources

    result = await list_sources()
    assert "Doc A" in result
    assert "12 chunks" in result


@pytest.mark.asyncio
async def test_list_sources_empty_returns_hint(patch_mcp_deps):
    patch_mcp_deps([])

    from docforge.mcp_server import list_sources

    result = await list_sources()
    assert "No sources indexed" in result
```

- [ ] **Step 3: Run MCP tests**

```bash
cd /e/docforge
source .venv/Scripts/activate
pytest tests/unit/test_mcp_server.py -v --no-cov
```
Expected: 5 tests pass.

- [ ] **Step 4: Commit**

```bash
cd /e/docforge
git add docforge/mcp_server.py tests/unit/test_mcp_server.py
git commit -m "feat(mcp): add user/team/area params, tag-aware SQL, response tags, logging"
```

---

## Task 11: Update CLI — new flags + Settings defaults

**Files:**
- Modify: `docforge/docforge/cli.py`
- Modify: `docforge/tests/unit/test_cli.py`

- [ ] **Step 1: Update the `search` command signature in `docforge/cli.py`**

Replace the `search` command and the `_search` helper. New definitions:

```python
@app.command()
def search(
    query: str = typer.Argument(help="Search query"),
    user_name: str = typer.Option(
        None, "--user",
        help="Your name (required; falls back to default_user_name setting)",
    ),
    team_name: str = typer.Option(
        None, "--team",
        help="Your team tag (required; falls back to default_team_name setting)",
    ),
    area_name: str = typer.Option(
        None, "--area",
        help="Your area tag (optional; falls back to default_area_name setting)",
    ),
    limit: int = typer.Option(5, help="Max results"),
):
    """Search the documentation index."""
    _setup_logging()
    from docforge.config import Settings

    settings = Settings()
    resolved_user = user_name or settings.default_user_name
    resolved_team = team_name or settings.default_team_name
    resolved_area = area_name or (settings.default_area_name or None) or None

    if not resolved_user:
        typer.echo(
            "Error: --user is required (or set default_user_name in docforge.yml).",
            err=True,
        )
        raise typer.Exit(1)
    if not resolved_team:
        typer.echo(
            "Error: --team is required (or set default_team_name in docforge.yml).",
            err=True,
        )
        raise typer.Exit(1)

    asyncio.run(_search(query, resolved_user, resolved_team, resolved_area, limit))
```

Replace the `_search` helper:

```python
async def _search(
    query: str, user_name: str, team_name: str, area_name: str | None, limit: int
):
    import numpy as np

    from docforge.config import Settings
    from docforge.db import close_pool, get_pool
    from docforge.processors.embedder import Embedder
    from docforge.query_log import log_query

    settings = Settings()
    try:
        embedder = Embedder(
            settings.embedding_model, hf_token=settings.hf_token.get_secret_value()
        )
    except RuntimeError as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(1)

    query_vector = embedder.embed_query(query)
    user_tags = [team_name] + ([area_name] if area_name else [])

    try:
        pool = await get_pool(settings.database_url)
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT c.text, c.section_title, s.title AS source_title,
                       s.tags AS source_tags,
                       1 - (c.embedding <=> $1::vector) AS similarity,
                       (1 - (c.embedding <=> $1::vector)) *
                         (1
                          + $2::float * cardinality(
                              ARRAY(SELECT unnest(s.tags) INTERSECT SELECT unnest($3::text[]))
                            )
                          + $4::float * (CASE WHEN 'org' = ANY(s.tags) THEN 1 ELSE 0 END)
                         ) AS boosted_score
                FROM chunks c JOIN sources s ON c.source_id = s.id
                WHERE s.status = 'active'
                ORDER BY boosted_score DESC LIMIT $5
                """,
                np.array(query_vector, dtype=np.float32),
                settings.tag_match_weight,
                user_tags,
                settings.org_tag_weight,
                limit,
            )
        await log_query(pool, user_name, team_name, area_name, query, len(rows))
    except OSError as e:
        typer.echo(
            f"Error: Cannot connect to database. Is PostgreSQL running?\n{e}",
            err=True,
        )
        raise typer.Exit(1)
    finally:
        await close_pool()

    if not rows:
        typer.echo("No results found.")
        return

    for i, row in enumerate(rows, 1):
        sim = row["similarity"]
        src = row["source_title"]
        sec = row["section_title"] or ""
        tags = list(row["source_tags"] or [])
        typer.echo(f"\n--- Result {i} (relevance: {sim:.2f}) --- {src}")
        if sec:
            typer.echo(f"Section: {sec}")
        if tags:
            typer.echo(f"Tags: {', '.join(tags)}")
        typer.echo(row["text"][:500])
```

- [ ] **Step 2: Update CLI tests**

Replace `TestSearchCommand` in `tests/unit/test_cli.py`:

```python
class TestSearchCommand:
    def test_success_with_required_flags(self, monkeypatch):
        captured = {}

        async def fake(query, user_name, team_name, area_name, limit):
            captured["query"] = query
            captured["user"] = user_name
            captured["team"] = team_name
            captured["area"] = area_name
            captured["limit"] = limit

        monkeypatch.setattr("docforge.cli._search", fake)
        result = runner.invoke(
            app,
            ["search", "q", "--user", "tobias", "--team", "ccl", "--area", "cloud", "--limit", "3"],
        )
        assert result.exit_code == 0
        assert captured == {
            "query": "q", "user": "tobias", "team": "ccl",
            "area": "cloud", "limit": 3,
        }

    def test_area_optional(self, monkeypatch):
        captured = {}

        async def fake(query, user_name, team_name, area_name, limit):
            captured["area"] = area_name

        monkeypatch.setattr("docforge.cli._search", fake)
        result = runner.invoke(
            app, ["search", "q", "--user", "u", "--team", "t"],
        )
        assert result.exit_code == 0
        assert captured["area"] is None

    def test_fails_when_user_missing(self):
        result = runner.invoke(app, ["search", "q", "--team", "t"])
        assert result.exit_code == 1
        assert "--user is required" in (result.output + (result.stderr or ""))

    def test_fails_when_team_missing(self):
        result = runner.invoke(app, ["search", "q", "--user", "u"])
        assert result.exit_code == 1
        assert "--team is required" in (result.output + (result.stderr or ""))

    def test_uses_settings_default_user(self, monkeypatch, tmp_path):
        captured = {}

        async def fake(query, user_name, team_name, area_name, limit):
            captured["user"] = user_name
            captured["team"] = team_name

        monkeypatch.setattr("docforge.cli._search", fake)
        monkeypatch.chdir(tmp_path)
        (tmp_path / "docforge.yml").write_text(
            "default_user_name: tobias.default\n"
            "default_team_name: ccl.default\n"
        )
        result = runner.invoke(app, ["search", "q"])
        assert result.exit_code == 0
        assert captured == {"user": "tobias.default", "team": "ccl.default"}
```

- [ ] **Step 3: Run CLI tests**

```bash
cd /e/docforge
source .venv/Scripts/activate
pytest tests/unit/test_cli.py -v --no-cov
```
Expected: all pass.

- [ ] **Step 4: Commit**

```bash
cd /e/docforge
git add docforge/cli.py tests/unit/test_cli.py
git commit -m "feat(cli): require --user/--team, add --area, honor Settings defaults"
```

---

## Task 12: Integration test for ranking SQL

**Files:**
- Create: `docforge/tests/integration/test_ranking_integration.py`

- [ ] **Step 1: Write the test**

Create `tests/integration/test_ranking_integration.py`:

```python
"""Integration test: tag-aware ranking against real pgvector."""

from __future__ import annotations

import asyncpg
import numpy as np
import pytest
from pgvector.asyncpg import register_vector


async def _insert_source(conn, title: str, tags: list[str]) -> str:
    return await conn.fetchval(
        """
        INSERT INTO sources (type, url, title, source_identifier, status, tags,
                             content_hash, last_crawled_at)
        VALUES ('git_repo', $1, $2, $1, 'active', $3, 'h', now())
        RETURNING id
        """,
        f"file:///{title}", title, tags,
    )


async def _insert_chunk(conn, source_id: str, text: str, vec: np.ndarray):
    await conn.execute(
        """
        INSERT INTO chunks (source_id, chunk_index, text, embedding, section_title)
        VALUES ($1, 0, $2, $3, NULL)
        """,
        source_id, text, vec,
    )


def _vec(last_dim: float) -> np.ndarray:
    v = np.zeros(768, dtype=np.float32)
    v[767] = last_dim
    return v


@pytest.mark.asyncio
async def test_team_tagged_source_ranks_above_untagged_on_similar_similarity(pg_url):
    conn = await asyncpg.connect(pg_url)
    try:
        await register_vector(conn)

        # Two sources at identical similarity (identical fake vectors), different tags.
        sid_tagged = await _insert_source(conn, "TaggedDoc", ["ccl"])
        sid_untagged = await _insert_source(conn, "UntaggedDoc", [])
        same_vec = _vec(0.001)
        await _insert_chunk(conn, sid_tagged, "tagged chunk", same_vec)
        await _insert_chunk(conn, sid_untagged, "untagged chunk", same_vec)

        # Run the boosted-score query shape.
        query_vec = _vec(0.001)
        rows = await conn.fetch(
            """
            SELECT s.title,
                   (1 - (c.embedding <=> $1::vector)) *
                     (1
                      + $2::float * cardinality(
                          ARRAY(SELECT unnest(s.tags) INTERSECT SELECT unnest($3::text[]))
                        )
                      + $4::float * (CASE WHEN 'org' = ANY(s.tags) THEN 1 ELSE 0 END)
                     ) AS score
            FROM chunks c JOIN sources s ON c.source_id = s.id
            ORDER BY score DESC
            """,
            query_vec, 0.1, ["ccl"], 0.05,
        )
        titles = [r["title"] for r in rows]
        assert titles == ["TaggedDoc", "UntaggedDoc"]
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_two_tag_overlap_outranks_one_tag_overlap(pg_url):
    conn = await asyncpg.connect(pg_url)
    try:
        await register_vector(conn)
        sid_one = await _insert_source(conn, "OneTag", ["ccl"])
        sid_two = await _insert_source(conn, "TwoTag", ["ccl", "cloud"])
        vec = _vec(0.001)
        await _insert_chunk(conn, sid_one, "one", vec)
        await _insert_chunk(conn, sid_two, "two", vec)

        rows = await conn.fetch(
            """
            SELECT s.title,
                   (1 - (c.embedding <=> $1::vector)) *
                     (1 + $2::float * cardinality(
                          ARRAY(SELECT unnest(s.tags) INTERSECT SELECT unnest($3::text[]))
                        )) AS score
            FROM chunks c JOIN sources s ON c.source_id = s.id
            ORDER BY score DESC
            """,
            vec, 0.1, ["ccl", "cloud"],
        )
        assert [r["title"] for r in rows] == ["TwoTag", "OneTag"]
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_org_tag_baseline_boost_applies_when_user_tags_empty(pg_url):
    conn = await asyncpg.connect(pg_url)
    try:
        await register_vector(conn)
        sid_org = await _insert_source(conn, "OrgDoc", ["org"])
        sid_plain = await _insert_source(conn, "PlainDoc", [])
        vec = _vec(0.001)
        await _insert_chunk(conn, sid_org, "org", vec)
        await _insert_chunk(conn, sid_plain, "plain", vec)

        rows = await conn.fetch(
            """
            SELECT s.title,
                   (1 - (c.embedding <=> $1::vector)) *
                     (1 + $2::float * (CASE WHEN 'org' = ANY(s.tags) THEN 1 ELSE 0 END)) AS score
            FROM chunks c JOIN sources s ON c.source_id = s.id
            ORDER BY score DESC
            """,
            vec, 0.05,
        )
        assert [r["title"] for r in rows] == ["OrgDoc", "PlainDoc"]
    finally:
        await conn.close()
```

- [ ] **Step 2: Run**

```bash
cd /e/docforge
source .venv/Scripts/activate
pytest tests/integration/test_ranking_integration.py -v -m integration --no-cov
```
Expected: 3 tests pass.

- [ ] **Step 3: Commit**

```bash
cd /e/docforge
git add tests/integration/test_ranking_integration.py
git commit -m "test(integration): verify tag-aware ranking against pgvector"
```

---

## Task 13: Full coverage checkpoint

- [ ] **Step 1: Run entire test suite**

```bash
cd /e/docforge
source .venv/Scripts/activate
pytest
```
Expected: all tests pass; coverage ≥60% (gate), likely 83-84%.

- [ ] **Step 2: If coverage fell below 60%, inspect**

Review the coverage report for newly uncovered lines in `ranking.py`, `query_log.py`, updated `api.py`, `mcp_server.py`, `cli.py`, and add tests. Do not proceed until the gate passes.

- [ ] **Step 3: No commit if no changes**

If Step 1 passed clean, move on. If you added tests in Step 2, commit them:

```bash
cd /e/docforge
git add tests/
git commit -m "test: backfill coverage after team-tagging changes"
```

---

## Task 14: Create `knowledge-hub/rag/teams.yml`

**Files:**
- Create: `/e/knowledge-hub/rag/teams.yml`

- [ ] **Step 1: Create the file**

```yaml
# Canonical tag vocabulary for docforge sources in the DocuWare deployment.
# docforge does not enforce this list; consumers (generate_sources.py, Spec-C
# linter, MCP client docs) read it.

teams:
  - id: ccl
    name: Cloud Customer Lifecycle
    area: cloud

# Additional teams will be added as other teams adopt docforge.

areas:
  - id: cloud
    name: Cloud

special_tags:
  - id: org
    name: Organization-wide (not team-specific)
  - id: cross-team
    name: Cross-team concern (optional additional tag)
```

- [ ] **Step 2: Commit**

```bash
cd /e/knowledge-hub
git add rag/teams.yml
git commit -m "docs(rag): add canonical tag vocabulary (teams.yml)"
```

---

## Task 15: Tag all entries in `knowledge-hub/rag/sources.yml`

**Files:**
- Modify: `/e/knowledge-hub/rag/sources.yml`

Tag every source. For the 44 Confluence pages and 28 git repos, apply these rules:

- Git repos under `E:/` discovered via the CCL project → `tags: [ccl]`
- Confluence pages with CCL-team scope (titles starting with `Team Cloud Customer Lifecycle`, `Domain -`, `[Tech Paper]`, `[TechPaper]`, `How to`, `Onboarding CCL`, `CCL PO`, `Application Catalog - Team CloudCL`, `Automatic Emails`, `Deletion of Cloud`, `Country Specific`, `Regional mapping`, `Update Shard Limits`, `Integration Test`) → `tags: [ccl]`
- Confluence pages with org-wide scope (titles: `Scrum Teams Responsibilities`, `Standardized architecture responsibilities`, `HTTP error handling guidelines`, `Application architecture guidelines`, `Standardized DevOps Processes`, `Security Threat Model guidelines`, `SonarQube guidelines`, `Mend/WhiteSource guidelines`) → `tags: [org]`

- [ ] **Step 1: Edit `sources.yml`**

For each entry in the file, add a `tags:` field according to the rules above. Every entry in the file must have the field after this step.

Spot-check mapping for guidance:
- `Scrum Teams Responsibilities` → `[org]`
- `Standardized architecture responsibilities` → `[org]`
- `HTTP error handling guidelines` → `[org]`
- `Team Cloud Customer Lifecycle` → `[ccl]`
- `Application Catalog - Team CloudCL` → `[ccl]`
- `Domain - Cloud Status` → `[ccl]`
- `Domain - Feature Flag Services` → `[ccl]`
- `[Tech Paper] Cluster Infrastructure` → `[ccl]`
- `Onboarding CCL member` → `[ccl]`
- `CCL PO Special Responsibilities` → `[ccl]`
- `Application architecture guidelines` → `[org]`
- `Standardized DevOps Processes` → `[org]`
- `Security Threat Model guidelines` → `[org]`
- `SonarQube guidelines` → `[org]`
- `Mend/WhiteSource guidelines` → `[org]`
- All `git_repo` entries → `[ccl]`

- [ ] **Step 2: Verify the file still parses**

```bash
cd /e/knowledge-hub/rag
python -c "import yaml; data = yaml.safe_load(open('sources.yml')); assert all('tags' in s for s in data['sources']); print(f'OK: {len(data[\"sources\"])} entries, all tagged')"
```
Expected: `OK: 72 entries, all tagged`

- [ ] **Step 3: Commit**

```bash
cd /e/knowledge-hub
git add rag/sources.yml
git commit -m "data(rag): tag all 72 sources (ccl or org)"
```

---

## Task 16: Update `generate_sources.py` to emit tags

**Files:**
- Modify: `/e/knowledge-hub/rag/generate_sources.py`

- [ ] **Step 1: Patch the CCL repo tagging in `find_local_repos`**

Replace the `git_sources.append({...})` block inside `find_local_repos` with:

```python
        if has_docs:
            git_sources.append({
                "type": "git_repo",
                "repo_path": str(repo_dir).replace("\\", "/"),
                "include_patterns": patterns,
                "title": repo_name,
                "tags": ["ccl"],
            })
```

- [ ] **Step 2: Run generate_sources.py and verify tags appear**

```bash
cd /e/knowledge-hub/rag
python generate_sources.py
python -c "import yaml; data = yaml.safe_load(open('sources.yml')); assert all('ccl' in (s.get('tags') or []) for s in data['sources'] if s['type']=='git_repo'); print('all git_repo entries tagged [ccl]')"
```
Expected: `all git_repo entries tagged [ccl]`.

(Note: re-running `generate_sources.py` overwrites manually-tagged Confluence entries because the script reads existing Confluence sources and rewrites. If it does, re-apply the Confluence tagging from Task 15 — or edit `generate_sources.py` to preserve existing `tags` fields on Confluence entries. Preserving is cleaner; see Step 3.)

- [ ] **Step 3: Preserve existing Confluence tags**

Inside `main()`, change the confluence_sources extraction so tags are kept:

```python
    confluence_sources = [
        s for s in data.get("sources", []) if s.get("type") == "confluence_page"
    ]
```

This line already keeps the full dict including `tags`. Verify by re-running Step 2 — confluence entries should still carry their `[ccl]` or `[org]` tags after the run.

- [ ] **Step 4: Commit**

```bash
cd /e/knowledge-hub
git add rag/generate_sources.py rag/sources.yml
git commit -m "feat(generate_sources): tag auto-discovered CCL repos with [ccl]"
```

---

## Task 17: Update `mcp_client.py` to pass user/team/area env vars

**Files:**
- Modify: `/e/knowledge-hub/rag/mcp_client.py`

- [ ] **Step 1: Read the current file to understand structure**

```bash
cat /e/knowledge-hub/rag/mcp_client.py
```

Note: the client makes HTTP calls to the hosted `/search` endpoint.

- [ ] **Step 2: Patch the client to read env vars and pass them**

At the top of the file, add:

```python
import os
import sys
```

Before the first use of the search API, add an identity-resolution helper:

```python
def _resolve_identity() -> tuple[str, str, str | None]:
    user = os.environ.get("KNOWLEDGE_HUB_USER", "").strip()
    team = os.environ.get("KNOWLEDGE_HUB_TEAM", "").strip()
    area = os.environ.get("KNOWLEDGE_HUB_AREA", "").strip() or None
    if not user or not team:
        print(
            "Error: KNOWLEDGE_HUB_USER and KNOWLEDGE_HUB_TEAM must be set.\n"
            "See knowledge-hub/rag/docs/team-setup-azure.md for setup.",
            file=sys.stderr,
        )
        sys.exit(1)
    return user, team, area
```

In the function that calls `/search` (locate the existing POST request), resolve identity and add fields to the request body. The expected shape of the call becomes:

```python
    user, team, area = _resolve_identity()
    body = {
        "query": query,
        "user_name": user,
        "team_name": team,
        "area_name": area,
        "limit": limit,
    }
    response = httpx.post(f"{API_URL}/search", json=body, timeout=30)
```

(Exact variable names may differ — preserve the existing style but ensure the four new fields are included.)

- [ ] **Step 3: Smoke-test against the hosted API (manual — only if env vars are set)**

```bash
export KNOWLEDGE_HUB_USER=tobias.ens
export KNOWLEDGE_HUB_TEAM=ccl
export KNOWLEDGE_HUB_AREA=cloud
python /e/knowledge-hub/rag/mcp_client.py <test-invocation>
```

This step is a manual smoke test and optional — the test will only succeed after docforge is redeployed with the new API. If the hosted API still runs the previous docforge version, the call will 422 on the unexpected fields (FastAPI is strict by default). Acceptable; mcp_client change is landed ahead of deployment.

- [ ] **Step 4: Commit**

```bash
cd /e/knowledge-hub
git add rag/mcp_client.py
git commit -m "feat(mcp_client): pass user/team/area; fail hard on missing identity"
```

---

## Task 18: Update `team-setup-azure.md` with identity setup

**Files:**
- Modify: `/e/knowledge-hub/rag/docs/team-setup-azure.md`

- [ ] **Step 1: Add identity-setup section**

Read the file first:

```bash
cat /e/knowledge-hub/rag/docs/team-setup-azure.md
```

Insert a new step after "### 2. Get the MCP client" and before "### 3. Register with Claude Code":

```markdown
### 2a. Set your identity

docforge tags each query with your identity for usage telemetry and
relevance weighting. Set three environment variables before registering
the MCP client:

```
KNOWLEDGE_HUB_USER=your.name        # e.g., tobias.ens
KNOWLEDGE_HUB_TEAM=your-team-tag    # e.g., ccl — see teams.yml
KNOWLEDGE_HUB_AREA=your-area-tag    # optional; e.g., cloud
```

Valid team and area tags are listed in
[`rag/teams.yml`](../teams.yml). If `USER` or `TEAM` is unset,
the MCP client will fail with a setup hint on first invocation.
```

Update step 3 so the claude mcp add command includes the env vars:

```markdown
### 3. Register with Claude Code

```bash
claude mcp add -s user \
  -e KNOWLEDGE_HUB_API_URL="<API_URL>" \
  -e KNOWLEDGE_HUB_USER="your.name" \
  -e KNOWLEDGE_HUB_TEAM="your-team-tag" \
  -e KNOWLEDGE_HUB_AREA="your-area-tag" \
  knowledge-hub -- python <FULL_PATH_TO>/mcp_client.py
```
```

- [ ] **Step 2: Commit**

```bash
cd /e/knowledge-hub
git add rag/docs/team-setup-azure.md
git commit -m "docs(rag): document KNOWLEDGE_HUB_USER/TEAM/AREA env var setup"
```

---

## Task 19: End-to-end smoke test

- [ ] **Step 1: Apply migrations to local Postgres**

```bash
cd /e/knowledge-hub/rag
source /e/docforge/.venv/Scripts/activate  # or the rag venv if different
docker compose up -d db
docforge init-db
```
Expected: migrations 001-004 applied cleanly (no errors about existing columns/tables).

- [ ] **Step 2: Re-ingest with tags**

```bash
cd /e/knowledge-hub/rag
python generate_sources.py
docforge ingest
```
Expected: ingest summary reports sources succeeded; the DB now has tagged source rows.

- [ ] **Step 3: Verify tags landed in DB**

```bash
psql "postgresql://docforge:localdev@localhost:5432/docforge" -c "SELECT title, tags FROM sources LIMIT 5"
```
Expected: rows show non-empty `tags` arrays.

- [ ] **Step 4: Run a tag-aware search locally**

```bash
docforge search "retry policy" --user tobias.ens --team ccl --area cloud --limit 3
```
Expected: results print with `Tags:` lines on tagged sources.

- [ ] **Step 5: Verify query_log captured the request**

```bash
psql "postgresql://docforge:localdev@localhost:5432/docforge" -c "SELECT user_name, team_name, area_name, query, result_count FROM query_log ORDER BY created_at DESC LIMIT 3"
```
Expected: most recent row reflects the CLI query above.

- [ ] **Step 6: No commit — this is verification**

---

## Task 20: Final verification + merge

- [ ] **Step 1: Run full test suite one more time in docforge**

```bash
cd /e/docforge
source .venv/Scripts/activate
pytest
```
Expected: all tests pass, coverage ≥60%.

- [ ] **Step 2: Verify no uncommitted changes**

```bash
cd /e/docforge && git status
cd /e/knowledge-hub && git status
```
Both: `nothing to commit, working tree clean`.

- [ ] **Step 3: Summary of shipped work**

```bash
cd /e/docforge && git log --oneline master..HEAD 2>&1 | head -15
cd /e/knowledge-hub && git log --oneline @{u}..HEAD 2>&1 | head -10
```

Report commit counts to the user.

---

## Done

Phase 4 Spec A shipped. Coverage maintained, tag-aware ranking working end-to-end against pgvector, knowledge-hub/rag updated to match. Next spec in Phase 4 ordering is Spec B (repo docs authoring guideline).
