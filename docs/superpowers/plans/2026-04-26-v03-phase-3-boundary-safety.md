# docforge v0.3 Phase 3 — Boundary Safety Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Hard-cap the API + MCP request boundaries and the embedder batch input so a buggy or runaway client can't amplify cost across the rest of the deployment, plus document the `query_log` privacy and retention policy.

**Architecture:** Pydantic `Field` constraints on `SearchRequest` in `api.py`. `Annotated[..., Field(...)]` on the MCP tool signature in `mcp_server.py`. A `MAX_BATCH_SIZE = 256` module constant in `embedder.py` enforced inside `Embedder.embed` with a clear error. A new `docs/log-privacy.md` policy document covers purpose, retention, redaction patterns, access, and right-to-erasure runbook — partially aspirational; Phase 5 implements redaction and shortens the retention default.

**Tech Stack:** Python 3.12+, FastAPI, FastMCP (built on Pydantic), Pydantic v2, pytest.

**Spec mapping:**

| Spec item | Plan task |
|---|---|
| Hard caps on API + MCP (Finding 4) | Task 1 |
| Embedder batch input bounded (Finding 4 — same finding) | Task 1 |
| `docs/log-privacy.md` policy doc (Finding 5 part 1) | Task 2 |
| CHANGELOG entry for the user-facing changes | Task 3 |

**Testing notes:**

- API boundary tests use the existing `_client()` ASGITransport pattern in `tests/unit/test_api.py`. FastAPI returns 422 with a Pydantic-shaped `detail` list; tests inspect the `loc` field to confirm the right field was rejected.
- Embedder batch test uses the existing `embedder` fixture in `tests/unit/test_embedder.py::TestEmbedderMethods` — its mocked `encode` is never reached because the size check raises first.
- **MCP boundary not explicitly tested in this plan.** FastMCP's Pydantic layer enforces Annotated constraints when a tool is invoked through the MCP protocol, but a direct Python call (which is how `tests/unit/test_mcp_server.py` exercises the tool) bypasses Pydantic. Adding a FastMCP-protocol-level test would expand scope; trusting FastMCP's well-tested validation layer is acceptable for v0.3. If MCP boundary testing becomes necessary, a follow-up task can introduce it.

---

### Task 1: Hard caps on API + MCP + Embedder batch

**Files:**
- Modify: `src/docforge/api.py` — `Field` constraints on `SearchRequest` (`query` max length, `limit` range)
- Modify: `src/docforge/mcp_server.py` — `Annotated[..., Field(...)]` on `search_documentation` parameters; add `Annotated`, `Field` imports
- Modify: `src/docforge/processors/embedder.py` — add `MAX_BATCH_SIZE = 256` constant; raise `ValueError` in `embed` when input exceeds it
- Modify: `tests/unit/test_api.py` — add 2 boundary tests in `TestSearchEndpoint`
- Modify: `tests/unit/test_embedder.py` — add 1 batch-limit test in `TestEmbedderMethods`

- [ ] **Step 1: Write the failing API boundary tests**

Append two new test methods to the `TestSearchEndpoint` class in `tests/unit/test_api.py` (after the existing tests, before the closing of the class):

```python
    @pytest.mark.asyncio
    async def test_search_rejects_limit_over_max(self):
        """limit > 50 returns 422 with the limit field in the error detail."""
        async with _client() as client:
            resp = await client.post(
                "/search",
                json={
                    "query": "q",
                    "user_name": "u",
                    "team_name": "t",
                    "limit": 51,
                },
            )
        assert resp.status_code == 422
        detail = resp.json()["detail"]
        assert any(err["loc"][-1] == "limit" for err in detail)

    @pytest.mark.asyncio
    async def test_search_rejects_query_over_max_length(self):
        """query > 8000 chars returns 422 with the query field in the error detail."""
        async with _client() as client:
            resp = await client.post(
                "/search",
                json={
                    "query": "x" * 8001,
                    "user_name": "u",
                    "team_name": "t",
                    "limit": 1,
                },
            )
        assert resp.status_code == 422
        detail = resp.json()["detail"]
        assert any(err["loc"][-1] == "query" for err in detail)
```

