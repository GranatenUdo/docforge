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
    user_oid: str | None = None,
    request_ms: int | None = None,
) -> None:
    """Record a search request. user_oid is the Entra object ID (post-auth)
    or None (pre-auth rows). request_ms is the handler's wall-clock time in
    milliseconds (post-C4.3) or None (pre-C4.3 rows). Never raises."""
    try:
        async with pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO query_log
                    (user_name, team_name, area_name, query, result_count, user_oid, request_ms)
                VALUES ($1, $2, $3, $4, $5, $6, $7)
                """,
                user_name,
                team_name,
                area_name,
                query,
                result_count,
                user_oid,
                request_ms,
            )
    except Exception as e:
        logger.warning("query_log insert failed: %s", e)
