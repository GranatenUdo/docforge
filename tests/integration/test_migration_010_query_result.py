"""Integration test: migration 010 adds the query_result table."""

from __future__ import annotations

import asyncpg
import pytest


@pytest.mark.asyncio
async def test_query_result_table_shape(pg_url):
    conn = await asyncpg.connect(pg_url)
    try:
        cols = {
            r["column_name"]: r["data_type"]
            for r in await conn.fetch(
                "SELECT column_name, data_type FROM information_schema.columns "
                "WHERE table_name = 'query_result'"
            )
        }
        assert cols, "query_result table missing"
        for name in (
            "id",
            "query_log_id",
            "rank",
            "score",
            "source_url",
            "source_title",
            "section_title",
            "chunk_text",
            "created_at",
        ):
            assert name in cols, f"missing column {name}"
        assert "chunk_id" not in cols and "source_id" not in cols
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_query_result_cascades_on_query_log_delete(pg_url):
    conn = await asyncpg.connect(pg_url)
    try:
        qid = await conn.fetchval(
            "INSERT INTO query_log (user_name, team_name, area_name, query, result_count) "
            "VALUES ('u','t',NULL,'q',1) RETURNING id"
        )
        await conn.execute(
            "INSERT INTO query_result "
            "(query_log_id, rank, score, source_url, source_title, chunk_text) "
            "VALUES ($1, 1, 0.03, 'http://x', 'X', 'body')",
            qid,
        )
        await conn.execute("DELETE FROM query_log WHERE id = $1", qid)
        remaining = await conn.fetchval(
            "SELECT count(*) FROM query_result WHERE query_log_id = $1", qid
        )
        assert remaining == 0, "query_result should cascade-delete with query_log"
    finally:
        await conn.execute("TRUNCATE query_log CASCADE")
        await conn.close()
