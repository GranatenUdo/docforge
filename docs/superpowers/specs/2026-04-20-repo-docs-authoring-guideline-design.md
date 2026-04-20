# Spec B — Repo Docs Authoring Guideline

**Date:** 2026-04-20
**Status:** Approved, ready for implementation plan
**Scope:** Write two documents (generic guideline + DocuWare addendum) defining what README.md, CLAUDE.md, and `docs/` should contain in any docforge-indexed repository. Zero changes to individual CCL repos; the guideline sets a standard that teams self-apply after it lands.

## Context

Phase 4 Spec A added team-tagging infrastructure so docforge can scope searches by team/area. Spec B addresses the complementary problem: **indexed content quality**. Team-tagged retrieval is only as good as what's been written into the indexed docs.

From a scan of 20+ CCL repos:
- **CLAUDE.md files are consistently strong** — Claude Code's `/init` produces a solid template (Project Overview, Common Commands, Architecture, Project Structure). Teams keep that structure.
- **README.md files are wildly inconsistent.** 12 of 20 contain placeholder boilerplate ("TODO: explain how to contribute", links to `ASP.NET Core` / `Microsoft/vscode` / `ChakraCore` for README inspiration, dead LastPass/VPN instructions). Only 3-4 READMEs clear a reasonable quality bar.
- `docs/` folders are undergoverned — present in some repos, populated variably.

This asymmetry is the target: lift README quality and formalize `docs/` layout without disturbing the CLAUDE.md pattern that already works.

## Goals

1. Publish a generic authoring guideline in `docforge/docs/authoring-guideline.md` — checklist + prose principles + annotated exemplars, 4-6 pages.
2. Publish a DocuWare-specific addendum in `knowledge-hub/rag/docs/authoring-conventions.md` — ~1 page.
3. Use two existing CCL repos as exemplars (real, achievable, clickable).
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
## README.md — structure checklist (1 page)
## CLAUDE.md — structure checklist (1 page)
## docs/ — layout principles     (½ page)
## Writing principles            (1 page)
## Annotated exemplars           (1 page)
```

### Section content

**Why this matters** — single mental model: "docforge chunks your docs and serves them to AI assistants. The assistants answer colleagues' questions using whatever you wrote. Doc quality = answer quality." Two-minute framing, no lectures.

**What to produce** — three artifacts per repo:
- `README.md` — the public hook. What is this, who uses it, design rationale.
- `CLAUDE.md` — AI-assistant context. Build/run/test commands, architecture, gotchas.
- `docs/` — depth content. Architecture papers, runbooks, ADRs, integration guides.

Clear split: README = intro + rationale; CLAUDE.md = how to work in this repo; docs/ = depth.

**README.md — structure checklist** — required sections, in order:
- Title matches repo name
- One-paragraph "what is this" + who uses it
- Section: "Scope / Use Cases" — concrete scenarios this service serves
- Section: "Architecture" — ≥1 paragraph on key design decisions (data model, interactions, constraints)
- Section: "Communication" or "Integration" — how other services call this
- Section: "Operations" or "Deploy" — at a glance how this runs
- Links to relevant external docs (Confluence pages, Tech Papers)

Banned content:
- Placeholder TODOs ("TODO: explain how to contribute")
- Azure DevOps / Microsoft README inspirational boilerplate (`create-a-readme` guide links, ASP.NET Core / vscode / ChakraCore reference links)
- "See LastPass for credentials"
- Dead VPN / environment setup instructions

**CLAUDE.md — structure checklist** — standard sections (Claude Code's `/init` produces most of these; keep them):
- Project Overview (2-4 sentences)
- Common Commands (build, test, run, package — with exact invocations)
- Architecture (project structure, key abstractions)
- Anything non-obvious (gotchas, integration quirks, env requirements)

Banned content:
- Duplication of README content (link instead)
- Meta-commentary about the CLAUDE.md file itself

**docs/ — layout principles** — when to put something in `docs/` vs inline:
- README/CLAUDE.md: content every reader benefits from (overview, build/run)
- `docs/`: content specific readers need (architecture papers, runbooks, deployment procedures, ADRs)

Recommended subdirectories:
- `docs/architecture/` — tech papers, design decisions, ADRs
- `docs/runbook/` — operational procedures (incident response, recovery)
- `docs/integration/` — how to call this service from elsewhere

No rigid file-naming convention. Cluster by concern.

**Writing principles** — four rules that shape good docforge-indexable content:

1. **Self-contained sections.** Each `##` heading + body stands alone under retrieval. No "see above." Include a one-sentence recap if needed.
2. **Specific over generic.** `"Retries use Polly.HttpRetryPolicy with max 3 attempts and exponential backoff"` beats `"We retry on failure."` Specificity is indexable terminology.
3. **Name the domain.** Use DocuWare-specific terms (organization, shard, data center, SmartUpdate, CCL, trial). These are the words colleagues will search with.
4. **No boilerplate.** Template text that's the same across every repo adds noise during retrieval. Cut it.

**Annotated exemplars** — inline excerpts with margin notes:

*README exemplar* — excerpts from `DataCenter.Organization.Audit/README.md` (111 lines, clean structure). Notes pointing out:
- Why the "Use Cases" section works (concrete scenarios indexable as queries)
- Why the "Persistence" section with schema tables retrieves well (queries like "audit schema" or "audit data model" hit this)
- What could still improve (no operations/deploy section, no Confluence links)

*CLAUDE.md exemplar* — excerpts from `Global.Organization.CreationTrial/CLAUDE.md` (253 lines). Notes pointing out:
- Why "Common Commands" with exact invocations is better than prose
- Why Tech Stack declaration helps AI pick correct code patterns
- Why architecture is an H3 list (discrete chunks retrieve better than paragraphs)

Full files linked so readers can click through.

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
| README.md pattern | `E:/DataCenter.Organization.Audit/README.md` |
| CLAUDE.md pattern | `E:/Global.Organization.CreationTrial/CLAUDE.md` |

Both are already indexed by docforge today. The guideline references them by URL in the knowledge-hub Confluence mirror plus inline excerpt.

## Success criteria

- [ ] `docforge/docs/authoring-guideline.md` exists, 4-6 pages, commit on master.
- [ ] `knowledge-hub/rag/docs/authoring-conventions.md` exists, ~1 page, commit on master.
- [ ] Generic guideline contains: checklist for README, checklist for CLAUDE.md, `docs/` layout principles, writing principles, two annotated exemplars.
- [ ] DocuWare addendum contains: team-tag reference, naming taxonomy, Confluence link guidance, CCL-specific expectations, contact.
- [ ] Exemplar excerpts quote real content from the two reference CCL repos (not paraphrases).
- [ ] Zero changes to any individual CCL repo's docs as part of this spec.
- [ ] Banned-content items in checklists are mechanically detectable (regex-matchable) — positions Spec C's linter for easy implementation.

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
- **Risk: CCL-internal content in the public docforge repo on future public release.** The generic guideline lives in docforge (planned public). It will embed excerpts from `DataCenter.Organization.Audit/README.md` (describes DocuWare audit data model) and `Global.Organization.CreationTrial/CLAUDE.md` (mentions `CloudCL.Common.Authentication`, Entra ID SSO, internal ADO pipeline). Acceptable while docforge stays private; at public-release time, review and either scrub DocuWare-specific strings from excerpts or replace with sanitized equivalents. Add to the docforge public-release checklist.
