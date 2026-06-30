"""Settings loading — merges defaults, docforge.yml, .env, env vars, and kwargs.

Precedence: kwargs > yml > env > .env > defaults. yml values are passed to
pydantic-settings via `super().__init__(**merged)`, which treats them as
init-kwargs (highest priority after explicit kwargs).
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Hard upper bound on rerank_top_n AND the max (query, passage) pairs the
# reranker sidecar will score in one request (the sidecar's RerankRequest.texts
# uses this as max_length). The search path sends head = rows[:rerank_top_n],
# so bounding rerank_top_n here guarantees a legitimate call never exceeds the
# sidecar cap — a too-large RERANK_TOP_N fails fast at startup instead of
# 502-ing at query time. Mirrors the embedder's MAX_BATCH_SIZE.
MAX_RERANK_BATCH = 256


class AuthSettings(BaseModel):
    mode: Literal["none", "entra"] = "none"
    tenant_id: str = ""
    audience: str = ""

    @model_validator(mode="after")
    def _validate_entra_fields(self):
        if self.mode == "entra":
            if not self.tenant_id:
                raise ValueError(
                    "auth.mode=entra requires auth.tenant_id to be set "
                    "(via docforge.yml or AUTH__TENANT_ID env var)"
                )
            if not self.audience:
                raise ValueError(
                    "auth.mode=entra requires auth.audience to be set "
                    "(via docforge.yml or AUTH__AUDIENCE env var)"
                )
        return self


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_nested_delimiter="__",
    )

    # Database
    database_url: str = "postgresql://docforge:localdev@localhost:5432/docforge"

    # Confluence
    confluence_base_url: str = ""
    confluence_email: str = ""
    confluence_api_token: SecretStr = SecretStr("")

    # HuggingFace token for model access
    hf_token: SecretStr = SecretStr("")

    # Embedding model
    embedding_model: str = "Qwen/Qwen3-Embedding-4B"
    embedding_dimensions: int = 1024
    # FP16 inference. Qwen3-Embedding-4B model card officially recommends
    # this for production GPU deployments — halves VRAM footprint
    # (~14 GiB FP32 -> ~7 GiB FP16 on the Tesla T4's 16 GiB), leaving
    # ample headroom for activation memory. CPU-only deployments should
    # flip this to False (FP16 on CPU is slow on most boxes; FP32 wins).
    embedding_fp16: bool = True
    # Maximum number of texts passed to a single SentenceTransformer.encode()
    # call. Larger batches use less Python overhead but more GPU VRAM for
    # activations. The default 32 was tuned for Qwen-4B + Tesla T4 (16 GiB
    # VRAM); accommodates ~500-token chunks without OOM. Raise on bigger
    # GPUs (A100/H100); lower if you hit OOM on smaller hardware.
    embedding_batch_size: int = 32
    chunk_max_tokens: int = 500

    # Sources config
    sources_file: str = "sources.yml"

    # Ranking weight (see docforge.ranking.compute_boosted_score). The boost is
    # similarity * (1 + tag_match_weight * |source_tags ∩ user_tags|). There is
    # deliberately no org/"everyone" boost: 'org' is an ordinary team tag.
    tag_match_weight: float = 0.1

    # Hybrid retrieval (RRF over dense + sparse). rrf_k=60 matches the universal
    # default (Azure AI Search, Elasticsearch, OpenSearch); higher k flattens
    # the rank distribution, lower amplifies. hybrid_pool_size is the top-N
    # from each retriever feeding RRF — 4-10x req.limit is the standard rule,
    # and req.limit caps at 50 so 100 covers under-recalled queries with margin.
    # fts_language is the Postgres text-search config; switch to 'simple' if
    # non-English content appears in the corpus.
    rrf_k: int = 60
    hybrid_pool_size: int = 100
    fts_language: str = "english"

    # Weighted RRF — multipliers on each retriever's reciprocal-rank contribution.
    # Defaults at 1.0 = classic RRF (the v0.5.0 default). Tune via env var
    # (DENSE_WEIGHT / SPARSE_WEIGHT) or docforge.yml; eval-driven.
    dense_weight: float = 1.0
    sparse_weight: float = 1.0

    # Sparse-pool dampening (sub-project D, v0.7.12). When the sparse CTE
    # returns more than sparse_flood_ratio * dense_count rows, the sparse leg
    # is treated as "flooded" with weakly-relevant chunks (typical for
    # short-common-token queries like "common terms shared across many docs") and
    # its RRF contribution is scaled by sparse_flood_dampening. Per-query
    # signal — legitimately rare long-tail queries (sparse pool small) keep
    # their full sparse weight. Both knobs tunable in docforge.yml without
    # an engine rebuild.
    # NOTE (v0.7.13 eval): with default hybrid_pool_size=100, both pools cap
    # at 100 so the ratio max is ~1.0 — the threshold rarely fires in
    # practice. Kept for future tuning but the title_weight_a knob below is
    # the load-bearing fix for short-common-token misses.
    sparse_flood_ratio: float = 3.0
    sparse_flood_dampening: float = 0.5

    # Title-dominance factor for ts_rank_cd (sub-project E, v0.7.13). Postgres
    # ts_rank_cd weights must be in [0, 1] so A is capped at 1.0. To make
    # title-matches dominate body-keyword density, the SQL divides D/C/B by
    # this factor (so weights become {D/F, C/F, B/F, A=1.0}). With F=4.0:
    # default ratio A:D goes from 10:1 to 40:1 — title-match contributes 4x
    # more, relative to body match, than under the Postgres defaults.
    # Migration 008 indexed chunks.title at position A. Fixes the 3 short-
    # common-token misses (Domain Catalog / Markus Koelmans / Morne) where
    # the target chunk's title contains the query terms but its body doesn't
    # repeat them as densely as competitor chunks. Tune in docforge.yml.
    title_weight_a: float = 4.0

    # Sources-hygiene rules — see 2026-05-20-sources-hygiene-design.md.
    # legacy_path_substring: when not None, files whose path (case-insensitive)
    # contains this substring get a "[LEGACY] " title prefix. Used to deprioritize
    # legacy-service docs (e.g. CIS.BackgroundProcessService/_legacy-components-descriptions/)
    # without removing them from the index.
    legacy_path_substring: str | None = "legacy"

    # stale_threshold_months: when not None, Confluence pages whose
    # version.createdAt is older than this many months get a "[STALE YYYY] "
    # title prefix. Mostly forward-looking — at the default 36mo threshold
    # the 2026-05-20 corpus has few pages crossing the line.
    stale_threshold_months: int | None = 36

    # Default identity (used as CLI flag defaults when set via env/yml)
    default_user_name: str = ""
    default_team_name: str = ""
    default_area_name: str = ""

    # MCP surface text for `serve --remote-api` (see remote_client.run_remote_mcp).
    # Empty = use the engine's built-in generic defaults. A downstream deployment
    # injects org-specific coverage + the team-name/abbreviation vocabulary via
    # MCP_INSTRUCTIONS / MCP_TOOL_DESCRIPTION env vars so the calling assistant
    # knows when to call docforge and what it covers.
    mcp_instructions: str = ""
    mcp_tool_description: str = ""

    # Auth (opt-in Entra ID for /search + /sources)
    auth: AuthSettings = AuthSettings()

    # query_log retention — app-level cleanup loop deletes rows older than this
    query_log_retention_days: int = 180

    # When true, /search writes per-result snapshots to query_result (capture
    # for the review/feedback loop). Default off so other consumers are
    # unaffected; a downstream deployment can enable it via bicepparam (LOG_RESPONSES=true).
    log_responses: bool = False

    # asyncpg pool sizing — defaults match the operating profile (multi-replica,
    # bursty AI-assistant traffic). Smaller deploys can lower these via
    # POOL_MIN_SIZE / POOL_MAX_SIZE env vars.
    pool_min_size: int = 5
    pool_max_size: int = 25

    # Embedder sidecar (Phase 4b). When `embedder_url` is set, the API,
    # MCP, and ingest paths delegate embedding to that URL via
    # RemoteEmbedder; when empty, an in-process Embedder is loaded.
    embedder_url: str = ""
    embedder_token: SecretStr = SecretStr("")

    # Cross-encoder reranker (default OFF). When `rerank_enabled`, the top
    # `rerank_top_n` hybrid candidates are re-scored by a cross-encoder served
    # at `reranker_url` (RemoteReranker, bearer auth via `reranker_token`).
    # `rerank_top_n` must not exceed `hybrid_pool_size` — you cannot rerank
    # more candidates than the hybrid pool produces. It should also be >= the
    # largest expected request limit, since positions beyond it in the search
    # results are raw RRF (not reranked) — see the perform_search seam.
    rerank_enabled: bool = False
    # rerank_model: consumed by the reranker sidecar (reranker_api.py) to load
    # the cross-encoder, NOT by the in-engine search path (which talks to the
    # sidecar over HTTP via RemoteReranker).
    rerank_model: str = "BAAI/bge-reranker-v2-m3"
    rerank_top_n: int = Field(50, ge=1, le=MAX_RERANK_BATCH)
    reranker_url: str = ""
    reranker_token: SecretStr = SecretStr("")
    # Reranker sidecar GPU controls (consumed by reranker_api.py / the in-process
    # Reranker, NOT the search path). They bound activation memory so a batch of
    # long passages does not OOM the T4: rerank_max_length truncates each
    # (query, passage) pair (bge-reranker-v2-m3 allows up to 8192 tokens, whose
    # O(n^2) attention is the dominant OOM driver), and rerank_batch_size caps
    # the per-forward batch. Mirrors the embedder's EMBEDDING_BATCH_SIZE fix and
    # is tunable via the reranker app's env (RERANK_BATCH_SIZE / RERANK_MAX_LENGTH)
    # without an image rebuild.
    rerank_batch_size: int = Field(8, ge=1)
    rerank_max_length: int = Field(512, ge=1)
    # Reranker fail-open (search path, NOT the sidecar). When True, a reranker
    # transport/timeout/5xx/malformed-permutation failure inside perform_search
    # is swallowed: the pre-rerank RRF-ordered pool is returned instead of
    # raising. Engine default is False (fail-CLOSED -- surface the 502/500 so a
    # silent recall drop is caught) to keep OSS behavior unchanged; dw-docforge
    # sets RERANK_FAIL_OPEN='true' in its bicepparam so off-hours reranker
    # scale-to-zero degrades to RRF instead of 502-ing. A Log Analytics alert on
    # the `search_rerank_fallback` WARNING replaces the old 502 signal.
    rerank_fail_open: bool = False
    # Per-request reranker timeout (seconds), forwarded into RemoteReranker so a
    # cold reranker sidecar can't hang the search path for the RemoteReranker
    # default 60s + retry (~120s). dw-docforge sets RERANK_TIMEOUT_SECONDS='12'.
    rerank_timeout_seconds: float = 60.0

    @model_validator(mode="after")
    def _validate_reranker(self):
        if self.rerank_enabled and not self.reranker_url:
            raise ValueError(
                "rerank_enabled is True but reranker_url is empty — "
                "the cross-encoder reranker needs a sidecar URL. Set "
                "RERANKER_URL via env or docforge.yml, or disable reranking."
            )
        if self.reranker_url and not self.reranker_token.get_secret_value():
            raise ValueError(
                "reranker_url is set but reranker_token is empty — "
                "RemoteReranker requires a bearer token. Set RERANKER_TOKEN "
                "via env or docforge.yml, or unset reranker_url."
            )
        # Only meaningful when reranking is on: lowering HYBRID_POOL_SIZE with
        # rerank OFF must not break startup over an unused rerank_top_n.
        if self.rerank_enabled and self.rerank_top_n > self.hybrid_pool_size:
            raise ValueError(
                f"rerank_top_n ({self.rerank_top_n}) must not exceed "
                f"hybrid_pool_size ({self.hybrid_pool_size}) — cannot rerank "
                "more candidates than the hybrid pool produces."
            )
        return self

    @model_validator(mode="after")
    def _validate_embedder_sidecar(self):
        if self.embedder_url and not self.embedder_token.get_secret_value():
            raise ValueError(
                "embedder_url is set but embedder_token is empty — "
                "RemoteEmbedder requires a bearer token. Set EMBEDDER_TOKEN "
                "via env or docforge.yml, or unset embedder_url."
            )
        return self

    def __init__(self, **kwargs) -> None:
        # Load from docforge.yml if present, then overlay with env vars
        yml_path = Path("docforge.yml")
        yml_values = {}
        if yml_path.exists():
            with open(yml_path, encoding="utf-8") as f:
                yml = yaml.safe_load(f) or {}
            # Flatten nested embedding config
            if "embedding" in yml:
                emb = yml.pop("embedding")
                if "model" in emb:
                    yml_values["embedding_model"] = emb["model"]
                if "dimensions" in emb:
                    yml_values["embedding_dimensions"] = emb["dimensions"]
                if "chunk_max_tokens" in emb:
                    yml_values["chunk_max_tokens"] = emb["chunk_max_tokens"]
            yml_values.update(yml)
        # YAML values are defaults; explicit kwargs and env vars override
        merged = {**yml_values, **kwargs}
        super().__init__(**merged)
