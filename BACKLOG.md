# Backlog

Open work and ideas, grouped by size. Updated by hand. When the repo flips
public, items here can migrate to GitHub Issues.

## In progress

(none)

## Small

- **Upload social preview card** (maintenance) — GitHub UI: *Settings → Social preview*; upload `docs/assets/social-preview.png`.
- **Spot-check Discussions categories** (maintenance) — `/discussions → ⋯ → Manage`. Confirm *Announcements / Q&A / Ideas / Show and tell* exist.
- **Add wheel-RECORD invariant guard to `release.yml`** (maintenance) — Catch a future misconfigured src layout before it ships a broken wheel. One-liner shell step: assert `grep -c '^docforge/' >= 1` AND `grep -c '^src/docforge' == 0`.

## Medium

- **Record demo GIF + embed** (launch) — 30-second screen recording per spec `.superpowers/specs/2026-04-23-documentation-polish-and-branding-design.md` §8.6. Embed in README + microsite landing.
- **Launch post plan** (launch) — Hacker News, `r/LocalLLaMA`, `r/selfhosted`, `r/ClaudeAI`, `r/cursor`. Coordinate when repo is public. Per-sub posting strategy in the same spec §6.

## Large

- **Hybrid retrieval (BM25 + dense)** (feature) — Postgres `tsvector` + weighted fusion. Highest retrieval-quality ROI; addresses the dense-only weakness on exact-identifier queries. Re-baseline the eval after.
- **Chunk overlap** (feature) — Small token overlap (~50–100 tokens) between consecutive chunks. Catches answers that span section boundaries.
- **MCP identity via session** (feature) — Remove `user_name` and `team_name` from the per-call MCP tool signature; carry via session state instead. Removes the LLM-side hallucination surface.

## Done

- **Repo cleanup PRs A/B/C — 2026-05-07 (verified done)** — Closed during continuation-plan critical review: PR A items already in (`[project.urls]`, Makefile, .editorconfig, FAQ trimmed; `.superpowers/` move done in PR #16). PR B done (`microsite/scripts/sync-assets.mjs` + `microsite/public/` removed). PR C done (`src/docforge/` package layout, `pyproject.toml` `where = ["src"]`). Plus removed `docforge/docforge/` __pycache__ cruft from before the src/ migration.
- **Publication readiness — 2026-05-07** — Closed: MCP server identifier rename to `docforge`, master CI fork-friendly fix, `deploy/azure/README.md` Phase-4b update (7 resources, embedder section, ACR Standard SKU note), microsite architecture + deployment embedder additions, broken `.superpowers/` link replaced with inline `az postgres restore` command, removal of leftover `docs/superpowers/` artifacts, README HF prereq promotion, v0.3.0 release.
