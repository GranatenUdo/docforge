# Repo Cleanup + Backlog Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Bring the repository to a professional 10/10 grade via three sequential PRs (polish bundle, asset dedup, src/ layout) ending in a v0.2.1 release, with a GitHub Project board stood up first to track this work and the deferred backlog.

**Architecture:** Phase 0 sets up the board (no PR — `gh` CLI only). Phase 1 ships PR A on `chore/polish-bundle`. Phase 2 ships PR B on `chore/asset-dedup`. Phase 3 ships PR C on `refactor/src-layout`. Phase 4 cuts v0.2.1 on `release-0.2.1`. Each PR merges to master before the next opens. No Python source code is edited in this plan — only paths, configs, and docs.

**Tech Stack:** Python 3.12+ (existing), Astro + Starlight microsite (existing), GitHub Project (v2) via `gh` CLI, GNU `make` for dev shortcuts.

**Spec:** `docs/superpowers/specs/2026-04-25-repo-cleanup-and-backlog-design.md`

---

## Prerequisites

These must be true before starting (verified in v0.2.0 already):

- `gh` CLI authenticated as `GranatenUdo` with `repo`, `workflow`, `read:org` scopes minimum.
- `git` with push access to `GranatenUdo/docforge`.
- Python 3.12+ with `pip`, `build`, `twine` installed.
- Node 22+ with `pnpm` installed (Phase 2 verification).
- Docker installed (Phase 3 verification).
- GNU `make` installed locally. On Windows-Git-Bash: `choco install make` or `winget install GnuWin32.Make`.

---

## File Structure

### Created
- `Makefile` (repo root) — Phase 1
- `.editorconfig` (repo root) — Phase 1
- `microsite/scripts/sync-assets.mjs` — Phase 2
- `docs/superpowers/plans/2026-04-25-repo-cleanup-and-backlog.md` (this file) — already created

### Moved
- `docforge/` → `src/docforge/` (entire tree, ~17 Python modules + sql/ + templates/ + scripts/) — Phase 3
- `docs/superpowers/` → `.superpowers/` (specs/ + plans/ + phase-4-plan.md) — Phase 1

### Modified
- `pyproject.toml` — `[project.urls]` added (Phase 1), `[tool.setuptools.packages.find] where = ["src"]` added (Phase 3), version bumped to `0.2.1` (Phase 4)
- `Dockerfile` — `COPY` paths updated (Phase 3)
- `.github/workflows/ci.yml` — ruff paths updated (Phase 3)
- `.github/workflows/microsite.yml` — path filter adds `docs/assets/**` (Phase 2)
- `microsite/astro.config.mjs` — unchanged (logo stays at `./src/assets/logo.svg`)
- `microsite/package.json` — `dev` and `build` scripts prefixed with sync-assets (Phase 2)
- `microsite/.gitignore` — entries for now-generated files (Phase 2)
- `microsite/src/content/docs/deployment.md` — one URL updated to `.superpowers/...` (Phase 1)
- `microsite/README.md` — note about `src/assets/logo.svg` being the one exception to "canonical assets in docs/assets/" (Phase 2)
- `README.md` — FAQ section trimmed to 3 items + microsite pointer (Phase 1); any `docforge/` path examples updated (Phase 3)
- `CHANGELOG.md` — `[Unreleased]` entries appended in Phase 1 / 2 / 3, promoted to `[0.2.1]` in Phase 4
- `CONTRIBUTING.md` — `docforge/sql/migrations/` references updated to `src/docforge/sql/migrations/` (Phase 3)

### Deleted (from git tracking)
- `microsite/public/assets/logo.svg`
- `microsite/public/assets/logo-mono.svg`
- `microsite/public/assets/architecture.svg`
- `microsite/public/assets/social-preview.png`
- `microsite/public/favicon.ico`
- `microsite/public/favicon-16x16.png`
- `microsite/public/favicon-32x32.png`
- `microsite/public/apple-touch-icon.png`

(8 files; the prebuild script regenerates them locally and in CI.)

### External actions (no file change)
- GitHub Project board creation + custom fields + 12 draft items (Phase 0)
- Tag push `v0.2.1` (Phase 4)

---

## Phase 0 — GitHub Project board setup

No PR. All actions via `gh` CLI. Captures the cleanup work as in-progress board items, plus seeds the deferred backlog.

### Task 1: Create the project

**Files:** None (gh API).

- [ ] **Step 1: Create project**

```bash
gh project create --owner @me --title "docforge"
```

Expected output: `https://github.com/users/GranatenUdo/projects/<NUMBER>`. Capture `<NUMBER>` for subsequent commands. Save it as a shell variable for the session:

```bash
PROJECT_NUMBER=<NUMBER>   # replace with the number returned
```

- [ ] **Step 2: Verify ownership**

```bash
gh project list --owner @me --format json | jq '.projects[] | select(.title=="docforge") | {number, title, url}'
```

Expected: one row with the title `docforge` and the project number you captured.

No commit.

### Task 2: Add custom fields

**Files:** None (gh API).

- [ ] **Step 1: Add Size single-select field**

```bash
gh project field-create $PROJECT_NUMBER --owner @me --name "Size" --data-type SINGLE_SELECT --single-select-options "Small,Medium,Large"
```

Expected output: JSON with `id` and `options`. Capture the field ID and option IDs:

```bash
gh project field-list $PROJECT_NUMBER --owner @me --format json | jq '.fields[] | select(.name=="Size")'
```

Note the `id` of the field and the `id` of each option (Small / Medium / Large) — they are referenced in Task 5.

- [ ] **Step 2: Add Area single-select field**

```bash
gh project field-create $PROJECT_NUMBER --owner @me --name "Area" --data-type SINGLE_SELECT --single-select-options "maintenance,feature,launch,infra"
```

Same pattern: capture the field ID and option IDs.

- [ ] **Step 3: Verify both fields**

```bash
gh project field-list $PROJECT_NUMBER --owner @me --format json | jq '.fields[] | select(.dataType=="SINGLE_SELECT") | {name, options: [.options[] | {name, id}]}'
```

Expected: two SINGLE_SELECT fields (Size, Area) listed with all their options.

No commit.

### Task 3: Create 12 draft items

**Files:** None (gh API).

For convenience, define the items as a bash array to loop through. Each draft item gets a title and body; field assignments come in Task 5.

- [ ] **Step 1: Create the four cleanup items**

