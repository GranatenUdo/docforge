# Authoring docs for a docforge-indexed repo

This guideline describes how to write `README.md`, `CLAUDE.md`, and `docs/` in a repository that is indexed by docforge. It targets generic docforge adopters; DocuWare-specific conventions live in `knowledge-hub/rag/docs/authoring-conventions.md`.

## Why this matters

docforge chunks the files in your repo's doc surface, embeds them into a vector store, and serves them to AI coding assistants. A colleague's assistant answers their question using whatever you wrote. **Doc quality = answer quality.** If your README is the Azure DevOps default template, the assistant tells them nothing useful. If your CLAUDE.md skips the build command, the assistant guesses.

The goal of this guideline is not comprehensive documentation. It's **indexable content**: sections that retrieve well under a similarity search, written so a colleague who just joined the team (and will never meet you) can get unstuck.

## What to produce

Three artifacts per repo:

- **`README.md`** — the human entry point. What is this, who uses it, where to find more.
- **`CLAUDE.md`** — AI-assistant context. Build/run/test commands, architecture, gotchas.
- **`docs/`** — depth content. Architecture papers, runbooks, ADRs, integration guides, diagrams.

Each serves a different reader and a different retrieval pattern. Don't duplicate content across all three — link instead.

## Two valid patterns

Teams write docs in two patterns. Both are in production use; both index well. Pick whichever fits your repo.

### Pattern A — short README + rich `docs/`

The README is ~25 lines: title, one-paragraph intro, a pointer to `docs/00-index.md`, and a one-liner per top-level solution or component. All depth lives in a numbered `docs/` sequence (`00-index.md`, `01-overview.md`, …, `09-operations.md`), optionally with appendices (`A1-*.md`, `A2-*.md`).

Onboarding-friendly: a new engineer reads the numbered sequence in order. The README is deliberately short because it's not the content — it's the pointer.

Example in CCL: `cloudstatus`.

### Pattern B — medium README + specialized `docs/`

The README is ~80-120 lines: title, "System at a glance" with a component bullet-list, "Documentation" section linking in-repo docs + external references (Confluence, etc.), "Local development" with prerequisites and exact commands. `docs/` holds specialized deep-dives organized by concern (`architecture.md`, `data-model.md`, `glossary.md`, `adr/` for architecture decision records).

The README itself is enough to understand the system; `docs/` is for going deeper on one concern at a time.

Example in CCL: `Global.FeatureManagement` (on `fix/cohort-removal-propagation` branch at time of writing).

### When to pick which

| Pick Pattern A when… | Pick Pattern B when… |
|---|---|
| The repo hosts multiple solutions or services | The repo is one coherent product |
| Onboarding new engineers is a primary use case | The README can reasonably carry the overview |
| You want the doc surface to teach the system end-to-end in order | You want readers to navigate to a specific concern |

## README + docs/ — content checklist

The **repo** (README and `docs/` together) must cover every topic below. Placement between the two files is up to you, based on the chosen pattern.

### Required content

- [ ] **Title / project name** — in the README
- [ ] **One-paragraph "what is this" + who uses it** — in the README
- [ ] **Scope / Use Cases** — concrete scenarios this service serves (README in Pattern B; `docs/01-overview.md` or equivalent in Pattern A)
- [ ] **Architecture** — key design decisions, data model, interactions, constraints (`docs/architecture.md` in both patterns; summarized in README for Pattern B)
- [ ] **Communication / Integration** — how other services call this
- [ ] **Operations / Deploy** — at a glance how this runs (`docs/09-operations.md` or `docs/operations.md`)
- [ ] **Links to relevant external docs** — Confluence pages, tech papers (in the README or in the `docs/` index)

### Banned content (regex-matchable — future linter targets)

These strings should not appear in README or `docs/`:

- `TODO.*Explain` or `TODO.*Contribute` — placeholder text from templated READMEs
- `create-a-readme` — link to Microsoft's "how to write a README" guide (noise)
- `ASP.NET Core`, `Microsoft/vscode`, `ChakraCore` in the context of "inspirational README examples" (noise; delete that whole section)
- `LastPass` — credential-source references belong in the team Teams channel, not indexed docs

