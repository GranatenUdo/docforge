"""Source configuration — pydantic models + YAML loader.

Each entry in `sources.yml` is a ConfluenceSourceConfig or a
GitRepoSourceConfig, discriminated by the `type` field.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Literal

import yaml
from pydantic import BaseModel, Field


class ConfluenceSourceConfig(BaseModel):
    type: Literal["confluence_page"]
    page_id: str
    space_key: str
    title: str
    tags: list[str] = []


class GitRepoSourceConfig(BaseModel):
    type: Literal["git_repo"]
    repo_path: str
    include_patterns: list[str] = ["README.md", "CLAUDE.md", "docs/**/*.md"]
    title: str
    tags: list[str] = []


class ConfluenceTreeSourceConfig(BaseModel):
    type: Literal["confluence_tree"]
    root_page_id: str
    space_key: str
    title: str
    tags: list[str] = []
    # Ingest only pages edited within this many months (None = no staleness
    # filter). Applied server-side via the CQL `lastmodified >= now("-NM")`
    # clause in enumerate_tree_page_ids. Default 24 = the ProDev policy.
    stale_months: int | None = 24


SourceConfig = Annotated[
    ConfluenceSourceConfig | GitRepoSourceConfig | ConfluenceTreeSourceConfig,
    Field(discriminator="type"),
]


class SourcesFile(BaseModel):
    sources: list[SourceConfig]


def load_sources(path: str | Path) -> list[SourceConfig]:
    """Load source configurations from a YAML file."""
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return SourcesFile.model_validate(data).sources
