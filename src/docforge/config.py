"""Settings loading — merges defaults, docforge.yml, .env, env vars, and kwargs.

Precedence: kwargs > yml > env > .env > defaults. yml values are passed to
pydantic-settings via `super().__init__(**merged)`, which treats them as
init-kwargs (highest priority after explicit kwargs).
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


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
    chunk_max_tokens: int = 500

    # Sources config
    sources_file: str = "sources.yml"

    # Ranking weights (see docforge.ranking.compute_boosted_score)
    tag_match_weight: float = 0.1
    org_tag_weight: float = 0.05

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

    # Default identity (used as CLI flag defaults when set via env/yml)
    default_user_name: str = ""
    default_team_name: str = ""
    default_area_name: str = ""

    # Auth (opt-in Entra ID for /search + /sources)
    auth: AuthSettings = AuthSettings()

    # query_log retention — app-level cleanup loop deletes rows older than this
    query_log_retention_days: int = 180

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
