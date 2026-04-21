# Spec D — Maturity Assessment (presentation artifact)

**Date:** 2026-04-21
**Status:** Approved, ready for writing-plans handoff for C3 and C4. The Spec D artifact itself is written after C3 + C4 merge + 2-week soak; this spec defines what that artifact must contain and derives the C3/C4 work it requires.
**Part of:** Phase 4, sub-spec D of four. Siblings: A (team tagging, shipped), B (authoring guideline, shipped), C1 (CI + supply-chain, shipped), C2 (quality harnesses, shipped), **C3 (security + privacy, derived below)**, **C4 (operational readiness, derived below)**.
**Scope:** Design the `knowledge-hub/rag/docs/readiness-assessment-<YYYY-MM-DD>.md` artifact that will be presented to the DocuWare architecture group, and derive the C3 + C4 deliverables required to defend the artifact's claims.
**Supersedes:** `2026-04-17-maturity-assessment-design.md` (retained as early thinking; do not implement from it).

## Context

docforge ships a generic documentation-indexing engine (CLI + MCP + FastAPI + pgvector) with a DocuWare-specific consumer (`knowledge-hub/rag`) deployed on Azure Container Apps. Phase 4 has already landed:

- **Spec A** — team tagging, MCP `user`/`team`/`area` parameters, relevance boosting.
- **Spec B** — authoring guideline (generic) + DocuWare addendum; cloudstatus exemplar.
- **Spec C1** — GitHub Actions CI (lint + test + coverage ≥60%) + Dependabot + ADO validation pipeline for `sources.yml`.
- **Spec C2** — quality harnesses: `docforge lint-docs` CLI subcommand + `eval_search.py` runner + DocuWare ground truth + baseline.

This spec closes the remaining Phase 4 loop by working backwards from the presentation artifact: the artifact's L3 claims determine C3 + C4 scope, not the other way round. That framing avoids hardening for its own sake and ensures C3 + C4 only ship what the artifact must defend.

## Goals

1. Specify the presentation artifact's outline, tone, length, writing rules, and the evidence it must cite.
2. Define L3 criteria across 8 dimensions; map each criterion to concrete evidence that either exists today or is assigned to C3 or C4.
3. Produce a derived C3 + C4 work-item list that, once complete, makes the presentation artifact a fill-in-the-blanks exercise.
4. Name plainly what is unreachable by engineering effort so the artifact earns credibility by not overclaiming.

Non-goals:

- Write the presentation artifact. (Deferred until C3 + C4 land + 2-week soak.)
- Brainstorm C3 or C4 internal structure or execution order. Each gets its own brainstorm and plan; this spec only defines *what* they deliver.
- Propose decisions (adoption, sanction, funding). Per Q3 answer A: info-sharing posture only.

## Design principles

- **Target L3 "Hardened at single site", honestly.** The system is genuinely one-tenant. Defending L3 with proof beats overreaching to L4 and getting picked apart.
- **Engineering effort closes what it can; calendar + people close the rest.** Gaps closeable by effort go into C3/C4. Gaps that need a second engineer (bus factor) or more production time (soak evidence) go into the artifact's "L4 requirements" section and the risk register.
- **Evidence outranks adjectives.** The artifact cites artifacts, counts, and metrics. Banned words unless immediately followed by a number: robust, scalable, secure, production-ready.
- **Generic engine vs DocuWare consumer.** Security/privacy decisions that are DocuWare-specific (Entra tenant, log-privacy policy) live in `knowledge-hub/rag/docs/`. Tool-generic decisions (threat model, CONTRIBUTING) live in `docforge/docs/`. Every C3/C4 deliverable names its home repo.

## The readiness framework

### 5-level scale

| Level | Name | Meaning |
|---|---|---|
| L1 | Experimental | Proof of concept; unproven |
| L2 | Validated at single site | One production deployment, one team, limited usage |
| L3 | Hardened at single site | Production-hardened (tests, CI, security pass, runbook, eval baseline); still one tenant |
| L4 | Multi-site validated | ≥2 teams actively using the shared deployment; cross-team ranking + tagging validated |
| L5 | Org-standard | Blessed pattern, platform-owned, SLA-backed |

