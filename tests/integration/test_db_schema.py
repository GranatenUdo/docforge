"""Integration test: verify init_db creates the expected schema and pgvector."""

from __future__ import annotations

import asyncpg
import numpy as np
import pytest
from pgvector.asyncpg import register_vector


@pytest.mark.asyncio
async def test_init_db_creates_schema_and_pgvector(pg_url):
    conn = await asyncpg.connect(pg_url)
    try:
        ext = await conn.fetchval("SELECT extname FROM pg_extension WHERE extname = 'vector'")
        assert ext == "vector"

        tables = await conn.fetch(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = 'public' AND table_name IN ('sources', 'chunks')"
        )
        names = {row["table_name"] for row in tables}
        assert names == {"sources", "chunks"}

        await register_vector(conn)
        source_id = await conn.fetchval(
            """
            INSERT INTO sources (type, url, title, status)
            VALUES ('git_repo', 'file:///tmp/a', 'A', 'active')
            RETURNING id
            """
        )
        vec = np.zeros(1024, dtype=np.float32)
        vec[0] = 1.0
        await conn.execute(
            """
            INSERT INTO chunks (source_id, chunk_index, text, embedding, section_title)
            VALUES ($1, 0, 'some text', $2, 'sec')
            """,
            source_id,
            vec,
        )
        returned = await conn.fetchval(
            "SELECT embedding FROM chunks WHERE source_id = $1", source_id
        )
        assert returned is not None
        # pgvector >=0.4 decodes to Vector (no __len__); older versions to list/ndarray
        values = returned.to_list() if hasattr(returned, "to_list") else list(returned)
        assert len(values) == 1024
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_sources_has_tags_column(pg_url):
    conn = await asyncpg.connect(pg_url)
    try:
        col = await conn.fetchrow(
            """
            SELECT column_name, data_type, is_nullable, column_default
            FROM information_schema.columns
            WHERE table_name = 'sources' AND column_name = 'tags'
            """
        )
        assert col is not None
        assert col["data_type"] == "ARRAY"
        assert col["is_nullable"] == "NO"
        assert "{}" in (col["column_default"] or "")

        idx = await conn.fetchval(
            """
            SELECT indexname FROM pg_indexes
            WHERE tablename = 'sources' AND indexname = 'sources_tags_idx'
            """
        )
        assert idx == "sources_tags_idx"
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_query_log_table_exists(pg_url):
    conn = await asyncpg.connect(pg_url)
    try:
        cols = await conn.fetch(
            """
            SELECT column_name FROM information_schema.columns
            WHERE table_name = 'query_log'
            ORDER BY ordinal_position
            """
        )
        names = [row["column_name"] for row in cols]
        assert names == [
            "id",
            "user_name",
            "team_name",
            "area_name",
            "query",
            "result_count",
            "created_at",
            "user_oid",
            "request_ms",
        ]
    finally:
        await conn.close()
