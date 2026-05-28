# Changelog

All notable changes to docforge are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Fixed
- `eval_search`: `--audience`, `--user`, `--team` now reject empty strings
  via argparse type-callable. Empty-string expansion (e.g.,
  `--user "$UNSET_VAR"`) previously ran the eval silently with empty
  identity fields, polluting query logs and disabling tag-match boosts.
- `eval_search`: now exits with code 1 if every query in the ground-truth
  suite reports a MISS (likely auth / connectivity failure). Previously
  returned 0 even with 0/N hits, masking failures in CI.
- `eval_search` `_non_empty_str` now also rejects `<placeholder>` literals
  (e.g., `<you>`, `<your-team>`) that the previous validator silently
  accepted. Closes a doc-recipe + hardening gap where users could paste
  the recipe verbatim and pollute query_log with placeholder identity rows.
- `eval_search` `_non_empty_str` now returns the stripped value (was
  unstripped); trailing/leading whitespace from env-var typos no longer
  flows through.
- `eval_search` `--area` argparse now uses `_non_empty_str` (symmetric
  with --user/--team/--audience).
- `eval_search` all-MISS error message now lists three possible causes
  (auth, ground-truth quality, retrieval regression) instead of blaming
  auth/connectivity alone.

## [0.7.13] - 2026-05-27

### Fixed
- Hybrid retrieval: `ts_rank_cd` now uses custom weights `{D=0.1/F, C=0.2/F,
  B=0.4/F, A=1.0}` with title-dominance factor F (default 4.0), making
  title-matches dominate body-keyword density 40:1 (vs Postgres default
  10:1). Migration 008's chunks.title is now load-bearing for short queries
  where the target page's title contains the query terms but its body
  doesn't repeat them as densely as competitor chunks. Resolves 2 of 3
  short-token misses left by sub-project D's eval (Markus Koelmans / Domain
  Catalog). Morne remains a data-side issue (chunk content gap).

### Added
- `Settings.title_weight_a: float = 4.0` — title-dominance factor. Higher =
  title-matches contribute more to sparse rank vs body-keyword density.
  Tune in docforge.yml without an engine rebuild. Eval sweep found 4.0
  optimal on the 60-query ground truth (recall@1: 32→34, MRR: 0.619→0.647).

### Notes
- v0.7.12's sparse-pool dampening machinery (`sparse_flood_ratio`,
  `sparse_flood_dampening`) is retained but inert at defaults: both CTEs
  cap at `hybrid_pool_size=100`, so the ratio can't exceed ~1.0 and the
  default 3.0 threshold doesn't fire. Kept for future tuning. Title-weight
  was the actual load-bearing fix.

## [0.7.12] - 2026-05-27

### Fixed
- Hybrid retrieval: sparse-leg RRF contribution is now dampened per-query
  when the sparse-CTE returns more than `sparse_flood_ratio * dense_count`
  rows. Targets the 3 short-common-token misses left by sub-project B
  (`Morne team developer role`, `Markus Koelmans team responsibility lead`,
  `Domain Catalog DocuWare domains`) without regressing the 5 long-rare-token
  wins from v0.7.8. The dampening fires only when the sparse leg is
  floodingly over-broad — long-tail queries that depend on OR-tsq recall stay
  untouched.

### Added
- `Settings.sparse_flood_ratio: float = 3.0` — pool-size ratio threshold
  (sparse_count / dense_count) above which dampening kicks in.
- `Settings.sparse_flood_dampening: float = 0.5` — multiplier applied to
  sparse_weight when threshold is exceeded. Both knobs are exposed in
  docforge.yml for per-deployment tuning without an engine rebuild.