```bash
gh project item-create $PROJECT_NUMBER --owner @me --title "Repo cleanup PR A — polish bundle" --body "[project.urls], Makefile, .editorconfig, .superpowers/ move, README FAQ trim. See spec docs/superpowers/specs/2026-04-25-repo-cleanup-and-backlog-design.md."

gh project item-create $PROJECT_NUMBER --owner @me --title "Repo cleanup PR B — asset dedup" --body "Astro prebuild copy script; remove duplicate copies from microsite/public/. Spec Phase 2."

gh project item-create $PROJECT_NUMBER --owner @me --title "Repo cleanup PR C — src/ layout" --body "git mv docforge/ src/docforge/; pyproject + Dockerfile + CI updates. Spec Phase 3."

gh project item-create $PROJECT_NUMBER --owner @me --title "v0.2.1 release" --body "Bump version + CHANGELOG promote + tag + push. Spec Phase 4."
```

- [ ] **Step 2: Create the three small backlog items**

```bash
gh project item-create $PROJECT_NUMBER --owner @me --title "Upload social preview card" --body "GitHub UI task: Settings → Social preview → upload docs/assets/social-preview.png. ~30 seconds."

gh project item-create $PROJECT_NUMBER --owner @me --title "Spot-check Discussions categories" --body "GitHub UI task: /discussions → ⋯ → Manage. Confirm Announcements / Q&A / Ideas / Show and tell exist."

gh project item-create $PROJECT_NUMBER --owner @me --title "Flip repo public" --body "When ready: gh repo edit GranatenUdo/docforge --visibility public --accept-visibility-change-consequences. Removes 404s on README's GitHub links for anonymous visitors."
```

- [ ] **Step 3: Create the two medium backlog items**

```bash
gh project item-create $PROJECT_NUMBER --owner @me --title "Record demo GIF + embed" --body "30-second screen recording per spec docs/superpowers/specs/2026-04-23-documentation-polish-and-branding-design.md §8.6. Embed in README + microsite landing."

gh project item-create $PROJECT_NUMBER --owner @me --title "Launch post plan (HN, r/LocalLLaMA, r/selfhosted)" --body "Coordinate launch when repo is public. Per-sub posting strategy in spec docs/superpowers/specs/2026-04-23-... §6."
```

- [ ] **Step 4: Create the three large backlog items**

```bash
gh project item-create $PROJECT_NUMBER --owner @me --title "Hybrid retrieval (BM25 + dense)" --body "Postgres tsvector + weighted fusion. Highest retrieval-quality ROI. Re-baseline eval after."

gh project item-create $PROJECT_NUMBER --owner @me --title "Chunk overlap" --body "Small token overlap between consecutive chunks (~50-100 tokens). Catches answers spanning section boundaries."

gh project item-create $PROJECT_NUMBER --owner @me --title "MCP identity via session" --body "Remove user_name + team_name from per-call tool signature; carry via MCP session state instead. Removes hallucination surface."
```

- [ ] **Step 5: Verify all 12 items exist**

```bash
gh project item-list $PROJECT_NUMBER --owner @me --format json | jq '.items | length'
```

Expected: `12`.

No commit.

### Task 4: Capture item IDs for field assignment

**Files:** None.

- [ ] **Step 1: Dump items with IDs**

```bash
gh project item-list $PROJECT_NUMBER --owner @me --format json --limit 20 | jq '.items[] | {id, title}'
```

Expected: 12 items with their `id` strings (PVTI_*) and titles. Capture the IDs by title — needed in Task 5.

No commit.

### Task 5: Set Size + Area + Status on each item

**Files:** None.

This task is verbose — 12 items × up to 3 field updates each. Group by Size+Area combination to minimise repetition.

- [ ] **Step 1: Set Size and Area on the four cleanup items**

For each item, run two `gh project item-edit` invocations (one per field):

```bash
# PR A — Medium / maintenance
gh project item-edit --id <PR-A-ITEM-ID>     --project-id <PROJECT-NODE-ID> --field-id <SIZE-FIELD-ID> --single-select-option-id <MEDIUM-OPTION-ID>
gh project item-edit --id <PR-A-ITEM-ID>     --project-id <PROJECT-NODE-ID> --field-id <AREA-FIELD-ID> --single-select-option-id <MAINTENANCE-OPTION-ID>

# PR B — Small / maintenance
gh project item-edit --id <PR-B-ITEM-ID>     --project-id <PROJECT-NODE-ID> --field-id <SIZE-FIELD-ID> --single-select-option-id <SMALL-OPTION-ID>
gh project item-edit --id <PR-B-ITEM-ID>     --project-id <PROJECT-NODE-ID> --field-id <AREA-FIELD-ID> --single-select-option-id <MAINTENANCE-OPTION-ID>

# PR C — Medium / maintenance
gh project item-edit --id <PR-C-ITEM-ID>     --project-id <PROJECT-NODE-ID> --field-id <SIZE-FIELD-ID> --single-select-option-id <MEDIUM-OPTION-ID>
gh project item-edit --id <PR-C-ITEM-ID>     --project-id <PROJECT-NODE-ID> --field-id <AREA-FIELD-ID> --single-select-option-id <MAINTENANCE-OPTION-ID>

# v0.2.1 release — Small / maintenance
gh project item-edit --id <RELEASE-ITEM-ID>  --project-id <PROJECT-NODE-ID> --field-id <SIZE-FIELD-ID> --single-select-option-id <SMALL-OPTION-ID>
gh project item-edit --id <RELEASE-ITEM-ID>  --project-id <PROJECT-NODE-ID> --field-id <AREA-FIELD-ID> --single-select-option-id <MAINTENANCE-OPTION-ID>
```

To get `<PROJECT-NODE-ID>` (the PVT_ID, not the integer NUMBER):

```bash
gh project view $PROJECT_NUMBER --owner @me --format json | jq -r '.id'
```

- [ ] **Step 2: Set Size and Area on backlog items**

| Item | Size | Area |
|---|---|---|
| Upload social preview card | Small | maintenance |
| Spot-check Discussions categories | Small | maintenance |
| Flip repo public | Small | launch |
| Record demo GIF + embed | Medium | launch |
| Launch post plan | Medium | launch |
| Hybrid retrieval (BM25 + dense) | Large | feature |
| Chunk overlap | Large | feature |
| MCP identity via session | Large | feature |

Run two `gh project item-edit` per item using the IDs captured in Task 4 and the field/option IDs from Task 2.

- [ ] **Step 3: Set Status to "In Progress" on the four cleanup items**

The default `Status` field is built-in; query its options:

```bash
gh project field-list $PROJECT_NUMBER --owner @me --format json | jq '.fields[] | select(.name=="Status")'
```

Then for each cleanup item:

```bash
gh project item-edit --id <ITEM-ID> --project-id <PROJECT-NODE-ID> --field-id <STATUS-FIELD-ID> --single-select-option-id <IN-PROGRESS-OPTION-ID>
```

