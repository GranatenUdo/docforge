# Maturity Assessment — Design

**Date:** 2026-04-17
**Status:** Approved, ready for implementation
**Scope:** Produce a stakeholder-facing readiness assessment of docforge, framed as a TRL-style artifact for an architecture-group audience.

## Context

docforge is a CLI + MCP server + FastAPI search service for ingesting documentation (Confluence pages and git-repo markdown) into PostgreSQL + pgvector and exposing it to AI coding assistants. It was developed inside `knowledge-hub/rag/` (DocuWare CCL team) and has recently been extracted into a standalone repo with a hardened Dockerfile, 81% test coverage, and documentation.

The user (CCL team lead) wants to produce a readiness assessment suitable for an architecture-group / CTO-level audience. The artifact is **not** intended to force a specific decision (adoption, funding, sanction) — it positions the technology and identifies what would be required to move it from its current maturity level to the next. That framing is deliberate: at 3 weeks of production history and one deployment, the evidence base is insufficient to defend stronger claims.

## Goals

1. Produce a committed markdown artifact at `docforge/docs/readiness-assessment-2026-04-17.md`, 3-4 pages, describing docforge's current readiness using a TRL-inspired 5-level scale across 7 dimensions.
2. Present an overall level (expected: L2 moving toward L3) with traceable evidence.
3. Identify, for each dimension, the concrete gap to the next level and an investment estimate (low/medium/high).
4. Be candid about weaknesses — CTO audiences punish overclaiming harder than they punish honest gaps.

Non-goals:

