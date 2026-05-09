"""Integration test: migration 007 adds chunks.text_tsv + GIN index, populates from text."""

from __future__ import annotations

import asyncpg
import numpy as np
import pytest
from pgvector.asyncpg import register_vector


@pytest.mark.asyncio
async def test_text_tsv_column_exists(pg_url):
    """text_tsv column is present on chunks after init_db."""
    conn = await asyncpg.connect(pg_url)
    try:
        col = await conn.fetchval(
            """
            SELECT data_type FROM information_schema.columns
            WHERE table_name = 'chunks' AND column_name = 'text_tsv'
            """
        )
        assert col == "tsvector"
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_gin_index_exists(pg_url):
    """chunks_text_tsv_idx GIN index exists on chunks(text_tsv)."""
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


@pytest.mark.asyncio
async def test_text_tsv_auto_populates_on_insert(pg_url):
    """Inserting a chunk auto-populates text_tsv via GENERATED ALWAYS."""
    conn = await asyncpg.connect(pg_url)
    try:
        await register_vector(conn)
        sid = await conn.fetchval(
            """
            INSERT INTO sources (type, url, title, source_identifier, status,
                                 content_hash, last_crawled_at)
            VALUES ('git_repo', 'file:///T', 'T', 'T', 'active', 'h', now())
            RETURNING id
            """
        )
        vec = np.zeros(768, dtype=np.float32)
        await conn.execute(
            """
            INSERT INTO chunks (source_id, chunk_index, text, embedding, section_title)
            VALUES ($1, 0, 'the quick brown fox jumps over lazy dog', $2, NULL)
            """,
            sid,
            vec,
        )
        tsv = await conn.fetchval("SELECT text_tsv::text FROM chunks LIMIT 1")
        # English config drops stopwords (the, over) and stems (jumps -> jump)
        assert "fox" in tsv
        assert "jump" in tsv
        assert "the" not in tsv  # stopword removed
    finally:
        await conn.close()
