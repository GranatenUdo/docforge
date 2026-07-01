"""Ingest pipeline — crawl → parse → chunk → embed → store.

`ingest_all` loads the sources list and runs the appropriate crawler for
each source type (Confluence page, Confluence tree, or local git repo). Per-source failures
are logged but do not abort the run.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Callable

import asyncpg
import numpy as np

from docforge.config import Settings
from docforge.crawlers.confluence import crawl_page, enumerate_tree_page_ids
from docforge.crawlers.git import crawl_repo
from docforge.db import get_pool
from docforge.processors.chunker import chunk_sections
from docforge.processors.embedder import Embedder
from docforge.processors.parser import Section, parse_confluence_html
from docforge.processors.tokenizer import get_chunk_tokenizer_fn
from docforge.sources import (
    ConfluenceSourceConfig,
    ConfluenceTreeSourceConfig,
    GitRepoSourceConfig,
    load_sources,
)

logger = logging.getLogger(__name__)


def _git_source_identifier(repo_path: str, file_path: str) -> str:
    """Canonical identifier for a git-repo source row. Must stay in sync with
    what _ingest_git_source INSERTs and what _purge_orphans matches against."""
    return f"git:{repo_path}:{file_path}"


async def ingest_all(
    settings: Settings,
    *,
    purge_orphans: bool = False,
    confirm: bool = False,
) -> None:
    """Run the full ingest pipeline for all configured sources.

    When purge_orphans=True, after all sources have been ingested, any
    `sources` rows whose identifier is not in the current sources.yml are
    reported (and — if confirm=True — deleted). See _purge_orphans."""
    sources = load_sources(settings.sources_file)
    logger.info("Loaded %d sources from %s", len(sources), settings.sources_file)

    logger.info("Loading embedding model...")
    embedder = Embedder.from_settings(settings)

    pool = await get_pool(
        settings.database_url,
        min_size=settings.pool_min_size,
        max_size=settings.pool_max_size,
    )
    # Use the real model tokenizer for chunk sizing regardless of embedder
    # backend. embedder.get_tokenizer_fn() is a word-count approximation on
    # RemoteEmbedder (embedder.py:329-330), which emits oversized chunks when
    # ingest delegates embedding to the sidecar (the ADO pipeline path).
    tokenizer_fn = get_chunk_tokenizer_fn(settings)

    succeeded = 0
    failed = 0
    failed_names: list[str] = []
    current_identifiers: set[str] = set()

    for source in sources:
        try:
            if isinstance(source, ConfluenceSourceConfig):
                await _ingest_confluence_source(source, settings, pool, embedder, tokenizer_fn)
                current_identifiers.add(source.page_id)
            elif isinstance(source, ConfluenceTreeSourceConfig):
                tree_ids = await _ingest_confluence_tree(
                    source, settings, pool, embedder, tokenizer_fn
                )
                current_identifiers.update(tree_ids)
            elif isinstance(source, GitRepoSourceConfig):
                git_identifiers = await _ingest_git_source(
                    source, settings, pool, embedder, tokenizer_fn
                )
                current_identifiers.update(git_identifiers)
            succeeded += 1
        except Exception:
            failed += 1
            failed_names.append(source.title)
            logger.error("Failed to ingest source: %s", source.title, exc_info=True)

    logger.info(
        "Ingest complete: %d succeeded, %d failed out of %d sources",
        succeeded,
        failed,
        len(sources),
    )
    if failed_names:
        logger.warning("Failed sources: %s", ", ".join(failed_names))

    if purge_orphans:
        # Only purge if ALL sources ingested cleanly. A failed source would
        # leave its identifier out of current_identifiers and get purged as
        # an orphan — data loss. Require zero failures before allowing purge.
        if failed > 0:
            logger.warning(
                "Skipping --purge-orphans: %d source(s) failed to ingest; "
                "their identifiers would be incorrectly classified as orphans.",
                failed,
            )
        else:
            await _purge_orphans(pool, current_identifiers, confirm=confirm)


async def _ingest_confluence_source(
    source: ConfluenceSourceConfig,
    settings: Settings,
    pool: asyncpg.Pool,
    embedder: Embedder,
    tokenizer_fn: Callable[[str], int],
) -> None:
    """Ingest a single configured Confluence page."""
    logger.info("Crawling Confluence: %s (page_id=%s)", source.title, source.page_id)
    await _ingest_one_confluence_page(
        source.page_id, source.tags, source.space_key, settings, pool, embedder, tokenizer_fn
    )


async def _ingest_confluence_tree(
    source: ConfluenceTreeSourceConfig,
    settings: Settings,
    pool: asyncpg.Pool,
    embedder: Embedder,
    tokenizer_fn: Callable[[str], int],
) -> list[str]:
    """Ingest every current, non-stale descendant page of a tree root.

    Returns the list of page-id identifiers enumerated (for orphan tracking)."""
    logger.info(
        "Crawling Confluence tree: %s (root_page_id=%s, stale_months=%s)",
        source.title,
        source.root_page_id,
        source.stale_months,
    )
    page_ids = await enumerate_tree_page_ids(
        source.root_page_id,
        base_url=settings.confluence_base_url,
        email=settings.confluence_email,
        api_token=settings.confluence_api_token.get_secret_value(),
        stale_months=source.stale_months,
    )
    logger.info("Tree %s: %d page(s) to ingest", source.title, len(page_ids))
    # A per-page failure propagates out of this loop to ingest_all's per-source
    # try/except, marking the whole tree source failed (like _ingest_git_source).
    # Do NOT wrap per-page in try/except — current_identifiers must only get this
    # tree's ids after a fully successful enumeration+ingest.
    for page_id in page_ids:
        await _ingest_one_confluence_page(
            page_id, source.tags, source.space_key, settings, pool, embedder, tokenizer_fn
        )
    return page_ids


async def _ingest_one_confluence_page(
    page_id: str,
    tags: list[str],
    space_key: str,
    settings: Settings,
    pool: asyncpg.Pool,
    embedder: Embedder,
    tokenizer_fn: Callable[[str], int],
) -> None:
    """Crawl one Confluence page, and (if changed) parse, chunk, embed, store it."""
    page = await crawl_page(
        page_id,
        base_url=settings.confluence_base_url,
        email=settings.confluence_email,
        api_token=settings.confluence_api_token.get_secret_value(),
        stale_threshold_months=settings.stale_threshold_months,
    )

    existing_hash = await _get_existing_hash(pool, page_id)
    if existing_hash == page.content_hash:
        logger.info("No changes detected for page %s (%s)", page_id, page.title)
        return

    sections = parse_confluence_html(page.html_content)
    chunks = chunk_sections(sections, max_tokens=500, tokenizer_fn=tokenizer_fn)
    if not chunks:
        logger.warning("No chunks produced for page %s (%s)", page_id, page.title)
        return

    logger.info("Embedding %d chunks for page %s (%s)", len(chunks), page_id, page.title)
    texts = [chunk.text for chunk in chunks]
    embeddings = await embedder.aembed(texts)

    async with pool.acquire() as conn:
        async with conn.transaction():
            source_id = await conn.fetchval(
                """
                INSERT INTO sources (type, url, title, confluence_page_id,
                                     confluence_space_key, last_crawled_at,
                                     content_hash, status, tags)
                VALUES ('confluence_page', $1, $2, $3, $4, $5, $6, 'active', $7)
                ON CONFLICT (confluence_page_id)
                DO UPDATE SET
                    title = EXCLUDED.title,
                    url = EXCLUDED.url,
                    last_crawled_at = EXCLUDED.last_crawled_at,
                    content_hash = EXCLUDED.content_hash,
                    status = 'active',
                    tags = EXCLUDED.tags
                RETURNING id
                """,
                page.url,
                page.title,
                page_id,
                space_key,
                datetime.now(timezone.utc),
                page.content_hash,
                tags,
            )

            await conn.execute("DELETE FROM chunks WHERE source_id = $1", source_id)

            for chunk, embedding in zip(chunks, embeddings):
                await conn.execute(
                    """
                    INSERT INTO chunks (source_id, chunk_index, text,
                                        embedding, section_title, title)
                    VALUES ($1, $2, $3, $4, $5, $6)
                    """,
                    source_id,
                    chunk.chunk_index,
                    chunk.text,
                    np.array(embedding, dtype=np.float32),
                    chunk.section_title,
                    page.title,
                )

    logger.info("Stored %d chunks for page %s (%s)", len(chunks), page_id, page.title)


async def _ingest_git_source(
    source: GitRepoSourceConfig,
    settings: Settings,
    pool: asyncpg.Pool,
    embedder: Embedder,
    tokenizer_fn: Callable[[str], int],
) -> list[str]:
    """Ingest documentation files from a local git repository.

    Returns the list of source identifiers enumerated from the repo (one per
    file crawled, not only those actually re-embedded). The caller can feed
    this into _purge_orphans without re-walking the filesystem.

    Raises FileNotFoundError if the configured repo path does not exist —
    important because crawl_repo otherwise silently returns [] for a missing
    path. A silent empty walk would let --purge-orphans delete all of the
    repo's historical sources as "orphans" on a transient mount failure."""
    from pathlib import Path

    logger.info("Crawling git repo: %s (%s)", source.title, source.repo_path)

    if not Path(source.repo_path).is_dir():
        raise FileNotFoundError(f"Configured git repo path does not exist: {source.repo_path}")

    files = crawl_repo(
        source.repo_path,
        source.include_patterns,
        legacy_path_substring=settings.legacy_path_substring,
    )
    identifiers = [_git_source_identifier(source.repo_path, f.file_path) for f in files]

    for file in files:
        identifier = _git_source_identifier(source.repo_path, file.file_path)

        existing_hash = await _get_hash_by_identifier(pool, identifier)
        if existing_hash == file.content_hash:
            logger.info("No changes: %s/%s", source.title, file.title)
            continue

        sections = _parse_markdown(file.content)
        chunks = chunk_sections(sections, max_tokens=500, tokenizer_fn=tokenizer_fn)

        if not chunks:
            continue

        logger.info("Embedding %d chunks for %s/%s", len(chunks), source.title, file.title)
        texts = [chunk.text for chunk in chunks]
        embeddings = await embedder.aembed(texts)

        url = f"file://{source.repo_path}/{file.file_path}"
        async with pool.acquire() as conn:
            async with conn.transaction():
                source_id = await conn.fetchval(
                    """
                    INSERT INTO sources (type, url, title, source_identifier,
                                         last_crawled_at, content_hash, status, tags)
                    VALUES ($1, $2, $3, $4, $5, $6, 'active', $7)
                    ON CONFLICT (source_identifier)
                        WHERE source_identifier IS NOT NULL
                    DO UPDATE SET
                        title = EXCLUDED.title,
                        last_crawled_at = EXCLUDED.last_crawled_at,
                        content_hash = EXCLUDED.content_hash,
                        status = 'active',
                        tags = EXCLUDED.tags
                    RETURNING id
                    """,
                    "git_repo",
                    url,
                    f"{source.title}/{file.title}",
                    identifier,
                    datetime.now(timezone.utc),
                    file.content_hash,
                    source.tags,
                )

                await conn.execute("DELETE FROM chunks WHERE source_id = $1", source_id)

                for chunk, embedding in zip(chunks, embeddings):
                    await conn.execute(
                        """
                        INSERT INTO chunks (source_id, chunk_index, text,
                                            embedding, section_title, title)
                        VALUES ($1, $2, $3, $4, $5, $6)
                        """,
                        source_id,
                        chunk.chunk_index,
                        chunk.text,
                        np.array(embedding, dtype=np.float32),
                        chunk.section_title,
                        file.title,
                    )

        logger.info("Stored %d chunks for: %s/%s", len(chunks), source.title, file.title)

    return identifiers


