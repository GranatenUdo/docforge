# Spec: Repository cleanup to 10/10 + backlog board

**Date:** 2026-04-25
**Target release:** v0.2.1
**Status:** design pending user spec review before implementation plan

## Context

After the v0.2.0 documentation polish and branding release, the repository
is in good shape (~8.5/10) but has a small list of structural and
hygiene gaps that prevent it from reading as a professional 10/10 OSS
project:

- Flat package layout (`docforge/` at root) instead of the PyPA-recommended
  `src/` layout. Catches packaging bugs less reliably; modern convention.
- Internal planning artifacts at `docs/superpowers/` sit next to user-facing
  docs (`threat-model.md`, `authoring-guideline.md`).
- `pyproject.toml` lacks `[project.urls]`; PyPI sidebar empty.
- Visual assets duplicated three times (`docs/assets/`, `microsite/public/`,
  `microsite/src/assets/logo.svg`) with manual sync.
- No top-level dev-shortcut runner; common commands documented in
  `CONTRIBUTING.md` but require multi-line invocations.
- No `.editorconfig` for cross-editor consistency.
- README's FAQ section duplicates `microsite/src/content/docs/faq.md`
  with drift hazard.

In parallel, several deferred items from v0.2.0's planning need a
durable home that isn't a markdown file in some scratch location: a
GitHub Project board.

## Goals

1. **Three sequential PRs** (A → B → C) close the structural gaps with
   no behavior change.
2. **One v0.2.1 release** at the end, batching all cleanup into a
   single coherent PyPI publish.
3. **A GitHub Project board** stood up before any cleanup PR, holding
   both the cleanup items and the deferred backlog (small/medium/large
   from prior planning).

## Non-goals

- Behavior changes — no Python source edits beyond path updates.
- Public API changes — `pip install docforge-cli` and `import docforge`
  unchanged.
- Touching `tests/` location — stays at repo root.
- Moving `deploy/azure/` or `microsite/` — fine as is.
- Renaming the public package `docforge-cli`.
- Migrating the Project board content to GitHub Issues — out of scope
  until repo flips public.

## Audience & voice

This spec is internal workflow output for the maintainer (Tobias). The
language is direct — no marketing voice, no hedging.

## Design

### Phase 0 — GitHub Project board setup (~5 minutes, no PR)

**Why first:** the board needs to exist *before* the cleanup PRs so it
can track them as work-in-progress, not just future items.

**Steps:**

1. `gh project create --owner @me --title "docforge"`. Capture the
   project number returned.
2. Add custom fields via `gh project field-create`:
   - **Size** (single-select): `Small`, `Medium`, `Large`
   - **Area** (single-select): `maintenance`, `feature`, `launch`, `infra`
3. Add 12 draft items via `gh project item-create` — see *Initial board
   contents* below.
4. Set Size + Area on each item via `gh api graphql` (the CLI's
   `field-set` works for built-in fields; custom fields need GraphQL).
5. Move the three cleanup items to **In Progress**; everything else
   stays in **Backlog** (default Status column).

**Initial board contents:**

| Title | Size | Area | Status |
|---|---|---|---|
| Repo cleanup PR A — polish bundle | Medium | maintenance | In Progress |
| Repo cleanup PR B — asset dedup | Small | maintenance | In Progress |
| Repo cleanup PR C — src/ layout | Medium | maintenance | In Progress |
| v0.2.1 release | Small | maintenance | In Progress |
| Upload social preview card | Small | maintenance | Backlog |
| Spot-check Discussions categories | Small | maintenance | Backlog |
| Flip repo public | Small | launch | Backlog |
| Record demo GIF + embed | Medium | launch | Backlog |
| Launch post plan (HN, r/LocalLLaMA, r/selfhosted) | Medium | launch | Backlog |
| Hybrid retrieval (BM25 + dense) | Large | feature | Backlog |
| Chunk overlap | Large | feature | Backlog |
| MCP identity via session | Large | feature | Backlog |