The 8 backlog items stay in the default `Backlog` (or `Todo`) Status — no edit needed.

- [ ] **Step 4: Verify**

```bash
gh project item-list $PROJECT_NUMBER --owner @me --format json --limit 20 | jq '.items[] | {title, status: .status, size: .["Size"], area: .["Area"]}'
```

Expected: 12 items, 4 with `status: "In Progress"`, 8 with the default Status. Each has Size and Area set.

No commit.

---

## Phase 1 — PR A: polish bundle

Branch: `chore/polish-bundle`. Touches no Python code. ~6 commits.

### Task 6: Create branch

**Files:** None (git only).

- [ ] **Step 1: Sync master and branch**

```bash
git checkout master && git pull
git checkout -b chore/polish-bundle
```

Expected: `Switched to a new branch 'chore/polish-bundle'`.

No commit.

### Task 7: Add `[project.urls]` to pyproject.toml

**Files:**
- Modify: `E:/docforge/pyproject.toml`

- [ ] **Step 1: Append `[project.urls]` block**

Open `pyproject.toml`. After the `[project]` section's last entry (currently `dependencies = [...]`) but before the next section header (currently `[project.scripts]`), insert:

```toml
[project.urls]
Homepage = "https://GranatenUdo.github.io/docforge/"
Source = "https://github.com/GranatenUdo/docforge"
Issues = "https://github.com/GranatenUdo/docforge/issues"
Changelog = "https://github.com/GranatenUdo/docforge/blob/master/CHANGELOG.md"
Documentation = "https://GranatenUdo.github.io/docforge/"
```

- [ ] **Step 2: Verify TOML parses**

```bash
python -c "import tomllib; d=tomllib.load(open('pyproject.toml','rb')); print(d['project']['urls'])"
```

Expected: dict with the five URL entries.

- [ ] **Step 3: Commit**

```bash
git add pyproject.toml
git commit -m "chore: add [project.urls] for PyPI sidebar"
```

### Task 8: Add Makefile

**Files:**
- Create: `E:/docforge/Makefile`

- [ ] **Step 1: Write Makefile**

Create `Makefile` at repo root with this exact content:

```makefile
# docforge developer shortcuts.
#
# Windows users on Git Bash: install make once via
#   choco install make    # or
#   winget install GnuWin32.Make
#
# Most targets assume an active venv with `pip install -e ".[dev,entra]"`.

.PHONY: install test test-all lint format format-check build clean \
        microsite-install microsite-dev microsite-build help

help:
	@echo "Targets:"
	@echo "  install            pip install -e .[dev,entra]"
	@echo "  test               pytest -m 'not integration'"
	@echo "  test-all           pytest (includes integration)"
	@echo "  lint               ruff check src/docforge tests"
	@echo "  format             ruff format src/docforge tests"
	@echo "  format-check       ruff format --check src/docforge tests"
	@echo "  build              clean build of sdist + wheel"
	@echo "  clean              remove build artefacts"
	@echo "  microsite-install  pnpm install in microsite/"
	@echo "  microsite-dev      pnpm run dev in microsite/"
	@echo "  microsite-build    pnpm run build in microsite/"

install:
	pip install -e ".[dev,entra]"

test:
	pytest -m "not integration"

test-all:
	pytest

lint:
	ruff check src/docforge tests

format:
	ruff format src/docforge tests

format-check:
	ruff format --check src/docforge tests

build: clean
	python -m build

clean:
	rm -rf dist/ build/ *.egg-info/ .pytest_cache/ .ruff_cache/

microsite-install:
	cd microsite && pnpm install

microsite-dev:
	cd microsite && pnpm run dev

microsite-build:
	cd microsite && pnpm run build
```

**Note:** `lint`, `format`, and `format-check` reference `src/docforge` — this matches the post-Phase-3 layout. PR A introduces this file with the post-migration paths so PR C doesn't need to edit it. Until PR C lands, `make lint` will fail on master because `src/docforge` doesn't exist yet. That's acceptable: nobody is running `make lint` on master between PRs A and C; the developer running it will be on the PR C branch.

If running `make lint` on master between PRs A merge and PR C merge is a real concern, override at invocation: `make lint TARGET_DIR=docforge` would require restructuring the Makefile with a variable. Not worth the complexity.

- [ ] **Step 2: Verify Makefile syntax**

```bash
make help
```

Expected: prints the help block. If make complains about tabs vs spaces, the file got copy-pasted with spaces — reopen and replace leading whitespace on recipe lines with tabs.

- [ ] **Step 3: Commit**

```bash
git add Makefile
git commit -m "chore: add Makefile with dev shortcuts"
```

### Task 9: Add .editorconfig

**Files:**
- Create: `E:/docforge/.editorconfig`

- [ ] **Step 1: Write .editorconfig**

Create `.editorconfig` at repo root with:

```ini
# https://editorconfig.org/
root = true

[*]
charset = utf-8
end_of_line = lf
insert_final_newline = true
trim_trailing_whitespace = true
indent_style = space

[*.py]
indent_size = 4

[*.{yml,yaml,md,mdx,json,svg,html,toml,xml}]
indent_size = 2

[Makefile]
indent_style = tab
```

- [ ] **Step 2: Commit**

```bash
git add .editorconfig
git commit -m "chore: add .editorconfig for cross-editor consistency"
```

### Task 10: Move docs/superpowers/ → .superpowers/

**Files:**
- Move: `E:/docforge/docs/superpowers/` → `E:/docforge/.superpowers/`
- Modify: `E:/docforge/microsite/src/content/docs/deployment.md`

- [ ] **Step 1: Move the directory**

```bash
git mv docs/superpowers/ .superpowers/
ls -la .superpowers/
```

Expected: `.superpowers/` exists with `phase-4-plan.md`, `plans/`, `specs/` inside.

- [ ] **Step 2: Update the one current reference in the microsite**

Open `microsite/src/content/docs/deployment.md` and find the line containing `docs/superpowers/specs/2026-04-22-operational-readiness-design.md` (around line 51). Change `docs/superpowers/` to `.superpowers/` in that URL only:

Before:
```markdown
[runbook](https://github.com/GranatenUdo/docforge/blob/master/docs/superpowers/specs/2026-04-22-operational-readiness-design.md)
```

After:
```markdown
[runbook](https://github.com/GranatenUdo/docforge/blob/master/.superpowers/specs/2026-04-22-operational-readiness-design.md)
```

- [ ] **Step 3: Verify the grep invariant**

```bash
git grep 'docs/superpowers' -- ':!.superpowers'
```

Expected: **no output**. (Matches outside `.superpowers/` mean a current reference was missed.)

