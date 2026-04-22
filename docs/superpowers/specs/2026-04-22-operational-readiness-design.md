# Spec C4 — Operational Readiness

**Date:** 2026-04-22
**Status:** Approved, ready for writing-plans handoff.
**Part of:** Phase 4 Spec C (hardening sprint) — sub-spec 4 of 4 (final). Siblings: C1 (CI + supply-chain, shipped), C2 (quality harnesses, shipped), C3 (security + privacy, shipped).
**Scope:** Six operational-readiness deliverables (C4.1 – C4.6) that close the Operational, Scale, and Sustainability gaps identified in Spec D §4. After C4 merges on both repos, the 14-day soak clock starts for the Spec D presentation artifact.
**Driven by:** Spec D §4 items **C4.1 – C4.6**.

## Context

Three C sub-specs have landed:

- **C1** — GitHub Actions CI (lint + test + coverage ≥60%) + Dependabot + ADO validation pipeline for sources.yml.
- **C2** — quality harnesses: `docforge lint-docs` + `eval_search.py` + DocuWare ground truth + baseline (recall@1 40%, recall@5 76%, MRR 0.533).
- **C3** — Entra ID authentication on `/search` + `/sources` (delegated user flow); `query_log.user_oid`; threat model; log-privacy doc; 180-day retention via FastAPI-lifespan cleanup loop.

Remaining to defend L3 "Hardened at single site" per Spec D: **incident runbook, request-timing instrumentation, load-profile documentation, CONTRIBUTING.md, Postgres backup verification, and — revised from the original spec — an orphan-purge capability on `docforge ingest`**.

**Revision during brainstorm (2026-04-22):** the original C4.2 ("fix 1/72 flaky ingest source") is **obsolete**. A fresh `docforge ingest` run against the live deployment reports **72/72 succeeded, 0 failures**. The failing source from earlier context was removed or fixed historically. However, the ingest run surfaced a **real operational issue**: 140 rows in the `sources` table vs 72 current entries in `sources.yml` — ingest never garbage-collects when sources are removed. Roughly half the index is stale, which affects `/search` relevance. C4.2 is re-scoped to an orphan-purge capability.

## Goals

1. Close the Operational, Scale, and Sustainability gaps identified in Spec D §4 at the L3 target.
2. Produce measured P95/P99 latency + query-volume evidence for the Spec D artifact's Scale dimension (currently only "chunk count known").
3. Keep the production index clean so `/search` relevance reflects current content, not historical noise.
4. After C4 merges on both repos, the 14-day soak clock starts — no further code changes required to defend L3.

## Non-goals

- Per-source ACLs (out of scope per Spec C3 trust model).
- Azure Files mount for the embedding-model cache. Spec D lists this as an optional C4 item; rejected here — `minReplicas: 1` means the warm-up cost happens only at deployment events (rare; acceptable at current scale).
- Structured logging / OpenTelemetry / APM instrumentation beyond `request_ms` in `query_log`.
- Horizontal scaling / load testing beyond what real CCL traffic produces.
- Automating the PITR dry-run in CI (one-time verification is sufficient for L3).

## Out of scope (tracked for Spec D artifact or future specs)

- Second-maintainer onboarding (Sustainability bus-factor-1 — unreachable by effort; named in the Spec D risk register).
- Azure Monitor alerts / paging runbook integration (Phase 5 concern once there is an on-call rotation).
- Multi-region / geo-replication (not needed at L3).

## Design principles

- **Prose docs take concrete numbers from code.** The runbook's PITR section cites real `az` commands from C4.6's dry-run; the load-profile cites real P50/P95/P99 from C4.3's latency report. No placeholder numbers.
- **Additive migrations only.** Migration 006 adds `request_ms TEXT NULL` alongside the existing `user_oid` column. Pre-migration rows keep NULL. No history destruction. Same pattern as C3.5.
- **Destructive ops require explicit confirmation.** The orphan-purge defaults to dry-run; `--confirm` required to mutate. A misconfigured ingest should produce a report, not delete data.
- **Maintain engine / consumer split.** Generic deliverables in docforge (migration, middleware, CLI flag, CONTRIBUTING); consumer-specific runbook + load-profile live in knowledge-hub.