### 8 dimensions

1. **Functional readiness** — does it do what it claims?
2. **Search Quality** — is retrieval demonstrably useful, with regression detection?
3. **Quality** — tests, lint/format, CI posture, automated dep updates
4. **Operational** — deployment maturity, healthchecks, runbook, incident paths, backup/restore
5. **Security** — authentication, secrets, trust model, threat model, dependency scanning
6. **Scale** — measured load characteristics for one team's volume, performance bounds
7. **Adoption** — authoring guideline, team-setup docs, time-to-first-value, measurable usage
8. **Sustainability** — maintainer footprint, CONTRIBUTING, license, repo hosting

Dimensions 1–3 cover the tool; 4–6 cover how it runs; 7–8 cover how it survives.

## Per-dimension L3 criteria + evidence state

Legend: ✓ exists today · ⚠ partial · ✗ missing (routed to C3/C4/admin)

### 1. Functional — L3 ✓

**Criterion:** CLI + MCP + API expose documented capabilities end-to-end; deployed on managed infra; ingest → search validated against real pgvector.

**Evidence:** `docforge/cli.py`, `mcp_server.py`, `api.py` functional; 133 tests pass; live deployment at `docforge-search-api.<id>.westeurope.azurecontainerapps.io` indexes 137 sources / 1,772 chunks.

### 2. Search Quality — L3 ✓

**Criterion:** Eval harness + ground-truth set (≥20 queries) + recorded baseline + documented re-run + re-baseline protocol.

**Evidence:** `docforge/scripts/eval_search.py` (C2); `knowledge-hub/rag/eval/ground_truth.yml` (25 entries); `baseline.md` (recall@1 40%, recall@5 76%, MRR 0.533); `rag/eval/README.md` operator doc.

**Artifact-writing rule:** the search-quality narrative must frame recall@N in context of (a) ground-truth authoring style dominating absolute magnitude (natural colleague phrasing vs title-matching), (b) the MCP client feeding top-N to the LLM — top-1 is not the user-facing metric. Without this framing the "40%" number invites misinterpretation.

### 3. Quality — L3 ✓

**Criterion:** ≥60% test coverage gated in CI; ruff format + check in CI; automated dependency updates.

**Evidence:** `.github/workflows/ci.yml` runs ruff + pytest on PR and push-to-master (branch protection enforces both); coverage 77%; `.github/dependabot.yml` (pip + github-actions, weekly).

**Out of L3 scope:** type-checking in CI. Explicitly rejected during C1 brainstorm as over-engineering for the project's size; artifact does not claim it.

### 4. Operational — L3 ⚠ → C4

**Criterion:** Managed infra via IaC; healthchecks/probes; incident runbook; known failure modes documented; backup/restore verified.

**Evidence exists:** Azure Container App + Bicep IaC (`docforge/deploy/azure/main.bicep`); Dockerfile HEALTHCHECK; startup probe (10s init × 10s × 60 failures = 10-min window); cold-start behavior documented in `knowledge-hub/rag/docs/deployment.md`.

**Gaps → C4:**

- **C4.1** Incident runbook at `knowledge-hub/rag/docs/runbook.md`
- **C4.2** Fix 1/72 flaky ingest source (or document as deliberately excluded)
- **C4.6** Verify + document Postgres Flexible Server backup retention + restore dry-run

### 5. Security — L3 ⚠ → C3 (headline dimension)

**Criterion:** Authentication on public endpoints; managed secret store; trust + threat model documented; log privacy policy defined; dependency scanning active.

**Evidence exists:** `SecretStr` for all secrets (`docforge/config.py`); Azure Key Vault + managed identity (Bicep); Dependabot for dependency vulnerabilities; container runs as non-root UID 1000; HTTPS terminated by Container Apps ingress.

**Current headline gap:** the `/search` endpoint is on the public internet (`external: true` in `main.bicep:350`) with no authentication. The `user_name` field in search requests is self-declared — anyone with the FQDN can query and claim to be anyone.

**Gaps → C3:**

