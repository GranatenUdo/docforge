"""Crawler for local git repository documentation files.

Reads markdown files (README.md, CLAUDE.md, docs/**/*.md) from a local
git repo directory. No git clone — the repo must already be on disk.
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class CrawledFile:
    file_path: str
    title: str
    content: str
    content_hash: str
    repo_path: str


def crawl_repo(
    repo_path: str,
    include_patterns: list[str] | None = None,
) -> list[CrawledFile]:
    """Read documentation files from a local git repository.

    Args:
        repo_path: Absolute path to the repo root (e.g., "E:/MyRepo").
        include_patterns: Glob patterns for files to include.
                          Defaults to ["README.md", "CLAUDE.md", "docs/**/*.md"].
    """
    if include_patterns is None:
        include_patterns = ["README.md", "CLAUDE.md", "docs/**/*.md"]

    root = Path(repo_path)
    if not root.is_dir():
        logger.warning("Repo path does not exist: %s", repo_path)
        return []

    results: list[CrawledFile] = []
    seen: set[Path] = set()

    for pattern in include_patterns:
        for file_path in root.glob(pattern):
            if not file_path.is_file():
                continue
            if file_path in seen:
                continue
            seen.add(file_path)

            try:
                content = file_path.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError) as e:
                logger.warning("Cannot read %s: %s", file_path, e)
                continue

            if not content.strip():
                continue

            relative = file_path.relative_to(root)
            content_hash = hashlib.sha256(content.encode()).hexdigest()

            results.append(
                CrawledFile(
                    file_path=str(relative),
                    title=str(relative),
                    content=content,
                    content_hash=content_hash,
                    repo_path=str(root),
                )
            )

    logger.info("Found %d files in %s", len(results), repo_path)
    return results
