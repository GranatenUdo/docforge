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

- **Chunk overlap** (feature) — Small token overlap (~50–100 tokens) between consecutive chunks. Catches answers that span section boundaries.
- **MCP identity via session** (feature) — Remove `user_name` and `team_name` from the per-call MCP tool signature; carry via session state instead. Removes the LLM-side hallucination surface.

## Done

- **Cross-encoder reranker — 2026-06-18/19 (engine 0.7.16)** — Re-scores the top `rerank_top_n` (default 50) candidates from the hybrid (dense pgvector + sparse lexical (ts_rank_cd) + RRF + tag boost) pool using `BAAI/bge-reranker-v2-m3` (xlm-roberta cross-encoder via sentence-transformers `CrossEncoder`). Runs as its own GPU Container App sidecar (`Dockerfile.reranker`) on a serverless Tesla-T4 profile (`gpu-nc8as-t4`, cpu=8/mem=56Gi), kept warm at `minReplicas=1`, fp32 (the fp16 `.half()` cast broke `CrossEncoder.predict` in sentence-transformers 5.x — `/health` passes but `/rerank` 500s); `max_length=512` + `batch_size=8` bound T4 activation memory; reuses the embedder bearer token (`embedder-token` Key Vault secret). Config: `RERANK_ENABLED`, `RERANK_MODEL`, `RERANK_TOP_N`, `RERANKER_URL`, `RERANKER_TOKEN`, `RERANK_BATCH_SIZE` (8), `RERANK_MAX_LENGTH` (512). Engine PRs #86–#91, parent rag PR #78620; images `docforge:v0.7.16` + `docforge-reranker:v0.3.0`. Eval (60-query org-wide ground truth, `rag/eval/CURRENT_BASELINE.md`): recall@1 43→65%, recall@20 87→92%, MRR 0.564→0.735.
- **Hybrid retrieval (ts_rank_cd lexical + dense) — shipped v0.5.0** — Postgres `tsvector` sparse lexical ranking (Postgres ts_rank_cd cover-density) + dense pgvector fused via RRF with tag boost. Addressed the dense-only weakness on exact-identifier queries; eval re-baselined after. Foundation for the cross-encoder reranker above. Engine releases v0.6.x–0.7.16 landed since 2026-05-07, culminating in the reranker.
- **Repo cleanup PRs A/B/C — 2026-05-07 (verified done)** — Closed during continuation-plan critical review: PR A items already in (`[project.urls]`, Makefile, .editorconfig, FAQ trimmed; `.superpowers/` move done in PR #16). PR B done (`microsite/scripts/sync-assets.mjs` + `microsite/public/` removed). PR C done (`src/docforge/` package layout, `pyproject.toml` `where = ["src"]`). Plus removed `docforge/docforge/` __pycache__ cruft from before the src/ migration.
- **Publication readiness — 2026-05-07** — Closed: MCP server identifier rename to `docforge`, master CI fork-friendly fix, `deploy/azure/README.md` Phase-4b update (7 resources, embedder section, ACR Standard SKU note), microsite architecture + deployment embedder additions, broken `.superpowers/` link replaced with inline `az postgres restore` command, removal of leftover `docs/superpowers/` artifacts, README HF prereq promotion, v0.3.0 release.