- **C3.1** Entra ID authentication on `/search` (server + client + Bicep)
- **C3.2** Entra app registration in DocuWare tenant (user-delegated scope)
- **C3.3** `docforge/docs/threat-model.md` (single doc with a "Trust model" section, not two separate docs)
- **C3.4** `knowledge-hub/rag/docs/log-privacy.md`
- **C3.5** Replace self-declared `user_name` in `query_log` with token's `preferred_username` / `oid` claim; `team_name` + `area_name` remain self-declared (they're routing hints, not identity)

### 6. Scale — L3 ⚠ → C4

**Criterion:** One-team load characteristics instrumented; performance bounds documented; HNSW index parameters rationalized; cold-start behavior measured.

**Evidence exists:** Volumes known (137 sources / 1,772 chunks); `query_log` captures query counts per user/team/area.

**Gaps → C4:**

- **C4.3** Request-timing middleware writing `request_ms` per `/search` into `query_log`; new column + migration; `scripts/latency_report.py` rolls up P50/P95/P99 with cold-start filter (`NOW() - container_start > 60s`)
- **C4.4** `knowledge-hub/rag/docs/load-profile.md` citing measurements + HNSW parameter rationale

### 7. Adoption — L3 ✓

**Criterion:** Authoring guideline published; team-setup docs exist; ≥1 team actively using with tagged sources + measurable queries.

**Evidence:** `docforge/docs/authoring-guideline.md` (Spec B, generic); `knowledge-hub/rag/docs/authoring-conventions.md` (Spec B, DocuWare); `knowledge-hub/rag/docs/team-setup-azure.md` (~2-min onboarding); 137 CCL-tagged sources; `query_log` accumulating per-user/team counts.

**Artifact-writing dependency:** once C3.5 replaces self-declared `user_name` with the Entra token claim, `query_log` counts become trustworthy evidence of real adoption (currently spoofable). The artifact cites post-Entra counts.

### 8. Sustainability — L3 ⚠ → C4 + pre-presentation admin

**Criterion:** CONTRIBUTING.md exists; license clear; repo hosting appropriate to stage; single-maintainer status acknowledged honestly.

**Evidence exists:** MIT `LICENSE` committed.

**Gaps:**

- **C4.5** `docforge/CONTRIBUTING.md` — pre-commit expectations, branch flow, PR requirements, pointer to `CLAUDE.md`
- **P.1** Make `docforge` public on GitHub (currently private at `GranatenUdo/docforge`) — pre-presentation admin, not a C3/C4 deliverable
- **P.2** Verify `LICENSE` + public-readability of the repo post-flip

**Unreachable by engineering effort (named in artifact, not fixed by Spec D):**

- **Bus factor of 1.** Closes only by onboarding a second maintainer. Named in Sustainability row and in the artifact's "what L4 would require" section.
- **Post-hardening production evidence.** Closes only by time. Handled via the 2-week soak requirement below.

## Derived C3 + C4 + admin work-item table

### Spec C3 — Security + privacy

| # | Deliverable | Repo | Sizing |
|---|---|---|---|
| C3.1 | Entra ID auth on `/search`: `fastapi-azure-auth` server-side; `azure-identity.DefaultAzureCredential` in `knowledge-hub/rag/mcp_client.py` + `docforge search`; Bicep adds `AZURE_TENANT_ID` + `ALLOWED_AUDIENCE`; opt-in config flag in `docforge.yml` keeps the engine generic | docforge + knowledge-hub | ~200 LoC + tests; ≈1 wk |
| C3.2 | Entra app registration in DocuWare tenant; user-delegated `api://<app-id>/search` scope; app-id + tenant-id recorded in `knowledge-hub/rag/docs/deployment.md` | DocuWare tenant (user has rights) | ≈10 min |
| C3.3 | `docforge/docs/threat-model.md`: trust model (single-company, single-tenant); assets (indexed docs, `query_log`); threat surfaces (public endpoint, ingest credentials, HF token); mitigations (Entra + Key Vault + non-root + Dependabot); risks-accepted (bus-factor-1, HF-gated model) | docforge | ≈3 pages |
| C3.4 | `knowledge-hub/rag/docs/log-privacy.md`: `query_log` schema; retention decision (90/180/365 day cutoff); access rules; aggregation for reports; GDPR posture for DocuWare-internal usage | knowledge-hub | ≈2 pages |
| C3.5 | Replace self-declared `user_name` in `query_log` with token `preferred_username` / `oid`; migration + backfill note | docforge | ≈40 LoC + migration |

