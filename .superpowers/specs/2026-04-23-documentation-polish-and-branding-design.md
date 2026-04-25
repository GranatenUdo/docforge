# Spec: Documentation polish & branding

**Date:** 2026-04-23
**Target release:** v0.2.0
**Status:** design approved; pending user spec review before implementation plan

## Context

docforge has reached Phase 4 operational readiness (spec C4) with strong
underlying engineering: spec-driven delivery, threat model, eval harness, CI,
operational runbook, Entra auth, per-source error isolation, query-log
governance. The public-facing surface has not caught up — the README is a
functional quick-start, the repository lacks standard OSS hygiene files, the
PyPI name has not been claimed (`pip install docforge-cli` in the README is
aspirational, not currently working), and the project has no visual identity
or positioning statement that communicates what docforge is *for* versus the
dense and growing field of adjacent tools (Onyx, Atlassian Rovo MCP,
zilliztech/claude-context, Cursor's built-in indexing, Copilot Spaces, Cody,
LangChain DIY).

This spec covers the documentation, repo-hygiene, visual-identity, and
artifact work needed to close that gap. It stops short of outbound promotion
(Hacker News, Reddit, LinkedIn/Twitter): those are deliberately deferred.

## Goals

1. **A self-contained README that sells docforge to a senior reader in 60
   seconds** — a clear tagline, a prominent comparison table, and explicit
   "when to use / when not to use" guidance that preempts "why not Onyx?"
   style objections.
2. **Standard OSS repository hygiene** — CHANGELOG, SECURITY, CODE_OF_CONDUCT,
   ROADMAP, issue/PR templates, enabled Discussions, tagged releases, a
   working PyPI package.
3. **A coherent visual identity** — monogram logo, two-colour palette,
   consistent typography, social preview card, SVG architecture diagram,
   30-second demo artifact.
4. **A microsite** that hosts expanded docs and a launch blog post.
5. **A v0.2.0 release** that bundles all of the above into a single
   coherent milestone.

## Non-goals

- Hacker News submission, subreddit posts, LinkedIn or Twitter announcements.
- Coordinated "launch day" choreography.
- Feature work: no changes to ingest, MCP server, retrieval, or auth.
- Backfilling history: no rewriting of existing commits or tags for aesthetics.

## Audience & voice

Two audiences:

- **Adopters** — engineers evaluating self-hosted RAG + MCP options for their
  team.
- **Portfolio readers** — peers and prospective collaborators reading the
  maintainer's public work.

Voice: **opinionated-honest** (SQLite / Tailscale / rqlite model). Explicitly
names what docforge is and is not. Redirects readers to better-fit tools
(Onyx, Rovo, Cody) where relevant. Never overclaims.

## Design

### 1. Positioning & tagline

**Category claim:** *self-hosted context engine for AI coding assistants.*

**GitHub repo description** (~120 chars, shown in search and link previews):

> Self-hosted context engine for AI coding assistants. Index Confluence + git, serve over MCP, own your data.

**README hero:**

```markdown
# docforge

**The self-hosted context engine for AI coding assistants.**

Point docforge at your Confluence spaces and local git repositories. It
indexes, embeds, and serves them over MCP — so Claude Code, Cursor, Copilot,
and any assistant that speaks MCP can search your team's knowledge without
your data leaving your infrastructure.

docforge doesn't replace your AI assistant. It feeds it — turning Claude
Code, Cursor, Copilot, and anything else that speaks MCP into tools that
actually know your team's docs and code.
```

The complementarity paragraph is load-bearing: without it, readers see Cursor
and Copilot in the comparison table and misread docforge as a competitor to
the assistants themselves.

### 2. README structure

Top to bottom:

1. Hero (H1 + tagline + supporting paragraph + complementarity line).
2. Badges row (CI, PyPI, Python 3.12+, License, Ruff).
3. Hero demo (animated GIF — see §8).
4. **Why docforge** — comparison table.
5. **When to use / When NOT to use**.
6. Quick start.
7. How it works (current ASCII diagram replaced with SVG — see §8).
8. Command reference (existing table, kept).
9. Deploy to your infrastructure.
10. Configuration (short pointer to microsite).
11. Contributing (short pointer to `CONTRIBUTING.md`).
12. Evaluation & retrieval quality (one paragraph, drift-detection framing).
13. License / Credits (MIT + EmbeddingGemma + pgvector + FastMCP).