## Per-deliverable design

### C4.1 — `knowledge-hub/rag/docs/runbook.md`

~3–4 pages rendered. Incident-response playbook for the CCL deployment at `docforge-search-api.ashyhill-c79f3b95.westeurope.azurecontainerapps.io`.

**Outline (sub-sections; prose written in plan/execution, not spec):**

1. **Purpose + audience** (~⅛ page). Reader: on-call engineer (currently = maintainer). Assumes Azure subscription access + DB admin creds in Key Vault. Not a general ops guide.

2. **How to reach the system** (~¼ page). Container App name + resource group. Postgres hostname. Key Vault name. Links to the Azure portal resource blades.

3. **Container App failure modes** (~¾ page) — each sub-section: symptom → diagnosis → fix.
   - Liveness/startup probe failing (model-load timeout, 503s)
   - Image-pull failure (ACR auth, new image not tagged)
   - Key Vault secret-sync failure (managed-identity RBAC)
   - Revision-rollout stuck (two revisions active, traffic split)
   - Entra `openid_config.load_config` failure at startup (tenant unreachable)
   - Entra 401 on valid-looking token (v1-vs-v2 format; admin-consent missing)

4. **Database failure modes** (~½ page).
   - Connection refused / timeout (firewall IP drift, SKU auto-stop)
   - Point-in-time restore procedure — step-by-step produced during C4.6's dry-run
   - `query_log` cleanup loop silent failure (diagnostic: tail container logs for `query_log cleanup:` lines)

5. **Ingest failure modes** (~½ page).
   - HF token expired
   - Confluence rate-limited (429) or token expired (401)
   - Parse failures (specific source — if any surface, document here)
   - Orphan accumulation — pointer to `docforge ingest --purge-orphans` from C4.2

6. **Auth failure modes** (~¼ page). Pointer to C3's `threat-model.md` for the full picture; runbook covers the "user sees 401 repeatedly" decision tree.

7. **Historical / resolved items** (~⅛ page). "1/72 ingest failure — no longer reproduces as of 2026-04-22; leaving the entry for context."

**Top-of-doc stamp:** `Last verified: <YYYY-MM-DD>` bumped whenever C4.6-style verification happens. Risk R5 — no ongoing enforcement.

### C4.2 — `docforge ingest --purge-orphans`

**(Revised from "fix 1/72 failure" — no failures reproduce today; real issue is 140-rows-vs-72 orphan accumulation.)**

**Code shape:**

- `docforge/cli.py` — existing `ingest` command gains two flags:
  - `--purge-orphans` (bool, default `False`) — enables the reconciliation step
  - `--confirm` (bool, default `False`) — required alongside `--purge-orphans` to actually delete
- `docforge/ingest.py` — new `_purge_orphans(pool, current_identifiers: set[str], confirm: bool) -> tuple[int, int]` function returning `(sources_to_delete, chunks_to_delete)`. If `confirm=False`, logs the would-be-deletes and returns counts without mutating. Called from `ingest_all` when the flag is set.
- Identifier matching: Confluence sources use the `page_id` string; git sources use the relative file path (OS-normalized). Identifier stability is the safety invariant — mismatches cause over-deletion.

**Behavior:**

| Flags | Effect |
|---|---|
| (none) | Normal ingest; orphans untouched. |
| `--purge-orphans` | Dry-run reconciliation after ingest; logs `Would delete N orphan sources (M chunks). Pass --confirm to execute.` and exits clean. |
| `--purge-orphans --confirm` | Deletes orphans. Logs `Purged N orphan sources (M chunks).` |

**Tests** (`tests/unit/test_ingest.py`):

- `test_purge_orphans_dry_run_does_not_delete` — populated DB + flag without confirm → counts reported, DB unchanged.
- `test_purge_orphans_with_confirm_deletes` — populated DB + both flags → orphans gone, current sources untouched.
- `test_purge_orphans_current_sources_untouched` — explicit check that a source present in both DB and sources.yml survives.

