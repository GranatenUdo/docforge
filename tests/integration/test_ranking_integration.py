"""Integration test: tag-aware ranking against real pgvector."""

from __future__ import annotations

import asyncpg
import numpy as np
import pytest
from pgvector.asyncpg import register_vector


async def _insert_source(conn, title: str, tags: list[str]) -> str:
    return await conn.fetchval(
        """
        INSERT INTO sources (type, url, title, source_identifier, status, tags,
                             content_hash, last_crawled_at)
        VALUES ('git_repo', $1, $2, $1, 'active', $3, 'h', now())
        RETURNING id
        """,
        f"file:///{title}",
        title,
        tags,
    )


async def _insert_chunk(conn, source_id: str, text: str, vec: np.ndarray):
    await conn.execute(
        """
        INSERT INTO chunks (source_id, chunk_index, text, embedding, section_title)
        VALUES ($1, 0, $2, $3, NULL)
        """,
        source_id,
        text,
        vec,
    )


def _vec(last_dim: float) -> np.ndarray:
    v = np.zeros(1024, dtype=np.float32)
    v[1023] = last_dim
    return v


@pytest.mark.asyncio
async def test_team_tagged_source_ranks_above_untagged_on_similar_similarity(pg_url):
    conn = await asyncpg.connect(pg_url)
    try:
        await register_vector(conn)

        sid_tagged = await _insert_source(conn, "TaggedDoc", ["platform"])
        sid_untagged = await _insert_source(conn, "UntaggedDoc", [])
        same_vec = _vec(0.001)
        await _insert_chunk(conn, sid_tagged, "tagged chunk", same_vec)
        await _insert_chunk(conn, sid_untagged, "untagged chunk", same_vec)

        query_vec = _vec(0.001)
        rows = await conn.fetch(
            """
            SELECT s.title,
                   (1 - (c.embedding <=> $1::vector)) *
                     (1
                      + $2::float * cardinality(
                          ARRAY(SELECT unnest(s.tags) INTERSECT SELECT unnest($3::text[]))
                        )
                     ) AS score
            FROM chunks c JOIN sources s ON c.source_id = s.id
            ORDER BY score DESC
            """,
            query_vec,
            0.1,
            ["platform"],
        )
        titles = [r["title"] for r in rows]
        assert titles == ["TaggedDoc", "UntaggedDoc"]
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_two_tag_overlap_outranks_one_tag_overlap(pg_url):
    conn = await asyncpg.connect(pg_url)
    try:
        await register_vector(conn)
        sid_one = await _insert_source(conn, "OneTag", ["platform"])
        sid_two = await _insert_source(conn, "TwoTag", ["platform", "cloud"])
        vec = _vec(0.001)
        await _insert_chunk(conn, sid_one, "one", vec)
        await _insert_chunk(conn, sid_two, "two", vec)

        rows = await conn.fetch(
            """
            SELECT s.title,
                   (1 - (c.embedding <=> $1::vector)) *
                     (1 + $2::float * cardinality(
                          ARRAY(SELECT unnest(s.tags) INTERSECT SELECT unnest($3::text[]))
                        )) AS score
            FROM chunks c JOIN sources s ON c.source_id = s.id
            ORDER BY score DESC
            """,
            vec,
            0.1,
            ["platform", "cloud"],
        )
        assert [r["title"] for r in rows] == ["TwoTag", "OneTag"]
    finally:
        await conn.close()
