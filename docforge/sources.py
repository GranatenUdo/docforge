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


class GitRepoSourceConfig(BaseModel):
    type: Literal["git_repo"]
    repo_path: str
    include_patterns: list[str] = ["README.md", "CLAUDE.md", "docs/**/*.md"]
    title: str


SourceConfig = Annotated[
    ConfluenceSourceConfig | GitRepoSourceConfig,
    Field(discriminator="type"),
]


class SourcesFile(BaseModel):
    sources: list[SourceConfig]


def load_sources(path: str | Path) -> list[SourceConfig]:
    """Load source configurations from a YAML file."""
    with open(path) as f:
        data = yaml.safe_load(f)
    return SourcesFile.model_validate(data).sources