Uses the existing `testcontainers` pattern (from `tests/integration/`). No CLI-level test (covered by existing `test_cli.py` pattern).

**Sizing:** ~50 LoC + ~80 LoC tests.

### C4.3 — Request-timing middleware

**Code shape:**

- `docforge/sql/migrations/006_add_query_log_request_ms.sql`:
  ```sql
  ALTER TABLE query_log ADD COLUMN IF NOT EXISTS request_ms INT;
  ```
  Additive. Pre-migration rows keep NULL.

- `docforge/api.py`:
  - Middleware `_timing_middleware(request, call_next)` wraps `call_next`, measures wall-clock via `time.perf_counter()`, stashes duration (ms) in `request.state.request_ms`.
  - Applied to `/search` + `/sources` only. `/health` has no DB access; measurement would be noise.
  - `/search` handler reads `request.state.request_ms` at return time and passes to `log_query(..., request_ms=...)`. Same pattern as `user_oid` from C3.5.

- `docforge/query_log.py`:
  ```python
  async def log_query(
      pool, user_name, team_name, area_name, query, result_count,
      user_oid: str | None = None,
      request_ms: int | None = None,
  ) -> None:
      ...
      INSERT INTO query_log (..., user_oid, request_ms)
      VALUES (..., $7, $8)
  ```

- `docforge/scripts/latency_report.py` — new standalone script (~80 LoC):
  ```
  python -m docforge.scripts.latency_report --since '7 days'
  ```
  Connects via admin connection string from env; runs SQL:
  ```sql
  SELECT
      percentile_cont(0.50) WITHIN GROUP (ORDER BY request_ms) AS p50,
      percentile_cont(0.95) WITHIN GROUP (ORDER BY request_ms) AS p95,
      percentile_cont(0.99) WITHIN GROUP (ORDER BY request_ms) AS p99,
      count(*)                                                  AS n
  FROM query_log
  WHERE request_ms IS NOT NULL
    AND created_at > now() - $1::interval
  ```
  Prints P50/P95/P99 + row count + cutover date (when `request_ms` went live).

**Cold-start filtering:** none. Per Spec D revision, `minReplicas: 1` means no runtime cold starts. Post-deployment warm-up queries (first 1–2 after each revision) include the 15–30s model-load cost and are kept in the data as honest signal. Load-profile doc (C4.4) must call this out so P95 isn't misread as steady-state.

**Tests:**

- `tests/unit/test_query_log.py` — 2 tests for `request_ms` kwarg, mirror of the `user_oid` tests (default None + accepts value).
- `tests/unit/test_api.py` — 1 test that exercises the middleware (ASGITransport with a custom endpoint that asserts `request.state.request_ms` is set after `call_next`).
- `tests/unit/test_latency_report.py` — pure-function unit tests for the summarize/format helpers (mirrors `test_eval_search.py` shape).

**Sizing:** ~100 LoC + migration + report + ~80 LoC tests.

### C4.4 — `knowledge-hub/rag/docs/load-profile.md`

~1–2 pages. Written **after** C4.3 has been in production long enough to have measurable data (ideally several days — flag during plan).

**Outline:**

1. **Volumes** — 44 Confluence pages + 28 git-repo sources at time of writing; ~1,770 chunks in `chunks` table; embedding dimension 768.
2. **Query volume** — queries/day from `query_log` counts + per-team breakdown. Populated at write time from a SQL query cited in the doc.
3. **Latency** — P50/P95/P99 numbers from C4.3's `latency_report.py` output. Populated at write time.
4. **Post-deployment warm-up window** — ~15–30s model-load after each new revision; first few queries may take that long. Reference: `team-setup-azure.md` troubleshooting entry. **Must be explicit** so P95 isn't misinterpreted.
5. **HNSW parameter rationale** — pgvector defaults (`m=16, ef_construction=64`); justified for current chunk count with a short link to pgvector tuning docs. Note when to re-evaluate (>10× chunk growth).

