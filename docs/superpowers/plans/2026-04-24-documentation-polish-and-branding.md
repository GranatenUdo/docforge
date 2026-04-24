# Documentation Polish & Branding Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship v0.2.0 with a credible public-facing surface: a positioning-led README with a prominent competitor comparison and "when NOT to use" section, standard OSS repo hygiene files, a monogram logo + Graphite+Amber palette, SVG architecture diagram, demo GIF, Astro+Starlight microsite, and a launch blog post published on the microsite. No outbound promotion (HN, subreddits, social) is part of this plan.

**Architecture:** Four sequential phases, one PR branch per phase, merged in order. Phase 1 is the foundation (PyPI name must be claimed before the README references it). Phase 4 ships the v0.2.0 tag + release notes covering all four phases. Content-heavy deliverables reference the committed spec at `docs/superpowers/specs/2026-04-23-documentation-polish-and-branding-design.md` — that spec is the source of truth for README text, comparison table, "when not to use" list, and ROADMAP content. This plan tells the engineer which file to put it in and how to verify.

**Tech Stack:** Python 3.12+ (existing docforge tooling), GitHub Actions (release workflow), Astro + Starlight (microsite), Excalidraw or hand-authored SVG (diagram), OBS/Loom + gifski/ffmpeg (demo capture), PyPI trusted publishing (release automation).

**Spec:** `docs/superpowers/specs/2026-04-23-documentation-polish-and-branding-design.md`

---

## Prerequisites

One-time setup before starting. All tasks below assume these exist.

