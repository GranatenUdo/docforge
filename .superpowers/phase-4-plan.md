# Phase 4 — Team Adoption Readiness

**Date:** 2026-04-17
**Status:** Planning — individual specs to be brainstormed in order below.

## Purpose

Phase 4 prepares docforge + the `knowledge-hub/rag` deployment for an architecture-group / CTO-level readiness conversation. The goal is a genuinely mature system to present, not a polished description of an immature one. Gaps closeable by engineering effort get closed; gaps that require calendar time (post-hardening production evidence) or a second engineer (bus factor) are named plainly rather than hidden.

## Guiding principles

- **Repo separation.** `docforge` (private GitHub, generic engine) stays free of DocuWare-specific data. DocuWare team lists, sources, naming conventions live in `knowledge-hub/rag` (DocuWare ADO). Every Phase 4 artifact names its home repo explicitly.
- **Trust model.** docforge is a single-company tool. There is no multi-tenant auth. Search requests carry a self-declared `user` and `team` as input parameters used for usage telemetry and relevance weighting, not access control.
- **L4 definition.** "Multi-tenant on shared" — ≥2 teams actively using one shared deployment with team-tagged sources and relevance ranking validated across teams. Per-team independent deployments do NOT count toward L4 under this framework.
- **No timeline pressure.** Quality over speed. This document orders the work but does not set a deadline.

## The four specs, in order

Specs are ordered by dependency: each builds on decisions made in the previous.

### Spec A — Team tagging + MCP `user`/`team` parameters

The structural change. Adds a `team` tag to source config, extends the MCP tool signature, and introduces per-query relevance weighting.

**Artifacts:**

| Artifact | Repo |
|---|---|
| Schema change (sources gain `team` column or tag array), MCP tool signature (`search_documentation(query, user_name, team_name, limit)`), query SQL with team-aware ranking, CLI + API updates, tests | `docforge` |
| DocuWare team list (`teams.yml` or similar), source→team mappings in `sources.yml`, `generate_sources.py` updates to emit tags | `knowledge-hub/rag` |

**Depends on:** nothing. Start here.

### Spec B — Repo docs authoring guideline

What makes a repo docforge-indexable and what to include (README structure, CLAUDE.md contents, docs/ layout, team metadata).

**Artifacts:**

| Artifact | Repo |
|---|---|
| Generic guideline ("how to author docs for a docforge index") | `docforge/docs/authoring-guideline.md` |
| DocuWare-specific addendum (canonical team tags, DocuWare naming conventions, CCL expectations) | `knowledge-hub/rag/docs/authoring-conventions.md` |

**Depends on:** Spec A — the team tag syntax must be defined before we tell teams to use it.

### Spec C — Hardening sprint

Every closeable-by-effort gap from the maturity matrix.

**Artifacts (non-exhaustive):**

| Artifact | Repo |
|---|---|
| CI pipeline (GitHub Actions — test + lint + type-check on PR) | `docforge` |
| Search evaluation harness (ground-truth set + scoring) | `docforge` |
| Threat model doc | `docforge/docs/threat-model.md` |
| SCA / dependency scanning (Dependabot) | `docforge` |
| CONTRIBUTING.md + onboarding doc | `docforge` |
| Incident runbook (Azure Container App failure modes, DB recovery, ingest failures) | `knowledge-hub/rag/docs/runbook.md` |
| Privacy policy for usage logs (retention, access, aggregation) | `knowledge-hub/rag/docs/log-privacy.md` |
| Cost doc citation (existing `deployment.md` already has figures) | `knowledge-hub/rag/docs/` — already present |

**Depends on:** Specs A and B merged, because CI gates test them and the runbook references the hardened deployment shape.

### Spec D — Maturity assessment (presentation artifact)

Written last, reflects post-hardening state. This is the document the architecture group reads.

**Artifacts:**

| Artifact | Repo |
|---|---|
| `readiness-assessment-<date>.md` | `knowledge-hub/rag/docs/` |

**Location rationale:** the evaluated system is docforge engine + knowledge-hub deployment together; the audience is DocuWare. Lives where the DocuWare deployment lives, not where the generic engine lives.

**Depends on:** Specs A, B, C complete. This assessment is an observation of the hardened state — writing it earlier captures obsolete state.

## Supersession note

The earlier spec `docs/superpowers/specs/2026-04-17-maturity-assessment-design.md` (committed in `ff17b44`) is **superseded by this plan**. It remains in-repo as early thinking. Key differences: that spec placed the assessment in `docforge/docs/` and treated it as the only Phase 4 artifact; Phase 4 now has four specs and places the assessment in `knowledge-hub/rag/docs/` as the final artifact.

## Remaining items to park

- **IP ownership of `docforge` repo.** Developed on DocuWare time but hosted in a private personal GitHub. Spec D should address this in the Sustainability dimension; short resolution recommended before the presentation.
- **Second-engineer onboarding (bus factor).** Cannot be closed by effort. Spec D names this as an unreachable-by-effort gap.
- **Post-hardening production evidence.** Cannot be closed by effort. Spec D names this as an unreachable-by-effort gap.

## Next step

Brainstorm Spec A.