Every number cited references the query or tool that produced it — re-generatable by anyone with DB access.

### C4.5 — `docforge/CONTRIBUTING.md`

~1 page. Sections:

1. **Quickstart** — clone, `.venv`, `pip install -e ".[dev,entra]"`, run tests. Pointer to `CLAUDE.md` for architectural context.
2. **PR requirements** — CI must pass (lint + test); coverage ≥60% gate; migration files numbered sequentially and named `NNN_description.sql`; schema changes to `query_log` require updating `knowledge-hub/rag/docs/log-privacy.md`.
3. **Branch flow** — branch-per-PR against master; direct-push disallowed by branch protection.
4. **Code style** — ruff format + check in CI; pyright/mypy deliberately not in CI at this size (documented rationale: signal-over-ritual, solo-maintainer scale).
5. **Optional extras** — `[entra]` extra for Entra-auth deployments; pointer to `deploy/azure/bootstrap-entra.sh` for initial app-registration setup.
6. **Where to ask questions** — repo issues; maintainer contact.

### C4.6 — Postgres PITR dry-run verification

**Not a code deliverable** — an operational task that produces a short runbook section.

**Procedure:**

1. In `docforge-test` resource group, create a throwaway target server named `docforge-pg-pitr-test` via `az postgres flexible-server restore`.
2. Point it at a timestamp ~30 minutes in the past on the source `docforge-pg` server.
3. Wait for restore completion (~10–15 min on B1ms).
4. Connect via `psql` with the same admin creds (secret lives on the new server too).
5. Run `SELECT count(*) FROM sources; SELECT count(*) FROM chunks; SELECT max(created_at) FROM query_log;` — confirm counts are consistent with the chosen timestamp.
6. Delete the throwaway server immediately.

**Output:** a subsection in C4.1's runbook titled **"Point-in-time restore (verified YYYY-MM-DD)"** containing the exact `az` commands used, time-to-restore, and expected cost (~few dollars for the hour-long throwaway).

**Success criterion:** the dry-run completes end-to-end; the runbook entry is populated with real commands and numbers (no placeholders).

## File summary

| Path | Status | Purpose | Approx LoC / length |
|---|---|---|---|
| `docforge/docforge/cli.py` | MODIFY | `--purge-orphans` + `--confirm` flags on `ingest` | +~15 |
| `docforge/docforge/ingest.py` | MODIFY | `_purge_orphans(pool, current_identifiers, confirm)` | +~40 |
| `docforge/docforge/api.py` | MODIFY | `_timing_middleware`; pass `request_ms` to `log_query` | +~25 |
| `docforge/docforge/query_log.py` | MODIFY | Accept optional `request_ms` kwarg | +~5 |
| `docforge/docforge/sql/migrations/006_add_query_log_request_ms.sql` | NEW | Additive migration | ~2 |
| `docforge/docforge/scripts/latency_report.py` | NEW | P50/P95/P99 rollup over `query_log.request_ms` | ~80 |
| `docforge/tests/unit/test_ingest.py` | MODIFY | 3 purge-orphan tests (testcontainers) | +~80 |
| `docforge/tests/unit/test_query_log.py` | MODIFY | 2 `request_ms` tests | +~20 |
| `docforge/tests/unit/test_api.py` | MODIFY | 1 middleware test | +~30 |
| `docforge/tests/unit/test_latency_report.py` | NEW | Pure-function unit tests | +~40 |
| `docforge/CONTRIBUTING.md` | NEW | Per §C4.5 outline | ~1 page |
| `knowledge-hub/rag/docs/runbook.md` | NEW | Per §C4.1 outline | ~3–4 pages |
| `knowledge-hub/rag/docs/load-profile.md` | NEW | Per §C4.4 outline | ~1–2 pages |

**Totals:** 6 new + 7 modifications across both repos; ~500 LoC + ~7 pages of docs.

## Success criteria