### Spec C4 — Operational readiness

| # | Deliverable | Repo | Sizing |
|---|---|---|---|
| C4.1 | `knowledge-hub/rag/docs/runbook.md`: Container App failure modes (probe, image pull, KV secret sync, cold-start timeout); DB recovery via Flexible Server point-in-time restore; ingest failures (HF token expiry, rate limits, parse errors); auth failures post-Entra | knowledge-hub | ≈3–4 pages |
| C4.2 | Fix 1/72 flaky ingest source; diagnose root cause (parse/HTTP/auth/content); fix or document deliberate exclusion | docforge or knowledge-hub (depends on cause) | ≤1 day |
| C4.3 | FastAPI request-timing middleware: logs `request_ms` per `/search` into `query_log` (new column + migration); `docforge/scripts/latency_report.py` rolls up P50/P95/P99 with cold-start filter | docforge | ≈60 LoC + migration + report |
| C4.4 | `knowledge-hub/rag/docs/load-profile.md`: cites P95/P99 from C4.3 + `query_log` counts + cold-start window; HNSW parameter rationale linking to pgvector docs | knowledge-hub | ≈1–2 pages |
| C4.5 | `docforge/CONTRIBUTING.md`: pre-commit (ruff, pytest, coverage gate); branch flow; PR requirements (Entra app implications, migration notes); pointer to `CLAUDE.md` | docforge | ≈1 page |
| C4.6 | Backup/restore verification: confirm Postgres Flexible Server backup retention + execute point-in-time restore dry-run; document in runbook (C4.1) or as separate `~/operations/backup.md` | knowledge-hub | ≈0.5 day |

### Pre-presentation admin track (not C3, not C4)

| # | Item | Sizing |
|---|---|---|
| P.1 | Make `docforge` public on GitHub (currently private `GranatenUdo/docforge`); README polish for public audience; confirm no secrets in history; add project description | 1–2 hrs |
| P.2 | Verify `LICENSE` (MIT already committed) + public-readability post-flip | 5 min |

## Soak requirement

The presentation artifact is written **no sooner than 2 weeks after C3 + C4 merge to `master` on both repos**. The soak window:

- Covers one normal work cycle (one CCL sprint review against the hardened system).
- Covers one weekly Dependabot pass without human intervention.
- Covers at least one live ingest/re-index cycle.
- Allows cold-start, probe, or Key Vault cert-rotation edge cases time to surface.

If anything material breaks during the soak, extend by another window rather than shrink the window. The soak is what gives the "hardened" claim its credibility — compressing it defeats the point.

## The presentation artifact — outline + writing rules

**Location:** `knowledge-hub/rag/docs/readiness-assessment-<YYYY-MM-DD>.md` where `<YYYY-MM-DD>` is the write date (after soak completion), not the spec date.
**Length:** 4–5 rendered pages. No padding.
**Audience:** DocuWare architecture group / CTO-adjacent reader.
**Intent:** info-sharing, no asks. Readiness, not recommendation.

### Outline

1. **TL;DR** (~half page) — overall level L3, 8-row summary table (dimension × current level), top 3 gaps to L4.
2. **Context** (~half page) — problem docforge solves, deployment footprint, relationship between docforge engine and `knowledge-hub/rag` consumer.
3. **Readiness by dimension** (~1.5 pages) — 8-row compact table (dimension, level, evidence, gap-to-next, investment) + 2–3 narrative paragraphs for dimensions with non-obvious gaps (expected: Security — citing Entra + threat model; Scale — citing P95; Sustainability — citing bus factor).
4. **Architectural observations** (~half page) — where docforge fits in a DocuWare stack; what it does not replace; overlap/tension with existing patterns.
5. **Risk register** (~half page) — bus factor of 1; external model dependency (HF-gated EmbeddingGemma-300M); embedding drift (model updates → re-embed cost); pgvector scale ceiling (~1M chunks before alternatives warranted).
6. **What L4 would require** (~half page) — multi-team adoption (≥2 teams actively using the shared deployment); second-maintainer onboarding; cross-team ranking validation; post-L3 production-soak evidence.