- **Python 3.12+** with `pip`, `build`, `twine` (install `build` and `twine` via pip).
- **Node.js 20+** with `npm` (for Phase 4's Astro microsite).
- **`gh` CLI** authenticated against the `GranatenUdo` account with admin on the `docforge` repo.
- **git** with push access to `GranatenUdo/docforge`.
- **PyPI account** with an API token, and (for Phase 2) rights to configure trusted publishing on the `docforge-cli` project.
- **Image tooling** for Phase 3: `rsvg-convert` (from `librsvg`) or the online fallback at https://realfavicongenerator.net/; `magick` (ImageMagick) for `.ico` assembly.
- **Video tooling** for Phase 3's demo: `ffmpeg`, `gifski`, and a screen recorder (OBS, Loom, or QuickTime).
- **A reachable docforge deployment with a populated index** for recording the demo — either the DocuWare CCL deployment (per spec) or a local instance populated via `docforge ingest`.

---

## File Structure

### New files

```
CHANGELOG.md                                           — Keep-a-Changelog format, v0.1.0 + v0.2.0 entries
SECURITY.md                                            — responsible disclosure
CODE_OF_CONDUCT.md                                     — Contributor Covenant 2.1 (downloaded, not inlined)
ROADMAP.md                                             — Next up / being considered / out of scope
.github/ISSUE_TEMPLATE/bug_report.yml                  — structured bug form
.github/ISSUE_TEMPLATE/feature_request.yml             — structured feature form
.github/ISSUE_TEMPLATE/config.yml                      — blank-issues disabled; Discussions link
.github/pull_request_template.md                       — PR checklist
.github/workflows/release.yml                          — tag-triggered PyPI + GitHub Release
docs/assets/logo.svg                                   — two-color monogram
docs/assets/logo-mono.svg                              — single-color variant
docs/assets/favicon/favicon.ico                        — derived from logo
docs/assets/favicon/favicon-16x16.png                  — derived from logo
docs/assets/favicon/favicon-32x32.png                  — derived from logo
docs/assets/favicon/apple-touch-icon.png               — derived from logo
docs/assets/architecture.svg                           — data-flow diagram
docs/assets/demo.gif                                   — 30-second demo capture (or demo.mp4 + poster.svg)
docs/assets/social-preview.png                         — 1280x640 social card
microsite/                                             — Astro + Starlight project (structure per Astro docs)
microsite/src/content/docs/index.md                    — landing
microsite/src/content/docs/install.md                  — quick start
microsite/src/content/docs/architecture.md             — diagram + explanation
microsite/src/content/docs/deployment.md               — Azure deploy guide
microsite/src/content/docs/faq.md                      — migrated from README troubleshooting
microsite/src/content/blog/2026-XX-XX-introducing-docforge.md  — launch post
```

### Modified files

```
README.md                                              — full rewrite per spec sections 1-5
pyproject.toml                                         — version bumps (0.1.0 → 0.1.1 → 0.2.0)
```

### Actions with no file

- PyPI: claim `docforge-cli`, publish v0.1.1, later v0.2.0
- Git: retro-tag v0.1.0 at commit `491db97`, later v0.2.0 at Phase 4 HEAD
- GitHub repo settings (UI): description, topics, website, Discussions, social preview upload

---

## Phase 0 — Setup

### Task 1: Verify clean starting state

**Files:** None (git-only).

- [ ] **Step 1: Confirm master is clean and up to date**

Run:
```bash
cd /e/docforge && git checkout master && git pull && git status
```
Expected: `On branch master, Your branch is up to date with 'origin/master', nothing to commit, working tree clean`.

- [ ] **Step 2: Verify the committed spec exists**

Run:
```bash
ls docs/superpowers/specs/2026-04-23-documentation-polish-and-branding-design.md
```
Expected: file listed. The spec is the content source of truth for this plan.

- [ ] **Step 3: Verify release-blocking fact — PyPI name availability**

Run:
```bash
curl -s -o /dev/null -w '%{http_code}' https://pypi.org/pypi/docforge-cli/json
```
Expected: `404` (name is available). If `200`, the name is taken — stop and choose a fallback (`docforge`, `docforge-server`) before proceeding; all subsequent README and spec references will need to be updated to the chosen name.

No commit.

---

## Phase 1 — Content (README + PyPI + tags)

Creates branch `phase-1-content`. Ships: working `pip install`, retroactive v0.1.0 tag, full README rewrite, updated repo description/topics.

### Task 2: Create Phase 1 branch

**Files:** None (git-only).

- [ ] **Step 1: Create and check out the branch**

```bash
git checkout -b phase-1-content
```
Expected: `Switched to a new branch 'phase-1-content'`.

No commit.

### Task 3: Retro-tag v0.1.0

**Files:** None (git-only).

- [ ] **Step 1: Tag commit 491db97 as v0.1.0**

```bash
git tag -a v0.1.0 491db97 -m "First tagged release. Covers Phase 1-3 (MVP + Phase 3 quality). Phase 4 hardening in flight."
```
Expected: tag created locally.

- [ ] **Step 2: Verify tag**

```bash
git show v0.1.0 --stat --no-patch
```
Expected: shows commit 491db97 and the tag message.

- [ ] **Step 3: Do not push the tag yet**

The tag push happens in Task 5 once PyPI v0.1.1 is confirmed. If anything goes wrong, a local-only tag is trivially removable with `git tag -d v0.1.0`.

No commit.

### Task 4: Bump version to 0.1.1 and build

**Files:**
- Modify: `E:/docforge/pyproject.toml:7`

- [ ] **Step 1: Bump version**

Change `pyproject.toml` line 7 from `version = "0.1.0"` to `version = "0.1.1"`.

- [ ] **Step 2: Install build tooling (one-time)**

```bash
python -m pip install --upgrade build twine
```

- [ ] **Step 3: Build the distribution**

```bash
rm -rf dist/ build/ *.egg-info && python -m build
```
Expected: `dist/docforge_cli-0.1.1.tar.gz` and `dist/docforge_cli-0.1.1-py3-none-any.whl` created.

- [ ] **Step 4: Sanity-check the wheel contents**

```bash
python -m zipfile -l dist/docforge_cli-0.1.1-py3-none-any.whl | head -40
```
Expected: includes `docforge/cli.py`, `docforge/templates/...`, `docforge/sql/...`.

- [ ] **Step 5: Commit the version bump**

```bash
git add pyproject.toml
git commit -m "chore: bump version to 0.1.1"
```

### Task 5: Publish v0.1.1 to PyPI

**Files:** None (PyPI action).

This task requires a PyPI account and an API token. If the maintainer does not have these set up, see https://pypi.org/help/#apitoken before starting.

- [ ] **Step 1: Upload to TestPyPI first (dry run)**

```bash
python -m twine upload --repository testpypi dist/*
```
Expected: upload succeeds. Verify at https://test.pypi.org/project/docforge-cli/.

- [ ] **Step 2: Upload to production PyPI**

```bash
python -m twine upload dist/*
```
Expected: upload succeeds. Verify at https://pypi.org/project/docforge-cli/.

- [ ] **Step 3: Smoke-test the install on a clean environment**

```bash
python -m venv /tmp/docforge-smoke && source /tmp/docforge-smoke/bin/activate && pip install docforge-cli && docforge --help && deactivate && rm -rf /tmp/docforge-smoke
```
Expected: `docforge --help` prints the CLI usage.

- [ ] **Step 4: Push the v0.1.0 tag (deferred from Task 3)**

```bash
git push origin v0.1.0
```
Expected: tag appears in GitHub Releases list (untitled release pending).

No commit.

### Task 6: Rewrite README

**Files:**
- Modify: `E:/docforge/README.md` (full rewrite)

The source of truth for the new README content is the committed spec at `docs/superpowers/specs/2026-04-23-documentation-polish-and-branding-design.md`. Assemble the README from these spec sections in order:

| README section | Spec section |
|---|---|
| H1 + tagline + supporting paragraph + complementarity line | §1 |
| Badge row | §5 |
| "Why docforge" — comparison table + "how to read this" paragraph | §3 |
| When to use / When NOT to use | §4 |
| Quick start (existing content, keep; fix any stale references) | N/A — keep existing with small edits |
| How it works (existing ASCII diagram for now — the SVG replaces it in Phase 3) | N/A — keep existing |
| Command reference | N/A — keep existing table unchanged |
| Deploy to your infrastructure | N/A — keep existing |
| Configuration (brief, pointer-only) | N/A — compress existing |
| Contributing (pointer to `CONTRIBUTING.md`) | N/A — one line |
| Evaluation & retrieval quality (one paragraph, drift-detection framing) | spec §2 item 12 — authored inline; see Task 6 Step 2 for content guidance |
| FAQ (migrated from current README troubleshooting, trimmed) | N/A |
| License + Credits | N/A |

- [ ] **Step 1: Read the spec sections listed above**

```bash
cat docs/superpowers/specs/2026-04-23-documentation-polish-and-branding-design.md
```
Read §§1, 3, 4, 5, 6 carefully. These are the verbatim content you embed in the README.

- [ ] **Step 2: Replace README.md with the new structure**

Open `README.md` in an editor and replace its contents with the README assembled per the table above. Specifically:

- Use the exact tagline, supporting paragraph, and complementarity line from spec §1.
- Use the exact badge markdown from spec §5.
- Use the exact comparison table markdown from spec §3 (eight rows including the **docforge** highlight row).
- Use the exact "How to read this" paragraph from spec §3.
- Use the exact "When to use / When NOT to use" bullet lists from spec §4.
- For the Quick Start: keep the existing commands; add one clarifying line under the Quick Start block that reads: *"The git crawler indexes **local** filesystem paths — docforge does not clone GitHub URLs. Clone first, then point docforge at the checkout path."*
- For Evaluation: one paragraph stating that retrieval quality is measured via a drift-detection eval harness (`docforge/scripts/eval_search.py`), not an absolute quality threshold, and linking to `docforge/scripts/README.md`.
- For FAQ: move the existing README troubleshooting items (database, HF token, first-run slowness, skip-when-unchanged) under a `## FAQ` heading at the bottom. No other changes to their content.

- [ ] **Step 3: Render-check**

```bash
# Inspect rendered Markdown locally (optional)
npx markdown-cli README.md | head -80
```
Or open the file in VS Code's Markdown preview. Verify:

- All badges point to real URLs.
- The comparison table renders as a table, not raw pipes.
- The "When to use / When NOT to use" sections have checkmark and cross emojis.
- No broken internal links.

- [ ] **Step 4: Link-check**

```bash
# Extract every URL from README and curl -I each, expecting 2xx/3xx
grep -oE '(https?://[^ )]+)' README.md | sort -u | while read url; do echo -n "$url: "; curl -sIo /dev/null -w '%{http_code}\n' "$url"; done
```
Expected: every link returns 200, 301, 302, or 308. If any return 4xx/5xx, fix before committing.

- [ ] **Step 5: Commit**

```bash
git add README.md
git commit -m "docs: rewrite README with positioning, comparison table, and when-not-to-use"
```

### Task 7: Update GitHub repo description, topics, and website (UI, manual)

**Files:** None (GitHub web UI or `gh` CLI).

- [ ] **Step 1: Set repo description**

```bash
gh repo edit GranatenUdo/docforge --description "Self-hosted context engine for AI coding assistants. Index Confluence + git, serve over MCP, own your data."
```

- [ ] **Step 2: Inspect existing topics, then clear any you do not want**

```bash
gh repo view GranatenUdo/docforge --json repositoryTopics
```

`gh repo edit --add-topic` *appends* — it does not replace. For any topic in the output that is NOT in the target list, remove it individually:

```bash
gh repo edit GranatenUdo/docforge --remove-topic <old-topic>
```

Then add the target set:

```bash
gh repo edit GranatenUdo/docforge --add-topic mcp,rag,confluence,ai-coding-assistant,llm,embeddings,pgvector,self-hosted,claude-code,cursor,copilot
```

- [ ] **Step 3: Website field — leave unset for now**

The microsite URL is assigned in Phase 4. Leave the Website field empty until then.

- [ ] **Step 4: Verify**

```bash
gh repo view GranatenUdo/docforge --json description,repositoryTopics
```
Expected: JSON output shows the new description and the eleven topics.

No commit.

### Task 8: Open Phase 1 PR

**Files:** None (git + gh).

- [ ] **Step 1: Push the branch**

```bash
git push -u origin phase-1-content
```

- [ ] **Step 2: Open the PR**

```bash
gh pr create --base master --title "Phase 1: rewrite README, claim PyPI, tag v0.1.0" --body "$(cat <<'EOF'
## Summary
- Retro-tagged v0.1.0 at commit 491db97.
- Published docforge-cli 0.1.1 to PyPI (so `pip install docforge-cli` now works).
- Rewrote README with positioning tagline, comparison table, when-not-to-use section, complementarity line, and FAQ reorganization.
- Updated repo description + topics.

Spec: docs/superpowers/specs/2026-04-23-documentation-polish-and-branding-design.md

## Test plan
- [ ] CI green on branch
- [ ] `pip install docforge-cli==0.1.1` works on a clean VM
- [ ] README renders correctly on the PR preview
- [ ] All README links return 2xx/3xx

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

- [ ] **Step 3: Merge after review**

Await CI + review. Once green and approved, merge via `gh pr merge --squash`. Delete the branch.

- [ ] **Step 4: Pull master back locally**

```bash
git checkout master && git pull
```

---

## Phase 2 — Repo hygiene

Creates branch `phase-2-hygiene`. Ships: `CHANGELOG.md`, `SECURITY.md`, `CODE_OF_CONDUCT.md`, `ROADMAP.md`, issue and PR templates, release workflow, Discussions enabled.

### Task 9: Create Phase 2 branch

- [ ] **Step 1: Branch from fresh master**

```bash
git checkout master && git pull && git checkout -b phase-2-hygiene
```

No commit.

### Task 10: Add CHANGELOG.md

**Files:**
- Create: `E:/docforge/CHANGELOG.md`

- [ ] **Step 1: Write the file**

Write this exact content to `CHANGELOG.md`:

```markdown
# Changelog

All notable changes to docforge are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- `CHANGELOG.md`, `SECURITY.md`, `CODE_OF_CONDUCT.md`, `ROADMAP.md`.
- GitHub issue and pull-request templates under `.github/`.
- Release workflow (`.github/workflows/release.yml`).

## [0.1.1] - 2026-04-24

### Fixed
- Published to PyPI so `pip install docforge-cli` works.

## [0.1.0] - 2026-04-23

First tagged release. Covers Phase 1–3 (MVP + Phase 3 quality). Phase 4
hardening (operational readiness, security, team tagging) is in flight.
```

- [ ] **Step 2: Commit**

```bash
git add CHANGELOG.md
git commit -m "docs: add CHANGELOG"
```

### Task 11: Add SECURITY.md

**Files:**
- Create: `E:/docforge/SECURITY.md`

- [ ] **Step 1: Write the file**

Write this exact content to `SECURITY.md`:

```markdown
# Reporting security issues

Please do **not** open a public GitHub issue for security concerns.

Instead, email the maintainer: **tobias.ens@docuware.com**. Include:

- A description of the issue and its impact.
- Reproduction steps (minimal, please).
- The docforge version (`docforge --version`) and any relevant environment details.

You can expect an acknowledgement within **7 days**. Further communication and
coordination happen over email until a fix is available.

## Supported versions

The **latest minor release** is supported. When a fix ships, it lands in the next
patch release. Users on older minor versions are encouraged to upgrade.

## Scope

This policy covers docforge itself. For issues in dependencies (EmbeddingGemma,
FastMCP, pgvector, FastAPI, etc.), please report upstream first; we will
coordinate follow-up.
```

- [ ] **Step 2: Commit**

```bash
git add SECURITY.md
git commit -m "docs: add SECURITY policy"
```

### Task 12: Add CODE_OF_CONDUCT.md

**Files:**
- Create: `E:/docforge/CODE_OF_CONDUCT.md`

The file content is the canonical Contributor Covenant 2.1. Do not retype it — download it verbatim.

- [ ] **Step 1: Download Contributor Covenant 2.1**

```bash
curl -sSL https://www.contributor-covenant.org/version/2/1/code_of_conduct/code_of_conduct.md -o CODE_OF_CONDUCT.md
```
Expected: `CODE_OF_CONDUCT.md` created, ~5 KB.

- [ ] **Step 2: Fill in the contact placeholder**

The downloaded template contains a `[INSERT CONTACT METHOD]` placeholder in the "Enforcement" section. Replace it with `tobias.ens@docuware.com`. If your `sed` differs, open the file and edit by hand — one occurrence.

```bash
sed -i 's/\[INSERT CONTACT METHOD\]/tobias.ens@docuware.com/' CODE_OF_CONDUCT.md
```

- [ ] **Step 3: Verify no remaining placeholders**

```bash
grep -n 'INSERT' CODE_OF_CONDUCT.md || echo "no placeholders"
```
Expected: `no placeholders`.

- [ ] **Step 4: Commit**

```bash
git add CODE_OF_CONDUCT.md
git commit -m "docs: add Contributor Covenant 2.1 Code of Conduct"
```

### Task 13: Add ROADMAP.md

**Files:**
- Create: `E:/docforge/ROADMAP.md`

- [ ] **Step 1: Write the file**

Use the exact content from spec §6.1 (ROADMAP.md content). Copy it verbatim into `ROADMAP.md`.

- [ ] **Step 2: Verify**

```bash
head -5 ROADMAP.md
```
Expected: the file starts with `# Roadmap`.

- [ ] **Step 3: Commit**

```bash
git add ROADMAP.md
git commit -m "docs: add ROADMAP"
```

### Task 14: Add issue templates

**Files:**
- Create: `E:/docforge/.github/ISSUE_TEMPLATE/bug_report.yml`
- Create: `E:/docforge/.github/ISSUE_TEMPLATE/feature_request.yml`
- Create: `E:/docforge/.github/ISSUE_TEMPLATE/config.yml`

- [ ] **Step 1: Create the template directory**

```bash
mkdir -p .github/ISSUE_TEMPLATE
```

- [ ] **Step 2: Write `bug_report.yml`**

```yaml
name: Bug report
description: Something isn't working as documented
labels: ["bug"]
body:
  - type: input
    id: version
    attributes:
      label: docforge version
      description: Output of `docforge --version`
      placeholder: "0.2.0"
    validations:
      required: true
  - type: textarea
    id: what-happened
    attributes:
      label: What happened?
      description: What did you do, what did you expect, what happened instead?
    validations:
      required: true
  - type: textarea
    id: logs
    attributes:
      label: Relevant logs
      description: Paste any relevant log output. Redact secrets.
      render: shell
  - type: input
    id: environment
    attributes:
      label: Environment
      description: OS, Python version, Postgres version
      placeholder: "Ubuntu 24.04, Python 3.12.3, Postgres 16 with pgvector 0.7"
```

- [ ] **Step 3: Write `feature_request.yml`**

```yaml
name: Feature request
description: Propose a change or addition
labels: ["enhancement"]
body:
  - type: textarea
    id: use-case
    attributes:
      label: Use case
      description: What problem are you trying to solve?
    validations:
      required: true
  - type: textarea
    id: alternatives
    attributes:
      label: Alternatives considered
      description: Other tools or workarounds you have tried. Why do they not fit?
  - type: textarea
    id: why-docforge
    attributes:
      label: Why docforge
      description: Why is this the right project to solve this? (See ROADMAP.md for explicit out-of-scope items.)
```

- [ ] **Step 4: Write `config.yml`**

```yaml
blank_issues_enabled: false
contact_links:
  - name: Question or discussion
    url: https://github.com/GranatenUdo/docforge/discussions
    about: For questions, ideas, and general discussion, please use GitHub Discussions.
```

- [ ] **Step 5: Commit**

```bash
git add .github/ISSUE_TEMPLATE/
git commit -m "chore: add issue templates"
```

### Task 15: Add pull_request_template.md

**Files:**
- Create: `E:/docforge/.github/pull_request_template.md`

- [ ] **Step 1: Write the file**

```markdown
## Summary

<!-- What does this PR do? One or two sentences. -->

## Checklist

- [ ] Tests added or updated (or `no-tests` explained below).
- [ ] `CHANGELOG.md` entry added under `## [Unreleased]` (or `no-changelog` explained below).
- [ ] Docs updated if behavior or configuration changed.
- [ ] CI green.

## Test plan

<!-- Commands and expected outcomes. -->
```

- [ ] **Step 2: Commit**

```bash
git add .github/pull_request_template.md
git commit -m "chore: add PR template"
```

### Task 16: Add release workflow

**Files:**
- Create: `E:/docforge/.github/workflows/release.yml`

- [ ] **Step 1: Write the workflow**

```yaml
name: release

on:
  push:
    tags:
      - 'v*'

jobs:
  build-and-publish:
    name: Build and publish to PyPI
    runs-on: ubuntu-latest
    permissions:
      contents: write
      id-token: write
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v6
        with:
          python-version: '3.12'
          cache: 'pip'
      - name: Install build
        run: python -m pip install --upgrade build
      - name: Build distribution
        run: python -m build
      - name: Publish to PyPI
        uses: pypa/gh-action-pypi-publish@release/v1
      - name: Create GitHub Release
        uses: softprops/action-gh-release@v2
        with:
          generate_release_notes: true
          files: |
            dist/*.whl
            dist/*.tar.gz
```

- [ ] **Step 2: Configure PyPI Trusted Publishing**

This requires a one-time manual setup at https://pypi.org/manage/project/docforge-cli/settings/publishing/:

- Add a trusted publisher with:
  - Owner: `GranatenUdo`
  - Repository: `docforge`
  - Workflow filename: `release.yml`
  - Environment name: *(leave blank)*

No token secret is needed; trusted publishing uses OIDC.

- [ ] **Step 3: Commit**

```bash
git add .github/workflows/release.yml
git commit -m "ci: add tag-triggered release workflow"
```

- [ ] **Step 4: Verify the workflow end-to-end with a disposable tag**

After the Phase 2 PR merges, push a disposable pre-release tag to confirm the workflow actually works. Catching misconfigured trusted publishing *now* is far cheaper than debugging during the Phase 4 v0.2.0 release.

```bash
git checkout master && git pull
git tag -a v0.1.2-rc1 -m "Release workflow verification tag."
git push origin v0.1.2-rc1
gh run watch $(gh run list --workflow=release.yml --limit 1 --json databaseId -q '.[0].databaseId')
```

Expected: the workflow runs, builds the distribution, and the PyPI publish step succeeds.

If it succeeds: the v0.1.2-rc1 release is now on PyPI. Yank it immediately so nobody installs it by accident:

```bash
python -m twine upload --skip-existing dist/*  # (already uploaded by CI; just in case)
# Yank the release:
# Navigate to https://pypi.org/project/docforge-cli/0.1.2rc1/ and click "Yank release".
# Or via the PyPI API — see https://warehouse.pypa.io/api-reference/integration-guide.html
```

And delete the git tag:

```bash
git push origin :refs/tags/v0.1.2-rc1
git tag -d v0.1.2-rc1
```

If it fails: read the Action logs. The most common failure is "OIDC token not permitted" — fix by completing trusted-publishing config in Step 2, then retry with a fresh tag (v0.1.2-rc2, etc.) until it passes.

### Task 17: Enable Discussions and configure categories

**Files:** None (GitHub settings).

- [ ] **Step 1: Enable Discussions via `gh`**

```bash
gh repo edit GranatenUdo/docforge --enable-discussions
```
Expected: no error. Verify with `gh repo view GranatenUdo/docforge --json hasDiscussionsEnabled`.

- [ ] **Step 2: Configure categories**

Navigate to `https://github.com/GranatenUdo/docforge/discussions` → *⋯* → *Manage discussions categories*. Ensure these four categories exist (create or rename as needed):

- **Announcements** (Announcement format, maintainers only)
- **Q&A** (Question/Answer format)
- **Ideas** (Open-ended format)
- **Show and tell** (Open-ended format)

Archive or delete any default categories you do not want.

- [ ] **Step 3: Verify the Issue-template config works**

Create a throwaway issue via the repo UI. The picker should show only *Bug report* and *Feature request* — no "Blank" option — and a link underneath pointing to Discussions. Cancel without submitting.

No commit.

### Task 18: Open Phase 2 PR

- [ ] **Step 1: Push the branch**

```bash
git push -u origin phase-2-hygiene
```

- [ ] **Step 2: Open the PR**

```bash
gh pr create --base master --title "Phase 2: repo hygiene (CHANGELOG, SECURITY, CoC, ROADMAP, templates, release workflow)" --body "$(cat <<'EOF'
## Summary
- Added CHANGELOG, SECURITY, CODE_OF_CONDUCT, ROADMAP.
- Added issue templates (bug, feature, config) and PR template.
- Added tag-triggered PyPI release workflow via trusted publishing.
- Discussions enabled with four categories (Announcements, Q&A, Ideas, Show and tell).

Spec: docs/superpowers/specs/2026-04-23-documentation-polish-and-branding-design.md

## Test plan
- [ ] CI green on branch
- [ ] Issue template picker shows only Bug / Feature + Discussions link
- [ ] Pushing a throwaway tag triggers release.yml (dry run — rollback afterward)

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

- [ ] **Step 3: Merge after review**

Await CI + review. `gh pr merge --squash`. Delete the branch.

- [ ] **Step 4: Pull master back locally**

```bash
git checkout master && git pull
```

---

## Phase 3 — Visual artifacts

Creates branch `phase-3-visuals`. Ships: monogram logo SVG, favicon set, architecture diagram SVG, social preview card PNG, demo GIF. Phase 3 produces assets; the microsite consumes them in Phase 4. Some steps are human-in-the-loop design work; the plan specifies deliverables and verification rather than pixel-level instructions.

### Task 19: Create Phase 3 branch

```bash
git checkout master && git pull && git checkout -b phase-3-visuals
mkdir -p docs/assets/favicon
```

No commit.

### Task 20: Create monogram logo SVG

**Files:**
- Create: `E:/docforge/docs/assets/logo.svg`
- Create: `E:/docforge/docs/assets/logo-mono.svg`

The logo is a geometric monogram of the letters "df", rendered on a graphite background with amber accents. This is design work — the plan specifies constraints and deliverables; the final mark is produced by the maintainer or a designer.

- [ ] **Step 1: Design the mark**

Constraints:
- Viewport: 128×128.
- Background: `#1a1a1a` (graphite).
- Foreground: `#fafaf7` (off-white) with one amber `#d97706` accent.
- Reads cleanly at 16×16 (favicon size) and at 1280×640 (social card).
- Plain SVG (no embedded fonts — convert any text to paths so it renders without font availability).

A minimal starter that meets these constraints (replace the inner `<path>` with the actual mark):

```xml
<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 128 128" width="128" height="128" role="img" aria-label="docforge logo">
  <rect width="128" height="128" rx="20" fill="#1a1a1a"/>
  <!-- df monogram: replace this path with the final mark, converted to outlines. -->
  <path d="M28 30h28v68h-28z M64 30h28v34h-28z M64 64h28v34h-28z" fill="#fafaf7"/>
  <circle cx="96" cy="96" r="6" fill="#d97706"/>
</svg>
```

- [ ] **Step 2: Save as `docs/assets/logo.svg`**

Write the final SVG to that path.

- [ ] **Step 3: Produce single-color variant**

Copy to `docs/assets/logo-mono.svg` and edit:
- Remove the amber accent circle.
- Set fill to `currentColor` on all paths.

This variant is used in contexts where the logo must adopt the surrounding text color (e.g., inline in prose on the microsite).

- [ ] **Step 4: Visual sanity check**

Open both SVGs in a browser. Confirm:
- `logo.svg` renders on dark graphite with off-white mark + one amber dot.
- `logo-mono.svg` renders as a single-color silhouette that inherits `color` from its parent.

- [ ] **Step 5: Commit**

```bash
git add docs/assets/logo.svg docs/assets/logo-mono.svg
git commit -m "design: add monogram logo in two variants"
```

### Task 21: Generate favicon set

**Files:**
- Create: `E:/docforge/docs/assets/favicon/favicon.ico`
- Create: `E:/docforge/docs/assets/favicon/favicon-16x16.png`
- Create: `E:/docforge/docs/assets/favicon/favicon-32x32.png`
- Create: `E:/docforge/docs/assets/favicon/apple-touch-icon.png`

- [ ] **Step 1: Install `librsvg` (one-time)**

macOS: `brew install librsvg`.
Ubuntu: `sudo apt install librsvg2-bin`.
Windows (Git Bash): `choco install rsvg-convert` or use the online fallback in Step 4.

- [ ] **Step 2: Render PNG sizes from `logo.svg`**

```bash
rsvg-convert -w 16 -h 16 docs/assets/logo.svg -o docs/assets/favicon/favicon-16x16.png
rsvg-convert -w 32 -h 32 docs/assets/logo.svg -o docs/assets/favicon/favicon-32x32.png
rsvg-convert -w 180 -h 180 docs/assets/logo.svg -o docs/assets/favicon/apple-touch-icon.png
```

- [ ] **Step 3: Build the multi-resolution `.ico`**

```bash
# Requires ImageMagick: `brew install imagemagick` or `apt install imagemagick`.
magick docs/assets/favicon/favicon-16x16.png docs/assets/favicon/favicon-32x32.png docs/assets/favicon/favicon.ico
```

- [ ] **Step 4: Fallback if tooling unavailable**

If `rsvg-convert` or `magick` are unavailable, use https://realfavicongenerator.net/: upload `docs/assets/logo.svg`, download the generated package, and copy the four specific files listed under *Files* above into `docs/assets/favicon/`. Do not commit the rest of the generator's output.

- [ ] **Step 5: Visual verification**

Open each PNG in a browser or image viewer. At 16×16 the mark must still be legible — if it is a fuzzy blur, simplify the logo.svg before regenerating.

- [ ] **Step 6: Commit**

```bash
git add docs/assets/favicon/
git commit -m "design: generate favicon set from logo"
```

### Task 22: Create architecture SVG diagram

**Files:**
- Create: `E:/docforge/docs/assets/architecture.svg`

- [ ] **Step 1: Author the diagram**

Shows data flow: `Confluence Space` and `Local git repos` → `docforge ingest` → `Postgres + pgvector` → `docforge serve` → `MCP` → `Claude Code / Cursor / Copilot`.

Use Excalidraw (https://excalidraw.com/) or hand-author SVG. Constraints:

- Brand palette only: background `#fafaf7` (light) or `#1a1a1a` (dark — produce both if you want light + dark README support; otherwise pick one and stick with it).
- Boxes: graphite `#1a1a1a` outlines on light bg; `#fafaf7` outlines on dark.
- Flow arrows: amber `#d97706`.
- Labels: JetBrains Mono (convert text to paths so no font dependency at render time).
- Viewport: 1200×520 recommended; must scale cleanly to 100% width in README.

- [ ] **Step 2: Save as `docs/assets/architecture.svg`**

- [ ] **Step 3: Verify in README render**

Temporarily add `![Architecture](docs/assets/architecture.svg)` at the top of `README.md`, `git diff` to confirm the line, then view the README preview in your editor or push to a feature branch and view on GitHub. Revert the temporary line before committing.

- [ ] **Step 4: Commit**

```bash
git add docs/assets/architecture.svg
git commit -m "design: add architecture data-flow diagram"
```

### Task 23: Create social preview card

**Files:**
- Create: `E:/docforge/docs/assets/social-preview.png`

- [ ] **Step 1: Author as SVG, export to PNG**

Design constraints (per spec §8.4):
- Viewport: 1280×640.
- Background: `#1a1a1a`.
- Top-left: monogram (from `docs/assets/logo.svg`) + wordmark `docforge` in JetBrains Mono, weight 500.
- Center: *"The self-hosted context engine for AI coding assistants."* — large, `#fafaf7`.
- Bottom: four pill labels separated by middle-dots — `Self-hosted · MCP · Vendor-neutral · MIT`. Amber `#d97706` dots.

Author in Figma, Excalidraw, or hand-SVG. Export to `docs/assets/social-preview.png` at exactly 1280×640.

- [ ] **Step 2: Verify dimensions and size**

```bash
# Requires ImageMagick.
magick identify docs/assets/social-preview.png
```
Expected: `... PNG 1280x640 ...`. File size should be under 1 MB.

- [ ] **Step 3: Commit**

```bash
git add docs/assets/social-preview.png
git commit -m "design: add social preview card"
```

### Task 24: Record demo GIF

**Files:**
- Create: `E:/docforge/docs/assets/demo.gif` *(or `demo.mp4` + `demo-poster.svg` if GIF budget breaks)*

This task requires interactive screen recording and cannot be fully automated. The agent can produce the script and verify the output; the recording itself is done by the maintainer.

**Deferral option:** If no working docforge + MCP + assistant setup is available when Phase 3 opens, skip this task and merge Phase 3 without the demo. Add a follow-up PR (Phase 3.5) that ships only the demo GIF + the README embed change (see Task 25 Step 2). Do NOT block Phase 3 waiting on the recording — the other Phase 3 artifacts (logo, diagram, social card, favicon) are independently shippable.

- [ ] **Step 1: Prepare the recording environment**

- A running docforge instance (local or Azure) with the indexed CCL corpus.
- Claude Code (or Cursor) configured to use docforge as an MCP server.
- A terminal window on the side with `docforge status` already typed but not yet entered.
- Recording dimensions: 1280×720 minimum, 30 fps.

- [ ] **Step 2: Record to the 30-second script in spec §8.6**

Capture with OBS, Loom, or QuickTime. Script:

| Time | Frame |
|---|---|
| 0–3s | Claude Code / Cursor open with an empty prompt |
| 3–8s | Type: "How does our team handle rate-limiting in the API gateway?" |
| 8–12s | Tool-call flash: `search_documentation` → `docforge` → chunks stream in |
| 12–22s | Assistant answer with two Confluence page citations + one CLAUDE.md snippet with source URLs visible |
| 22–28s | Cut to terminal: `docforge status` → `44 sources · 1,770 chunks · healthy` |
| 28–30s | Logo + tagline outro (use `docs/assets/logo.svg` as a still) |

Save the raw capture as `demo-raw.mov` or `demo-raw.mp4` (not committed).

- [ ] **Step 3: Convert to GIF under 2 MB**

```bash
# Requires gifski: `brew install gifski` or `cargo install gifski`.
ffmpeg -i demo-raw.mp4 -vf "fps=12,scale=960:-1:flags=lanczos" -f image2pipe -vcodec png - | gifski -o docs/assets/demo.gif --fps 12 --width 960 -
ls -lh docs/assets/demo.gif
```

Expected: `docs/assets/demo.gif` exists and is under 2 MB. If over, drop to fps 10 or width 800 and re-run.

- [ ] **Step 4: Fallback — MP4 + poster**

If the GIF still exceeds 2 MB at acceptable quality:

```bash
ffmpeg -i demo-raw.mp4 -vf "scale=1280:-1" -vcodec libx264 -crf 28 -preset slow -an docs/assets/demo.mp4
```

And export the first frame as an SVG poster (screenshot then trace, or use a logo+"▶ play demo" composition) at `docs/assets/demo-poster.svg`.

Skip committing `demo.gif` in the MP4 case; update the README to embed the MP4 via `<video>`.

- [ ] **Step 5: Commit**

```bash
git add docs/assets/demo.gif  # or demo.mp4 demo-poster.svg
git commit -m "design: add 30-second product demo"
```

### Task 25: Wire the visuals into README

**Files:**
- Modify: `E:/docforge/README.md`

- [ ] **Step 1: Replace the ASCII diagram with the SVG**

Find the ASCII architecture block (around the "How it works" section) and replace it with:

```markdown
![docforge architecture: Confluence + local git → ingest → Postgres + pgvector → serve → MCP → AI assistants](docs/assets/architecture.svg)
```

- [ ] **Step 2: Add the hero demo GIF above the comparison**

Directly after the badge row and before the "Why docforge" heading, add:

```markdown
<p align="center">
  <img src="docs/assets/demo.gif" alt="docforge demo: asking an AI assistant about internal documentation" width="720"/>
</p>
```

*(If using the MP4 fallback, replace the `<img>` with a `<video>` element or an anchor to the `.mp4`.)*

- [ ] **Step 3: Render-check**

Open the README in a Markdown previewer. Verify both assets display.

- [ ] **Step 4: Commit**

```bash
git add README.md
git commit -m "docs: embed architecture diagram and demo in README"
```

### Task 26: Upload social preview to GitHub (UI, manual)

- [ ] **Step 1: Upload**

Navigate to `https://github.com/GranatenUdo/docforge/settings` → *Social preview* → *Edit*. Upload `docs/assets/social-preview.png`. Save.

- [ ] **Step 2: Verify**

Paste the repo URL into a Slack or Twitter draft; confirm the preview renders. Delete the draft.

No commit.

### Task 27: Open Phase 3 PR

- [ ] **Step 1: Push**

```bash
git push -u origin phase-3-visuals
```

- [ ] **Step 2: Open PR**

```bash
gh pr create --base master --title "Phase 3: visual identity (logo, favicon, architecture diagram, social card, demo)" --body "$(cat <<'EOF'
## Summary
- Added monogram logo (two variants) and favicon set.
- Added architecture SVG diagram (replaces ASCII in README).
- Added social preview card (uploaded to GitHub settings).
- Added 30-second demo GIF embedded at top of README.

Spec: docs/superpowers/specs/2026-04-23-documentation-polish-and-branding-design.md

## Test plan
- [ ] README renders diagram + demo correctly on PR preview
- [ ] Favicon visible in browser tab when repo loads
- [ ] Social card renders in Slack/Twitter preview test
- [ ] Demo under 2 MB (or MP4 fallback in place)

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

- [ ] **Step 3: Merge, delete branch, pull master**

```bash
# after merge
git checkout master && git pull
```

---

## Phase 4 — Microsite + blog + release

Creates branch `phase-4-microsite`. Ships: Astro + Starlight microsite deployed to GitHub Pages, launch blog post, v0.2.0 tag + PyPI release + GitHub Release notes.

### Task 28: Create Phase 4 branch and scaffold Astro

**Files:**
- Create: `E:/docforge/microsite/...` (Astro project scaffold)

- [ ] **Step 1: Branch**

```bash
git checkout master && git pull && git checkout -b phase-4-microsite
```

- [ ] **Step 2: Scaffold Astro + Starlight**

```bash
cd /e/docforge
npm create astro@latest microsite -- --template starlight --typescript strict --install --no-git --yes
```

Expected: `microsite/` created with Astro + Starlight boilerplate.

**Important:** `--no-git` is mandatory — without it the scaffolder initializes a fresh git repository inside `microsite/`, which would nest a repo inside docforge's existing repo. The `--yes` flag accepts remaining defaults; `--no-git` overrides the git default specifically.

Verify no nested `.git` directory was created:

```bash
ls microsite/.git 2>/dev/null && echo "BROKEN: nested git repo — delete microsite/.git" || echo "OK: no nested repo"
```

- [ ] **Step 3: Configure the site**

Edit `microsite/astro.config.mjs`. Replace the Starlight config block with:

```javascript
import { defineConfig } from 'astro/config';
import starlight from '@astrojs/starlight';

export default defineConfig({
  site: 'https://GranatenUdo.github.io',
  base: '/docforge',
  integrations: [
    starlight({
      title: 'docforge',
      description: 'Self-hosted context engine for AI coding assistants.',
      logo: { src: './src/assets/logo.svg', replacesTitle: false },
      favicon: '/favicon.ico',
      social: {
        github: 'https://github.com/GranatenUdo/docforge',
      },
      sidebar: [
        { label: 'Install', slug: 'install' },
        { label: 'Architecture', slug: 'architecture' },
        { label: 'Deployment', slug: 'deployment' },
        { label: 'FAQ', slug: 'faq' },
        { label: 'Blog', autogenerate: { directory: 'blog' } },
      ],
    }),
  ],
});
```

**Path notes:**
- `logo.src` is resolved from the project root; Starlight requires the logo to live under `src/` (copied in Task 29 Step 6, below).
- `favicon: '/favicon.ico'` is resolved from `microsite/public/` at runtime, with Astro's `base` automatically prefixed — the browser requests `/docforge/favicon.ico`.
- Assets referenced from Markdown content files (architecture diagram, demo GIF) live in `microsite/public/assets/` and are linked as `/assets/...` in the Markdown — Astro handles the base prefix.

- [ ] **Step 4: Commit the scaffold**

```bash
git add microsite/
git commit -m "chore(microsite): scaffold Astro + Starlight"
```

### Task 29: Write microsite content pages

**Files:**
- Create: `E:/docforge/microsite/src/content/docs/index.md`
- Create: `E:/docforge/microsite/src/content/docs/install.md`
- Create: `E:/docforge/microsite/src/content/docs/architecture.md`
- Create: `E:/docforge/microsite/src/content/docs/deployment.md`
- Create: `E:/docforge/microsite/src/content/docs/faq.md`

Each page is thin Markdown with Starlight frontmatter. Content source is the spec and the current README.

- [ ] **Step 1: Replace the default index page**

Delete the scaffolded `microsite/src/content/docs/index.mdx` (if present) and write `index.md` with:

- Starlight `title` + `description` frontmatter.
- The hero tagline + supporting paragraph + complementarity line from spec §1.
- The comparison table from spec §3 (copy verbatim).
- The "When to use / When NOT to use" section from spec §4.
- Bottom: call-to-action linking to `/install`.

- [ ] **Step 2: Write `install.md`**

- Frontmatter `title: "Install"`, `description: "Five-minute quick start."`
- Content: the Quick Start block from the current README, with the local-git-path clarifier added.

- [ ] **Step 3: Write `architecture.md`**

- Frontmatter `title: "Architecture"`.
- Embed the SVG: `![Architecture](/docs/assets/architecture.svg)` *(adjust relative path for Astro's public dir — copy the SVG to `microsite/public/assets/architecture.svg` if Astro cannot resolve the repo-relative path).*
- Brief explanation of each stage: crawl, parse, chunk, embed, store, serve.

- [ ] **Step 4: Write `deployment.md`**

- Frontmatter `title: "Deploy to Azure"`.
- Content: the "Deploy to your infrastructure" section of the current README, expanded with any cross-references to the Bicep templates under `infrastructure/`.

- [ ] **Step 5: Write `faq.md`**

- Frontmatter `title: "FAQ"`.
- Content: the FAQ section being moved out of the README's troubleshooting block.

- [ ] **Step 6: Copy required static assets into microsite**

Starlight and Astro have two asset locations that serve different purposes:
- **`microsite/src/assets/`** for the Starlight logo (referenced in `astro.config.mjs`).
- **`microsite/public/`** for static files served at URL paths (architecture diagram, demo, favicon, social preview).

Copy accordingly:

```bash
# Starlight logo lives under src/assets/ (referenced from astro.config.mjs)
mkdir -p microsite/src/assets
cp docs/assets/logo.svg microsite/src/assets/

# Static public assets
mkdir -p microsite/public/assets
cp docs/assets/logo.svg microsite/public/assets/
cp docs/assets/logo-mono.svg microsite/public/assets/
cp docs/assets/architecture.svg microsite/public/assets/
cp docs/assets/demo.gif microsite/public/assets/ 2>/dev/null || cp docs/assets/demo.mp4 microsite/public/assets/
cp docs/assets/social-preview.png microsite/public/assets/

# Favicon at the microsite root (referenced as /favicon.ico from astro.config.mjs)
cp docs/assets/favicon/favicon.ico microsite/public/favicon.ico
cp docs/assets/favicon/apple-touch-icon.png microsite/public/apple-touch-icon.png
cp docs/assets/favicon/favicon-16x16.png microsite/public/favicon-16x16.png
cp docs/assets/favicon/favicon-32x32.png microsite/public/favicon-32x32.png
```

Update any `![...](docs/assets/...)` references in microsite content files to `/assets/...` (Astro prefixes the `base` automatically).

- [ ] **Step 7: Build and preview locally**

```bash
cd microsite && npm run build && npm run preview
```

Open http://localhost:4321/docforge/. Verify all pages render, images load, sidebar shows the expected structure.

- [ ] **Step 8: Commit**

```bash
git add microsite/
git commit -m "docs(microsite): add landing, install, architecture, deployment, FAQ pages"
```

### Task 30: Write the launch blog post

**Files:**
- Create: `E:/docforge/microsite/src/content/docs/blog/2026-04-XX-introducing-docforge.md` *(replace XX with the day of writing)*

- [ ] **Step 1: Write per spec §10 outline**

Seven sections, ~1,800 words total, per the spec:

1. The gap (~200w)
2. What docforge is, in 90 seconds (~250w)
3. Where it sits vs. alternatives (~300w) — include the comparison table
4. The design choices (~400w) — Postgres + pgvector, EmbeddingGemma, MCP-first, no ACLs yet, narrow-by-design
5. What's shaky today (~250w) — dense-only, no chunk overlap, no ACLs, eval framing
6. Try it in five minutes (~300w) — quick start + screenshot
7. Credits & what's next (~100w)

Frontmatter:

```yaml
---
title: "docforge — a self-hosted context engine for AI coding assistants"
description: "Why I built it, where it fits, and what's still shaky."
date: 2026-04-XX
---
```

- [ ] **Step 2: Preview**

Restart the local dev server (`npm run dev` in `microsite/`), browse to `/blog/2026-04-XX-introducing-docforge/`. Verify rendering, heading levels, and the inline comparison table.

- [ ] **Step 3: Commit**

```bash
git add microsite/src/content/docs/blog/
git commit -m "docs(microsite): add launch blog post"
```

### Task 31: Configure GitHub Pages deployment

**Files:**
- Create: `E:/docforge/.github/workflows/microsite.yml`

- [ ] **Step 1: Add workflow**

```yaml
name: microsite

on:
  push:
    branches: [master]
    paths:
      - 'microsite/**'
      - '.github/workflows/microsite.yml'
  workflow_dispatch:

permissions:
  contents: read
  pages: write
  id-token: write

concurrency:
  group: pages
  cancel-in-progress: false

jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with:
          node-version: '20'
          cache: 'npm'
          cache-dependency-path: microsite/package-lock.json
      - name: Install dependencies
        working-directory: microsite
        run: npm ci
      - name: Build
        working-directory: microsite
        run: npm run build
      - name: Upload artifact
        uses: actions/upload-pages-artifact@v3
        with:
          path: microsite/dist
  deploy:
    needs: build
    runs-on: ubuntu-latest
    environment:
      name: github-pages
      url: ${{ steps.deployment.outputs.page_url }}
    steps:
      - name: Deploy
        id: deployment
        uses: actions/deploy-pages@v4
```

- [ ] **Step 2: Enable Pages in repo settings (UI)**

Navigate to `https://github.com/GranatenUdo/docforge/settings/pages`. Source: **GitHub Actions**.

- [ ] **Step 3: Commit**

```bash
git add .github/workflows/microsite.yml
git commit -m "ci: add microsite deploy workflow"
```

### Task 32: Deploy and verify microsite

- [ ] **Step 1: Push branch**

```bash
git push -u origin phase-4-microsite
```

- [ ] **Step 2: Open draft PR to observe CI**

```bash
gh pr create --draft --base master --title "Phase 4: microsite + blog + v0.2.0 release" --body "Draft while microsite deploy is verified."
```

The microsite workflow does not build off feature branches by default (the trigger is `branches: [master]`). To verify the build works before merge, either:

- **Option A:** trigger it manually via `gh workflow run microsite.yml` after merge; roll back if it fails.
- **Option B:** temporarily add the branch name to the workflow's `branches:` list, verify, then remove before merging.

- [ ] **Step 3: Merge PR**

```bash
gh pr ready
gh pr merge --squash
```

- [ ] **Step 4: Confirm the microsite is live**

```bash
curl -sIo /dev/null -w '%{http_code}\n' https://GranatenUdo.github.io/docforge/
```
Expected: `200`. Open the URL in a browser and spot-check pages.

- [ ] **Step 5: Update repo Website field**

```bash
gh repo edit GranatenUdo/docforge --homepage "https://GranatenUdo.github.io/docforge/"
```

No commit (master-side only).

### Task 33: Cut v0.2.0 release

**Files:**
- Modify: `E:/docforge/pyproject.toml` (version 0.1.1 → 0.2.0)
- Modify: `E:/docforge/CHANGELOG.md` (move Unreleased to 0.2.0 with today's date)

- [ ] **Step 1: Branch from fresh master**

```bash
git checkout master && git pull && git checkout -b release-0.2.0
```

- [ ] **Step 2: Bump version**

Change `pyproject.toml` line 7 to `version = "0.2.0"`.

- [ ] **Step 3: Move CHANGELOG unreleased section**

Edit `CHANGELOG.md`:

- Replace `## [Unreleased]` heading with `## [0.2.0] - YYYY-MM-DD` (use today's date).
- Add a new `## [Unreleased]` section at the top, empty, for future entries.
- Expand the release entry to cover Phases 1–4: README rewrite with comparison table, repo hygiene files, release workflow, visual identity (logo, diagram, demo), microsite with launch blog post.

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml CHANGELOG.md
git commit -m "chore: release v0.2.0"
```

- [ ] **Step 5: Push and PR**

```bash
git push -u origin release-0.2.0
gh pr create --base master --title "Release v0.2.0" --body "Bumps version and moves CHANGELOG unreleased to 0.2.0."
# After CI, approval, merge:
gh pr merge --squash
git checkout master && git pull
```

- [ ] **Step 6: Tag and push**

```bash
git tag -a v0.2.0 -m "Documentation polish & branding: README rewrite with comparison table, repo hygiene, visual identity, microsite + blog."
git push origin v0.2.0
```

- [ ] **Step 7: Verify release.yml ran**

Watch the Actions tab: `release.yml` should trigger on the tag push, build the distribution, publish to PyPI via trusted publishing, and create a GitHub Release with auto-generated notes.

```bash
gh run list --workflow=release.yml --limit 1
```

- [ ] **Step 8: Smoke-test the installed release**

```bash
python -m venv /tmp/docforge-020 && source /tmp/docforge-020/bin/activate && pip install docforge-cli==0.2.0 && docforge --version && deactivate && rm -rf /tmp/docforge-020
```
Expected: `docforge 0.2.0` (or the version string the CLI produces).

- [ ] **Step 9: Edit the GitHub Release to polish notes**

Open the auto-generated v0.2.0 Release on GitHub. Replace the auto-notes with a human-written summary of Phases 1–4. Point readers at the launch blog post URL for the full story.

No final commit needed.

---

## Self-review

**Spec coverage** — Walk through spec sections and confirm a task implements each:

- §1 Positioning / tagline → Task 6 (README) and Task 29 (microsite index).
- §2 README structure → Task 6.
- §3 Comparison table → Task 6 (README) + Task 29 (microsite) + Task 30 (blog post).
- §4 When-to / when-not-to → Task 6 and Task 29.
- §5 Badges → Task 6.
- §6 Repo hygiene files → Tasks 10, 11, 12, 13.
- §6.1 ROADMAP content → Task 13.
- §7 GitHub repo settings → Task 7 (description/topics) + Task 17 (Discussions) + Task 26 (social preview) + Task 32 (website field).
- §8.1 Logo → Task 20.
- §8.2 Palette → encoded in Tasks 20, 22, 23 via hex values.
- §8.3 Typography → encoded in Task 23 (wordmark) + Task 29 (microsite via Starlight defaults + font overrides if needed).
- §8.4 Social preview card → Task 23.
- §8.5 Architecture diagram → Task 22, wired to README in Task 25.
- §8.6 Demo GIF → Task 24.
- §9 Microsite → Tasks 28, 29, 31, 32.
- §10 Blog post → Task 30.
- §11 Release strategy → Tasks 3, 4, 5 (v0.1.0 + v0.1.1), Task 16 (release workflow), Task 33 (v0.2.0).
- Phases & ordering → Reflected in the four-phase structure, with explicit dependencies between phases noted in each Phase-open PR body.

**Placeholder scan** — Search performed; no `TBD`, `TODO`, or unqualified "implement later" remain. The only intentional placeholder is the blog post filename date (`2026-04-XX`) which resolves to the day of writing and is called out at its use site.

**Type consistency** — File paths use `docs/assets/` consistently; microsite static files live under `microsite/public/assets/` with explicit `cp` commands in Task 29 Step 6 to bridge. Branch names follow `phase-N-<topic>` convention across all four phases.

**Font dependency** — JetBrains Mono is referenced in the social card and wordmark. Tasks 20 (logo) and 23 (social card) instruct conversion of text to paths so rendering does not depend on font availability. Starlight's default fonts are acceptable for microsite body.

---

## Execution handoff

Plan complete and saved to `docs/superpowers/plans/2026-04-24-documentation-polish-and-branding.md`.

Two execution options:

**1. Inline Execution (recommended for this plan)** — Tasks executed in the current session using `superpowers:executing-plans`, with a mandatory checkpoint at the end of each phase (review the merged PR before opening the next phase's branch). Recommended because ~12 of the 33 tasks involve maintainer credentials (PyPI, GitHub admin), subjective judgment (logo, blog-post voice), or interactive work (demo recording) — subagents can prep mechanical sub-tasks but the plan's rhythm is human-led.

**2. Subagent-Driven** — Fresh subagent per task with two-stage review via `superpowers:subagent-driven-development`. Fastest mechanical throughput, but the maintainer still holds the design and credential tasks, so the gain over inline execution is small for this plan.

Which approach?
