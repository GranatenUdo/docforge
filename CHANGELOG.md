# Changelog

All notable changes to docforge are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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
