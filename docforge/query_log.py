"""Async helper for inserting rows into query_log.

Failures are logged and swallowed — query logging must never break a search.
"""

from __future__ import annotations

import logging

import asyncpg

logger = logging.getLogger(__name__)


async def log_query(
    pool: asyncpg.Pool,
    user_name: str,
    team_name: str,
    area_name: str | None,
    query: str,
    result_count: int,
) -> None:
    """Record a search request to the query_log table. Never raises."""
    try:
        async with pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO query_log
                    (user_name, team_name, area_name, query, result_count)
                VALUES ($1, $2, $3, $4, $5)
                """,
                user_name, team_name, area_name, query, result_count,
            )
    except Exception as e:
        logger.warning("query_log insert failed: %s", e)
