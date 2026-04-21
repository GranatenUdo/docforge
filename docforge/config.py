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
    embedding_model: str = "google/embeddinggemma-300m"
    embedding_dimensions: int = 768
    chunk_max_tokens: int = 500

    # Sources config
    sources_file: str = "sources.yml"

    # Ranking weights (see docforge.ranking.compute_boosted_score)
    tag_match_weight: float = 0.1
    org_tag_weight: float = 0.05

    # Default identity (used as CLI flag defaults when set via env/yml)
    default_user_name: str = ""
    default_team_name: str = ""
    default_area_name: str = ""

    # Auth (opt-in Entra ID for /search + /sources)
    auth: AuthSettings = AuthSettings()

    # query_log retention — app-level cleanup loop deletes rows older than this
    query_log_retention_days: int = 180

    def __init__(self, **kwargs) -> None:
        # Load from docforge.yml if present, then overlay with env vars
        yml_path = Path("docforge.yml")
        yml_values = {}
        if yml_path.exists():
            with open(yml_path) as f:
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
