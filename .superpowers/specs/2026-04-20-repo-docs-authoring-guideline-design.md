# Spec B — Repo Docs Authoring Guideline

**Date:** 2026-04-20
**Status:** Approved, ready for implementation plan
**Scope:** Write two documents (generic guideline + DocuWare addendum) defining what README.md, CLAUDE.md, and `docs/` should contain in any docforge-indexed repository. Zero changes to individual CCL repos; the guideline sets a standard that teams self-apply after it lands.

## Context

Phase 4 Spec A added team-tagging infrastructure so docforge can scope searches by team/area. Spec B addresses the complementary problem: **indexed content quality**. Team-tagged retrieval is only as good as what's been written into the indexed docs.

From a scan of 22 CCL repos (all with README.md present):
- **CLAUDE.md files are consistently strong** — Claude Code's `/init` produces a solid template (Project Overview, Common Commands, Architecture, Project Structure). Teams keep that structure.
- **12 of 22 READMEs carry the Azure DevOps default template** verbatim: a 19-line stub with "TODO: Explain how other users and developers can contribute" and links to Microsoft's README inspiration (`ASP.NET Core`, `Microsoft/vscode`, `ChakraCore`). That's 55% of CCL repos where the README hasn't been touched since repo creation.
- Of the remaining 10, quality varies from a 26-line intro to a 111-line design-paper; 3 genuinely clear a reasonable bar today (`DataCenter.Organization.Audit`, `Global.FeatureManagement`, `Global.Organization.Domain`), plus two recent retrofits (see below).
- `docs/` folders are undergoverned — present in 9 of 22 repos, structures vary (numbered sequence, ad-hoc, specialized).

**Recent retrofits that prove the pattern is achievable:**
- `cloudstatus` (main, merged) — adopted a short-README + rich numbered `docs/` approach.
- `Global.FeatureManagement` (on branch `fix/cohort-removal-propagation`, not yet merged) — adopted a medium-README with specialized `docs/`.

This asymmetry is the target: lift README quality and formalize `docs/` layout without disturbing the CLAUDE.md pattern that already works.

## Goals

1. Publish a generic authoring guideline in `docforge/docs/authoring-guideline.md` — checklist + prose principles + annotated exemplars, 4-6 pages.
2. Publish a DocuWare-specific addendum in `knowledge-hub/rag/docs/authoring-conventions.md` — ~1 page.
3. Use `cloudstatus` as the primary exemplar (real, recently retrofitted, on main). Add `Global.FeatureManagement` as a second exemplar once its `fix/cohort-removal-propagation` branch merges — the two repos demonstrate two equally-valid doc patterns (short-README + numbered `docs/` vs medium-README + specialized `docs/`).
4. Frame the guideline so a future linter (Spec C) can mechanically enforce the structural rules.