(Draft items have no underlying GitHub Issue. When the repo goes public,
items can be converted to Issues from the board UI.)

### Phase 1 — PR A: polish bundle (`chore/polish-bundle`)

Touches no Python code. All low-risk doc/config changes.

**1.1 — `[project.urls]` in `pyproject.toml`**

Five URL entries (Homepage, Source, Issues, Changelog, Documentation).
Effective on next PyPI publish (v0.2.1).

**1.2 — `Makefile` at repo root**

Eight targets: `install`, `test`, `test-all`, `lint`, `format`,
`format-check`, `build`, `clean`. Plus microsite shortcuts:
`microsite-install`, `microsite-dev`, `microsite-build`. All use commands
already documented in `CONTRIBUTING.md`.

**Note for Windows users:** `make` is not pre-installed in Git Bash.
Document `choco install make` or `winget install GnuWin32.Make` in the
Makefile header comment.

**1.3 — `.editorconfig` at root**

Six declarations: `indent_style=space`; `indent_size=4` for `*.py`;
`indent_size=2` for `*.{yml,yaml,md,mdx,json,svg,html,toml}`;
`end_of_line=lf`; `insert_final_newline=true`; `charset=utf-8`.

**1.4 — Move `docs/superpowers/` → `.superpowers/`**

`git mv docs/superpowers/ .superpowers/`. Updates only **current**
references — historical plan/spec files inside the moved directory keep
their original `docs/superpowers/...` strings (they describe past
state; rewriting would falsify history).

The single non-historical reference to update:

- `microsite/src/content/docs/deployment.md:51` — absolute GitHub URL
  pointing at `docs/superpowers/specs/2026-04-22-operational-readiness-design.md`.
  Change to `.superpowers/specs/...`.

Verify with `git grep 'docs/superpowers'` — the only remaining matches
should be inside files within the moved directory itself.

**Note:** `.foo/` directories (other than `.github/`) are NOT hidden by
GitHub's web UI; the dot prefix is a convention signaling "internal,"
not actual visual hiding. Maintainers see them; casual readers can
ignore them.

**1.5 — Trim README FAQ to a pointer**

Replace the existing `## FAQ` section in `README.md` with three high-frequency
items inline + a "see microsite FAQ for more" pointer at the bottom. The
microsite's `faq.md` remains canonical for the full list.

**1.6 — CHANGELOG `[Unreleased]` entry**

Single entry summarising 1.1–1.5 + planned PR B + PR C content
(forward-referencing).

### Phase 2 — PR B: asset deduplication (`chore/asset-dedup`)

Touches `microsite/` only. Removes ~70 KB of duplicate binaries from git.

**Approach: prebuild copy script** (Astro's `publicDir` outside-root
path was investigated and rejected — see *Approaches considered*).

**2.1 — Create `microsite/scripts/sync-assets.mjs`**

Node ES module script. Copies from `../docs/assets/` to `microsite/public/`:

- `*.svg`, `*.png` at the root of `docs/assets/` → `microsite/public/assets/`
- `favicon/*` (favicon.ico, favicon-16x16.png, favicon-32x32.png,
  apple-touch-icon.png) → `microsite/public/` (root, so `/favicon.ico`
  resolves correctly)
- Idempotent: copies only if the source is newer or destination is missing.

**2.2 — Update `microsite/package.json` build scripts**

```json
"dev": "node scripts/sync-assets.mjs && astro dev",
"build": "node scripts/sync-assets.mjs && astro build"
```

**2.3 — Delete duplicate copies from git**

Remove (with `git rm`) eight files:

- `microsite/public/assets/logo.svg`
- `microsite/public/assets/logo-mono.svg`
- `microsite/public/assets/architecture.svg`
- `microsite/public/assets/social-preview.png`
- `microsite/public/favicon.ico`
- `microsite/public/favicon-16x16.png`
- `microsite/public/favicon-32x32.png`
- `microsite/public/apple-touch-icon.png`

**2.4 — Update `microsite/.gitignore`**

Add the deleted paths so they don't reappear after the prebuild script
populates them locally:

