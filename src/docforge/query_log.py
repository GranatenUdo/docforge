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
) -> str | None:
    """Record a search request and return the new row id (str UUID), or None on
    failure. Never raises — query logging must never break a search."""
    try:
        async with pool.acquire() as conn:
            row_id = await conn.fetchval(
                """
                INSERT INTO query_log
                    (user_name, team_name, area_name, query, result_count, user_oid, request_ms)
                VALUES ($1, $2, $3, $4, $5, $6, $7)
                RETURNING id
                """,
                user_name,
                team_name,
                area_name,
                query,
                result_count,
                user_oid,
                request_ms,
            )
        return str(row_id) if row_id is not None else None
    except Exception as e:
        logger.warning("query_log insert failed: %s", e)
        return None


async def log_results(
    pool: asyncpg.Pool,
    query_log_id: str,
    results: list[dict],
) -> None:
    """Batch-insert per-result snapshots into query_result. Best-effort; never
    raises. Each item needs: rank, score, source_url, source_title,
    section_title (optional), chunk_text."""
    if not results:
        return
    try:
        rows = [
            (
                query_log_id,
                r["rank"],
                r["score"],
                r["source_url"],
                r["source_title"],
                r.get("section_title"),
                r["chunk_text"],
            )
            for r in results
        ]
        async with pool.acquire() as conn:
            await conn.executemany(
                """
                INSERT INTO query_result
                    (query_log_id, rank, score, source_url, source_title, section_title, chunk_text)
                VALUES ($1, $2, $3, $4, $5, $6, $7)
                """,
                rows,
            )
    except Exception as e:
        logger.warning("query_result insert failed: %s", e)