- Propose decisions (adopt / don't adopt / sanction / fund). The doc is readiness, not recommendation.
- Polish into slide deck or marketing format. Factual, neutral prose.
- Promise future work. Investment estimates indicate scale, not commitment.

## Audience and framing

- **Audience:** DocuWare architecture group / CTO-adjacent reader.
- **Framing:** TRL-inspired technology readiness. Answers "where on a readiness curve does this sit?" not "should X do Y?".
- **Tone:** Honest numerics over adjectives. Concede weaknesses plainly.

## Readiness framework

### 5-level scale (adapted from TRL for software tooling)

| Level | Name | Meaning |
|---|---|---|
| L1 | Experimental | Proof of concept; unproven |
| L2 | Validated at single site | One production deployment, one team, limited usage |
| L3 | Hardened at single site | Production-hardened (tests, HC, security pass); still one tenant |
| L4 | Multi-site validated | ≥2 independent deployments; usage evidence across teams |
| L5 | Org-standard | Blessed pattern, platform-owned, SLA-backed |

### 7 dimensions

1. **Functional readiness** — does it do what it claims?
2. **Quality readiness** — tests, type safety, docs, lint/CI posture
3. **Operational readiness** — healthchecks, observability, deployment maturity, runbooks
4. **Security readiness** — secrets handling, auth, dependency posture, threat model coverage
5. **Scale readiness** — load characteristics, performance limits, multi-tenancy
6. **Adoption readiness** — onboarding cost, docs, authoring guidelines, time-to-first-value
7. **Sustainability readiness** — maintainer footprint, knowledge transfer, bus factor

Each dimension receives a row in a compact table and, where the gap is non-obvious, a short paragraph of narrative underneath.

## Document structure

Target length: **3-4 pages** total.

```
# docforge readiness assessment — 2026-04-17

## TL;DR (~half page)
- Overall level: L2, moving toward L3
- docforge in 2 sentences
- Summary table: dimension × current level (7 rows)
- Top 3 gaps blocking L3
- Top 3 gaps blocking L4 (multi-site)

## Context (~half page)
- Problem statement: why docforge exists
- Current deployment footprint
- Relationship to knowledge-hub/rag

## Readiness by dimension (~1 page)
Single compact table + 2-3 narrative paragraphs for dimensions with
non-obvious gaps (likely Security, Scale, Adoption).

## Architectural observations (~half page)
- Where docforge fits in a DocuWare stack
- What it does NOT replace
- Overlap/tension with existing patterns

## Risk register (~half page)
- Single-maintainer risk
- External model dependency (HF-gated EmbeddingGemma-300M)
- Embedding drift (model updates → re-embed cost)
- pgvector scale ceiling (~1M chunks before alternatives warranted)

## What "org-blessed" would require (~half page)
- Concrete gating criteria an architecture group would reasonably ask for
- Framed as visibility, not commitment
```

## Readiness-by-dimension table

| Dimension | Level | Evidence | Gap to next | Investment |
|---|---|---|---|---|
| Functional | L3 | CLI + MCP + API all working; 82 tests passing; end-to-end git ingest + search validated against real pgvector | Search quality not characterized against ground truth; no evaluation harness | Medium |
| Quality | L3 | 82% test coverage; type hints; module + public-function docstrings; ruff configured | No CI pipeline (no automated test gate on PRs) | Low |
| Operational | L2 → L3 | HEALTHCHECK + non-root user in Dockerfile; Azure Container App deployment | No dashboards, no alerting, no written runbook for common failures | Medium |
| Security | L2 | Secrets via `.env` + pydantic `SecretStr`; container runs as UID 1000 | No threat model doc; no SCA/SAST in CI; HF-gated model introduces external dependency | Medium |
| Scale | L2 | One tenant, ~69 indexed sources, query volume not instrumented | No load profile; no multi-tenant auth; pgvector HNSW index present but unsized | High |
| Adoption | L1 | Templates exist (`docforge init`); CCL team using it; no other team has onboarded | No repo-docs authoring guideline; no source organization pattern (Phase 4 specs 2 & 3) | Medium |
| Sustainability | L1 | Single author in git log; no CONTRIBUTING/onboarding doc; no succession plan | Bus factor = 1 | Medium |

## Evidence sourcing plan

For each dimension, evidence is gathered fresh at write time (turns authoring into a small audit):

- **Functional**: inspect CLI (`docforge/cli.py`), MCP tools (`docforge/mcp_server.py`), API routes (`docforge/api.py`); run `pytest` to count passing tests; check for evaluation harness (absent).
- **Quality**: run `pytest --cov=docforge`; list configured linters from `pyproject.toml`; check for `.github/workflows/` (absent).
- **Operational**: inspect `Dockerfile` (HEALTHCHECK, non-root verified); check `knowledge-hub/rag/docs/` for deployment + runbook docs; note absence of dashboards or alerting rules.
- **Security**: inspect secrets handling (`SecretStr` usage in `config.py`); check Dockerfile for user; look for threat-model doc, SCA/SAST integration (absent).
- **Scale**: read `knowledge-hub/rag/sources.yml` (count sources); check pgvector index type in `sql/schema.sql` (HNSW confirmed); note absence of load testing; inspect `api.py` for auth (none).
- **Adoption**: check `docforge/templates/` (present); count pages in `README.md` + `CLAUDE.md`; check for authoring guideline (absent — is Phase 4 Spec #2).
- **Sustainability**: `git shortlog -sn` on docforge repo; look for `CONTRIBUTING.md` (absent); check for onboarding doc.

## What will NOT appear in the doc

- Usage metrics — none instrumented.
- SLA / SLO claims — none defined.
- Cost figures — require pricing pass (Azure Container App resource SKU, Postgres Flexible Server SKU, HF model bandwidth). If the user provides these, include; otherwise mark as "unknown; pricing pass needed."
- Adoption recommendations or decisions.

## Location and naming

- File: `docforge/docs/readiness-assessment-2026-04-17.md`
- Date-stamped: point-in-time artifact; future assessments are new files, not edits.
- Lives in docforge repo (the tool) because the readiness claim is about docforge. Deployment facts from `knowledge-hub/rag/` are evidence feeding in, not the subject.

## Success criteria

- [ ] File committed at the path above.
- [ ] 3-4 pages rendered length; no padding.
- [ ] Every claim in the readiness table maps to at least one concrete evidence bullet in the doc body.
- [ ] Overall level stated in TL;DR; top-3 gaps to next level listed.
- [ ] Risk register includes the 4 items in the structure above.
- [ ] No adjectives substituting for measurements ("robust", "scalable" — banned unless immediately followed by a number).

## Out of scope (tracked elsewhere)

- Repo docs authoring guideline — Phase 4 Spec #2 (to be brainstormed).
- Confluence source organization pattern — Phase 4 Spec #3 (to be brainstormed).
- CI pipeline setup — flagged as a Quality gap but not implemented by this spec.
- Threat model doc — flagged as a Security gap but not implemented by this spec.