```bash
git grep 'docs/superpowers' -- '.superpowers'
```

Expected: many matches. (These are historical references inside the moved files, intentionally left as-is.)

- [ ] **Step 4: Commit**

```bash
git add -A
git commit -m "chore: move docs/superpowers/ → .superpowers/"
```

### Task 11: Trim README FAQ to a pointer

**Files:**
- Modify: `E:/docforge/README.md`

- [ ] **Step 1: Replace the FAQ section**

Open `README.md` and find the `## FAQ` section. Replace its entire body (down to the `## License` heading) with:

```markdown
## FAQ

The three install-time issues new users hit most often are inline below. The
full FAQ — including "no results found", "ingest skipped everything", removing
sources, swapping embedding models, and where to file issues — lives on the
[microsite FAQ](https://GranatenUdo.github.io/docforge/faq/).

### "HF_TOKEN required" or model download fails

The embedding model `google/embeddinggemma-300m` requires a Hugging Face token with access to the gated model. Create one at https://huggingface.co/settings/tokens, accept the model license at https://huggingface.co/google/embeddinggemma-300m, and set `HF_TOKEN=hf_...` in `.env`.

### First ingest / first container start is very slow

The first run downloads the 300M embedding model (~1.2 GB) from Hugging Face. Locally, the model is cached at `~/.cache/huggingface/`. In the Docker image, it is cached at `/app/.cache/huggingface/` — **mount this as a volume** so container restarts do not re-download: `docker run -v docforge-hf-cache:/app/.cache/huggingface ...`.

### "Cannot connect to PostgreSQL"

Check that the database is running: `docker compose up -d db`. Verify `DATABASE_URL` in `.env` points to `postgresql://docforge:localdev@localhost:5432/docforge` (or your custom value).
```

- [ ] **Step 2: Verify the README still renders**

```bash
grep -c '^## ' README.md
```

Expected: same heading count as before, minus 0 (FAQ section retained, just shorter).

```bash
grep -E '^### ' README.md | head -10
```

Expected: 3 FAQ subheadings (HF_TOKEN, First ingest, Cannot connect) plus the existing "When docforge fits" / "When docforge is the wrong choice" subheadings.

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "docs: trim README FAQ to top-3 install issues + microsite pointer"
```

### Task 12: Update CHANGELOG [Unreleased]

**Files:**
- Modify: `E:/docforge/CHANGELOG.md`

- [ ] **Step 1: Append entries**

Open `CHANGELOG.md`. Under the existing `## [Unreleased]` heading (which is currently empty after the v0.2.0 promotion), insert:

```markdown
### Added

- `[project.urls]` in `pyproject.toml` (Homepage, Source, Issues, Changelog, Documentation) — populates the PyPI sidebar on next publish.
- `Makefile` at repo root with developer shortcuts: `install`, `test`, `lint`, `format`, `build`, `clean`, plus microsite shortcuts.
- `.editorconfig` at repo root for cross-editor consistency.

### Changed

- Internal planning artifacts moved from `docs/superpowers/` to `.superpowers/`. Historical cross-references inside the moved files are preserved as-is. The single current reference in `microsite/.../deployment.md` was updated.
- README's FAQ trimmed to the three install-time issues new users hit most often (HF_TOKEN, first-run slow, Postgres connection); the full FAQ remains canonical on the [microsite](https://GranatenUdo.github.io/docforge/faq/).
```

- [ ] **Step 2: Commit**

```bash
git add CHANGELOG.md
git commit -m "docs: note PR A polish bundle in CHANGELOG"
```

### Task 13: Open PR A and merge

**Files:** None (git + gh).

- [ ] **Step 1: Push the branch**

```bash
git push -u origin chore/polish-bundle
```

- [ ] **Step 2: Open the PR**

```bash
gh pr create --base master --title "Phase 1: polish bundle ([project.urls], Makefile, .editorconfig, .superpowers/, FAQ trim)" --body "$(cat <<'EOF'
## Summary
Phase 1 of the v0.2.1 cleanup. No Python code changes. No behavior changes.

- Added [project.urls] to pyproject.toml.
- Added Makefile with dev shortcuts (note: lint/format targets reference src/docforge — works post-Phase-3).
- Added .editorconfig.
- Moved docs/superpowers/ → .superpowers/. Historical references inside the moved files are intentionally preserved.
- Trimmed README FAQ to top-3 install issues + microsite pointer.

Spec: docs/superpowers/specs/2026-04-25-repo-cleanup-and-backlog-design.md (Phase 1).

## Test plan
- [ ] CI green
- [ ] git grep 'docs/superpowers' -- ':!.superpowers' returns nothing

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

- [ ] **Step 3: Wait for CI, then merge**

```bash
gh pr checks --watch
gh pr merge --merge --delete-branch
```

- [ ] **Step 4: Sync master**

```bash
git checkout master && git pull
```

- [ ] **Step 5: Update board**

Move the "Repo cleanup PR A — polish bundle" item to **Done** via `gh project item-edit` (using the IDs captured in Task 4 and the Done option ID from `gh project field-list`).

---

## Phase 2 — PR B: asset deduplication

Branch: `chore/asset-dedup`. Touches `microsite/` only. ~5 commits.

### Task 14: Create branch

**Files:** None.

- [ ] **Step 1: Branch from fresh master**

```bash
git checkout master && git pull
git checkout -b chore/asset-dedup
```

No commit.

### Task 15: Create the prebuild sync script

**Files:**
- Create: `E:/docforge/microsite/scripts/sync-assets.mjs`

- [ ] **Step 1: Create scripts directory**

```bash
mkdir -p microsite/scripts
```

- [ ] **Step 2: Write sync-assets.mjs**

Create `microsite/scripts/sync-assets.mjs` with:

```javascript
#!/usr/bin/env node
// Copy canonical assets from ../docs/assets/ into microsite/public/.
//
// Source of truth: docs/assets/
// Destination:     microsite/public/
//
// Run automatically before `astro dev` and `astro build` via package.json.

import { mkdir, copyFile, readdir } from 'node:fs/promises';
import { join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));
const docsAssets = join(here, '..', '..', 'docs', 'assets');
const publicDir = join(here, '..', 'public');

async function ensureDir(path) {
  await mkdir(path, { recursive: true });
}

async function copyToplevelAssets() {
  // Logo, diagram, social preview → public/assets/
  const dest = join(publicDir, 'assets');
  await ensureDir(dest);
  const entries = await readdir(docsAssets, { withFileTypes: true });
  for (const entry of entries) {
    if (entry.isFile()) {
      await copyFile(join(docsAssets, entry.name), join(dest, entry.name));
    }
  }
}

