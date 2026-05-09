"""Integration test: migration 008 adds chunks.title + recreates weighted text_tsv."""

from __future__ import annotations

import asyncpg
import numpy as np
import pytest
from pgvector.asyncpg import register_vector


@pytest.mark.asyncio
async def test_title_column_exists(pg_url):
    """chunks.title is TEXT NOT NULL DEFAULT '' after init_db."""
    conn = await asyncpg.connect(pg_url)
    try:
        col = await conn.fetchrow(
            """
            SELECT data_type, is_nullable, column_default
            FROM information_schema.columns
            WHERE table_name = 'chunks' AND column_name = 'title'
            """
        )
        assert col is not None, "chunks.title column not found"
        assert col["data_type"] == "text"
        assert col["is_nullable"] == "NO"
        assert "''" in (col["column_default"] or "")
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_text_tsv_includes_weighted_title(pg_url):
    """Inserting a chunk with title and text produces a tsvector where
    title tokens have weight A and body tokens have weight D."""
    conn = await asyncpg.connect(pg_url)
    try:
        await register_vector(conn)
        sid = await conn.fetchval(
            """
            INSERT INTO sources (type, url, title, source_identifier, status,
                                 content_hash, last_crawled_at)
            VALUES ('git_repo', 'file:///T', 'Weighted Title Test', 'T',
                    'active', 'h', now())
            RETURNING id
            """
        )
        vec = np.zeros(768, dtype=np.float32)
        await conn.execute(
            """
            INSERT INTO chunks (source_id, chunk_index, text, embedding,
                                section_title, title)
            VALUES ($1, 0, 'unique body content', $2, 'Heading Section', 'Weighted Title Test')
            """,
            sid,
            vec,
        )
        tsv = await conn.fetchval("SELECT text_tsv::text FROM chunks LIMIT 1")
        # Title contains 'Weighted Title Test' -> stems to 'weight', 'titl', 'test'
        # at weight 'A'. Postgres tsvector text representation uses :NA where N is
        # position and A is weight letter (e.g., "'weight':1A").
        assert "A" in tsv, f"expected weight A on title tokens, got: {tsv}"
        assert "'weight'" in tsv or "'titl'" in tsv or "'test'" in tsv, (
            f"expected title tokens (stemmed), got: {tsv}"
        )
        # Section heading 'Heading Section' -> 'head', 'section' at weight 'B'
        assert "B" in tsv, f"expected weight B on section_title tokens, got: {tsv}"
        assert "'section'" in tsv or "'head'" in tsv, f"expected section_title tokens, got: {tsv}"
        # Body 'unique body content' -> 'uniqu', 'bodi', 'content' at weight 'D'
        # (default; appears in text representation without trailing weight letter)
        assert "'uniqu'" in tsv or "'bodi'" in tsv or "'content'" in tsv, (
            f"expected body tokens, got: {tsv}"
        )
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_backfill_join_logic(pg_url):
    """Verify the JOIN UPDATE backfill SQL works correctly. (Note: testcontainer
    applies migrations on session setup, so all chunks here are post-008 already.
    This test instead verifies the JOIN logic in isolation by clearing title
    on a chunk and re-running the backfill SQL.)"""
    conn = await asyncpg.connect(pg_url)
    try:
        await register_vector(conn)
        sid = await conn.fetchval(
            """
            INSERT INTO sources (type, url, title, source_identifier, status,
                                 content_hash, last_crawled_at)
            VALUES ('git_repo', 'file:///B', 'Backfill Source', 'B',
                    'active', 'h', now())
            RETURNING id
            """
        )
        vec = np.zeros(768, dtype=np.float32)
        # Insert with explicit empty title (simulating pre-backfill state)
        await conn.execute(
            """
            INSERT INTO chunks (source_id, chunk_index, text, embedding,
                                section_title, title)
            VALUES ($1, 0, 'body', $2, NULL, '')
            """,
            sid,
            vec,
        )
        before = await conn.fetchval("SELECT title FROM chunks WHERE source_id = $1", sid)
        assert before == ""

        # Run the backfill SQL the migration runs (only-if-empty guard)
        await conn.execute(
            """
            UPDATE chunks SET title = s.title
            FROM sources s
            WHERE s.id = chunks.source_id AND chunks.title = ''
            """
        )
        after = await conn.fetchval("SELECT title FROM chunks WHERE source_id = $1", sid)
        assert after == "Backfill Source"
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_gin_index_still_present(pg_url):
    """chunks_text_tsv_idx GIN index is recreated by migration 008."""
    conn = await asyncpg.connect(pg_url)
    try:
        idx = await conn.fetchrow(
            """
            SELECT indexname, indexdef FROM pg_indexes
            WHERE tablename = 'chunks' AND indexname = 'chunks_text_tsv_idx'
            """
        )
        assert idx is not None, "chunks_text_tsv_idx not found"
        assert "using gin" in idx["indexdef"].lower()
        assert "text_tsv" in idx["indexdef"]
    finally:
        await conn.close()