- [ ] **Step 2: Write the failing embedder batch test**

Append one new test method to the `TestEmbedderMethods` class in `tests/unit/test_embedder.py` (after `test_get_tokenizer_fn_counts_tokens`, before any closing of the class):

```python
    def test_embed_rejects_batch_over_max_size(self, embedder):
        """Batch larger than MAX_BATCH_SIZE raises ValueError before reaching the model."""
        from docforge.processors.embedder import MAX_BATCH_SIZE

        with pytest.raises(ValueError, match="exceeds max"):
            embedder.embed(["x"] * (MAX_BATCH_SIZE + 1))
```

- [ ] **Step 3: Run the new tests — verify they fail**

```bash
python -m pytest tests/unit/test_api.py::TestSearchEndpoint::test_search_rejects_limit_over_max tests/unit/test_api.py::TestSearchEndpoint::test_search_rejects_query_over_max_length tests/unit/test_embedder.py::TestEmbedderMethods::test_embed_rejects_batch_over_max_size -v --tb=short 2>&1 | tail -20
```

Expected:
- API tests fail (current `SearchRequest` accepts any limit and query length, returning 200 or a downstream 503, not 422).
- Embedder test fails with `ImportError: cannot import name 'MAX_BATCH_SIZE'`.

- [ ] **Step 4: Apply the API constraints in `src/docforge/api.py`**

Replace the existing `SearchRequest` class (currently at lines 121-126) — find this block:

```python
class SearchRequest(BaseModel):
    query: str
    user_name: str
    team_name: str
    area_name: str | None = None
    limit: int = 5
```

with:

```python
class SearchRequest(BaseModel):
    query: str = Field(..., max_length=8000)
    user_name: str
    team_name: str
    area_name: str | None = None
    limit: int = Field(5, ge=1, le=50)
```

Add `Field` to the existing pydantic import at the top of the file. Currently the import line reads:

```python
from pydantic import BaseModel
```

Replace with:

```python
from pydantic import BaseModel, Field
```

- [ ] **Step 5: Apply the MCP constraints in `src/docforge/mcp_server.py`**

Add two imports at the top of the file alongside the existing imports (after `import logging`):

```python
from typing import Annotated
```

And alongside the `from fastmcp import FastMCP` line, add:

```python
from pydantic import Field
```

Replace the `search_documentation` function signature (currently at lines 51-57) — find this:

```python
@mcp.tool()
async def search_documentation(
    query: str,
    user_name: str,
    team_name: str,
    area_name: str | None = None,
    limit: int = 5,
) -> str:
```

with:

```python
@mcp.tool()
async def search_documentation(
    query: Annotated[str, Field(max_length=8000)],
    user_name: str,
    team_name: str,
    area_name: str | None = None,
    limit: Annotated[int, Field(ge=1, le=50)] = 5,
) -> str:
```

The function body and docstring stay unchanged. FastMCP picks up the Annotated metadata when registering the tool with the MCP protocol; clients invoking the tool with `limit=51` or a query longer than 8000 chars receive a Pydantic validation error before the function body runs.

- [ ] **Step 6: Apply the embedder batch limit in `src/docforge/processors/embedder.py`**

Add a module-level constant near the top of the file, after the `logger = logging.getLogger(__name__)` line:

```python
MAX_BATCH_SIZE = 256
```

Update the `embed` method body (currently at lines 92-101) — find this:

```python
    def embed(self, texts: list[str]) -> list[list[float]]:
        """Generate embeddings for a list of texts.

        Returns a list of float vectors, one per input text.
        """
        if not texts:
            return []

        embeddings = self._model.encode(texts, show_progress_bar=False, normalize_embeddings=True)
        return embeddings.tolist()
```

Replace with:

```python
    def embed(self, texts: list[str]) -> list[list[float]]:
        """Generate embeddings for a list of texts.

        Returns a list of float vectors, one per input text.

        Raises:
            ValueError: when len(texts) exceeds MAX_BATCH_SIZE. Callers that
                need to embed more than that should chunk before calling.
        """
        if not texts:
            return []
        if len(texts) > MAX_BATCH_SIZE:
            raise ValueError(
                f"Embedder batch size {len(texts)} exceeds max {MAX_BATCH_SIZE}; "
                f"chunk into smaller batches before calling embed()"
            )

        embeddings = self._model.encode(texts, show_progress_bar=False, normalize_embeddings=True)
        return embeddings.tolist()
```