Non-goals:
- Do NOT modify any individual CCL repo's docs (each team applies the guideline on their own cadence).
- Do NOT ship a linter (Spec C).
- Do NOT define a template repo or cookiecutter (teams don't fork; they copy patterns from live repos).
- Do NOT dictate tone / voice / length beyond what the checklist implies.
- Do NOT cover CONTRIBUTING / CHANGELOG / SECURITY files (not present at scale today; out of scope).

## Design principles

- **Real over fictional.** Exemplars are existing CCL files, not ideal inventions. Teams should see "this is achievable" not "this is aspirational."
- **Checklist for structure, prose for content.** Hard rules on sections + bans are auditable by humans now and machines later. "What makes content good" is prose because it resists mechanical enforcement.
- **Two tiers, clean split.** docforge repo holds the generic document (future adopters see a pragmatic, opinion-only-where-needed guide). knowledge-hub holds only the DocuWare-specific overlay. No duplication.
- **YAGNI on tone rules.** Teams write differently; docforge's relevance ranking doesn't care. Don't enforce voice.

## Generic guideline (`docforge/docs/authoring-guideline.md`)

Target length: 4-6 pages.

### Section layout

```
# Authoring docs for a docforge-indexed repo

## Why this matters              (½ page)
## What to produce               (½ page)
## Two valid patterns            (½ page)
## README + docs/ — content checklist (1 page)
## CLAUDE.md — structure checklist (1 page)
## Writing principles            (1 page)
## Annotated exemplar            (1 page)
```

### Section content

**Why this matters** — single mental model: "docforge chunks your docs and serves them to AI assistants. The assistants answer colleagues' questions using whatever you wrote. Doc quality = answer quality." Two-minute framing, no lectures.

**What to produce** — three artifacts per repo:
- `README.md` — human entry point. Title, what-is-this, where to find more.
- `CLAUDE.md` — AI-assistant context. Build/run/test commands, architecture, gotchas.
- `docs/` — depth content. Architecture papers, runbooks, ADRs, integration guides, diagrams.

**Two valid patterns** — teams pick whichever fits. Both are in production use.

*Pattern A (short README + rich `docs/`)* — cloudstatus-style. README is ~25 lines: title, one-paragraph intro, a pointer to `docs/00-index.md`, and a one-liner per top-level solution/component. All depth lives in a numbered `docs/` sequence (`00-index`, `01-overview`, …, `09-operations`, appendices `A1`, `A2`). Onboarding-friendly: a new engineer reads the numbered sequence in order.

*Pattern B (medium README + specialized `docs/`)* — FRED-style. README is ~80-120 lines: title, "System at a glance" with a component bullet-list, "Documentation" section linking in-repo docs + Confluence, "Local development" with prerequisites + exact commands. `docs/` holds specialized deep-dives (`architecture.md`, `data-model.md`, `glossary.md`, `adr/`). The README itself is enough to understand the system; `docs/` is for going deeper on a specific concern.

Pick Pattern A if the repo hosts multiple solutions/services and onboarding is a primary use case; pick Pattern B if the repo is one coherent product where the README can reasonably carry the overview.

**README + docs/ content checklist** — the REPO (README + docs/ together) must cover each topic. Placement is up to the team based on the chosen pattern:

- Title / project name — in the README
- One-paragraph "what is this" + who uses it — in the README
- **Scope / Use Cases** — concrete scenarios this service serves (README in Pattern B; `docs/01-overview` or equivalent in Pattern A)
- **Architecture** — key design decisions, data model, interactions, constraints (`docs/architecture.md` in both patterns, summarized in README for Pattern B)
- **Communication / Integration** — how other services call this (same placement as Architecture)
- **Operations / Deploy** — at a glance how this runs (`docs/09-operations.md` or `docs/operations.md`)
- **Links to relevant external docs** — Confluence pages, Tech Papers (README or `docs/` index)

Banned content (regex-matchable — future linter targets):
- Placeholder TODOs ("TODO: explain how to contribute", "TODO: Explain how")
- Azure DevOps / Microsoft README inspirational boilerplate (`create-a-readme` guide links, `ASP.NET Core` / `Microsoft/vscode` / `ChakraCore` reference links)
- "See LastPass for credentials"

**CLAUDE.md — structure checklist** — standard sections (Claude Code's `/init` produces most of these; keep them):
- Project Overview (2-4 sentences)
- Common Commands (build, test, run, package — with exact invocations)
- Architecture (project structure, key abstractions)
- Anything non-obvious (gotchas, integration quirks, env requirements)

Banned content:
- Duplication of README content (link instead)
- Meta-commentary about the CLAUDE.md file itself

**Writing principles** — five rules that shape good docforge-indexable content:

1. **Self-contained sections.** Each `##` heading + body stands alone under retrieval. No "see above." Include a one-sentence recap if needed.
2. **Specific over generic.** `"Retries use Polly.HttpRetryPolicy with max 3 attempts and exponential backoff"` beats `"We retry on failure."` Specificity is indexable terminology.
3. **Name the domain.** Use DocuWare-specific terms (organization, shard, data center, SmartUpdate, CCL, trial). These are the words colleagues will search with.
4. **No boilerplate.** Template text that's the same across every repo adds noise during retrieval. Cut it.
5. **Avoid stale references.** Don't link to dead VPN instructions, deleted Confluence pages, or retired auth systems. If a reference becomes obsolete, remove it rather than leaving a dead link.

**Annotated exemplar** — inline excerpts with margin notes from `cloudstatus` (main, recently retrofitted). Three pieces annotated:

*README excerpt* — from `cloudstatus/readme.md` (22 lines). Notes:
- Why the README is intentionally SHORT in Pattern A (all depth delegated to `docs/`)
- How the one-liner-per-solution list sets up the reader for `docs/` navigation
- Why the "Included Solutions" section uses bolded solution names + short descriptions (indexable chunks)

*CLAUDE.md excerpt* — from `cloudstatus/CLAUDE.md` (187 lines). Notes:
- Why "Common Commands" with exact invocations is better than prose
- Why Tech Stack declaration helps AI pick correct code patterns
- Why Architecture Notes are H3 bullet-lists (discrete chunks retrieve better than paragraphs)
- Why the "Cross-repo integration" inline note (on StorageStatisticsCollector) is gold — searchable at query time

*docs/ structure excerpt* — from `cloudstatus/docs/00-index.md` and the file tree. Notes:
- How numbered sequence (`00`, `01`, …) signals onboarding order
- How appendices (`A1`, `A2`) separate reference material from the main sequence
- Why the "Maintenance" section in the index (which doc to update on what change) is itself indexable — colleagues querying "how to update architecture doc" hit it
- How the `diagrams/` folder houses `.drawio` source (editable, not images)

Full files linked so readers can click through.

**Note on Pattern B exemplar:** A `Global.FeatureManagement` exemplar showing the medium-README + specialized `docs/` pattern will be added once the `fix/cohort-removal-propagation` branch merges to main. Until then, the guideline describes Pattern B in prose but illustrates only Pattern A.

## DocuWare addendum (`knowledge-hub/rag/docs/authoring-conventions.md`)

Target length: ~1 page.

### Content

**Team tags** — list current canonical tags (`ccl`, `org`, `cross-team`), point at `knowledge-hub/rag/teams.yml` as source of truth. New teams must add their tag id to `teams.yml` before tagging sources.

**Repo naming taxonomy** — document the existing CCL conventions and what they imply for doc content:
- `DataCenter.Organization.*` — data-center-scoped services; README should say so in Scope
- `Global.*` — cross-datacenter services; README should note single-URL global nature
- `Infrastructure.*` — shared platform components
- `Domain.*` — domain event contracts
- No prefix — tools/utilities

**Linking to Confluence** — preferred link targets:
- Team responsibilities pages in HEL space
- "Application architecture guidelines"
- Domain papers ("[Tech Paper]" prefix in HEL)

Dead links must be fixed, not kept.

**CCL-specific expectations** — things every CCL README/CLAUDE.md should include:
- README: one paragraph in DocuWare-business terms; link to "Domain - X" Confluence page; mention owning team (today: CCL)
- CLAUDE.md: .NET version; that builds run in ADO; any `CloudCL.Common.*` shared libraries used

**Who to ask** — contact for questions about these conventions, via the CCL team's Teams channel.

### Not included in the addendum
- Per-repo ownership map (lives in `teams.yml`, would rot here)
- Per-team rules for teams other than CCL (only CCL exists today; revisit on 2+)
- Enforcement tooling (Spec C)

## Exemplar files (already exist in CCL)

| Exemplar role | File (existing, unmodified) |
|---|---|
| README.md (Pattern A — short) | `E:/cloudstatusrepos/cloudstatus/readme.md` (main) |
| CLAUDE.md | `E:/cloudstatusrepos/cloudstatus/CLAUDE.md` (main) |
| docs/ layout (Pattern A — numbered sequence) | `E:/cloudstatusrepos/cloudstatus/docs/` (main) |
| README + docs/ (Pattern B) | `E:/Global.FeatureManagement/readme.md` + `docs/` (planned; on `fix/cohort-removal-propagation`, added after merge) |

All cloudstatus exemplars are on main (PR merged 2026-04-20). The guideline quotes short excerpts inline and links to the full files.

## Success criteria

- [ ] `docforge/docs/authoring-guideline.md` exists, 4-6 pages, commit on master.
- [ ] `knowledge-hub/rag/docs/authoring-conventions.md` exists, ~1 page, commit on master.
- [ ] Generic guideline contains: the two-patterns description, README+docs/ content checklist, CLAUDE.md structure checklist, writing principles, annotated exemplar from cloudstatus.
- [ ] DocuWare addendum contains: team-tag reference, naming taxonomy, Confluence link guidance, CCL-specific expectations, contact.
- [ ] Exemplar excerpts quote real content from cloudstatus (not paraphrases). Files referenced by repo-relative path so future moves are traceable.
- [ ] Zero changes to any individual CCL repo's docs as part of this spec.
- [ ] Banned-content items in the checklist are regex-matchable — positions Spec C's linter for easy implementation. "Avoid stale references" lives in prose (judgment-required), not banned-content list.
- [ ] Follow-up noted (not enforced by this spec): after `Global.FeatureManagement` branch merges, add Pattern B exemplar excerpts.

## Out of scope (tracked elsewhere)

- Implementation of the linter to enforce the structural rules — Spec C.
- Retrofitting individual CCL repo docs to meet the guideline — per-team follow-up, not Phase 4.
- Per-team ownership map updates — lives in `knowledge-hub/rag/teams.yml`, Spec A.
- Any new CCL-wide doc conventions beyond what's already practiced (no new required files).

## Dependencies

- Spec A (team tagging) merged — yes, as of 2026-04-20. `teams.yml` referenced in the addendum is from Spec A.

## Open questions / risks

- **Risk: the guideline lands and is never applied.** Mitigation: the guideline alone doesn't force adoption. Bundle it with a Teams channel post when it lands; revisit adoption after 30 days during the Spec D readiness pass.
- **Risk: "docforge-indexable" framing bleeds into the generic guideline in a way that doesn't land for public adopters.** Mitigation: generic doc frames principles in AI-retrieval terms ("chunked, embedded, served to AI assistants") — true for any RAG system, not only docforge.
- **Risk: CCL-internal content in the public docforge repo on future public release.** The generic guideline lives in docforge (planned public). It will embed excerpts from `cloudstatus/readme.md`, `cloudstatus/CLAUDE.md`, and `cloudstatus/docs/` (references DocuWare production URLs, internal architecture, ADO pipelines, `rotwand.azurecr.io`, `docuware.cloud` domain, etc.). Acceptable while docforge stays private; at public-release time, review and either scrub DocuWare-specific strings from excerpts or replace with sanitized equivalents. Add to the docforge public-release checklist.
