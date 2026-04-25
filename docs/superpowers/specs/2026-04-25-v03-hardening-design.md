# docforge v0.3 hardening — design

**Status:** Approved 2026-04-25
**Author:** Tobias Ens
**Scope:** Cross-phase design for the v0.3 release. Each phase will get its own
implementation plan via the writing-plans workflow.

## Goal & framing

Remediate the eight findings from the v0.2.1 critical review. Calibrated for
the operating profile of one large internal deployment — roughly 30 engineering
teams, 500 engineers, and AI-assistant-driven query traffic — while preserving
externally-adoptable OSS posture as a hard constraint. The shape of v0.3 is
*"harden the v0.2.1 architecture into something that scales to a single-company
internal SaaS"*. Multi-tenant isolation, per-document ACLs, hybrid retrieval,
and chunk overlap are explicitly deferred to v0.4+.

The eight findings, recalibrated for the operating profile:

| # | Finding | v0.2.1 severity | At 30 teams / 500 eng |
|---|---|---|---|
| 1 | Sync embedder blocks async event loop | High | Critical |
| 2 | Test depth misleading (mocks-of-mocks, integration gated out, eval is measurement-only) | High | High |
| 3 | Engineer-facing onboarding doc absent | Low | High |
| 4 | Boundary validation (`limit`, query length, batch) absent | Medium | Medium |
| 5 | `query_log` retains raw query text without redaction | Medium | Medium-High |
| 6 | README does not link to threat model | Low | Low |
| 7 | Loose dependency pins (`>=` floors only) | Low | Low-Medium |
| 8 | Hardcoded operational knobs (pool size, dimension, fallback) | Low | Medium-High (pool) |

## Constraints

- **Single-maintainer cadence.** Phases must be small enough to land
  independently, with each phase shippable as a minor or patch release.
- **Backwards-compatible config within 0.x.** No env-variable renames or
  schema-breaking changes mid-cycle. v0.3 is the version that opts into
  anything that would break a v0.2.x deployer.
- **CI time budget.** Total CI under 5 minutes for the unit job and under 10
  minutes for unit + integration. No 30-minute matrix runs.
- **External adopter parity.** Anything we test internally has to work for
  `pip install docforge-cli` on a fresh machine. No internal-deployment-only
  assumptions in tests, defaults, or example configs.

## Phases

The phases are sequenced. Within a phase, items are parallel-safe.

### Phase 1 — Quick wins (no architectural risk)

Land first so the rest of the work has the right foundation.

- **README → threat-model link** (Finding 6). One-line edit at the bottom of
  "When docforge is the wrong choice" pointing at `docs/threat-model.md`.
- **Dependency upper bounds** (Finding 7). Add a ceiling at the next major
  version for each runtime dependency in `pyproject.toml` (e.g., `fastapi>=0.115,<1.0`,
  `pydantic>=2.9,<3.0`). Add a "License compatibility" note to the README
  naming the Gemma license restrictions.
- **Embedder dimension guard** (Finding 8 partial). Assert that the loaded
  model's `get_sentence_embedding_dimension()` matches `self.dimensions` in
  `Embedder.__init__`. Raise `RuntimeError` with a clear message on mismatch.
- **Capture pre-refactor eval baseline** (Finding 2 free pre-step,
  deployer-side). Run `eval_search.py` against current production with the
  deployer-specific ground-truth set; save the report alongside the
  ground-truth file in the deployer's own state (not the public repo). This
  is a deployer-side reference for the maintainer's own use across the v0.3
  refactor — it answers "did this change degrade retrieval against my
  actual corpus." Phase 5's CI gate is a different artefact (a synthetic
  in-repo fixture); see Phase 5.

Risk: trivial. All four items can land in one PR.

### Phase 2 — Test-depth bedrock

Must precede Phase 4. The Phase-4 refactor will touch `db.py`, `embedder.py`,
the API lifecycle, and the cleanup loop. We need a real safety net first.