- Two integration tests (`test_sparse_pool_dampening.py`): one for the
  flooded-pool scenario (target wins post-dampening), one regression guard
  for the balanced-pool case (sub-project B's wins preserved).

## [0.7.11] - 2026-05-27

### Changed
- **BREAKING:** minimum supported Python is now 3.13 (was 3.12). Bumped after
  `test_serve_remote_api_falls_back_to_env_var` was found to fail only on 3.12
  with a typer CliRunner stdout-flush bug that couldn't be reproduced or
  bisected on 3.13. CI now pins to 3.13.
- Integration-test helpers (`_vec`, `_insert_source`, `_insert_chunk`) extracted
  to `tests/integration/_helpers.py`. Removed duplicated copies from
  `test_search_hybrid.py` and `test_sparse_tsquery_or.py`.
- `test_sparse_tsquery_or.py` now constructs `Settings()` with kwargs instead
  of post-init mutation — safer if `Settings` ever becomes frozen.
- `latency_report.py:compute_summary` docstring trimmed (2nd paragraph
  duplicated the module-level WHY at lines 21-23).
- Over-narrative module/test docstrings in `test_sparse_tsquery_or.py` trimmed
  to one sentence each.

### Fixed
- CI test job installs `[azure,entra]` extras, resolving the 1 pre-existing
  failure (`test_azure_auth_raises_when_audience_unset`) and 3 collection
  errors in `test_auth.py::TestAuthModeEntra::*`.
- `test_serve_remote_api_falls_back_to_env_var` un-skipped (was skipped on
  Python 3.12; not relevant after the minimum bump).

## [0.7.10] - 2026-05-26

### Fixed
- **Critical MCP hang on first tool call** (`docforge serve --remote-api`). `RemoteBackend.search()` lazy-imported `format_search_results_markdown` from `docforge.mcp_server`, which transitively pulls in numpy, fastmcp, asyncpg, and the embedder model. Running this synchronous import chain inside the active asyncio event loop on first tool dispatch deadlocked the MCP subprocess for 90+ seconds with no inner timeout firing — the HTTP call returned 200 in ~700ms but the post-HTTP formatter import never completed. Symptom: `dw-docforge__search_documentation` tool calls appear to hang indefinitely.
- Fix: extracted `format_search_results_markdown` to a new stdlib-only `docforge.formatters` module. Both `remote_client.py` and `mcp_server.py` now import from there at module level. Reproduced fix end-to-end: MCP tool returns in ~1.6s, no hang. The v0.7.9 60s safety-net timeout still applies as a backstop but no longer fires under normal load.
- Regression guard (`test_formatters_module_has_no_heavy_imports`) ensures `docforge.formatters` stays import-light.

### Added
- Diagnostic log breadcrumbs inside `RemoteBackend.search()` at each phase (request start/return, JSON parse, format, return) for future hang diagnosis.

## [0.7.9] - 2026-05-26

### Fixed
- MCP server (`docforge serve --remote-api`): added hard 60s safety-net timeout at the tool wrapper layer (`search_documentation` and `list_sources`). Existing inner timeouts (httpx 30s read + 2s retry-backoff + 15s Azure token-mint) rely on `asyncio.wait_for` cancellation propagating through the call chain — but if any downstream code (Azure SDK token refresh, FastMCP stdio, httpx pool) doesn't honor cancel, the tool call hangs indefinitely. The new outer `asyncio.timeout(60.0)` strictly bounds total wall-clock time per tool call regardless of inner state. On safety-net timeout, returns a diagnostic error string pointing at common causes.

### Added
- MCP server stderr logging at each phase (auth, HTTP request, tool entry/exit) with elapsed-ms tags. Next time a hang occurs, the last phase logged identifies where execution stalled. Logs use stderr (not stdout) to avoid corrupting the FastMCP JSON-RPC protocol.

## [0.7.8] - 2026-05-26

### Fixed
- Hybrid retrieval: sparse-leg tsquery now uses OR between tokens (was AND). Multi-keyword queries (5+ tokens, common with AI-coding-assistant clients) were getting ~0 hits from the sparse leg, causing RRF to collapse to dense-only. With OR, the sparse leg surfaces chunks with partial keyword matches and `ts_rank_cd` grades them by overlap + IDF.

## [0.7.7] - 2026-05-22

### Fixed

- **`chunks.title` now carries Rule 4's `[STALE YYYY] ` prefix on Confluence ingest.** In v0.7.6 the prefix was applied to `sources.title` (via `crawl_page` returning a prefixed `CrawledPage.title`) but the chunk-level INSERT in `_ingest_confluence_source` was still passing `source.title` — the unprefixed YAML config name — so the prefix never reached `chunks.title`, the column the search API surfaces. Surgical one-line fix at the chunks INSERT site (`source.title` → `page.title`). Git ingest (`_ingest_git_source`) was unaffected — it already passes `file.title` which correctly carries Rule 3's `[LEGACY]` prefix.

### Notes for operators

- **Re-ingest required to backfill.** Prod data created with v0.7.6 has `sources.title = "[STALE YYYY] …"` but `chunks.title = "…"` (no prefix). After upgrading to v0.7.7, re-run `docforge ingest` for any sources that were marked stale to backfill the prefix into chunks (the content_hash short-circuit will skip pages whose Confluence body hasn't changed — bump the threshold or force a re-ingest if you need every previously-stale source to refresh).

## [0.7.6] - 2026-05-21

### Added

- **`legacy_path_substring` setting (default `"legacy"`).** Files whose path (case-insensitive) contains this substring get a `[LEGACY] ` title prefix during git ingest. Signals to downstream consumers — both AI assistants and FTS tokenizers — that the content describes a deprecated component. Set to `None` to disable. Implemented in `crawlers/git.py`. **NB: when this lands, all existing git titles change shape (POSIX paths, optional prefix). Deployments upgrading from <0.7.6 must truncate `sources` + `chunks` and re-ingest, OR run `docforge ingest --purge-orphans --confirm` to clean orphaned rows from the previous Windows-style identifiers.**
- **`stale_threshold_months` setting (default `36`).** Confluence pages whose `version.createdAt` is older than this many months get a `[STALE YYYY] ` title prefix. Mostly forward-looking — at the default threshold a 2026 corpus has very few pages crossing the line. Set to `None` to disable. Implemented in `crawlers/confluence.py` via a pure `_apply_stale_prefix` helper applied inside `crawl_page` itself (kwarg-driven, mirroring `crawl_repo`'s `legacy_path_substring`).
- **`CrawledPage.last_modified: datetime` field.** Extracted from Confluence v2 API `version.createdAt`. Missing/unparseable values fall back to `datetime.now(timezone.utc)` with a debug/warning log line (page treated as fresh, prefix not applied).

### Changed

- **Git crawler titles are POSIX-normalized.** Previously, on Windows ingest, titles contained mixed `/` (repo boundary) and `\` (in-repo path) separators — a Windows-ingest artifact that also degraded Postgres FTS tokenization. The `relative.as_posix()` fix means titles like `cloud-proxy/docs/aot-benchmarks.md` everywhere, regardless of ingest host OS. **This is a breaking change for `_git_source_identifier` shape on Windows-ingested deployments — see the migration note in the `legacy_path_substring` bullet above.**
- **`_ingest_git_source` signature gained `settings: Settings` as a 2nd positional argument** (mirroring `_ingest_confluence_source`). Internal-only; the only caller (`ingest_all`) was updated.
- **`lint.py` no longer double-normalizes paths.** Dropped two `.replace("\\", "/")` calls that became no-ops after the crawler's POSIX guarantee.

## [0.7.5] - 2026-05-19

### Added

- **Split httpx timeouts + one retry on 5xx in `RemoteBackend`.** Replaces the single 30s timeout with `connect=10s, read=30s, write=10s, pool=5s` and retries once on 5xx with a 2-second backoff. Failed calls return clear error strings (e.g., `"DocForge /search timed out after 30s"`) instead of hanging the MCP session indefinitely.
- **15s timeout on Azure token mint.** `AzureAuth.headers()` wraps `DefaultAzureCredential.get_token` in a 15-second `asyncio.wait_for`. Token-mint stalls from corrupted credential caches now surface as `TimeoutError` rather than blocking forever.
- **`/search` debug mode.** New optional `debug: bool` request field. When true, the response includes per-result `dense_rank`, `sparse_rank`, `rrf_score` plus an envelope-level `debug` block carrying `weights` and `k`. Default behavior is unchanged for callers that don't opt in.
- **`docforge.scripts.eval_search --direct` mode.** Bypasses the HTTP API and calls `perform_search()` directly against the configured Postgres + Embedder. Mutually exclusive with `--api-url`. Hard-fails if `embedder_url` is unset to prevent accidental local Qwen-4B download. Use cases: local sweep without operating the Container App, identical-rank parity testing.
- **Inline rank info in `eval_search --debug` output.** Per-result `(d#N s#M)` rank info displayed inline, making per-query failure-mode categorization tractable.

### Changed

- `api.search` refactored to delegate to a new `perform_search()` helper that is also called by `eval_search --direct`. SQL now projects `dense_rank` and `sparse_rank` from the inner CTEs. No behavior change at default request shape; opens the door to debug-mode rank introspection and direct-mode eval runs.

## [0.7.4] - 2026-05-15

### Fixed

- **CUDA cache accumulation between encode batches.** `Embedder.embed` now calls `torch.cuda.empty_cache()` after each inner batch. Without this, PyTorch's activation buffers from prior sub-batches stay resident; large sources (e.g., a 100-chunk file at `batch_size=8` → 13 inner encodes) accumulate cache until later batches OOM despite each individual batch being tiny. Diagnosed via `nvidia-smi` on the running embedder: idle GPU memory was 15.4 GiB / 16 GiB even with no inference in flight.
- **FP16 partial-load workaround.** Empirically, the `model_kwargs={"torch_dtype": "float16"}` path doesn't reach every submodule for sentence-transformers + Qwen3 + Matryoshka (Dense/projection layers can stay FP32, doubling effective model VRAM). `Embedder.__init__` now also calls `self._model = self._model.half()` post-init when `fp16=True`, as belt-and-suspenders FP16 enforcement.

## [0.7.3] - 2026-05-13

### Fixed

- **Embedder OOM on sources with >25-30 chunks.** v0.7.2's FP16 fix raised the per-call ceiling but sources with 50+ chunks (Confluence release-note pages, git_repos with many markdown files) still tripped CUDA OOM. `Embedder.embed` now splits the input into batches of `Settings.embedding_batch_size` (default 32) before calling `SentenceTransformer.encode`. Activation memory per call is now bounded regardless of input size.

### Added

- `Settings.embedding_batch_size: int = 32` — internal cap on per-encode batch size. Configurable via env `EMBEDDING_BATCH_SIZE` or `docforge.yml`. Raise on bigger GPUs (A100/H100); lower if you hit OOM on smaller hardware.

## [0.7.2] - 2026-05-13

### Fixed

- **Embedder OOM under load on Tesla T4 GPU.** `Embedder` now loads Qwen3-Embedding-4B in FP16 by default. Halves VRAM footprint (~14.2 GiB FP32 → ~7.2 GiB FP16 on the T4's 16 GiB), eliminating `torch.OutOfMemoryError` on batches above ~10 chunks. Qwen3 model card officially recommends FP16 for production inference.
- **CUDA driver mismatch in embedder image.** `Dockerfile.embedder` now pre-installs `torch==2.5.1+cu124` from PyTorch's cu124 index. Without this pin, pip resolved a torch with CUDA 13 nvidia wheels which silently fell back to CPU on Azure Container Apps T4 nodes (host driver 12.4).
- **`RemoteEmbedder` default timeout was too tight for Qwen-4B inference under cold connections.** Bumped from 5s → 60s. The retry loop still bounds total wait to ~120s.

### Added

- `Settings.embedding_fp16: bool = True` — controls the FP16 default. CPU-only deployments can flip to False via env `EMBEDDING_FP16=false` or `docforge.yml`. GPU deployments should leave at True.

### Notes for operators

- CCL production deployment: redeploy `docforge-embedder` from the new image. No schema migration; no search-api rebuild required (search-api on v0.7.0 continues to function — it benefits from the bundled 60s timeout the next time it's rebuilt for other reasons).
- See dw-docforge `docs/superpowers/specs/2026-05-13-ingest-completion-design.md` for the full cutover procedure.

## [0.7.0] - 2026-05-12

### Changed

- **Embedder model: EmbeddingGemma-300M → Qwen3-Embedding-4B.** Default embedding model swap with full operational migration. Apache 2.0 license replaces Gemma Terms; ~7pp MTEB-Multilingual lift at the model level. Engine code defaults now `Qwen/Qwen3-Embedding-4B` / 1024 dim. The `processors.Embedder` class now forwards `truncate_dim=expected_dimensions` to `SentenceTransformer(...)` so Matryoshka truncation happens at the ST layer. `Embedder.embed_query()` passes `prompt_name="query"` when the model has the template (Qwen3 family); legacy models skip the kwarg.
- **`chunks.embedding` dim 768 → 1024.** Matryoshka truncation from Qwen-4B's 2560 native; quality retention estimated 95-98% per Qwen's own truncation guidance.
- **`schema.sql` updated to `vector(1024)`** for fresh-DB init parity.

### Added

- `deploy/azure/main.bicep`: optional Workload-Profiles env (Consumption + opt-in `gpu-nc8as-t4` profile), plus `nameSuffix`, `searchApiWorkloadProfileName`, `embedderWorkloadProfileName`, `embedderCpu`, `embedderMemoryGi`, `enableWorkloadProfiles`, `enableGpuProfile` params. Operators can keep the existing Consumption-tier sizing (default) or opt into GPU inference via bicepparam.
- `sql/migrations/009_embedding_dim_1024.sql`: drops + re-creates `chunks.embedding` at the new dim. **BREAKING**: re-ingest required after applying.

### Migration notes

This release requires a coordinated cutover: bring up a new embedder Container App backed by the GPU workload profile, point search-api at it, apply migration 009, truncate chunks, re-ingest all sources. Expected downtime: 30-45 min during low-usage hours. See the migration plan in `dw-docforge/docs/superpowers/plans/2026-05-12-qwen-embedder-migration-plan.md` for the exact step ordering and rollback procedure.

Operators on legacy Gemma deployments can continue on v0.6.x indefinitely — the engine doesn't require this upgrade.

## [0.6.2] - 2026-05-12

### Fixed

- `api.py` lifespan now calls `logging.basicConfig(level=INFO, force=True)` so that `docforge.api` INFO logs (per-phase `search_phases` line, `query_log cleanup` heartbeat, error context) reach Container Apps stdout. Uvicorn's default config leaves the root logger at WARNING, which silently dropped all application-side INFO logs. Discovered during the v0.6.1 deploy: the `search_phases` line we just added was working in unit tests (pytest's caplog intercepts everything) but invisible in production.

## [0.6.1] - 2026-05-12

### Added

- `api.py`: per-phase latency log line on every `/search` call:

      search_phases query_len=N t_embed_ms=X t_db_ms=Y t_total_ms=Z rows=M

  Lets operators tail Container Apps logs to see where /search time is spent (embedder vs Postgres vs Python) without a full distributed-tracing setup. No behavior change.

## [0.6.0] - 2026-05-09

### Added

- Migration 008: `chunks.title` TEXT NOT NULL DEFAULT '' column, backfilled from `sources.title` via JOIN UPDATE. New `chunks.text_tsv` GENERATED expression combines title (weight A), section_title (weight B), and text (weight D) via `setweight()`. Lock window roughly 15-90 seconds on ~20k chunks during deploy.
- `ingest.py`: both INSERT call sites (Confluence path uses `source.title`; git path uses `file.title`) populate the new column so post-deploy ingests stay populated.

### Changed

- **Sparse retrieval path now matches titles and section headings**, weighted via `ts_rank_cd` defaults (title ~10x body, section ~4x body). Improves recall on queries where the right doc's title contains query terms but its chunk bodies don't — the failure mode identified in `dw-docforge/docs/superpowers/findings/2026-05-09-hybrid-regression-diagnosis.md`. No engine code default changes; behavior shift is purely in the GENERATED tsvector expression.

### Migration notes

- Migration 008 must be applied to the production Postgres BEFORE the new image rolls. The OLD container's SQL doesn't reference the new column shape, so adding it (via a column drop+recreate) is safe while the old container is still serving. The NEW container's SQL uses the new column shape directly. Same migration-first deploy ordering as v0.5.0's migration 007.

## [0.5.2] - 2026-05-09

### Added

- `deploy/azure/main.bicep`: new `denseWeight` and `sparseWeight` parameters (default `'1.0'`) wired through to Container App env vars `DENSE_WEIGHT` and `SPARSE_WEIGHT`. Lets deployers tune weighted RRF via bicepparam without touching engine code defaults. Engine code defaults stay at 1.0 (= classic RRF) per Bruch et al. 2023's caution that weight tuning is dataset-specific.

### Changed

- No runtime behavior change at engine defaults. Operators can now express their tuned weights declaratively in `*.bicepparam` instead of imperatively via `az containerapp update --set-env-vars`.

## [0.5.1] - 2026-05-09

### Added

- `Settings.dense_weight` (default 1.0) and `Settings.sparse_weight` (default 1.0): per-retriever multipliers on the RRF reciprocal-rank score. At defaults, behavior is identical to v0.5.0 classic RRF. Tune via `DENSE_WEIGHT` / `SPARSE_WEIGHT` env vars or `docforge.yml`.
- New integration test `test_weights_shift_ranking` proving the weight params flow through the SQL formula end-to-end (`sparse_weight=0` collapses to dense-only ranking; `dense_weight=0` collapses to sparse-only).

### Changed

- `/search` SQL RRF formula now multiplies each retriever's reciprocal-rank by its corresponding weight. No behavior change at default weights; opens the door to weight-tuned hybrid retrieval. See `dw-docforge/docs/superpowers/plans/2026-05-09-hybrid-retrieval-followup-plan.md` for the sweep methodology.

## [0.5.0] - 2026-05-09

### Added

- **Hybrid retrieval** (`api.py /search`): Postgres FTS sparse path runs alongside the existing pgvector dense path; results fused via classic Reciprocal Rank Fusion (k=60). Most useful for exact-identifier queries ("BackgroundProcessService dispatch", "ADR-002") that dense-only retrieval missed. Tag-boost re-rank now applies to the RRF score.
- New `Settings` fields: `rrf_k` (default 60), `hybrid_pool_size` (default 100), `fts_language` (default `'english'`). All safe defaults; no .env / docforge.yml change required.
- Migration 007: adds `chunks.text_tsv` GENERATED STORED `tsvector` column + GIN index. Postgres backfills existing rows on `ALTER TABLE` — no re-ingest needed.

### Changed

- **`SearchResult.similarity` field semantic.** Previously: cosine similarity ∈ [0, 1]. Now: fused RRF score, typically ∈ [0, 0.033]. Result ordering is what consumers should rely on; the absolute score is no longer cosine-comparable. The MCP search-tool consumer (Claude) reads results by rank, so end-user behavior is unchanged.

### Migration notes

- The migration is additive. Existing dense-only queries continue to work against a v0.4.x database (the new column and index simply go unused). After upgrading to v0.5.0 image, run `init_db` (which iterates packaged migrations) or apply `007_add_chunks_text_tsv.sql` directly to add the column and index. For ~tens of thousands of chunks, lock window is sub-second.

## [0.4.1] - 2026-05-08

### Changed

- `RemoteBackend` now reuses a single `httpx.AsyncClient` across calls (was: a fresh client per request). Reduces tool-invocation latency by ~100-200 ms over public-internet deployments by amortizing TCP+TLS handshake. Pattern mirrors `RemoteEmbedder`.
- `--auth` is now an `AuthName` Enum (was: plain string). Adds Typer tab-completion, earlier validation, and `mypy` exhaustiveness on the dispatch.
- `serve()` now warns to stderr when `--auth` is set without `--remote-api` (previously silently ignored).
- Extracted `format_search_results_markdown()` shared helper between local `mcp_server.py` and remote `remote_client.py`. Standardized result-header separator on `--`. (Was: em-dash in local, double-hyphen in remote.)
- `RemoteBackend.search` and `list_sources` now share a `_request()` helper that owns auth-fetch, network-error handling, and 401/5xx/non-200 branching. Removes ~20 lines of duplicated scaffolding.

## [0.4.0] - 2026-05-08

### Added

- `docforge serve --remote-api $URL` mode runs an MCP server that proxies tool calls to a remote docforge search-api. Use this on team-member machines to consume a hosted deployment without running a local Postgres or ingest pipeline.
- `--auth none|bearer|azure` flag selects the auth provider. `azure` requires `pip install docforge-cli[azure]`.
- New `[azure]` extra: client-side `azure-identity` + `aiohttp` (subset of `[entra]`).
- Identity env vars (`DOCFORGE_USER`, `DOCFORGE_TEAM`, `DOCFORGE_AREA`) supplied to the search request body when set; omitted if unset.

### Changed

- `SearchRequest.user_name` and `SearchRequest.team_name` are now optional (`str | None = None`). Backwards-compatible: existing clients sending strings still validate.
- `/search` handler resolves the effective user from the auth subject (`user.preferred_username`) when present, falling back to `req.user_name` or `"anonymous"` if both are absent.

## [0.3.0] - 2026-05-07

### Added

- Threat model now linked from the "When docforge is the wrong choice" section in both `README.md` and the microsite homepage. External adopters comparing docforge against alternatives can find the explicit trust assumptions without having to dig into `docs/`.
- "License compatibility" section in `README.md` naming the [Gemma Terms of Use](https://ai.google.dev/gemma/terms) restrictions (no harmful use, no Gemma-derivative competitors) for adopters considering redistribution.
- Optional `expected_dimensions` parameter on `Embedder.__init__`. When provided, asserts the loaded model's dimension matches; raises `RuntimeError` with a clear remediation message on mismatch. Defaults to `None` (guard dormant) for backwards compatibility with direct `Embedder()` callers.
- `docs/log-privacy.md` — privacy & retention policy for the `query_log` table. Documents purpose, retention, redaction patterns, access roles, and a right-to-erasure runbook. Partially aspirational as of Phase 3; the "Implementation status" section names which items ship later in v0.3.

### Changed

- MCP server identifier renamed from `knowledge-hub` to `docforge` (the original name was a leftover from the project's original DocuWare-internal incarnation). **Behavior change for MCP clients:** the server name shown in MCP client UIs changes; clients that filter on server name need to update. No protocol or tool surface changes.
- All runtime and dev dependencies in `pyproject.toml` now carry strict-major upper bounds (e.g. `fastapi>=0.115,<1.0`, `pydantic>=2.9,<3.0`, `pytest>=9.0,<10.0`). Floor-only pins previously allowed fresh installs to pull an untested next-major version of any dep. `numpy>=1.26,<3.0` is the documented exception, covering both 1.x and 2.x. Dependabot continues to pick up minors and patches.
- All four `Embedder(...)` construction sites in the API, MCP server, ingest pipeline, and CLI now pass `expected_dimensions=settings.embedding_dimensions`, enabling the new dimension guard in production. **Behavior change:** if your configured `embedding_dimensions` disagrees with the loaded embedding model's actual dimension, the process now fails fast at startup with a clear remediation message ("change `embedding_model` in `docforge.yml`, or update `embedding_dimensions` and migrate the schema"), instead of failing later at INSERT time with a cryptic pgvector error. Adopters with a stale `embedding_dimensions` should update it before upgrading.
- API and MCP search request boundaries are now hard-capped: `query` is rejected over 8000 characters, `limit` is rejected outside `[1, 50]`. **Behavior change:** clients that previously got 200 with `limit=10000` (and a slow response) now get HTTP 422 with a Pydantic-shaped error detail naming the offending field. Internal `Embedder.embed` raises `ValueError` when called with more than 256 texts in one batch.
- API process is now stateless — module globals replaced by a FastAPI lifespan that yields settings, pool, embedder, and azure_scheme into per-request `request.state`; handlers access them via `Depends` getters. **Behavior change for tests:** consumers that monkey-patched `api._embedder`, `api._get_settings`, or `api.get_pool` need to switch to `app.dependency_overrides`. No deployer-facing change.
- Asyncpg pool sizing is tunable per deployment via the new `Settings.pool_min_size` and `pool_max_size` fields (env: `POOL_MIN_SIZE`, `POOL_MAX_SIZE`). Defaults raised from `1`/`5` to `5`/`25` to match the operating profile. Operators on smaller Postgres tiers should lower these explicitly.
- `query_log` cleanup loop now coordinates across replicas via a transaction-scoped Postgres advisory lock (`pg_try_advisory_xact_lock(0xD0CF0001)`). At most one replica runs DELETE per interval; the others log a debug line and skip. Replaces the prior "every replica deletes once per hour" pattern (which was idempotent but wasteful).
- `api.py:search` and `mcp_server.py:search_documentation` now wrap the synchronous `Embedder.embed_query` call in `asyncio.to_thread`. The event loop remains responsive during embedding inference. Closes the original Finding 1 from the v0.2.1 critical review.
- The embedding model can now be hosted as a separate Container App via the new `EMBEDDER_URL` setting (Phase 4b). When set, the search API, MCP server, and ingest worker delegate embedding to that URL instead of loading the model in-process. Search API replicas drop from ~2 GB RSS to ~400 MB and start in <10s. The split is opt-in: leaving `EMBEDDER_URL` empty keeps the in-process behaviour.
- New `Dockerfile.embedder` builds the embedder service image. The EmbeddingGemma-300M model is baked into the image at build time using a BuildKit secret mount (`--mount=type=secret,id=hf_token`); the HuggingFace token never enters any image layer.
- New shared-secret bearer auth between the search API and the embedder service via `EMBEDDER_TOKEN`. The embedder service refuses to start without it; `RemoteEmbedder` raises at construction if `embedder_url` is set without `embedder_token`. **Behavior change for hosted deployments:** Bicep gains a new `embedderToken` parameter (required; operators generate via `openssl rand -hex 32` and rotate by re-deploying with a new value); the embedder service and search API both reference this secret from Key Vault.
- Async-only `RemoteEmbedder` surface; `Embedder` gains `aembed` / `aembed_query` async wrappers via `asyncio.to_thread`; all async call sites (api, mcp_server, ingest) now use `await embedder.aembed_query(...)` / `aembed(...)`. The CLI bypasses the factory and constructs `Embedder(...)` directly so local CLI runs always use the in-process model regardless of `EMBEDDER_URL`.
- Documentation polish: `deploy/azure/README.md` updated for v0.3 Phase 4b architecture (7 resources, embedder section, ACR Standard SKU note, updated cost). Microsite architecture and deployment pages note the embedder sidecar split. README's HF token prerequisite promoted from FAQ to quick-start. Broken `.superpowers/`-internal link in microsite deployment guide replaced with the actual `az postgres flexible-server restore` command. Stale internal planning artifacts removed from `docs/superpowers/` (the move to gitignored `.superpowers/` was claimed in 0.2.1 but the originals weren't deleted).
- Bicep template: `acrSku` parameter added (default `'Standard'`) so the v0.3 Phase 4b embedder image (~13.6 GB) deploys to ACR out-of-the-box. Previously `'Basic'` was hard-coded, requiring a manual `az acr update --sku Standard` post-deploy. Documentation updated to describe the actual template defaults: `embedderMinReplicas=0` (scale-to-zero, set to `1` for production), embedder Container App size `2 CPU / 4 GiB`, embedder cold-start ~5–10s with baked model (Dockerfile.embedder bakes EmbeddingGemma at build time, so there is no runtime download). Cost estimate updated from ~$45/month (incorrect, based on the wrong embedder size) to ~$90/month for default-on production sizing. Deploy README and microsite deployment guide also gain a Windows-friendly `HF_TOKEN` export prerequisite and PowerShell/Python alternatives to `openssl rand -hex 32` for embedder-token generation.

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