- [ ] **Step 7: Run the targeted tests — verify they pass**

```bash
python -m pytest tests/unit/test_api.py::TestSearchEndpoint::test_search_rejects_limit_over_max tests/unit/test_api.py::TestSearchEndpoint::test_search_rejects_query_over_max_length tests/unit/test_embedder.py::TestEmbedderMethods::test_embed_rejects_batch_over_max_size -v --tb=short 2>&1 | tail -15
```

Expected: 3 tests pass.

- [ ] **Step 8: Run the full unit suite**

```bash
python -m pytest -m "not integration" -q --no-header --tb=line 2>&1 | tail -5
```

Expected: `161 passed, 12 deselected` (158 pre-existing + 3 new). No regressions.

If any pre-existing test fails because it sent `limit > 50` or a long query, update that test's payload to a valid value — the boundary is the contract now. The most likely candidate is anything that sets `limit` very high "just in case." Search for `"limit":` in `tests/` and audit before relaxing the new caps.

- [ ] **Step 9: Run lint**

```bash
python -m ruff check src/docforge tests && python -m ruff format --check src/docforge tests
```

Expected: clean. If `ruff format --check` complains about the new `Annotated[...]` lines in `mcp_server.py`, run `python -m ruff format src/docforge` and re-stage.

- [ ] **Step 10: Commit**

```bash
git add src/docforge/api.py src/docforge/mcp_server.py src/docforge/processors/embedder.py tests/unit/test_api.py tests/unit/test_embedder.py
git commit -m "$(cat <<'EOF'
feat(api,mcp,embedder): hard-cap request boundaries

Phase 3 of v0.3 hardening — Finding 4 from the v0.2.1 critical review.
A buggy or runaway client (custom MCP integration with limit=10000, a
runaway eval script firing 50 KB queries, an ingest job that batches
everything in one go) can degrade service for the rest of the
deployment. Three caps stop that:

- SearchRequest.query: max_length=8000 (~2k tokens, more than enough
  for any legitimate question)
- SearchRequest.limit: ge=1, le=50 (clients meaningfully consume
  ~5-10 results; 50 is generous headroom)
- Embedder.embed: raises ValueError when len(texts) > 256 (the typical
  per-call batch size for sentence-transformers; chunk above that)

API and MCP both surface 422 with Pydantic's named-field error detail
so a misbehaving client can fix itself on first contact. The embedder
batch raises ValueError with a remediation hint ("chunk into smaller
batches").

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 2: `docs/log-privacy.md` policy doc

**Files:**
- Create: `docs/log-privacy.md` — purely additive, no code change

The policy is **partially aspirational**: redaction is implemented in Phase 5; the retention default change from 180 → 60 days also lands in Phase 5. The doc has an "Implementation status" section that names what's true today vs. what's coming.

- [ ] **Step 1: Create `docs/log-privacy.md`**

Write the new file at `docs/log-privacy.md` with this exact content:

```markdown
# docforge `query_log` — privacy & retention policy

This document defines what `query_log` stores, how long, who can read it, what gets redacted, and how to honour a delete request. It is the policy a docforge deployer commits to operate by; the implementation in `src/docforge/` and `deploy/azure/main.bicep` should match it.

## Purpose

`query_log` exists to support **retrieval drift signals** — detecting when search quality regresses against real usage. Aggregate metrics on retention, recall@k, and request latency are derived from the `query` text plus the `result_count` and `request_ms` columns.

The table is *not* used for:

- per-user activity surveillance
- billing or quota enforcement
- audit trail for regulatory compliance

If your deployment has any of those needs, they are out of scope for docforge and should be served by a separate system.

## Retention

Default: **60 days**.