- **Integration tests in CI** (Finding 2A). Add a Postgres service (with
  pgvector extension) to the workflow. Either drop the `-m "not integration"`
  filter from the existing test job, or split into two jobs — `unit-fast` and
  `integration-postgres` — so the unit job stays at ~30 s.
- **Real-model embedder smoke test** (Finding 2C). Use
  `sentence-transformers/all-MiniLM-L6-v2` (384-d, ungated) for CI. Two
  assertions: `dim == self.dimensions` and `embed("a") != embed("b")`. Catches
  dim-drift and degenerate-embedding bugs without HuggingFace gating in CI.
- *(Optional, same phase)*: add `mypy --strict` and `bandit` as their own CI
  jobs. Cheap signal; not a blocker.

Risk: moderate. Integration tests need testcontainers in CI on Linux; the suite
already passes locally so this is mainly workflow plumbing.

### Phase 3 — Boundary safety

Independent of Phase 2 and 4; can land in parallel with either.

- **Hard caps on API + MCP** (Finding 4). Pydantic `Field` constraints on
  `SearchRequest` (`limit: int = Field(5, le=50)`,
  `query: str = Field(..., max_length=8000)`) and matching constraints on the
  MCP tool signature. HTTP 422 with named-field error messages
  (`"limit (got 5000) exceeds maximum (50)"`). Embedder batch input bounded
  inside the embedder (≤ 256 by default; configurable).
- **`docs/log-privacy.md` policy doc** (Finding 5 part 1). One page covering:
  *purpose* (retrieval drift signals), *retention* (60 days, configurable),
  *redaction patterns* (HF-token shapes, JWTs, email addresses, common
  API-key shapes), *access* (named DB role with read-only grant on
  `query_log`), *right-to-erasure runbook*
  (`DELETE FROM query_log WHERE user_oid = $1`).

Risk: low. The hard caps are 5–10 lines of code; the doc is purely additive.

### Phase 4 — Async correctness + embedding sidecar

The structural change. Gated on Phase 2 landing.

- **Stateless API replicas.** Replace module globals (`_pool`, `_embedder`,
  `_settings`, `_azure_scheme`, `_cleanup_task`) with a FastAPI `lifespan`
  context that creates resources, plus `Depends`-injected access at the
  handler level. No model loaded in the API process.
- **Dedicated embedding service.** New small FastAPI process that loads the
  model once and accepts embed requests. Default transport: HTTP on localhost
  (works in both Container Apps and bare-metal deploys). Unix-socket transport
  is a follow-up optimisation, not v0.3 scope. Sidecar uses
  `asyncio.to_thread` around `model.encode` for thread-level parallelism on
  inference.
- **Cleanup loop out of per-worker.** Either (a) a Postgres-side scheduled job
  if `pg_cron` is available, or (b) advisory-lock guarded so only one
  replica's loop runs at a time. The latter is cheaper and chosen by default.
- **Pool config knobs** (Finding 8 rest). `pool_min_size`, `pool_max_size` as
  `Settings` fields. Defaults 5 / 25.
- **Bicep changes** for the new sidecar component in
  `deploy/azure/main.bicep` — second Container App, internal-only ingress,
  the API replicas reference it via env var.
- **Feature-flag fallback.** A v0.3 deployment can re-enable the v0.2.x
  in-process embedder if the sidecar misbehaves under real load. Removed in
  v0.4.

Risk: highest of the work. Adds an operational component; cleanup-loop
relocation has subtle correctness corners; pool resizing changes the
connection profile against Postgres. Mitigations: feature flag + the
integration-test net from Phase 2 + a canary deploy on the live infra before
flipping defaults.

### Phase 5 — Quality gates + engineer enablement

Builds on the cleaner architecture and the captured baseline.