async function copyFavicons() {
  // docs/assets/favicon/* → public/ (root, so /favicon.ico resolves).
  const src = join(docsAssets, 'favicon');
  const entries = await readdir(src, { withFileTypes: true });
  for (const entry of entries) {
    if (entry.isFile()) {
      await copyFile(join(src, entry.name), join(publicDir, entry.name));
    }
  }
}

async function main() {
  await ensureDir(publicDir);
  await copyToplevelAssets();
  await copyFavicons();
  console.log(`sync-assets: copied from ${docsAssets} → ${publicDir}`);
}

main().catch((err) => {
  console.error('sync-assets failed:', err);
  process.exit(1);
});
```

- [ ] **Step 3: Commit**

```bash
git add microsite/scripts/sync-assets.mjs
git commit -m "chore(microsite): add prebuild script syncing canonical assets from docs/assets"
```

### Task 16: Update microsite package.json scripts

**Files:**
- Modify: `E:/docforge/microsite/package.json`

- [ ] **Step 1: Update dev and build scripts**

Open `microsite/package.json`. Change:

```json
"dev": "astro dev",
"build": "astro build",
```

To:

```json
"dev": "node scripts/sync-assets.mjs && astro dev",
"build": "node scripts/sync-assets.mjs && astro build",
```

(Also leave `start`, `preview`, `astro` as-is.)

- [ ] **Step 2: Verify the prebuild step runs**

```bash
cd microsite && pnpm run build 2>&1 | head -5
```

Expected: first line of output is `sync-assets: copied from ...` followed by Astro build output.

```bash
ls public/favicon.ico public/assets/architecture.svg
```

Expected: both files exist (regenerated by the script).

- [ ] **Step 3: Commit**

```bash
cd /e/docforge
git add microsite/package.json
git commit -m "chore(microsite): wire sync-assets prebuild into dev + build"
```

### Task 17: Delete duplicate copies and update .gitignore

**Files:**
- Delete: `E:/docforge/microsite/public/assets/logo.svg`
- Delete: `E:/docforge/microsite/public/assets/logo-mono.svg`
- Delete: `E:/docforge/microsite/public/assets/architecture.svg`
- Delete: `E:/docforge/microsite/public/assets/social-preview.png`
- Delete: `E:/docforge/microsite/public/favicon.ico`
- Delete: `E:/docforge/microsite/public/favicon-16x16.png`
- Delete: `E:/docforge/microsite/public/favicon-32x32.png`
- Delete: `E:/docforge/microsite/public/apple-touch-icon.png`
- Modify: `E:/docforge/microsite/.gitignore`

- [ ] **Step 1: Remove the 8 duplicates from git**

```bash
git rm microsite/public/assets/logo.svg microsite/public/assets/logo-mono.svg microsite/public/assets/architecture.svg microsite/public/assets/social-preview.png
git rm microsite/public/favicon.ico microsite/public/favicon-16x16.png microsite/public/favicon-32x32.png microsite/public/apple-touch-icon.png
```

- [ ] **Step 2: Update microsite/.gitignore**

Open `microsite/.gitignore` and append:

```
# Generated by scripts/sync-assets.mjs from ../docs/assets/
public/assets/
public/favicon.ico
public/favicon-*.png
public/apple-touch-icon.png
```

- [ ] **Step 3: Re-run the sync to repopulate locally**

```bash
cd microsite && node scripts/sync-assets.mjs
ls public/favicon.ico public/assets/architecture.svg
```

Expected: both files present locally (but git no longer tracks them — verify with `git status`).

- [ ] **Step 4: Commit**

```bash
cd /e/docforge
git add microsite/.gitignore
git commit -m "chore(microsite): delete duplicate assets, gitignore generated copies"
```

### Task 18: Update microsite workflow path filter

**Files:**
- Modify: `E:/docforge/.github/workflows/microsite.yml`

- [ ] **Step 1: Add docs/assets/** to the path filter**

Open `.github/workflows/microsite.yml` and find the `paths:` block under `on.push`:

Before:
```yaml
on:
  push:
    branches: [master]
    paths:
      - 'microsite/**'
      - '.github/workflows/microsite.yml'
  workflow_dispatch:
```

After:
```yaml
on:
  push:
    branches: [master]
    paths:
      - 'microsite/**'
      - '.github/workflows/microsite.yml'
      - 'docs/assets/**'
  workflow_dispatch:
```

- [ ] **Step 2: Commit**

```bash
git add .github/workflows/microsite.yml
git commit -m "ci(microsite): rebuild on docs/assets/** changes (canonical source)"
```

### Task 19: Update microsite README and append CHANGELOG

**Files:**
- Modify: `E:/docforge/microsite/README.md`
- Modify: `E:/docforge/CHANGELOG.md`

- [ ] **Step 1: Append note to microsite/README.md**

Open `microsite/README.md` and append (before the "## Notes for Windows developers" section if present, otherwise at the end):

```markdown
## Asset sources

Canonical visual assets (logo, favicon, architecture diagram, social preview) live in `docs/assets/` at the repo root. The `microsite/scripts/sync-assets.mjs` prebuild step copies them into `microsite/public/` before each `astro dev` or `astro build` run, so nothing in `public/assets/` or the favicon files at `public/` root needs to be edited or committed.

**One exception:** `microsite/src/assets/logo.svg` is a duplicate of `docs/assets/logo.svg` that lives inside the Astro project source. Starlight's `astro.config.mjs` `logo` config requires the file under `src/assets/`, and Astro's image pipeline can't follow symlinks across the project boundary. Keep this file in sync with the canonical when the logo changes.
```

- [ ] **Step 2: Append CHANGELOG entries**

Open `CHANGELOG.md`. Under `## [Unreleased]` (where Phase 1's entries already sit), append a new `### Changed` block (or append to the existing one if it has one already):

```markdown
- Microsite no longer ships duplicate copies of canonical assets. `microsite/scripts/sync-assets.mjs` runs before `astro dev` / `astro build` and copies from `docs/assets/`. Saves ~70 KB of redundant binaries in git.
```

- [ ] **Step 3: Commit**

```bash
git add microsite/README.md CHANGELOG.md
git commit -m "docs: document asset dedup in microsite README + CHANGELOG"
```

### Task 20: Open PR B and merge

**Files:** None.

- [ ] **Step 1: Push and open PR**