Changes from current README: the comparison moves above the quick start
(conversion priority); troubleshooting moves to a dedicated FAQ section at
the bottom, with less-common items migrated to the microsite.

### 3. Comparison table

```markdown
| Tool | Self-hosted | Integration | Confluence + code | Footprint | Complements AI assistants? |
|---|---|---|---|---|---|
| **docforge** | ✓ | MCP server | ✓ (Confluence + local git) | Minimal (PG + 1 container) | ✓ (any MCP client) |
| Atlassian Rovo MCP | ✗ (Cloud-only) | MCP server | Confluence only (Cloud) | SaaS | ✓ |
| zilliztech/claude-context | ✓ | MCP server | Code only | Minimal | ✓ |
| Onyx | ✓ | MCP + chat UI | ✓ (50+ connectors) | Heavy (Standard) / Minimal (Lite) | ✓ (+ its own UI) |
| Cursor codebase index + @Docs | ✗ | Proprietary | Code + public web docs | SaaS | — (built into Cursor only) |
| Copilot Spaces | ✗ | Proprietary (MCP for actions) | Code + attachments | SaaS | — (built into Copilot only) |
| Sourcegraph Cody | ✓ (Enterprise) | OpenCtx / MCP | ✓ (via OpenCtx) | Heavy (Sourcegraph platform) | — (built into Cody only) |
| LangChain / LlamaIndex DIY | ✓ | Whatever you build | You wire it | Depends | Depends |
```

Paragraph under the table:

> docforge is the narrow, focused option in this landscape: minimal
> footprint, MCP-native so it works with every assistant, and combines
> Confluence + code out of the box. It doesn't compete on connector count
> (Onyx wins there), visual UX (Cursor and Cody win), or SaaS convenience
> (Rovo). It competes on being **small, legible, vendor-neutral, and
> self-hosted** — four properties no commercial option offers together.

All competitor rows link to canonical sources (Atlassian blog for Rovo MCP,
GitHub repos for Onyx / claude-context, Cursor docs, Copilot community
discussion, Sourcegraph docs).

### 4. When to use / When NOT to use

```markdown
### ✅ When docforge fits

- You run Confluence Data Center/Server, or you want to self-host.
- Your team uses MCP-capable assistants (Claude Code, Cursor with MCP,
  Copilot with MCP, etc.).
- You want Confluence + git repos indexed together with one tool.
- Operational simplicity matters — one Postgres, one container,
  MIT-licensed code you can audit in an afternoon.

### ❌ When docforge is the wrong choice

- You need 50+ connectors (Slack, Jira, Gmail, Drive, Notion) → use
  **Onyx** or **Glean**.
- You need per-document ACLs enforced at query time → not yet supported;
  use **Onyx**.
- You need a chat UI for non-developers → docforge has no UI; use
  **Onyx**, **Glean**, or **Cody**.
- You're on Atlassian Cloud and happy with SaaS → **Atlassian Rovo MCP** is
  free and official.
- You need SSO / SCIM / RBAC → out of scope; docforge authenticates but
  doesn't authorize per-resource.
- Your corpus is very large (>100K pages/chunks) → dense-only retrieval
  without hybrid starts to degrade; on the roadmap.
- You need near-real-time updates → ingest is batch; no webhook-driven
  continuous sync yet.
- You need multilingual search evaluated → EmbeddingGemma is multilingual
  but docforge has no eval coverage on non-English corpora yet.
```

### 5. Badges

```markdown
[![CI](https://github.com/GranatenUdo/docforge/actions/workflows/ci.yml/badge.svg)](https://github.com/GranatenUdo/docforge/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/docforge-cli.svg)](https://pypi.org/project/docforge-cli/)
[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)
```

Excluded: stars counter, coverage percentage, "built with love" banners.

### 6. Repo hygiene files