If the Azure DevOps default `# Introduction` + `TODO: ...` skeleton is still present, delete it and start over.

## CLAUDE.md — structure checklist

Claude Code's `/init` command produces most of what's needed. Keep that structure and keep it current.

### Required sections

- [ ] **Project Overview** — 2-4 sentences describing what this repo does in business terms
- [ ] **Common Commands** — build, test, run, package. Use exact invocations (`dotnet build X.sln --configuration Release`), not prose
- [ ] **Architecture** — project structure, key abstractions. Bullet lists retrieve better than paragraphs
- [ ] **Anything non-obvious** — gotchas, integration quirks, env requirements, cross-repo dependencies

### Banned content

- Duplicated content from README (link instead)
- Meta-commentary about the CLAUDE.md file itself
- Speculation about future work (those belong in `docs/adr/` as architecture decision records)

## Writing principles

Five rules that shape good docforge-indexable content. These resist mechanical enforcement — use judgment.

### 1. Self-contained sections

Each `##` heading + its body should stand alone under retrieval. Don't write "see above" — the AI won't have seen above. If a section needs context, include a one-sentence recap.

Bad:
> ## Retry Policies
> As mentioned in the previous section, we use Polly. The retry policy is configured with…

Good:
> ## Retry Policies
> This service uses Polly for retry handling. The `HttpRetryPolicy` allows 3 attempts with exponential backoff; the `SqlConnectionRetryPolicy` handles transient connection failures…

### 2. Specific over generic

`"Retries use Polly.HttpRetryPolicy with max 3 attempts and exponential backoff"` beats `"We retry on failure"`. Specificity is indexable terminology — the more specific a noun, the more likely a colleague's query will match.

### 3. Name the domain

Use the business-specific terms colleagues actually search with. In DocuWare context: *organization*, *shard*, *data center*, *SmartUpdate*, *CCL*, *trial*. Don't write around them in generic .NET language.

### 4. No boilerplate

Template text identical across every repo adds noise during retrieval. If you can find the same paragraph in three other repos, delete it.

### 5. Avoid stale references

Don't link to dead VPN instructions, deleted Confluence pages, or retired auth systems. If a reference becomes obsolete, remove it rather than leaving it. Out-of-date docs are worse than missing docs — they actively mislead.

## Annotated exemplar

Excerpts from `cloudstatus` (merged to main, 2026-04-20). Each excerpt is paired with notes explaining why the pattern works for retrieval.

### README excerpt (Pattern A — short)

Full file: `cloudstatusrepos/cloudstatus/readme.md` (22 lines total).

````markdown
[![Build status](…)](…)

Cloud Status
=======================
"Cloud Status" is a collection of Services around the DW-Cloud.
Hosted on: https://dwcr.visualstudio.com/CloudStatus

Documentation
--------------------

For comprehensive system documentation, architecture diagrams, and operational guides, see **[docs/](docs/00-index.md)**.

Included Solutions
--------------------

**CloudStatusWeb.sln** — Web services (CloudStatusCore dashboard + CloudAnalyticsDataServiceCore OData API)

**DataCollectors.sln** — 6 background data collection tasks deployed as Docker containers per shard

See [docs/](docs/00-index.md) for architecture, data flows, and detailed documentation.
````

Notes:

- The README is 22 lines. All depth is delegated to `docs/`. This is Pattern A.
- **"Included Solutions"** uses bolded solution names + a one-line description. This chunks well — a query for "CloudStatusWeb" retrieves that line plus adjacent context.
- No TODO placeholders, no `create-a-readme` Microsoft inspirational links. The stub has been fully replaced.
- **Missing from this excerpt** (and arguably should appear somewhere): explicit scope statement, operations summary. Both exist in `docs/` — so the repo-as-whole covers them.

### CLAUDE.md excerpt (cloudstatus/CLAUDE.md, 187 lines)

Key sections:

````markdown
## Project Overview

