# Spec A — Team Tagging + MCP user/team/area Parameters

**Date:** 2026-04-17
**Status:** Approved, ready for implementation plan
**Scope:** Add tag-based scoping to source config and database; extend MCP tool, API, and CLI to accept `user_name`, `team_name`, and optional `area_name`; apply small multiplicative boost to similarity ranking based on tag overlap.

## Context

docforge currently serves a single company (DocuWare) via a single shared Azure deployment. Indexed content spans ~44 Confluence pages + ~28 git repos, with content owned by different teams (mostly CCL) and content that is org-wide (architecture guidelines, DevOps processes). Today the engine has no concept of source ownership, so a query from any user against any documentation topic returns the same ranked list — org-wide results compete with team-specific results purely on embedding similarity.

Spec A introduces team context. A source can be tagged (e.g., `["ccl"]`, `["ccl", "cloud"]`, `["org"]`). An MCP query carries the caller's user identity, team, and optional area. Ranking applies a small multiplicative boost when source tags overlap the caller's scope tags, and a baseline boost when the source carries the special `org` tag. Semantic similarity remains the primary ranking signal; tags are a tiebreaker with teeth.

## Goals

1. Add a `tags TEXT[]` column to `sources` and propagate tags through ingest.
2. Extend the MCP tool, `/search` API, and CLI `search` command with required `user_name`, required `team_name`, optional `area_name`, and existing `limit`.
3. Apply a tag-aware boost to the query SQL, configurable via Settings.
4. Log each query (`user_name`, `team_name`, `area_name`, `query`, `result_count`, `created_at`) to a new `query_log` table.
5. Maintain ≥60% test coverage gate; add unit and integration tests that cover the ranking path.
6. Publish a canonical tag vocabulary in `knowledge-hub/rag/teams.yml` (not enforced by docforge; consumed by tooling).