Configurable via `Settings.query_log_retention_days` (env: `QUERY_LOG_RETENTION_DAYS`). The application-level cleanup loop in `docforge.api._query_log_cleanup_loop` runs hourly and deletes rows where `created_at < now() - interval '<N> days'`.

Rationale: 60 days is long enough to catch drift across a typical model-swap or chunker-tweak cycle, short enough to limit privacy exposure. Shorter retention is fine (down to 30 days; below that, drift signals become statistically thin); longer retention should be paired with stricter redaction (see below) and a documented operational reason.

## Redaction

The application redacts these patterns from `query` text before insert:

| Pattern | Regex (illustrative) | Replacement |
|---|---|---|
| HuggingFace tokens | `\bhf_[A-Za-z0-9]{30,}\b` | `[REDACTED:HF_TOKEN]` |
| JWTs | `\beyJ[A-Za-z0-9_=-]{40,}\.[A-Za-z0-9_=-]{40,}\.[A-Za-z0-9_=-]{20,}\b` | `[REDACTED:JWT]` |
| Email addresses | `\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b` | `[REDACTED:EMAIL]` |
| Long opaque tokens (heuristic) | `\b[A-Za-z0-9_-]{40,}\b` (when not matching any other category) | `[REDACTED:KEY?]` |

The redactor is fail-open at the search-handler level: if a regex throws, the redaction step is skipped, the query goes into the table verbatim, and a `WARN` log line is emitted naming the failed pattern. Logging a query is best-effort and must never gate the user's search.

These patterns catch the common cases. Deployments that handle highly sensitive content (PII, medical, legal) should layer additional redaction on top or skip query logging entirely (set `query_log_retention_days = 0` to delete on the next cleanup cycle).

## Access

Two database roles are expected, provisioned by the deployer (e.g. via `deploy/azure/main.bicep`):

- `docforge_app` — the application's identity. **Read + write** on `query_log`. Used by the API to insert rows and by the cleanup loop to delete expired rows.
- `docforge_log_reader` — a separate role for analytics. **Read-only** on `query_log`. Granted to a small named group via Postgres role membership; that group is reviewed quarterly.

Direct queries against `query_log` outside these two roles are not authorised. Operators with break-glass access should use the role grants when answering an erasure request rather than connecting as a superuser.

## Right to erasure

When a user invokes their right to erasure (GDPR Article 17 or equivalent), an authorised operator runs:

```sql
DELETE FROM query_log WHERE user_oid = $1;
```

Where `$1` is the user's Entra `oid` (object ID, immutable). For rows from before migration `005_add_query_log_user_oid.sql` (where `user_oid` is `NULL`), fall back to `user_name`:

```sql
DELETE FROM query_log WHERE user_oid IS NULL AND user_name = $1;
```

Operational runbook:

1. Verify the requester's identity and authority to make the request.
2. Look up their Entra `oid` (`az ad user show --id <upn> --query id`).
3. Connect to the database with the `docforge_app` role (or higher).
4. `BEGIN; DELETE FROM query_log WHERE user_oid = $1; COMMIT;` — confirm rowcount.
5. If a pre-migration `user_name` deletion is also needed, run the second query.
6. Log the operation in the deletion register (operator-side ticket / change log).
7. Notify the requester with the rowcount deleted.

## Implementation status (as of v0.3)

| Item | Status |
|---|---|
| Retention configurable, hourly cleanup | ✓ Implemented (`docforge.api._query_log_cleanup_loop`) |
| Default retention 60 days | ✗ Default is 180 days; Phase 5 changes the default |
| Redaction at insert | ✗ Not yet; Phase 5 implements `query_log.log_query` redaction |
| `docforge_app` + `docforge_log_reader` roles | ~ Operator-provided; not enforced by docforge |
| Right-to-erasure SQL | ✓ Works today (manual SQL) |
| Right-to-erasure CLI command | ✗ Not yet; manual SQL is the supported path |

Items marked ✗ ship in v0.3 Phase 5. Until they land, the policy describes the deployer's commitment; the implementation hasn't fully met it. Operators deploying v0.3 between Phase 3 and Phase 5 should assume queries are stored verbatim with 180-day retention by default and adjust `query_log_retention_days` accordingly.

## Review cadence