| File | Purpose | Notes |
|---|---|---|
| `CHANGELOG.md` | Keep-a-Changelog format | Seed with v0.1.0 entry (existing Phase 1–3 work); populate v0.2.0 with this rebrand |
| `SECURITY.md` | Responsible disclosure | Email contact; 7-day ack SLA; supported versions = latest minor |
| `CODE_OF_CONDUCT.md` | Community norms | Contributor Covenant 2.1, boilerplate |
| `ROADMAP.md` | Forward motion signal | "Next up / being considered / out of scope" format (see §6.1) |
| `.github/ISSUE_TEMPLATE/bug_report.yml` | Structured bug reports | Version, repro steps, logs |
| `.github/ISSUE_TEMPLATE/feature_request.yml` | Feature proposals | Use case, alternatives considered, why docforge |
| `.github/ISSUE_TEMPLATE/config.yml` | Disable blank issues; route casual Q&A to Discussions | |
| `.github/pull_request_template.md` | PR checklist | Tests, CHANGELOG entry, docs updated |

#### 6.1 ROADMAP.md content

```markdown
# Roadmap

docforge follows a signal-over-ritual roadmap: we list what we're actively
working on and what's explicitly out of scope. Dates are aspirational, not
committed.

## Next up (0.3.x)

- **Hybrid retrieval** (BM25 + dense) — Postgres `tsvector` + weighted fusion.
- **Chunk overlap** — small token overlap between consecutive chunks.
- **MCP identity via session**, not per-call args — remove `user_name` /
  `team_name` from the tool signature.

## Being considered (0.4.x+)

- **Per-source ACLs** — honor Confluence space permissions at query time.
- **Confluence Data Center auth hardening** — SSO / SAML / PAT flows.
- **Incremental Confluence ingest** — `updatedSince` API instead of hash-diff.

## Explicitly out of scope

- A web chat UI (use Onyx or Glean if you need one).
- 50-connector sprawl (Slack, Drive, Notion, Jira, Gmail).
- Multi-tenant SaaS (docforge assumes a single-company trust boundary).
```

### 7. GitHub repo settings (UI)

- **Description:** set to the repo description line from §1.
- **Website:** link to the microsite once live (§9).
- **Topics:** `mcp`, `rag`, `confluence`, `ai-coding-assistant`, `llm`,
  `embeddings`, `pgvector`, `self-hosted`, `claude-code`, `cursor`, `copilot`.
- **Discussions:** enabled. Categories: *Announcements*, *Q&A*, *Ideas*,
  *Show and tell*.
- **Social preview:** upload the 1280×640 card (§8.4).
- **Issues:** keep on, with the structured templates routing casual Q&A to
  Discussions via `config.yml`.
- **Wiki:** off.

### 8. Visual identity & artifacts

#### 8.1 Logo

**Monogram** ("df" or a custom glyph) as SVG. Scales from 16px favicon to
1280×640 social card. Simple enough to hand-author or generate with a
designer in <1 day. Wordmark (`docforge` in JetBrains Mono, weight 500,
tight letter-spacing) used alongside the monogram where space allows.

Deliverable: `docs/assets/logo.svg`, `docs/assets/logo-mono.svg` (single
colour), favicon set (`.ico`, `apple-touch-icon.png`, 32×32, 16×16) under
`docs/assets/favicon/`.

#### 8.2 Palette — "Graphite + Amber"

```
Primary text / dark surface:  #1a1a1a
Background light:             #fafaf7
Accent:                       #d97706  (amber-600)
Muted:                        #737373
Success:                      #16a34a  (restrained, for status only)
Destructive:                  #dc2626  (restrained, for errors only)
```

Amber is uncommon as a primary accent in dev tools (most go purple-blue or
Claude-orange); warm neutrals read as carefully made vs default Tailwind
slate.

#### 8.3 Typography

- **Wordmark:** JetBrains Mono, lowercase, weight 500, tight letter-spacing.
- **Microsite headings:** Inter or system-ui.
- **Body:** system font stack.
- **Code:** JetBrains Mono.

Two typefaces maximum.

#### 8.4 Social preview card (1280×640 PNG)