```
public/assets/
public/favicon*.png
public/favicon.ico
public/apple-touch-icon.png
```

**2.5 — Keep `microsite/src/assets/logo.svg`**

Starlight's `astro.config.mjs` `logo: { src: './src/assets/logo.svg' }`
requires the logo *inside* the project's `src/`. This file remains
git-tracked and is the *one* exception to "canonical assets live in
docs/assets/". Document the exception in `microsite/README.md`.

**2.6 — Update microsite workflow path filter**

`.github/workflows/microsite.yml` `paths:` already covers `microsite/**`.
**Add** `docs/assets/**` so changes to canonical assets trigger a redeploy.

**2.7 — Verify**

Local: `cd microsite && rm -rf public/assets public/favicon* public/apple-touch-icon.png && pnpm run build` → must succeed and produce a working `dist/`. Spot-check that `dist/architecture.svg` exists,
`dist/favicon.ico` exists, etc.

### Phase 3 — PR C: src/ layout migration (`refactor/src-layout`)

Largest diff. No Python source edits — purely path-anchored
configuration and references.

**3.1 — `git mv docforge/ src/docforge/`**

History preserved via Git's rename detection.

**3.2 — `pyproject.toml`**

```toml
[tool.setuptools.packages.find]
where = ["src"]
include = ["docforge*"]
```

`[tool.setuptools.package-data]` paths inside the package are unchanged
(still `templates/**/*` and `sql/**/*` relative to `docforge/`).

`[tool.coverage.report]` and pytest's `--cov=docforge` use the import
name (`docforge`), not the path — no change needed.

**3.3 — `Dockerfile`**

```dockerfile
COPY src/ src/
RUN pip install --no-cache-dir ".[entra]"
```

(Currently `COPY docforge/ docforge/`. After src layout the project
installs from `src/`; the install step needs the source at the path
pyproject expects.)

**3.4 — CI workflow `ci.yml`**

Update the two ruff invocations:

- `ruff check src/docforge tests`
- `ruff format --check src/docforge tests`

`pip install -e ".[dev]"` and `pytest` lines are unchanged (they read
from pyproject.toml; the package install discovers `src/` via the
new `where` setting).

**3.5 — `CONTRIBUTING.md`**

Update path references (line 31 currently cites `docforge/sql/migrations/`).

**3.6 — `README.md`**

Update any inline path examples that cite `docforge/<file>`. Verified
during implementation via `git grep '\bdocforge/' README.md`.

**3.7 — `Makefile`**

Targets that reference paths (`lint`, `format`, `clean`) updated to
`src/docforge`.

**3.8 — Local pre-commit verification**

Before pushing the branch:

```bash
pip install -e ".[dev,entra]"
pytest -m "not integration"
ruff check src/docforge tests
ruff format --check src/docforge tests
python -m build && python -m zipfile -l dist/*.whl | head -20
docker build -t docforge:test .
```

All five must succeed.

### Phase 4 — v0.2.1 release

After PR C merges:

**4.1 — Branch `release-0.2.1`**

`pyproject.toml`: `version = "0.2.1"`.
`CHANGELOG.md`: replace `## [Unreleased]` heading with
`## [0.2.1] - 2026-04-25` (use the actual day); insert a fresh empty
`## [Unreleased]` block above it.

**4.2 — PR + merge + tag**

```bash
git tag -a v0.2.1 -m "Cleanup release: src/ layout, asset dedup, polish."
git push origin v0.2.1
```

`release.yml` fires → builds → publishes to PyPI via trusted
publishing → creates GitHub Release.

**4.3 — Board update**

Move all four cleanup items (PR A / PR B / PR C / v0.2.1) to **Done**.

## File structure (new files / moved files / deleted files)

### Created
- `Makefile` (repo root)
- `.editorconfig` (repo root)
- `microsite/scripts/sync-assets.mjs`

### Moved
- `docforge/` → `src/docforge/` (entire tree)
- `docs/superpowers/` → `.superpowers/`

