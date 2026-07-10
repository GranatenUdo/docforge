"""Integration test: migration 011 makes query_log.team_name nullable."""

from __future__ import annotations

import asyncpg
import pytest


@pytest.mark.asyncio
async def test_team_name_is_nullable(pg_url):
    conn = await asyncpg.connect(pg_url)
    try:
        is_nullable = await conn.fetchval(
            "SELECT is_nullable FROM information_schema.columns "
            "WHERE table_name = 'query_log' AND column_name = 'team_name'"
        )
        assert is_nullable == "YES"
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_insert_with_null_team_name_succeeds(pg_url):
    conn = await asyncpg.connect(pg_url)
    try:
        qid = await conn.fetchval(
            "INSERT INTO query_log (user_name, team_name, area_name, query, result_count) "
            "VALUES ('u', NULL, NULL, 'q', 0) RETURNING id"
        )
        assert qid is not None
    finally:
        await conn.execute("TRUNCATE query_log CASCADE")
        await conn.close()