Non-goals:
- Multi-tenant authentication or authorization (single-company trust model).
- Personalization based on `user_name` (deferred; this spec uses it only for logging).
- Aggregate analytics / dashboards on `query_log` (deferred to Spec C).
- Role or topic tags beyond team/area/org (schema supports via `tags TEXT[]`, but this spec doesn't define them).

## Design principles

- **Repo separation.** docforge is generic: it accepts any string tags. Controlled vocabulary lives in knowledge-hub/rag, docforge doesn't enforce.
- **Similarity dominates.** Boost is small and multiplicative so a strong semantic match outside the user's tags still wins over a weak in-scope match.
- **Fail hard at config boundaries.** Missing required identity at MCP/API/CLI is an error, not a silent fallback.
- **Log, don't personalize.** `user_name` is telemetry this iteration; future personalization is out of scope.

## Schema changes

Two migrations under `docforge/docforge/sql/migrations/`:

**`003_add_source_tags.sql`:**
```sql
ALTER TABLE sources
    ADD COLUMN IF NOT EXISTS tags TEXT[] NOT NULL DEFAULT '{}';

CREATE INDEX IF NOT EXISTS sources_tags_idx ON sources USING gin (tags);
```

`NOT NULL DEFAULT '{}'` — existing rows get an empty array and rank neutrally (no boost, no penalty). GIN index keeps array-overlap operators fast as source count grows.

**`004_add_query_log.sql`:**
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

No result contents stored (fat, privacy-sensitive). `result_count` lets us observe zero-result queries. No FK to `sources` (results sets churn). Retention policy is a separate Spec-C deliverable (`knowledge-hub/rag/docs/log-privacy.md`).

## Source config schema

`docforge/docforge/sources.py`:

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

Default `[]` keeps existing configs valid.

## MCP tool signature

`docforge/mcp_server.py::search_documentation`:

```python
@mcp.tool()
async def search_documentation(
    query: str,
    user_name: str,
    team_name: str,
    area_name: str | None = None,
    limit: int = 5,
) -> str:
    """Search indexed documentation.

    Args:
        query: Natural language search query.
        user_name: Caller's name (e.g., "tobias.ens"). Used for usage telemetry.
        team_name: Caller's team tag (e.g., "ccl"). Boosts team-tagged docs.
        area_name: Caller's area tag (e.g., "cloud"). Optional; boosts area-tagged docs.
        limit: Max results (default 5).
    """
```

Required params enforced by MCP runtime before the tool is called. Missing `user_name` or `team_name` → protocol error; the tool body is not entered.

## API surface

`docforge/api.py::SearchRequest` and `/search`:

```python
class SearchRequest(BaseModel):
    query: str
    user_name: str
    team_name: str
    area_name: str | None = None
    limit: int = 5
```

Any caller not supplying `user_name`/`team_name` gets a 422 (pydantic validation). This is the fail-hard boundary for API consumers.

## CLI surface

`docforge/cli.py::search`:

```python
@app.command()
def search(
    query: str = typer.Argument(help="Search query"),
    user_name: str = typer.Option(..., "--user", help="Your name"),
    team_name: str = typer.Option(..., "--team", help="Your team tag"),
    area_name: str | None = typer.Option(None, "--area", help="Your area tag (optional)"),
    limit: int = typer.Option(5, help="Max results"),
):
```

Settings defaults in `docforge/config.py`:

```python
default_user_name: str = ""
default_team_name: str = ""
default_area_name: str = ""
```

If set (via `.env` or `docforge.yml`), CLI uses them as flag defaults so local iteration doesn't require typing `--user --team` every invocation. Explicit flags still win.

## Ranking formula

```
final_score = similarity × (1 + tag_match_weight × |user_tags ∩ source.tags| + org_tag_weight × ('org' ∈ source.tags))
```

Where `user_tags` is `[team_name]` when no area, else `[team_name, area_name]`.

`docforge/config.py`:
```python
tag_match_weight: float = 0.1
org_tag_weight: float = 0.05
```

Conservative defaults — boost caps at ~15% in common cases. Configurable without code change.

## Query SQL

In both `docforge/mcp_server.py::search_documentation` and `docforge/api.py::search`:

```sql
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
```

Parameters:
- `$1` — query vector (`float32[768]`)
- `$2` — `tag_match_weight` (e.g., `0.1`)
- `$3` — `user_tags` as `TEXT[]` (e.g., `{ccl,cloud}` or `{ccl}`)
- `$4` — `org_tag_weight` (e.g., `0.05`)
- `$5` — `limit`

Notes:
- `ORDER BY boosted_score DESC` replaces the prior `ORDER BY embedding <=> $1::vector`. Correctness: `boost ≥ 1` always, so same-profile rows preserve their similarity order.
- Overlap count via `INTERSECT`-on-unnest — portable, works with the GIN index via `sources.tags && $3::text[]` if we later want a prefilter.
- HNSW index on `chunks.embedding` still used by the planner for the inner distance computation.

## Ranking helper

New module `docforge/ranking.py`:

```python
def compute_boosted_score(
    similarity: float,
    source_tags: list[str],
    user_tags: list[str],
    tag_weight: float,
    org_weight: float,
) -> float:
    overlap = len(set(source_tags) & set(user_tags))
    has_org = "org" in source_tags
    return similarity * (1 + tag_weight * overlap + org_weight * (1 if has_org else 0))
```

Pure function, unit-testable without SQL. The SQL implements the same formula; tests verify both.

## Response format

MCP tool output includes a tag line when non-empty:

```
**Result 1** (relevance: 0.92) — Team Responsibilities > Platform
Source: https://wiki/page/1
Tags: ccl, cloud

[chunk text]
```

Helps the AI caller phrase answers like "from your team's docs" vs. "from an overarching guideline." Empty tag arrays produce no tag line.

API response adds `source_tags: list[str]` to each `SearchResult`.

## Query logging

New helper in `docforge/query_log.py`:

```python
async def log_query(
    pool: asyncpg.Pool,
    user_name: str,
    team_name: str,
    area_name: str | None,
    query: str,
    result_count: int,
) -> None:
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

Failures swallowed — logging must not break a search. Called after each search from MCP tool, `/search` API handler, and CLI `search` command.

## Tests

**Unit (under `tests/unit/`):**

- `test_ranking.py` — NEW. Parameterized tests of `compute_boosted_score`:
  - 0 overlap, no org → `similarity × 1.0`
  - 1 overlap, no org → `similarity × 1.1`
  - 2 overlap, no org → `similarity × 1.2`
  - 0 overlap, has org → `similarity × 1.05`
  - 1 overlap, has org → `similarity × 1.15`
  - Configurable weights honored.
- `test_query_log.py` — NEW. Fake pool captures `INSERT INTO query_log` args; verifies values; verifies exceptions in log path don't surface.
- `test_api.py` — extend. New required `user_name`/`team_name`; 422 when missing; `area_name` optional; tag line in response; query_log insert triggered.
- `test_mcp_server.py` — extend. Same shape; tag line in formatted output; empty-tags case produces no tag line.
- `test_cli.py` — extend. `--user`/`--team` required; `--area` optional; Settings defaults used when flags missing.

**Integration (under `tests/integration/`):**

- `test_ranking_integration.py` — NEW. Real pgvector + FakeEmbedder. Seeds 5 sources with varied tag combinations and deterministic vectors; asserts result order for several `user_tags` values including the area-absent case.
- `test_db_schema.py` — extend. Verifies `tags` column, `query_log` table, GIN index.
- `test_ingest_git_integration.py` — extend. Ingest with `tags` in source config; verify tags land on the `sources` row.

**Coverage:** ≥60% gate preserved. Projected net ~83-84% after additions.

## Data migration (knowledge-hub/rag/)

**`teams.yml` (new):**

```yaml
# Canonical tag vocabulary for docforge sources.
# docforge does not enforce this list; consumers (generate_sources.py,
# Spec-C linter, MCP client docs) read it.

teams:
  - id: ccl
    name: Cloud Customer Lifecycle
    area: cloud
  # ... full list of ~25 teams

areas:
  - id: cloud
    name: Cloud
  # ... ~4-8 areas

special_tags:
  - id: org
    name: Organization-wide (not team-specific)
  - id: cross-team
    name: Cross-team concern (optional additional tag)
```

**`sources.yml` (update):**

Tag all 72 existing entries. Strategy:
- Automated via `generate_sources.py`: all CCL-discovered git repos get `[ccl]`.
- Manual for the 44 Confluence pages (one-time pass, ~20-30 min):
  - Domain-* / [Tech Paper] / How to* / CCL-specific pages → `[ccl]`
  - Org-wide guidelines (Application architecture guidelines, Standardized DevOps Processes, Security Threat Model, SonarQube guidelines, Mend/WhiteSource guidelines, HTTP error handling guidelines) → `[org]`
  - Cross-cutting Tech Papers optionally tagged `[ccl, cloud]` — deferred to a later refinement pass; default to `[ccl]`.

**`generate_sources.py` (update):**

Add `tags: ["ccl"]` to each auto-discovered CCL git repo entry. Keep existing Confluence entries untouched (they carry manually-assigned tags).

**`mcp_client.py` (update):**

Read `KNOWLEDGE_HUB_USER`, `KNOWLEDGE_HUB_TEAM`, `KNOWLEDGE_HUB_AREA` from environment; pass to each search call. If `USER` or `TEAM` is unset, fail with a clear message pointing at `team-setup-azure.md`.

**`team-setup-azure.md` (update):**

Add a "Set your identity" step walking new users through the three env vars, with a link to the `teams.yml` canonical list.

## Breaking-change handling

Existing MCP client configs without the new env vars will fail at first query. Resolution: fail hard with a message like:

```
KNOWLEDGE_HUB_USER and KNOWLEDGE_HUB_TEAM are required.
See knowledge-hub/rag/docs/team-setup-azure.md for setup.
```

~8-10 current users, one-time migration, explicit error is clearer than a silent `"unknown"` fallback that would rot into a permanent state.

## Success criteria

- [ ] Migrations 003 + 004 applied; existing rows backfilled with empty tags.
- [ ] Schema tests (Spec A adds, Spec C may extend) pass against a fresh pgvector container.
- [ ] MCP tool signature updated; missing required params produce protocol-level errors.
- [ ] `/search` API rejects requests missing `user_name`/`team_name` with 422.
- [ ] CLI `search` command requires `--user`/`--team`; honors Settings defaults when set.
- [ ] Ranking formula implemented in SQL AND in `docforge/ranking.py`; unit tests verify parity.
- [ ] Integration test proves team-tagged sources rank above untagged on otherwise-equal similarity, and org-tagged sources get the baseline boost.
- [ ] Query logs land in `query_log`; log failures do not surface to the caller.
- [ ] `knowledge-hub/rag/teams.yml` exists with canonical vocabulary.
- [ ] `knowledge-hub/rag/sources.yml` tagged for all 72 entries.
- [ ] `mcp_client.py` passes new env vars; fails hard when required ones are unset.
- [ ] Test coverage ≥60%; projected 83-84%.

## Out of scope (tracked elsewhere)

- Personalization of `user_name` — deferred; revisit after usage data.
- Privacy policy for `query_log` (retention, access, aggregation) — Spec C.
- Tag linter (validate source tags against `teams.yml`) — Spec C.
- Threat model update reflecting new data (query logs) — Spec C.
- Authoring guidelines for repos (including team-tagging conventions) — Spec B.