### Modified
- `pyproject.toml` (urls + package discovery + version bump for v0.2.1)
- `Dockerfile` (COPY path)
- `.github/workflows/ci.yml` (ruff paths)
- `.github/workflows/microsite.yml` (path filter)
- `microsite/astro.config.mjs` (none if logo path unchanged)
- `microsite/package.json` (dev + build scripts)
- `microsite/.gitignore` (additions)
- `microsite/src/content/docs/deployment.md` (one URL)
- `microsite/README.md` (note about the src/assets/logo.svg exception)
- `README.md` (FAQ trim + path examples)
- `CHANGELOG.md` (Unreleased entries + 0.2.1 promotion)
- `CONTRIBUTING.md` (path updates)

### Deleted
- 8 duplicate files in `microsite/public/` (asset dedup)

## Approaches considered and rejected

### Astro `publicDir: '../docs/assets'` for asset dedup

Astro docs confirm publicDir outside the project root is supported, but
"static content comes exclusively from publicDir." Choosing this would
force:

- Renaming `docs/assets/favicon/*` → `docs/assets/*` to match a flat
  publicDir layout, OR `astro.config.mjs` `favicon: '/favicon/favicon.ico'`
- Updating every `/assets/<file>` reference in microsite content to
  `/<file>` (since publicDir is now the root, not a subdirectory)
- A more brittle build for portability gain that's marginal

The prebuild-script approach keeps content-relative paths stable and
makes the duplication explicit-but-automated.

### `docs/_planning/` instead of `.superpowers/`

User chose `.superpowers/` in brainstorming. The dot-prefix convention
is consistent with `.github/`, `.vscode/`. GitHub's web UI shows
dot-prefixed directories normally (only `.github/` is special-cased);
the convention signals "internal" without literal hiding.

### One mega cleanup PR

Three PRs (A → B → C) chosen for revertability. If PR C's src/ migration
breaks something subtle, A and B remain shipped without rollback.

### `Taskfile.yaml` instead of Makefile

Considered after surfacing Windows-Git-Bash `make` install friction.
User chose to install `make` once via `choco install make` rather than
introduce a non-universal runner.

## Risk plan

| Risk | Likelihood | Mitigation |
|---|---|---|
| `publicDir` route taken accidentally and breaks favicon | low (rejected) | Spec explicitly mandates prebuild-script approach |
| Stale `docs/superpowers/` path references missed | medium | `git grep 'docs/superpowers'` exhaustive sweep before commit |
| `src/` migration breaks Docker build | medium | `docker build .` is part of pre-commit verification |
| `src/` migration breaks `pip install -e .` | medium | Local install + test gate before commit |
| Microsite asset paths broken after dedup | low | Local `pnpm run build` + render check before commit |
| v0.2.1 release fails (PyPI side) | very low | release.yml proven on v0.2.0; trusted publishing already configured |
| Project board misconfigured | low | Board lives outside repo; failing creation does not block any code |

**Order matters.** A → B → C → v0.2.1 release → board updates. If C
becomes too painful, A + B alone tag as v0.2.1 (skipping the src/
migration entirely is acceptable).

## Success criteria

After v0.2.1 ships:

1. `pip install docforge-cli==0.2.1` works in a clean venv.
2. `docforge --help` works post-install.
3. `pip show docforge-cli` shows populated `Project-URLs:`.
4. Microsite redeploys cleanly on master push.
5. `make test`, `make lint`, `make build` all succeed locally.
6. `git ls-files microsite/public/` shows no asset duplicates.
7. Repo root contains `src/docforge/` (not `docforge/`).
8. `docs/superpowers/` no longer exists; `.superpowers/` does.
9. PyPI sidebar shows Homepage / Source / Issues / Changelog / Docs.
10. GitHub Project board exists with 12 items, 4 in Done, 8 in Backlog.

## Open questions

None at spec time. All decisions finalised in brainstorming.

## Implementation plan

To be produced by the `writing-plans` skill after this spec is reviewed
and approved.