Reviewed annually or on changes to:

- `Settings.query_log_retention_days` default
- the redaction pattern set
- the role grants in `deploy/azure/main.bicep` (or equivalent)
- the right-to-erasure runbook above

**Last reviewed:** 2026-04-26 (initial authoring alongside v0.3 Phase 3).
```

- [ ] **Step 2: Verify the file renders**

```bash
python -c "
import pathlib
content = pathlib.Path('docs/log-privacy.md').read_text(encoding='utf-8')
assert content.startswith('# docforge'), 'header missing'
assert 'right to erasure' in content.lower(), 'erasure section missing'
assert 'Implementation status' in content, 'status section missing'
print('OK')
"
```

Expected: prints `OK`.

- [ ] **Step 3: Run lint (only relevant if CI lints docs/, which it doesn't currently — sanity check)**

```bash
python -m ruff check src/docforge tests 2>&1 | tail -2
```

Expected: clean. Doc changes don't affect ruff scope, but verify nothing else regressed.

- [ ] **Step 4: Commit**

```bash
git add docs/log-privacy.md
git commit -m "$(cat <<'EOF'
docs: add query_log privacy & retention policy

Documents what query_log stores, how long, who reads it, what gets
redacted, and how to honour a right-to-erasure request. The policy is
the commitment; the implementation in src/docforge/ and the deployer's
config should match it.

Partially aspirational as of v0.3 Phase 3:
- redaction at insert lands in Phase 5
- default retention shortens 180→60 days in Phase 5
- right-to-erasure CLI command may follow Phase 5 (manual SQL works
  today)

The "Implementation status" section names exactly which lines of the
policy are real today and which are coming, so deployers don't read
the policy and assume more than what's implemented.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 3: CHANGELOG entry

**Files:**
- Modify: `CHANGELOG.md` — add bullets to the existing `[Unreleased]` section.

- [ ] **Step 1: Read the current `[Unreleased]` section in `CHANGELOG.md`**

Confirm it has `### Added` and `### Changed` subsections from earlier Phase 1 work. The Phase 3 entries append to the existing structure.

- [ ] **Step 2: Add the Phase 3 bullets**

Find the existing `### Added` block under `## [Unreleased]` and append two new bullets to it (do not replace existing bullets; do not reorder):

```markdown
- `docs/log-privacy.md` — privacy & retention policy for the `query_log` table. Documents purpose, retention, redaction patterns, access roles, and a right-to-erasure runbook. Partially aspirational as of Phase 3; the "Implementation status" section names which items ship later in v0.3.
```

Find the existing `### Changed` block under `## [Unreleased]` and append:

```markdown
- API and MCP search request boundaries are now hard-capped: `query` is rejected over 8000 characters, `limit` is rejected outside `[1, 50]`. **Behavior change:** clients that previously got 200 with `limit=10000` (and a slow response) now get HTTP 422 with a Pydantic-shaped error detail naming the offending field. Internal `Embedder.embed` raises `ValueError` when called with more than 256 texts in one batch.
```

- [ ] **Step 3: Verify the structure is intact**

```bash
python -c "
import pathlib
content = pathlib.Path('CHANGELOG.md').read_text(encoding='utf-8')
unreleased = content.split('## [Unreleased]')[1].split('## [0.2.1]')[0]
assert 'log-privacy.md' in unreleased, 'doc bullet missing'
assert 'hard-capped' in unreleased, 'caps bullet missing'
print('OK')
"
```

Expected: prints `OK`.

- [ ] **Step 4: Commit**

```bash
git add CHANGELOG.md
git commit -m "$(cat <<'EOF'
docs(changelog): add unreleased entries for v0.3 phase 3

Two user-facing changes from the Phase 3 PR:

- New docs/log-privacy.md policy doc — additive.
- Hard caps on API + MCP request boundaries — a behavior change for
  clients that previously sent oversized payloads. Fail with HTTP 422
  and a named-field detail, rather than degrading service.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Post-merge actions

None additional — the new constraints are enforced at the application layer, no infrastructure or branch-protection changes required. The next phase (Phase 4 — async + sidecar) builds on this foundation.