```bash
git push -u origin chore/asset-dedup
gh pr create --base master --title "Phase 2: asset deduplication via microsite prebuild script" --body "$(cat <<'EOF'
## Summary
Removes ~70 KB of duplicated visual assets from git. docs/assets/ is now the single source of truth; microsite/scripts/sync-assets.mjs copies into microsite/public/ on every astro dev / astro build run.

- Added microsite/scripts/sync-assets.mjs.
- Updated microsite/package.json dev + build scripts to run the sync first.
- Removed 8 duplicate files from microsite/public/ (logos, diagram, social preview, four favicon files).
- Added the deleted paths to microsite/.gitignore so future builds don't re-track them.
- Microsite workflow now also rebuilds when docs/assets/** changes.

Spec: docs/superpowers/specs/2026-04-25-repo-cleanup-and-backlog-design.md (Phase 2).

## Test plan
- [ ] CI green
- [ ] After merge, microsite workflow rebuilds successfully on master
- [ ] https://GranatenUdo.github.io/docforge/ still serves /favicon.ico, /apple-touch-icon.png, /assets/architecture.svg, /assets/logo.svg

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

- [ ] **Step 2: Merge after CI**

```bash
gh pr checks --watch
gh pr merge --merge --delete-branch
git checkout master && git pull
```

- [ ] **Step 3: Verify microsite workflow runs and passes on master**

```bash
gh run watch $(gh run list --workflow=microsite.yml --limit 1 --json databaseId -q '.[0].databaseId') --exit-status
```

Expected: build + deploy steps both green. If the build step fails because `docs/assets/` isn't reachable from inside `microsite/`, fix the relative path in `sync-assets.mjs` and re-run.

- [ ] **Step 4: Update board**

Move the "Repo cleanup PR B — asset dedup" item to **Done** on the project board.

---

## Phase 3 — PR C: src/ layout migration

Branch: `refactor/src-layout`. Largest diff. ~7 commits.

### Task 21: Create branch

**Files:** None.

- [ ] **Step 1: Branch from fresh master**

```bash
git checkout master && git pull
git checkout -b refactor/src-layout
```

No commit.

### Task 22: git mv the package

**Files:**
- Move: `E:/docforge/docforge/` → `E:/docforge/src/docforge/`

- [ ] **Step 1: Run git mv**

```bash
mkdir -p src
git mv docforge src/docforge
ls src/docforge/ | head -5
```

Expected: `src/docforge/` contains `__init__.py`, `cli.py`, `api.py`, `config.py`, `crawlers/`, `processors/`, `scripts/`, `sql/`, `templates/`, etc.

- [ ] **Step 2: Verify history is rename-detected**

```bash
git status | head -20
git log --oneline --diff-filter=R -1
```

Expected: `git status` shows `R  docforge/cli.py -> src/docforge/cli.py` style entries; `git log` confirms previous commits are renames not deletes-plus-adds.

- [ ] **Step 3: Commit**

```bash
git commit -m "refactor: move docforge/ → src/docforge/"
```

### Task 23: Update pyproject.toml package discovery

**Files:**
- Modify: `E:/docforge/pyproject.toml`

- [ ] **Step 1: Add `where = ["src"]`**

Open `pyproject.toml`. Find the existing block:

```toml
[tool.setuptools.packages.find]
include = ["docforge*"]
```

Change to:

```toml
[tool.setuptools.packages.find]
where = ["src"]
include = ["docforge*"]
```

The `[tool.setuptools.package-data]` block (`docforge = ["templates/**/*", "sql/**/*"]`) is unchanged — those paths are relative to the package directory, which is the same in both layouts.

- [ ] **Step 2: Re-install in editable mode and verify**

```bash
pip install -e ".[dev,entra]"
python -c "import docforge; print('docforge imported from:', docforge.__file__)"
```

Expected: `docforge.__file__` resolves to a path containing `src/docforge/__init__.py`.

```bash
docforge --version 2>&1 | head -3
```

Expected: prints the docforge version (proves the entry point resolves correctly).

- [ ] **Step 3: Commit**

```bash
git add pyproject.toml
git commit -m "chore: pyproject packages.find where=['src']"
```

### Task 24: Update Dockerfile

**Files:**
- Modify: `E:/docforge/Dockerfile`

- [ ] **Step 1: Update COPY paths**

Open `Dockerfile`. Find the line:

```dockerfile
COPY docforge/ docforge/
```

Change to:

```dockerfile
COPY src/ src/
```

The earlier `RUN pip install --no-cache-dir ".[entra]"` line is unchanged — pip reads pyproject.toml which now points at `src/`.

- [ ] **Step 2: Verify image builds**

```bash
docker build -t docforge:src-test .
```

Expected: build succeeds. Image size should be roughly the same as before.

- [ ] **Step 3: Quick smoke test inside the image**

```bash
docker run --rm docforge:src-test python -c "import docforge; print(docforge.__file__)"
```

Expected: import succeeds and prints a path containing `docforge/__init__.py` (in the installed location, not `src/`).

- [ ] **Step 4: Commit**

```bash
git add Dockerfile
git commit -m "chore: Dockerfile COPY src/ for new layout"
```

### Task 25: Update CI workflow ruff paths

**Files:**
- Modify: `E:/docforge/.github/workflows/ci.yml`

- [ ] **Step 1: Update ruff invocations**

Open `.github/workflows/ci.yml`. Find the two ruff lines under the `lint` job:

```yaml
      - run: ruff check docforge tests
      - run: ruff format --check docforge tests
```

Change both `docforge` to `src/docforge`:

```yaml
      - run: ruff check src/docforge tests
      - run: ruff format --check src/docforge tests