- [ ] `docforge ingest --purge-orphans` without `--confirm` prints the list of would-be-deleted orphans and exits without mutating.
- [ ] `docforge ingest --purge-orphans --confirm` deletes orphans; subsequent `SELECT count(*) FROM sources` matches the number of current-sources-yml entries processed this run.
- [ ] `query_log.request_ms` exists; populated non-NULL on post-migration `/search` calls; pre-migration rows have NULL.
- [ ] `python -m docforge.scripts.latency_report` prints P50/P95/P99 over recent `query_log` rows (run once manually against live DB as end-to-end validation).
- [ ] `knowledge-hub/rag/docs/runbook.md` committed per outline; all failure-mode sub-sections have concrete symptom/diagnosis/fix text (no TBDs); top-of-doc `Last verified:` stamp present.
- [ ] `knowledge-hub/rag/docs/load-profile.md` committed with real numbers from C4.3's latency report + a current-volume snapshot from the DB.
- [ ] `docforge/CONTRIBUTING.md` committed per outline.
- [ ] PITR dry-run executed against a throwaway Postgres server; restore succeeded; step-by-step `az` commands + timing recorded in the runbook's PITR section; throwaway server deleted.
- [ ] All new unit tests pass; coverage gate ≥60% preserved (projected ~75–78%).
- [ ] CI green on both repos.
- [ ] Eval harness reproduces the C2 baseline (recall@1 40%, recall@5 76%, MRR 0.533) — confirms the middleware + purge didn't regress retrieval.

## Risks

- **R1 — Purge deletes more than intended.** An identifier mismatch (e.g., path-separator change) could mark live sources as orphans. Mitigation: `--confirm` required; dry-run default; identifier stability (Confluence page_id is a GUID; git file path is stable on a given OS).
- **R2 — Timing middleware adds latency.** `time.perf_counter()` on both sides of `call_next` plus an int column write is single-microsecond overhead. Not a real concern at our scale; flag if later measurements show otherwise.
- **R3 — Latency P95 is dominated by post-deployment warm-ups.** Per Spec D revision, warm-ups are kept in the data as honest signal. The load-profile doc must call this out so the P95 number isn't misread as steady-state.
- **R4 — PITR dry-run incurs cost.** Throwaway B1ms + storage for an hour ≈ $1–3. Negligible but named. Mitigation: delete the target server immediately after verification.
- **R5 — Runbook drifts from reality.** Runbooks atrophy. Mitigation: `Last verified: YYYY-MM-DD` stamp at the top, bumped whenever C4.6-style verification happens. No ongoing enforcement.
- **R6 — `CONTRIBUTING.md` says "pyright not in CI by design" — future contributors may disagree.** Mitigation: document the rationale (signal-over-ritual, solo-maintainer scale). Revisit if team grows.

## Dependencies and ordering

- **C4.2** (purge flag) is independent of C3 and everything else.
- **C4.3** (timing middleware) depends on migration 006 being run in prod before its feature lands; plan-level concern.
- **C4.4** (load profile) depends on C4.3 being in production long enough to have measurable data (ideally several days).
- **C4.6** (PITR dry-run) depends on C4.1 (runbook file exists) to have a place to document the procedure.

**Suggested execution order:** C4.2 → C4.5 → C4.3 → C4.6 → C4.1 → C4.4.

Rationale: purge first (small, independent); CONTRIBUTING while thinking; middleware next so data starts accumulating; PITR drill; then the runbook that gets populated from all the above; load profile last once enough latency data exists.

## Follow-up items (tracked, not in C4)

- **Structured logging / OpenTelemetry / APM.** Out of scope at L3. Candidate for L4 if multi-team adoption happens.
- **Azure Monitor alerts / pager integration.** Out of scope — no on-call rotation today. Runbook is the substitute.
- **Second maintainer.** Bus-factor-1 — unreachable by effort. Named plainly in Spec D's Sustainability row and risk register.
- **Automated PITR drills on schedule.** Future concern if DR requirements tighten.

## What this unlocks

After C4 merges on both repos, the **14-day soak clock starts** (per Spec D success criterion). No further code changes are required to defend L3. Once the soak completes, Spec D artifact writing can begin — the final Phase 4 deliverable.
