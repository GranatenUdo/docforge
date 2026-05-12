"""Integration test: migration 009 changes chunks.embedding dim 768 -> 1024.

The migration is intentionally destructive (drops + re-adds the column,
forces re-ingest). The session-scoped pgvector testcontainer applies all
migrations in order; this test asserts the post-migration column shape.
"""
from __future__ import annotations

import asyncpg
import pytest


@pytest.mark.asyncio
async def test_embedding_column_is_1024_dim(pg_url):
    """chunks.embedding has type vector(1024) after migration 009."""
    conn = await asyncpg.connect(pg_url)
    try:
        type_str = await conn.fetchval(
            """
            SELECT format_type(atttypid, atttypmod)
            FROM pg_attribute
            WHERE attrelid = 'chunks'::regclass
              AND attname = 'embedding'
            """
        )
        assert type_str == "vector(1024)", \
            f"expected vector(1024), got {type_str!r}"
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_hnsw_index_on_embedding_recreated(pg_url):
    """chunks_embedding_idx is rebuilt against the new column."""
    conn = await asyncpg.connect(pg_url)
    try:
        idx = await conn.fetchrow(
            """
            SELECT indexname, indexdef FROM pg_indexes
            WHERE tablename = 'chunks' AND indexname = 'chunks_embedding_idx'
            """
        )
        assert idx is not None, "chunks_embedding_idx not found"
        assert "hnsw" in idx["indexdef"].lower()
        assert "vector_cosine_ops" in idx["indexdef"]
    finally:
        await conn.close()