def _parse_markdown(content: str) -> list[Section]:
    """Parse markdown content into sections by headings."""
    sections: list[Section] = []
    current_title = ""
    current_level = 0
    current_parts: list[str] = []

    for line in content.split("\n"):
        if line.startswith("#"):
            if current_parts:
                text = "\n".join(current_parts).strip()
                if text:
                    sections.append(Section(title=current_title, text=text, level=current_level))
                current_parts = []

            level = len(line) - len(line.lstrip("#"))
            current_title = line.lstrip("#").strip()
            current_level = level
        else:
            current_parts.append(line)

    if current_parts:
        text = "\n".join(current_parts).strip()
        if text:
            sections.append(Section(title=current_title, text=text, level=current_level))

    return sections


async def _get_existing_hash(pool: asyncpg.Pool, page_id: str) -> str | None:
    """Get the content hash of a Confluence source."""
    async with pool.acquire() as conn:
        return await conn.fetchval(
            "SELECT content_hash FROM sources WHERE confluence_page_id = $1",
            page_id,
        )


async def _get_hash_by_identifier(pool: asyncpg.Pool, identifier: str) -> str | None:
    """Get the content hash of a source by its identifier."""
    async with pool.acquire() as conn:
        return await conn.fetchval(
            "SELECT content_hash FROM sources WHERE source_identifier = $1",
            identifier,
        )