- **Eval-harness baseline gate** (Finding 2B). Ship a *synthetic*
  ground-truth set (`eval/synthetic-ground-truth.yml`) with docforge — a
  small fixture of fictional documents and paired natural-language queries
  that exercises the chunker, embedder, and ranking SQL end-to-end. Run the
  eval against this fixture in CI and snapshot the result into
  `eval/baseline.json` in the repo. `eval_search.py --check-baseline` exits
  non-zero if recall@5 against the fixture drops more than X% (X
  configurable, default 5%). Wired as a scheduled GitHub Action — nightly.
  Distinct from Phase 1's deployer-side baseline: this gate catches *code*
  regressions (algorithm, chunker, or ranking changes) against a known-good
  fixture, while the Phase 1 reference catches *deployer-side* retrieval
  drift against real content.
- **`query_log` redaction implementation** (Finding 5 part 2). Pre-INSERT
  scrubbing in `log_query` using compiled regex patterns from the Phase-3
  policy doc. Retention default shortened to 60 days. Migration to update
  existing config defaults.
- **"Connect your AI assistant" page** (Finding 3). New documentation in
  repo `docs/` and the microsite. Sections per assistant — Claude Code,
  Cursor, Copilot, generic-MCP — covering both the centralized-config recipe
  (for the rollout team) and the self-service snippet (for the long-tail
  engineer). The `mcp_client.py` template hardened to be a starting point an
  engineer can drop into their config without surgery.

Risk: low. Mostly additive content; one DB write-path change with the policy
doc as its specification.

## Dependencies

```
Phase 1 ───┬─────────────────────────────────────► Phase 5
           │
           ├─► Phase 2 ──► Phase 4 ───────────────► Phase 5
           │
           └─► Phase 3 ───────────────────────────► Phase 5
```

- Phase 1 has no dependencies; lands first.
- Phase 2 must precede Phase 4.
- Phase 3 is independent of Phase 2 and 4; can land any time after Phase 1.
- Phase 5 depends on Phase 1's baseline file and reads cleaner against
  Phase 4's architecture, but doesn't strictly require Phase 4.

## Out of scope (deferred to v0.4+)

Acknowledging up front so the design is not asked to grow:

- Per-document ACLs (would change the threat model)
- Hybrid retrieval (BM25 + dense fusion)
- Chunk overlap
- MCP identity via session (so `user_name` / `team_name` come off the
  per-call signature)
- Multi-tenant isolation (separate threat model entirely)
- Multilingual eval coverage

## Success criteria

- Unit and integration tests gate every PR; coverage trending up from the
  v0.2.1 baseline (73.79%).
- Eval-harness regression gate is live and has flagged at least one synthetic
  regression in pre-prod testing.
- Boundary 422s are emitted for known buggy patterns; metrics show clamping
  events without operator intervention.
- Embedding service sustains 30 req/s **average** and 60 req/s **burst (5 s
  window)** on one CPU worker without P95 latency exceeding 500 ms; API
  replicas can scale independently of embedding capacity.
- Externally-installed `pip install docforge-cli==0.3.0` works against a
  fresh Postgres on Python 3.12 and 3.13 with no dependency conflicts.
- One adopter outside the maintainer's organization successfully deploys
  docforge against their own Confluence + git corpus, runs a search, gets
  non-zero results that look correct to them, and reports the experience
  publicly (GitHub Issue / Discussion / blog post) — following only the
  docs, with no maintainer-DM hand-holding.

## Implementation plans

Each phase will receive its own implementation plan under
`docs/superpowers/plans/YYYY-MM-DD-v03-phase-N-<topic>.md`, generated via the
writing-plans workflow. Plans land sequentially; each carries its own review
checkpoints, test gates, and acceptance criteria.

| Phase | Implementation plan |
|---|---|
| Phase 1 — quick wins | *(to be drafted next)* |
| Phase 2 — test-depth bedrock | *(after Phase 1)* |
| Phase 3 — boundary safety | *(parallel-safe with Phase 2)* |
| Phase 4 — async + sidecar | *(after Phase 2)* |
| Phase 5 — quality gates + enablement | *(after Phase 1; reads cleaner after Phase 4)* |
