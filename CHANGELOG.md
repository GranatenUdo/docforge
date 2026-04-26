# Changelog

All notable changes to docforge are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- Threat model now linked from the "When docforge is the wrong choice" section in both `README.md` and the microsite homepage. External adopters comparing docforge against alternatives can find the explicit trust assumptions without having to dig into `docs/`.
- "License compatibility" section in `README.md` naming the [Gemma Terms of Use](https://ai.google.dev/gemma/terms) restrictions (no harmful use, no Gemma-derivative competitors) for adopters considering redistribution.
- Optional `expected_dimensions` parameter on `Embedder.__init__`. When provided, asserts the loaded model's dimension matches; raises `RuntimeError` with a clear remediation message on mismatch. Defaults to `None` (guard dormant) for backwards compatibility with direct `Embedder()` callers.
- `docs/log-privacy.md` — privacy & retention policy for the `query_log` table. Documents purpose, retention, redaction patterns, access roles, and a right-to-erasure runbook. Partially aspirational as of Phase 3; the "Implementation status" section names which items ship later in v0.3.

### Changed

- All runtime and dev dependencies in `pyproject.toml` now carry strict-major upper bounds (e.g. `fastapi>=0.115,<1.0`, `pydantic>=2.9,<3.0`, `pytest>=9.0,<10.0`). Floor-only pins previously allowed fresh installs to pull an untested next-major version of any dep. `numpy>=1.26,<3.0` is the documented exception, covering both 1.x and 2.x. Dependabot continues to pick up minors and patches.
- All four `Embedder(...)` construction sites in the API, MCP server, ingest pipeline, and CLI now pass `expected_dimensions=settings.embedding_dimensions`, enabling the new dimension guard in production. **Behavior change:** if your configured `embedding_dimensions` disagrees with the loaded embedding model's actual dimension, the process now fails fast at startup with a clear remediation message ("change `embedding_model` in `docforge.yml`, or update `embedding_dimensions` and migrate the schema"), instead of failing later at INSERT time with a cryptic pgvector error. Adopters with a stale `embedding_dimensions` should update it before upgrading.
- API and MCP search request boundaries are now hard-capped: `query` is rejected over 8000 characters, `limit` is rejected outside `[1, 50]`. **Behavior change:** clients that previously got 200 with `limit=10000` (and a slow response) now get HTTP 422 with a Pydantic-shaped error detail naming the offending field. Internal `Embedder.embed` raises `ValueError` when called with more than 256 texts in one batch.

## [0.2.1] - 2026-04-25

### Added

- `[project.urls]` in `pyproject.toml` (Homepage, Source, Issues, Changelog, Documentation) — populates the PyPI sidebar on next publish.
- `Makefile` at repo root with developer shortcuts: `install`, `test`, `lint`, `format`, `build`, `clean`, plus microsite shortcuts.
- `.editorconfig` at repo root for cross-editor consistency.
- `BACKLOG.md` at repo root tracking in-flight cleanup work and the deferred small/medium/large items.

### Changed

- Internal planning artifacts moved from `docs/superpowers/` to `.superpowers/`. Historical cross-references inside the moved files are preserved as-is. The single current reference in `microsite/.../deployment.md` was updated.
- README's FAQ trimmed to the three install-time issues new users hit most often (HF_TOKEN, first-run slow, Postgres connection); the full FAQ remains canonical on the [microsite](https://GranatenUdo.github.io/docforge/faq/).
- Microsite no longer ships duplicate copies of canonical assets. `microsite/scripts/sync-assets.mjs` runs before `astro dev` / `astro build` and copies from `docs/assets/`. Saves ~70 KB of redundant binaries in git.
- Repository switched to `src/` layout (`docforge/` → `src/docforge/`). Public package and import name (`docforge-cli` / `import docforge`) unchanged. CI ruff paths, Dockerfile COPY (now reordered to copy source before install for proper site-packages installation), and CONTRIBUTING.md / README path examples updated.

## [0.2.0] - 2026-04-24

### Added

- Positioning-led README with comparison table against Onyx, Atlassian Rovo MCP, zilliztech/claude-context, Cursor, Copilot Spaces, Sourcegraph Cody, and LangChain DIY, plus an explicit "when not to use" section.
- `CHANGELOG.md`, `SECURITY.md`, `CODE_OF_CONDUCT.md` (Contributor Covenant 2.1), `ROADMAP.md`.
- GitHub issue templates (bug report, feature request) and pull-request template under `.github/`.
- Tag-triggered release workflow at `.github/workflows/release.yml` using PyPI trusted publishing.
- GitHub Discussions enabled with categories *Announcements*, *Q&A*, *Ideas*, *Show and tell*.
- Visual identity under `docs/assets/`: monogram logo (two variants), favicon set (16×16, 32×32, 180×180 PNG + multi-res ICO), architecture data-flow SVG, 1280×640 social preview card. Graphite (`#1a1a1a`) + amber (`#d97706`) palette.
- Astro + Starlight microsite under `microsite/` with landing, install, architecture, deployment, and FAQ pages, plus a launch blog post. Deployed to GitHub Pages via `.github/workflows/microsite.yml` on every `master` push that touches `microsite/**`.

### Changed

- Repository description and topics updated to reflect the new positioning.
- README "How it works → Architecture" replaces the ASCII diagram with the new SVG.

## [0.1.0] - 2026-04-24

First tagged release. Retroactive tag at commit `491db97`. Covers Phase 1–3
(MVP + Phase 3 quality) and Phase 4 hardening (operational readiness,
security, team tagging).