```

The test job (`pytest -m "not integration"`) needs no change — it discovers tests from root and imports `docforge` by package name.

- [ ] **Step 2: Verify locally first**

```bash
ruff check src/docforge tests
ruff format --check src/docforge tests
```

Expected: both succeed (or both report any pre-existing issues consistently — no new issues introduced by the move).

- [ ] **Step 3: Commit**

```bash
git add .github/workflows/ci.yml
git commit -m "ci: update ruff paths for src/ layout"
```

### Task 26: Update CONTRIBUTING.md path references

**Files:**
- Modify: `E:/docforge/CONTRIBUTING.md`

- [ ] **Step 1: Find and update path references**

```bash
git grep -n '\bdocforge/' CONTRIBUTING.md
```

Expected: at least one match around line 31 (`docforge/sql/migrations/`).

For each match, update the path to `src/docforge/...`. Specifically (line 31, currently):

```markdown
SQL migrations live under `docforge/sql/migrations/` and are numbered sequentially: `NNN_description.sql`. The next free number is easy to see with `ls docforge/sql/migrations/ | tail -1`.
```

Becomes:

```markdown
SQL migrations live under `src/docforge/sql/migrations/` and are numbered sequentially: `NNN_description.sql`. The next free number is easy to see with `ls src/docforge/sql/migrations/ | tail -1`.
```

- [ ] **Step 2: Verify no remaining `docforge/` paths in CONTRIBUTING**

```bash
git grep -n '\bdocforge/' CONTRIBUTING.md
```

Expected: no output.

- [ ] **Step 3: Commit**

```bash
git add CONTRIBUTING.md
git commit -m "docs: update CONTRIBUTING.md paths for src/ layout"
```

### Task 27: Update README path examples

**Files:**
- Modify: `E:/docforge/README.md`

- [ ] **Step 1: Find path references**

```bash
git grep -nE '\bdocforge/(scripts|sql|crawlers|processors|templates|cli\.py|api\.py)' README.md
```

Expected: matches like `docforge/scripts/eval_search.py`, `docforge/scripts/README.md`.

- [ ] **Step 2: Update each match**

Replace `docforge/...` with `src/docforge/...` where the reference is a path in the repo (not an `import docforge` reference, not the PyPI package name).

Examples:

- `[`docforge/scripts/eval_search.py`](docforge/scripts/eval_search.py)` → `[`src/docforge/scripts/eval_search.py`](src/docforge/scripts/eval_search.py)`
- `[`docforge/scripts/README.md`](docforge/scripts/README.md)` → `[`src/docforge/scripts/README.md`](src/docforge/scripts/README.md)`

Do **not** change:

- `pip install docforge-cli` (PyPI name; unaffected)
- `from docforge.X import Y` (import name; unaffected)
- The `docforge` CLI command (entry point; unaffected)

- [ ] **Step 3: Verify**

```bash
git grep -nE '\(docforge/' README.md
```

Expected: no output (all internal-path references converted).

- [ ] **Step 4: Commit**

```bash
git add README.md
git commit -m "docs: update README path examples for src/ layout"
```

### Task 28: Local pre-commit verification

**Files:** None.

Before pushing, run the full verification matrix.

- [ ] **Step 1: Editable install**

```bash
pip install -e ".[dev,entra]"
```

Expected: succeeds. The egg-info directory is regenerated under the new layout.

- [ ] **Step 2: Test count parity check**

```bash
pytest -m "not integration" --collect-only 2>&1 | tail -5
```

Note the test count printed. Compare to the count from before the migration (run on master to baseline). They must match.

```bash
pytest -m "not integration"
```

Expected: same number of tests pass as before the migration.

- [ ] **Step 3: Lint and format check**

```bash
make lint
make format-check
```

Expected: both pass. (`make lint` is `ruff check src/docforge tests` per the Makefile written in PR A.)

- [ ] **Step 4: Build wheel and inspect RECORD**

```bash
make build
python -m zipfile -l dist/*.whl | head -25
```

Expected (key lines):

- `docforge/cli.py`
- `docforge/api.py`
- `docforge/templates/...`
- `docforge/sql/...`

The wheel must contain `docforge/...` paths, **not** `src/docforge/...` — the src layout is build-time only. If the wheel has `src/docforge/`, the install would put `src/` on `sys.path` instead of the package; users would need `import src.docforge` which is wrong.

- [ ] **Step 5: Docker build**

```bash
docker build -t docforge:src-test .
docker run --rm docforge:src-test docforge --help | head -10
```

Expected: build succeeds, `docforge --help` prints the Typer banner.

- [ ] **Step 6: Make all targets sanity check**

```bash
make help
make clean
```

Expected: help prints the targets; clean removes `dist/`, `build/`, etc.

If any of steps 1–6 fail, fix before committing further.

No commit (verification only).

### Task 29: Append CHANGELOG entry

**Files:**
- Modify: `E:/docforge/CHANGELOG.md`

- [ ] **Step 1: Append to [Unreleased]**

Under the existing `### Changed` block in `[Unreleased]`, append:

```markdown
- Repository switched to `src/` layout (`docforge/` → `src/docforge/`). Public package and import name (`docforge-cli` / `import docforge`) unchanged. CI ruff paths, Dockerfile COPY, and CONTRIBUTING.md path examples updated.
```

- [ ] **Step 2: Commit**

```bash
git add CHANGELOG.md
git commit -m "docs: note src/ layout migration in CHANGELOG"
```

### Task 30: Open PR C and merge

**Files:** None.

- [ ] **Step 1: Push and open PR**

```bash
git push -u origin refactor/src-layout
gh pr create --base master --title "Phase 3: switch to src/ layout (docforge/ → src/docforge/)" --body "$(cat <<'EOF'
## Summary
Moves the package from a flat layout (docforge/ at repo root) to the PyPA-recommended src/ layout (src/docforge/). Internal restructuring only — no behavior change, no public API change.

- git mv docforge → src/docforge (history preserved via rename detection).
- pyproject.toml: [tool.setuptools.packages.find] where=['src'].
- Dockerfile: COPY src/ src/.
- CI: ruff paths updated to src/docforge.
- CONTRIBUTING.md + README path examples updated.

The build wheel still contains docforge/... paths (not src/docforge/...), so installed users see no difference. pip install docforge-cli works identically.

Spec: docs/superpowers/specs/2026-04-25-repo-cleanup-and-backlog-design.md (Phase 3).

## Test plan
- [ ] CI green
- [ ] Wheel RECORD contains `docforge/cli.py` etc. (NOT `src/docforge/...`)
- [ ] Docker image builds and `docforge --help` works inside

Note for reviewers: GitHub web UI may show file history starting at the rename commit. Use `git log --follow src/docforge/<file>` locally for full history.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

- [ ] **Step 2: Wait for CI, then merge**

```bash
gh pr checks --watch
gh pr merge --merge --delete-branch
git checkout master && git pull
```

- [ ] **Step 3: Update board**

Move the "Repo cleanup PR C — src/ layout" item to **Done**.

---

## Phase 4 — v0.2.1 release

Branch: `release-0.2.1`. Final commit before tag. ~2 commits.

### Task 31: Create release branch and bump version

**Files:**
- Modify: `E:/docforge/pyproject.toml`
- Modify: `E:/docforge/CHANGELOG.md`

- [ ] **Step 1: Branch**

```bash
git checkout master && git pull
git checkout -b release-0.2.1
```

- [ ] **Step 2: Bump version**

Open `pyproject.toml`. Find `version = "0.2.0"` and change to `version = "0.2.1"`.

- [ ] **Step 3: Promote CHANGELOG [Unreleased] → [0.2.1]**

Open `CHANGELOG.md`. Replace the heading `## [Unreleased]` with:

```markdown
## [Unreleased]

## [0.2.1] - 2026-04-25
```

(Use the actual day if different. The empty `[Unreleased]` block stays at the top for future entries.)

The existing entries that were under `[Unreleased]` (Added: project.urls, Makefile, .editorconfig; Changed: .superpowers move, README FAQ trim, asset dedup, src/ layout) now sit under `[0.2.1]`.

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml CHANGELOG.md
git commit -m "chore: release v0.2.1"
```

### Task 32: Open release PR and merge

**Files:** None.

- [ ] **Step 1: Push and open PR**

```bash
git push -u origin release-0.2.1
gh pr create --base master --title "Release v0.2.1" --body "$(cat <<'EOF'
## Summary
Promotes CHANGELOG [Unreleased] → [0.2.1] and bumps pyproject.toml version. Bundles the polish bundle (PR A), asset dedup (PR B), and src/ layout migration (PR C).

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

- [ ] **Step 2: Wait for CI, then merge**

```bash
gh pr checks --watch
gh pr merge --merge --delete-branch
git checkout master && git pull
```

### Task 33: Tag and push v0.2.1

**Files:** None.

- [ ] **Step 1: Tag master HEAD**

```bash
git tag -a v0.2.1 -m "Cleanup release: src/ layout, asset dedup, polish (project.urls, Makefile, .editorconfig, .superpowers/, FAQ trim)."
```

- [ ] **Step 2: Push tag**

```bash
git push origin v0.2.1
```

This triggers `release.yml` → builds → publishes to PyPI via trusted publishing → creates GitHub Release.

- [ ] **Step 3: Watch the release workflow**

```bash
gh run watch $(gh run list --workflow=release.yml --limit 1 --json databaseId -q '.[0].databaseId') --exit-status
```

Expected: all steps green (Build distribution, Publish to PyPI, Create GitHub Release).

- [ ] **Step 4: Verify PyPI publish**

```bash
curl -s https://pypi.org/pypi/docforge-cli/json | python -c "import json, sys; d=json.load(sys.stdin); print('latest:', d['info']['version']); print('urls:', d['info'].get('project_urls'))"
```

Expected: `latest: 0.2.1`; `urls:` shows the five entries from `[project.urls]`.

- [ ] **Step 5: Smoke-test installation**

```bash
python -m venv /tmp/df-021-smoke
source /tmp/df-021-smoke/Scripts/activate    # Windows Git Bash: Scripts; Linux/Mac: bin
pip install docforge-cli==0.2.1
docforge --help | head -5
deactivate
rm -rf /tmp/df-021-smoke
```

Expected: install succeeds, `docforge --help` prints the Typer banner.

### Task 34: Update board

**Files:** None.

- [ ] **Step 1: Move v0.2.1 item to Done**

Move the "v0.2.1 release" item to **Done** on the project board.

- [ ] **Step 2: Verify board state**

```bash
gh project item-list $PROJECT_NUMBER --owner @me --format json --limit 20 | jq '.items[] | {title, status: .status}'
```

Expected: 4 items with `status: "Done"` (PR A, PR B, PR C, v0.2.1 release); 8 items in the default Backlog status (the deferred small/medium/large items).

---

## Self-review

**Spec coverage:**

- §Phase 0 board setup → Tasks 1–5 ✓
- §Phase 1 PR A: project.urls → Task 7 ✓
- §Phase 1 PR A: Makefile → Task 8 ✓
- §Phase 1 PR A: .editorconfig → Task 9 ✓
- §Phase 1 PR A: .superpowers/ move → Task 10 ✓
- §Phase 1 PR A: FAQ trim → Task 11 ✓
- §Phase 1 PR A: CHANGELOG → Task 12 ✓
- §Phase 1 PR A: PR open + merge → Task 13 ✓
- §Phase 2 PR B: prebuild script → Task 15 ✓
- §Phase 2 PR B: package.json → Task 16 ✓
- §Phase 2 PR B: delete duplicates + .gitignore → Task 17 ✓
- §Phase 2 PR B: workflow path filter → Task 18 ✓
- §Phase 2 PR B: microsite README + CHANGELOG → Task 19 ✓
- §Phase 2 PR B: PR open + merge → Task 20 ✓
- §Phase 3 PR C: git mv → Task 22 ✓
- §Phase 3 PR C: pyproject → Task 23 ✓
- §Phase 3 PR C: Dockerfile → Task 24 ✓
- §Phase 3 PR C: CI ruff → Task 25 ✓
- §Phase 3 PR C: CONTRIBUTING → Task 26 ✓
- §Phase 3 PR C: README → Task 27 ✓
- §Phase 3 PR C: pre-commit verification → Task 28 ✓
- §Phase 3 PR C: CHANGELOG → Task 29 ✓
- §Phase 3 PR C: PR open + merge → Task 30 ✓
- §Phase 4 v0.2.1: version + CHANGELOG → Task 31 ✓
- §Phase 4 v0.2.1: PR + merge → Task 32 ✓
- §Phase 4 v0.2.1: tag + watch → Task 33 ✓
- §Phase 4 v0.2.1: board → Task 34 ✓

All spec sections have a corresponding task.

**Placeholder scan:** No `TBD`, `TODO`, "implement later" found. The only placeholder-style strings are `<NUMBER>` / `<PR-A-ITEM-ID>` / `<PROJECT-NODE-ID>` / `<MEDIUM-OPTION-ID>` etc. — these are explicitly captured by named earlier steps and are clearly not unfilled gaps.

**Type / path consistency:** Paths use forward slashes consistently (Windows Git Bash compatible). The Makefile is introduced in Phase 1 with `src/docforge` paths to avoid editing it in Phase 3. Acknowledged as a small dent: `make lint` won't work on master between PRs A and C; mitigated by noting it inline.

**Risk / known limitations called out inline:**
- Wheel RECORD layout check (Task 28 Step 4) catches the most likely src/-layout regression.
- Test count parity (Task 28 Step 2) catches silent test discovery breaks.
- Docker build verification (Task 28 Step 5) catches Dockerfile path errors.
- The `git grep` invariant (Task 10 Step 3) catches missed `.superpowers/` references.
- The microsite redeploy after PR B (Task 20 Step 3) confirms `sync-assets.mjs` works in CI.

---

## Execution handoff

Plan complete and saved to `docs/superpowers/plans/2026-04-25-repo-cleanup-and-backlog.md`.

**Two execution options:**

**1. Inline Execution (recommended for this plan)** — Tasks executed in the current session using `superpowers:executing-plans`, with a mandatory checkpoint at the end of each phase. Recommended because credentials (PyPI trusted publishing already configured, but still gated) and judgement calls (FAQ wording, README path matches) appear throughout. Same rhythm worked well for v0.2.0.

**2. Subagent-Driven** — Fresh subagent per task with two-stage review via `superpowers:subagent-driven-development`. Higher mechanical throughput but more overhead per task; the design + credential touches still need the maintainer.

Which approach?