async def _purge_orphans(
    pool: asyncpg.Pool,
    current_identifiers: set[str],
    confirm: bool,
) -> tuple[int, int]:
    """Find `sources` rows whose identifier is not in the current sources.yml,
    report them, and (if confirm=True) delete them along with their chunks.

    Identifier format:
        - Confluence: the page_id string (e.g., "5108006937")
        - Git:        f"git:{repo_path}:{file_path}"

    Returns (orphan_source_count, orphan_chunk_count). When confirm=False,
    returns the counts of what WOULD be deleted and leaves the DB untouched.

    chunks.source_id has ON DELETE CASCADE, so deleting from sources
    cascades to chunks automatically.
    """
    if not current_identifiers and confirm:
        logger.error(
            "_purge_orphans called with empty current_identifiers and confirm=True. "
            "This would delete every source in the DB. Aborting — this is almost "
            "certainly a caller bug (e.g., load_sources returned empty)."
        )
        return (0, 0)

    async with pool.acquire() as conn:
        async with conn.transaction():
            rows = await conn.fetch(
                """
                SELECT id,
                       title,
                       COALESCE(confluence_page_id, source_identifier) AS identifier
                  FROM sources
                 WHERE COALESCE(confluence_page_id, source_identifier) IS NOT NULL
                """
            )
            db_identifiers = {r["identifier"]: r for r in rows}
            orphan_ids = [
                r["id"] for ident, r in db_identifiers.items() if ident not in current_identifiers
            ]

            if not orphan_ids:
                logger.info("No orphan sources detected.")
                return (0, 0)

            chunk_count = await conn.fetchval(
                "SELECT count(*) FROM chunks WHERE source_id = ANY($1::uuid[])",
                orphan_ids,
            )

            logger.info(
                "Orphans detected: %d sources / %d chunks not in current sources.yml",
                len(orphan_ids),
                chunk_count,
            )
            for ident, r in db_identifiers.items():
                if ident not in current_identifiers:
                    logger.debug("  orphan: %s  (%s)", r["title"], ident)

            if not confirm:
                logger.info(
                    "Would delete %d orphan sources (%d chunks). Re-run with --confirm to execute.",
                    len(orphan_ids),
                    chunk_count,
                )
                return (len(orphan_ids), chunk_count)

            await conn.execute(
                "DELETE FROM sources WHERE id = ANY($1::uuid[])",
                orphan_ids,
            )
            logger.info(
                "Purged %d orphan sources (%d chunks).",
                len(orphan_ids),
                chunk_count,
            )
            return (len(orphan_ids), chunk_count)
