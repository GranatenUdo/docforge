"""Integration tests for docforge.ingest._purge_orphans against pgvector."""

from __future__ import annotations

from datetime import datetime, timezone

import asyncpg
import pytest

from docforge.ingest import _purge_orphans


async def _insert_source(conn, identifier: str, title: str, is_git: bool = True) -> str:
    """Insert a sources row with either source_identifier (git) or
    confluence_page_id (confluence). Returns the inserted id."""
    if is_git:
        return await conn.fetchval(
            """
            INSERT INTO sources (type, url, title, source_identifier,
                                 last_crawled_at, content_hash, status)
            VALUES ('git_repo', $1, $2, $3, $4, 'hash', 'active')
            RETURNING id
            """,
            f"file://fake/{identifier}",
            title,
            identifier,
            datetime.now(timezone.utc),
        )
    return await conn.fetchval(
        """
        INSERT INTO sources (type, url, title, confluence_page_id,
                             last_crawled_at, content_hash, status)
        VALUES ('confluence', $1, $2, $3, $4, 'hash', 'active')
        RETURNING id
        """,
        f"https://fake/{identifier}",
        title,
        identifier,
        datetime.now(timezone.utc),
    )


@pytest.mark.asyncio
async def test_purge_orphans_dry_run_reports_but_does_not_delete(pg_url):
    pool = await asyncpg.create_pool(pg_url)
    try:
        async with pool.acquire() as conn:
            await _insert_source(conn, "git:/repo:current.md", "current")
            await _insert_source(conn, "git:/repo:orphan.md", "orphan")

        # Current sources.yml contains only the first identifier.
        current = {"git:/repo:current.md"}
        sources_deleted, chunks_deleted = await _purge_orphans(pool, current, confirm=False)

        assert sources_deleted == 1
        assert chunks_deleted == 0  # no chunks were inserted above

        async with pool.acquire() as conn:
            n = await conn.fetchval("SELECT count(*) FROM sources")
        assert n == 2, "dry-run must not delete"
    finally:
        await pool.close()


@pytest.mark.asyncio
async def test_purge_orphans_with_confirm_deletes(pg_url):
    pool = await asyncpg.create_pool(pg_url)
    try:
        async with pool.acquire() as conn:
            kept_id = await _insert_source(conn, "git:/repo:current.md", "current")
            orphan_id = await _insert_source(conn, "git:/repo:orphan.md", "orphan")

            # Give the orphan a chunk to verify cascade.
            await conn.execute(
                """
                INSERT INTO chunks (source_id, chunk_index, text, embedding, content_hash)
                VALUES ($1, 0, 'body', array_fill(0.0::real, ARRAY[768])::vector(768), 'h')
                """,
                orphan_id,
            )

        current = {"git:/repo:current.md"}
        sources_deleted, chunks_deleted = await _purge_orphans(pool, current, confirm=True)

        assert sources_deleted == 1
        assert chunks_deleted == 1

        async with pool.acquire() as conn:
            remaining = await conn.fetch(
                "SELECT id, source_identifier FROM sources ORDER BY source_identifier"
            )
            chunks = await conn.fetchval("SELECT count(*) FROM chunks")

        assert [r["source_identifier"] for r in remaining] == ["git:/repo:current.md"]
        assert remaining[0]["id"] == kept_id
        assert chunks == 0, "chunks should cascade-delete with the source"
    finally:
        await pool.close()


@pytest.mark.asyncio
async def test_purge_orphans_confluence_identifier(pg_url):
    pool = await asyncpg.create_pool(pg_url)
    try:
        async with pool.acquire() as conn:
            await _insert_source(conn, "111", "confluence-kept", is_git=False)
            await _insert_source(conn, "222", "confluence-orphan", is_git=False)

        current = {"111"}
        sources_deleted, _ = await _purge_orphans(pool, current, confirm=True)

        assert sources_deleted == 1
        async with pool.acquire() as conn:
            remaining = await conn.fetchval("SELECT confluence_page_id FROM sources")
        assert remaining == "111"
    finally:
        await pool.close()
