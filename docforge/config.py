from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

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

    def __init__(self, **kwargs):
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