Layout: monogram + wordmark upper-left, tagline ("The self-hosted context
engine for AI coding assistants.") centred, four pill labels at the bottom
(*Self-hosted · MCP · Vendor-neutral · MIT*). Background `#1a1a1a`, accent
`#d97706`.

Produced once as SVG, exported to PNG at `docs/assets/social-preview.png`.
Uploaded via GitHub repo settings.

#### 8.5 Architecture SVG diagram

Replaces the current ASCII diagram in the README and microsite. Shows data
flow: Confluence space + local git repos → `docforge ingest` → Postgres +
pgvector → `docforge serve` → MCP → AI assistants (Claude Code, Cursor,
Copilot).

Authored in Excalidraw or hand-written SVG. Rendered in the brand palette:
graphite boxes, amber flow arrows, monospace labels. Exported at 2× for
retina.

Deliverable: `docs/assets/architecture.svg` and embedded reference in the
README's "How it works" section.

#### 8.6 Demo GIF / screencast

**Length:** 30 seconds. **File budget:** ≤2 MB (GitHub's sweet spot for
inline rendering).

Script:

| Time | Frame |
|---|---|
| 0–3s | Claude Code (or Cursor) open with an empty prompt |
| 3–8s | Type: "How does our team handle rate-limiting in the API gateway?" |
| 8–12s | Tool-call flash: `search_documentation` → `docforge` → chunks stream in |
| 12–22s | Assistant's answer appears, citing two Confluence pages + one `CLAUDE.md` snippet with source URLs |
| 22–28s | Cut to terminal: `docforge status` shows `44 sources · 1,770 chunks · healthy` |
| 28–30s | Logo + tagline outro |

Capture via OBS or Loom; post-process with `gifski` or `ffmpeg`. If the 2 MB
ceiling breaks, fall back to MP4 with an SVG poster (GitHub renders MP4
inline).

Deliverable: `docs/assets/demo.gif` (or `.mp4` + `.svg` poster fallback).

### 9. Microsite

**Stack:** Astro + Starlight theme. Markdown-native, zero-config,
5-minute GitHub Pages deploy.

**Pages:**

```
/                    — landing (mirrors README hero, comparison, when-not-to-use)
/docs/install        — 5-minute quick start
/docs/architecture   — the SVG diagram + explanation
/docs/deployment     — Azure Container Apps + Postgres flexible
/docs/faq            — expanded FAQ migrated from README troubleshooting
/blog                — launch blog post (§10)
```

**Hosting:** initially at `granatenudo.github.io/docforge` or
`<repo>.pages.dev`. Custom domain (`docforge.dev` / `docforge.io`) is a
nice-to-have, not a blocker.

**What stays in repo vs. microsite:**

- **Repo README:** hero, comparison, when-not-to-use, quick start, pointers
  to everything else. Remains the primary adoption surface.
- **Microsite:** expanded docs, architecture deep-dive, FAQ, blog. Optimised
  for search engines and newcomer reading.

### 10. Launch blog post

Written as a content artifact on the microsite `/blog`. Not distributed
externally (per scope decision).

**Title:** *docforge — a self-hosted context engine for AI coding assistants*

**Target length:** ~1,800 words.

**Outline:**

1. The gap (200w). AI coding assistants answer generically about your team's
   code because they don't know it. Retrieval problem, not model problem.
2. What docforge is, in 90 seconds (250w). Point at Confluence + git →
   indexes → serves MCP → any assistant searches your knowledge. One
   screenshot, one code block.
3. Where it sits vs. alternatives (300w). The comparison table with the
   "how to read this" paragraph. Honest about where Onyx / Rovo / Cursor
   @Docs beat docforge.
4. The design choices (400w). Why Postgres + pgvector over dedicated vector
   DB. Why EmbeddingGemma. Why MCP-first. Why no ACLs yet. Why narrow
   solo-maintainer tools punch above their weight.
5. What's shaky today (250w). Dense-only retrieval; no chunk overlap; no
   per-source ACLs. Honest roadmap. "When NOT to use" list inline.
6. Try it in five minutes (300w). Copy-pasteable quick start. Screenshot of
   the answer.
7. Credits & what's next (100w). EmbeddingGemma, pgvector, FastMCP, MCP
   spec team. Follow on GitHub; Discussions open.

Deliverable: a blog post authored in the microsite's blog directory
(exact path determined by the Starlight layout chosen in Phase 4). File
name pattern: `YYYY-MM-DD-introducing-docforge.md`, date set at publish.

### 11. Release strategy

1. **Claim `docforge-cli` on PyPI.** If the name is taken, fall back to
   `docforge` or `docforge-server`. Publish v0.1.1 from current HEAD
   (commit `491db97`) so `pip install docforge-cli` works *before* any
   README change ships.
2. **Retro-tag v0.1.0** at commit `491db97` with a minimal release note:
   "First tagged release, covering Phase 1–3 (MVP + Phase 3 quality). Phase
   4 hardening in flight."
3. **Cut v0.2.0** when all of this spec is merged. Release notes summarise:
   rebrand, comparison-driven README, repo scaffolding, visual identity,
   microsite, blog post.
4. **CHANGELOG discipline** from v0.2.0 forward — every PR either adds a
   changelog entry or is marked `no-changelog` in the PR template.
5. **Release workflow** (`.github/workflows/release.yml`) — tag-triggered,
   runs tests, builds wheel, publishes to PyPI via trusted publishing,
   creates a GitHub Release with CHANGELOG-derived notes. (Manual
   `twine upload` is an acceptable interim; automate when convenient.)
6. **SemVer.** Until 1.0, breaking changes bump minor with a prominent
   CHANGELOG warning. After 1.0, breaking changes bump major.

## Phases & ordering

Work proceeds in four phases. Pace is flexible; the *order* is the
constraint.

| Phase | Ships |
|---|---|
| **1 — content** | Claim `docforge-cli` on PyPI, publish v0.1.1, retro-tag v0.1.0, rewrite README (hero + comparison + when-not-to-use + complementarity + trimmed troubleshooting), add badges, update repo description + topics |
| **2 — hygiene** | CHANGELOG, SECURITY, CODE_OF_CONDUCT, ROADMAP, issue/PR templates, `release.yml`, enable Discussions |
| **3 — visuals** | Monogram logo, palette locked, SVG architecture diagram, 30s demo GIF, social preview card |
| **4 — microsite + blog + release** | Astro + Starlight microsite live, launch blog post written and published on the microsite blog, cut v0.2.0 with release notes covering all four phases |

Hard dependencies:

- Phase 1 blocks all others (the PyPI name must exist before the README
  references it).
- Phase 4 depends on Phase 3 (the microsite embeds logo, diagram, demo).
- `release.yml` (built in Phase 2) is what cuts the v0.2.0 tag in Phase 4.

## Out of scope

- Hacker News submission.
- Subreddit posts (r/selfhosted, r/LocalLLaMA, r/ClaudeAI, r/cursor,
  r/Python, r/opensource, r/programming).
- LinkedIn / Twitter announcements.
- Coordinated launch-day choreography.
- Any feature work (ingest, retrieval, MCP, auth unchanged).
- Custom domain purchase.

These may be revisited in a later spec. They are not part of this one.

## Success criteria

A reader who lands on the repo cold can:

1. Understand what docforge is in under 60 seconds.
2. See where it fits (and doesn't fit) vs. alternatives in under 2 minutes.
3. Install and run a working demo via `pip install docforge-cli` +
   `docforge init` in under 5 minutes.
4. See that the project is actively maintained (badges green, recent
   release, responsive issues).

A peer reviewing the repo as a portfolio artifact can:

1. Read the public-facing material and form a coherent view of the
   maintainer's judgment (positioning, honesty, engineering discipline)
   without digging into source.
2. Find evidence of engineering craft (threat model, eval harness, runbook,
   CONTRIBUTING) when they do dig in.

A v0.2.0 release tag exists, published to PyPI, with release notes matching
the CHANGELOG.

## Open questions

1. **PyPI name availability for `docforge-cli`.** Verified 404 on
   `pypi.org/pypi/docforge-cli/json` at spec time (2026-04-23). Needs
   re-verification and claim immediately in Phase 1.
2. **Microsite domain.** Default: GitHub Pages subdomain. A custom domain is
   a nice-to-have; decide at Phase 4.
3. **Logo authoring.** Self-designed SVG monogram vs. commissioned designer.
   Default: self-designed to keep scope contained.

## Implementation plan

To be produced by the `writing-plans` skill after this spec is reviewed and
approved.