Cloud Status is a collection of services for monitoring and managing DocuWare Cloud infrastructure. The system tracks shard status, organization metrics, performance data, and quota information across multiple data centers.

**Production URLs:**
- Main Status Page: https://status.docuware.cloud/
- Preview/Testing: https://previewstatus.docuware.cloud/

## Repository Structure

### CloudStatusWeb.sln
…
- **CloudStatusCore**: ASP.NET Core web application providing status dashboards and APIs
…

## Build and Development Commands

### Restore Dependencies
```bash
dotnet restore Core/**/*.csproj --configfile nuget.config
```

### Build
```bash
dotnet build Core/CloudStatusWeb.sln --configuration Release
```

## Architecture Notes

### Authentication & Authorization
CloudStatusCore uses a multi-scheme authentication approach:
- **OpenID Connect** for DocuWare employee authentication via Azure AD
- **JWT Bearer** tokens for API access
…

### Data Collection Architecture
The ScheduledMaintenance container orchestrates multiple data collectors:
- Each collector runs as a separate executable in isolated directories
- Cron schedules are randomized on startup (0-60 minute offset)…
````

Notes:

- **Exact command invocations** in "Build and Development Commands" — not "use dotnet to build" prose. A colleague asking "how to build cloudstatus" retrieves the exact command.
- **Architecture Notes as H3 bullet-lists** — "Authentication & Authorization", "Data Collection Architecture", "Shared Model Library", etc. Each H3 is a self-contained chunk. Queries for "cloudstatus auth" hit the auth chunk without dragging in the whole Architecture section.
- **Cross-repo integration** (`StorageStatisticsCollector writes to the SubscriptionPlan database`) is inline in the data collector description — indexable at query time when someone searches "SubscriptionPlan database writer".

### docs/ structure excerpt (cloudstatus/docs/)

File tree:

```
cloudstatus/docs/
├── 00-index.md             # landing page with document table
├── 01-overview.md          # business purpose, consumers, high-level diagram
├── 02-getting-started.md   # prerequisites, setup, build, run, test
├── 03-architecture.md      # project reference graph, DI, dependencies
├── 04-data-flow.md         # end-to-end ASCII diagrams for each pipeline
├── 05-cloudstatuscore.md   # the web app
├── 06-analytics-service.md # the OData API
├── 07-data-collectors.md   # ScheduledMaintenance + 6 collectors
├── 08-data-model.md        # database tables, stored procedures, views
├── 09-operations.md        # configuration, deployment, monitoring
├── A1-security-and-debt.md # appendix: security findings
├── A2-authentication.md    # appendix: auth deep-dive
└── diagrams/
    └── cloudstatus-technical.drawio   # editable source, not a rendered image
```

From `00-index.md`:

````markdown
## Documents

| # | Document | Description |
|---|----------|-------------|
| 01 | [Overview](01-overview.md) | Business purpose, consumers, high-level architecture diagram |
| 02 | [Getting Started](02-getting-started.md) | Prerequisites, setup, build, run, test |
…

## Maintenance

When making significant changes to CloudStatus, update the relevant documentation:

1. **Relevant numbered doc** — new data flows, changed architecture…
2. **Architecture diagrams** (`diagrams/`) — new external dependencies…
3. **A1-security-and-debt.md** — new security findings…
4. **CLAUDE.md** — changed build commands, new collectors…
````

Notes:

- **Numbered sequence** (`00`, `01`, …, `09`) signals reading order. New engineers go top-to-bottom.
- **Appendices** (`A1`, `A2`) separate reference material that isn't part of the main onboarding flow.
- The **"Maintenance" section is itself indexable** — colleagues querying "which doc to update when I add a new data collector" hit this section.
- `diagrams/cloudstatus-technical.drawio` keeps the **editable source** rather than exported images. Future edits don't require re-creating the diagram.

### Pattern B exemplar (planned)

An excerpt demonstrating Pattern B (medium README + specialized `docs/`) from `Global.FeatureManagement` will be added once the `fix/cohort-removal-propagation` branch merges to main. The pattern is described in the "Two valid patterns" section above.
