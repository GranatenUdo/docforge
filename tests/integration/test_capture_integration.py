"""Integration: log_search writes query_log (+ query_result) against real Postgres."""

from __future__ import annotations

import asyncpg
import pytest

from docforge.query_log import log_search


@pytest.mark.asyncio
async def test_log_search_captures_query_and_results(pg_url):
    pool = await asyncpg.create_pool(pg_url, min_size=1, max_size=2)
    try:
        qid = await log_search(
            pool,
            "u",
            "t",
            None,
            "q",
            1,
            results=[
                {
                    "rank": 1,
                    "score": 0.03,
                    "source_url": "u1",
                    "source_title": "T1",
                    "section_title": "S1",
                    "chunk_text": "b1",
                }
            ],
        )
        assert qid is not None
        async with pool.acquire() as conn:
            nq = await conn.fetchval("SELECT count(*) FROM query_log")
            nr = await conn.fetchval("SELECT count(*) FROM query_result")
        assert nq == 1 and nr == 1
    finally:
        await pool.close()


@pytest.mark.asyncio
async def test_log_search_query_only_when_no_results(pg_url):
    pool = await asyncpg.create_pool(pg_url, min_size=1, max_size=2)
    try:
        qid = await log_search(pool, "u", "t", None, "q", 0, results=None)
        assert qid is not None
        async with pool.acquire() as conn:
            nq = await conn.fetchval("SELECT count(*) FROM query_log")
            nr = await conn.fetchval("SELECT count(*) FROM query_result")
        assert nq == 1 and nr == 0
    finally:
        await pool.close()