### Writing rules

- **Banned adjectives unless immediately followed by a number:** robust, scalable, secure, production-ready, enterprise-grade. Their replacements are measurements (e.g., "77% test coverage gated in CI", "recall@5 76% on a 25-query baseline", "Entra-authenticated under DocuWare tenant <id>").
- **Every claim in the readiness table maps to at least one concrete evidence bullet in the doc body** (file path, metric, commit, or doc link).
- **Concede weaknesses plainly.** The Security narrative names the public endpoint and Entra's role closing it. The Sustainability narrative names bus-factor-1. Hiding these invites the audience to discover them live.
- **Search quality framing is non-optional.** Per §2 artifact-writing rule above, recall@N numbers must come with the ground-truth-authoring + top-N-to-LLM framing. Otherwise "40%" reads as failure.
- **Evidence sourcing is a write-time audit.** For each row, the author re-verifies evidence against the current repo state at write time (not copies from this spec). If anything has drifted since C3/C4 merged, the artifact reflects the drift, not the spec.
- **Date-stamped, not versioned.** Future assessments are new files (`readiness-assessment-<new-date>.md`), not edits. The spec is once; the assessments are point-in-time.

## What will NOT appear in the artifact

- Adoption recommendations or decisions.
- SLA or SLO claims (none defined).
- Usage metrics beyond `query_log` rollups (nothing else instrumented).
- Cost figures unless provided at write time with Azure SKU + current pricing; otherwise marked "pricing pass pending".
- Polish beyond plain markdown (no slide deck, no marketing prose).

## Success criteria

- [ ] `knowledge-hub/rag/docs/readiness-assessment-<YYYY-MM-DD>.md` committed, 4–5 rendered pages, no padding.
- [ ] All 8 dimensions present in the summary table.
- [ ] Every readiness-table row maps to a concrete evidence bullet in the doc body (file path, metric, commit, or linked doc).
- [ ] Overall level stated in the TL;DR; top-3 L4 gaps listed.
- [ ] Risk register covers the 4 items listed in the outline.
- [ ] No banned adjectives appear without an immediately-following number.
- [ ] Write date ≥14 days after the most-recent of: the final C3 merge on `docforge` master, the final C3 merge on `knowledge-hub` master, the final C4 merge on `docforge` master, the final C4 merge on `knowledge-hub` master.
- [ ] `GranatenUdo/docforge` is public on GitHub at write time (P.1, P.2 complete).

## Risks

- **C3.1 Entra integration takes longer than estimated.** ~200 LoC is the happy-path estimate; real Entra debugging against a live tenant often surfaces tenant-config mismatches. Mitigation: start C3 with C3.2 (app registration) so the tenant is available before C3.1 begins.
- **The 2-week soak surfaces a material issue.** Not a risk — the point of the soak is to surface issues. If one appears, fix it and reset the soak clock. Do not compress.
- **The artifact reads as "we mostly built docs".** Risk if the search-quality + Entra + instrumentation stories aren't foregrounded. Mitigation: the outline puts TL;DR and per-dimension table first so the engineering artifacts are visible before the doc artifacts.
- **Arch-group audience asks for L4.** Handled: §6 of the outline ("what L4 would require") names the path explicitly and the intent is info-sharing, not an ask.

## Follow-up items (noted for future specs)

- **Second-maintainer onboarding** is the only closeable-by-people-not-effort gap toward L4. Not in scope for Spec D; likely a post-presentation conversation with DocuWare engineering leadership.
- **Cross-team pilot** (onboarding a second DocuWare team to the same deployment with their own team tag) is the engineering-path toward L4. Not in scope for Spec D; candidate for a future Phase 5.
- **Presentation deck / talk track** is downstream of the artifact. Spec D produces the artifact; presentation prep is its own exercise.
