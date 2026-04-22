"""Ingest pipeline — crawl → parse → chunk → embed → store.

`ingest_all` loads the sources list and runs the appropriate crawler for
each source type (Confluence page or local git repo). Per-source failures
are logged but do not abort the run.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Callable

import asyncpg
import numpy as np

from docforge.config import Settings
from docforge.crawlers.confluence import crawl_page
from docforge.crawlers.git import crawl_repo
from docforge.db import get_pool
from docforge.processors.chunker import chunk_sections
from docforge.processors.embedder import Embedder
from docforge.processors.parser import Section, parse_confluence_html
from docforge.sources import (
    ConfluenceSourceConfig,
    GitRepoSourceConfig,
    load_sources,
)

logger = logging.getLogger(__name__)


async def ingest_all(settings: Settings) -> None:
    """Run the full ingest pipeline for all configured sources."""
    sources = load_sources(settings.sources_file)
    logger.info("Loaded %d sources from %s", len(sources), settings.sources_file)

    logger.info("Loading embedding model...")
    embedder = Embedder(settings.embedding_model, hf_token=settings.hf_token.get_secret_value())

    pool = await get_pool(settings.database_url)
    tokenizer_fn = embedder.get_tokenizer_fn()

    succeeded = 0
    failed = 0
    failed_names: list[str] = []

    for source in sources:
        try:
            if isinstance(source, ConfluenceSourceConfig):
                await _ingest_confluence_source(source, settings, pool, embedder, tokenizer_fn)
            elif isinstance(source, GitRepoSourceConfig):
                await _ingest_git_source(source, pool, embedder, tokenizer_fn)
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


async def _ingest_confluence_source(
    source: ConfluenceSourceConfig,
    settings: Settings,
    pool: asyncpg.Pool,
    embedder: Embedder,
    tokenizer_fn: Callable[[str], int],
) -> None:
    """Ingest a single Confluence page: crawl, parse HTML, chunk, embed, store."""
    logger.info("Crawling Confluence: %s (page_id=%s)", source.title, source.page_id)

    page = await crawl_page(
        source.page_id,
        base_url=settings.confluence_base_url,
        email=settings.confluence_email,
        api_token=settings.confluence_api_token.get_secret_value(),
    )

    existing_hash = await _get_existing_hash(pool, source.page_id)
    if existing_hash == page.content_hash:
        logger.info("No changes detected for: %s", source.title)
        return

    logger.info("Parsing: %s", source.title)
    sections = parse_confluence_html(page.html_content)
    logger.info("Found %d sections", len(sections))

    chunks = chunk_sections(sections, max_tokens=500, tokenizer_fn=tokenizer_fn)
    logger.info("Created %d chunks", len(chunks))

    if not chunks:
        logger.warning("No chunks produced for: %s", source.title)
        return

    logger.info("Embedding %d chunks...", len(chunks))
    texts = [chunk.text for chunk in chunks]
    embeddings = embedder.embed(texts)

    async with pool.acquire() as conn:
        async with conn.transaction():
            source_id = await conn.fetchval(
                """
                INSERT INTO sources (type, url, title, confluence_page_id,
                                     confluence_space_key, last_crawled_at,
                                     content_hash, status, tags)
                VALUES ($1, $2, $3, $4, $5, $6, $7, 'active', $8)
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
                source.type,
                page.url,
                page.title,
                source.page_id,
                source.space_key,
                datetime.now(timezone.utc),
                page.content_hash,
                source.tags,
            )

            await conn.execute("DELETE FROM chunks WHERE source_id = $1", source_id)

            for chunk, embedding in zip(chunks, embeddings):
                await conn.execute(
                    """
                    INSERT INTO chunks (source_id, chunk_index, text,
                                        embedding, section_title)
                    VALUES ($1, $2, $3, $4, $5)
                    """,
                    source_id,
                    chunk.chunk_index,
                    chunk.text,
                    np.array(embedding, dtype=np.float32),
                    chunk.section_title,
                )

    logger.info("Stored %d chunks for: %s", len(chunks), source.title)


async def _ingest_git_source(
    source: GitRepoSourceConfig,
    pool: asyncpg.Pool,
    embedder: Embedder,
    tokenizer_fn: Callable[[str], int],
) -> None:
    """Ingest documentation files from a local git repository."""
    logger.info("Crawling git repo: %s (%s)", source.title, source.repo_path)

    files = crawl_repo(source.repo_path, source.include_patterns)

    for file in files:
        identifier = f"git:{source.repo_path}:{file.file_path}"

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
        embeddings = embedder.embed(texts)

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
                                            embedding, section_title)
                        VALUES ($1, $2, $3, $4, $5)
                        """,
                        source_id,
                        chunk.chunk_index,
                        chunk.text,
                        np.array(embedding, dtype=np.float32),
                        chunk.section_title,
                    )

        logger.info("Stored %d chunks for: %s/%s", len(chunks), source.title, file.title)


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
    async with pool.acquire() as conn:
        # All known identifiers in the DB (both columns are populated
        # exclusively — confluence or source_identifier, never both).
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
                logger.info("  orphan: %s  (%s)", r["title"], ident)

        if not confirm:
            logger.info(
                "Would delete %d orphan sources (%d chunks). Re-run with --confirm to execute.",
                len(orphan_ids),
                chunk_count,
            )
            return (len(orphan_ids), chunk_count)

        async with conn.transaction():
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
