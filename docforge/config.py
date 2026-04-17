from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    # Database
    database_url: str = "postgresql://docforge:localdev@localhost:5432/docforge"

    # Confluence
    confluence_base_url: str = "https://"
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
