# Backlog

Open work and ideas, grouped by size. Updated by hand. When the repo flips
public, items here can migrate to GitHub Issues.

## In progress

- **Repo cleanup PR A — polish bundle** (Medium, maintenance) — `[project.urls]`, `Makefile`, `.editorconfig`, `.superpowers/` move, README FAQ trim, this `BACKLOG.md`. Spec: `.superpowers/specs/2026-04-25-repo-cleanup-and-backlog-design.md`.
- **Repo cleanup PR B — asset dedup** (Small, maintenance) — Astro prebuild copy script (`microsite/scripts/sync-assets.mjs`); remove the eight duplicate copies from `microsite/public/`.
- **Repo cleanup PR C — src/ layout** (Medium, maintenance) — `git mv docforge/ src/docforge/`; `pyproject.toml`, `Dockerfile`, CI workflow, `CONTRIBUTING.md`, `README.md` path updates.
- **v0.2.1 release** (Small, maintenance) — Bump version, promote `CHANGELOG` `[Unreleased]` to `[0.2.1]`, tag, push.

## Small

- **Upload social preview card** (maintenance) — GitHub UI: *Settings → Social preview*; upload `docs/assets/social-preview.png`.
- **Spot-check Discussions categories** (maintenance) — `/discussions → ⋯ → Manage`. Confirm *Announcements / Q&A / Ideas / Show and tell* exist.
- **Flip repo public** (launch) — When ready: `gh repo edit GranatenUdo/docforge --visibility public --accept-visibility-change-consequences`.
- **Add wheel-RECORD invariant guard to `release.yml`** (maintenance) — Catch a future misconfigured src layout before it ships a broken wheel. One-liner shell step: assert `grep -c '^docforge/' >= 1` AND `grep -c '^src/docforge' == 0`.

## Medium

- **Record demo GIF + embed** (launch) — 30-second screen recording per spec `.superpowers/specs/2026-04-23-documentation-polish-and-branding-design.md` §8.6. Embed in README + microsite landing.
- **Launch post plan** (launch) — Hacker News, `r/LocalLLaMA`, `r/selfhosted`, `r/ClaudeAI`, `r/cursor`. Coordinate when repo is public. Per-sub posting strategy in the same spec §6.

## Large

- **Hybrid retrieval (BM25 + dense)** (feature) — Postgres `tsvector` + weighted fusion. Highest retrieval-quality ROI; addresses the dense-only weakness on exact-identifier queries. Re-baseline the eval after.
- **Chunk overlap** (feature) — Small token overlap (~50–100 tokens) between consecutive chunks. Catches answers that span section boundaries.
- **MCP identity via session** (feature) — Remove `user_name` and `team_name` from the per-call MCP tool signature; carry via session state instead. Removes the LLM-side hallucination surface.

## Done

- **Publication readiness — 2026-05-07** — Closed: MCP server identifier rename to `docforge`, master CI fork-friendly fix, `deploy/azure/README.md` Phase-4b update (7 resources, embedder section, ACR Standard SKU note), microsite architecture + deployment embedder additions, broken `.superpowers/` link replaced with inline `az postgres restore` command, removal of leftover `docs/superpowers/` artifacts, README HF prereq promotion, v0.3.0 release.
