"""Integration test: hybrid retrieval (dense + sparse via RRF) in /search.

Tests the SQL CTE directly against a real pgvector + tsvector Postgres so
we exercise both indexes end-to-end. Three scenarios:

  - Dense-only winner: query that semantically matches but has no shared
    keyword with target chunk; sparse path returns nothing; RRF degrades
    to dense-only.

  - Sparse-only winner: query is a rare identifier; dense embedding miss
    is expected; sparse path picks it up; RRF surfaces it.

  - Hybrid winner: chunk that appears in BOTH top-k pools wins over a
    chunk that appears only in one.
"""

from __future__ import annotations

import math

import asyncpg
import numpy as np
import pytest
from pgvector.asyncpg import register_vector


def _vec(angle_rad: float) -> np.ndarray:
    """Deterministic 768-dim unit vector at angle `angle_rad` in the (axis 0, axis 1) plane.

    Two vectors at angles a and b have cosine distance 1 - cos(a - b):
        _vec(0.0) and _vec(0.0)       -> distance 0     (identical)
        _vec(0.0) and _vec(0.1)       -> distance ~0.005 (very close)
        _vec(0.0) and _vec(math.pi/2) -> distance 1     (orthogonal)

    Use this to control which chunks rank close vs far on the dense path.
    """
    v = np.zeros(768, dtype=np.float32)
    v[0] = float(np.cos(angle_rad))
    v[1] = float(np.sin(angle_rad))
    return v


async def _insert_source(conn, title: str, tags: list[str] | None = None) -> str:
    return await conn.fetchval(
        """
        INSERT INTO sources (type, url, title, source_identifier, status, tags,
                             content_hash, last_crawled_at)
        VALUES ('git_repo', $1, $2, $1, 'active', $3, 'h', now())
        RETURNING id
        """,
        f"file:///{title}",
        title,
        tags or [],
    )


async def _insert_chunk(conn, source_id: str, text: str, vec: np.ndarray) -> None:
    await conn.execute(
        """
        INSERT INTO chunks (source_id, chunk_index, text, embedding, section_title)
        VALUES ($1, 0, $2, $3, NULL)
        """,
        source_id,
        text,
        vec,
    )


# The SQL under test — the production /search query, parameterized identically.
# Keep this string in sync with src/docforge/api.py if either changes.
# Parameters: $1=query_vec, $2=query_text, $3=pool_size, $4=tag_match_weight,
#             $5=user_tags, $6=org_tag_weight, $7=req.limit, $8=fts_language,
#             $9=rrf_k.
HYBRID_SEARCH_SQL = """
WITH q_tsq AS (SELECT websearch_to_tsquery($8::regconfig, $2::text) AS q),
     dense AS (
         SELECT id, source_id, text, section_title,
                ROW_NUMBER() OVER (ORDER BY dist) AS rank
         FROM (
             SELECT c.id, c.source_id, c.text, c.section_title,
                    c.embedding <=> $1::vector AS dist
             FROM chunks c JOIN sources s ON c.source_id = s.id
             WHERE s.status = 'active'
             ORDER BY c.embedding <=> $1::vector
             LIMIT $3
         ) AS t
     ),
     sparse AS (
         SELECT id, source_id, text, section_title,
                ROW_NUMBER() OVER (ORDER BY rk DESC) AS rank
         FROM (
             SELECT c.id, c.source_id, c.text, c.section_title,
                    ts_rank_cd(c.text_tsv, (SELECT q FROM q_tsq)) AS rk
             FROM chunks c JOIN sources s ON c.source_id = s.id
             WHERE s.status = 'active'
               AND c.text_tsv @@ (SELECT q FROM q_tsq)
             ORDER BY ts_rank_cd(c.text_tsv, (SELECT q FROM q_tsq)) DESC
             LIMIT $3
         ) AS t
     ),
     fused AS (
         SELECT COALESCE(d.id, sp.id) AS id,
                COALESCE(d.source_id, sp.source_id) AS source_id,
                COALESCE(d.text, sp.text) AS text,
                COALESCE(d.section_title, sp.section_title) AS section_title,
                COALESCE(1.0/($9 + d.rank), 0) + COALESCE(1.0/($9 + sp.rank), 0) AS rrf
         FROM dense d FULL OUTER JOIN sparse sp ON d.id = sp.id
     )
SELECT s.title AS source_title, f.rrf AS similarity,
       f.rrf * (1
                + $4::float * cardinality(
                    ARRAY(SELECT unnest(s.tags) INTERSECT SELECT unnest($5::text[]))
                  )
                + $6::float * (CASE WHEN 'org' = ANY(s.tags) THEN 1 ELSE 0 END)
       ) AS boosted_score
FROM fused f JOIN sources s ON f.source_id = s.id
ORDER BY boosted_score DESC
LIMIT $7
"""


# Common test defaults — match production Settings defaults
POOL = 100
WEIGHT_TAG = 0.1
WEIGHT_ORG = 0.05
LIMIT = 5
FTS_LANG = "english"
RRF_K = 60


@pytest.mark.asyncio
async def test_dense_only_winner(pg_url):
    """Query embedding aligns with one chunk; query text matches no keywords;
    sparse CTE returns 0 rows; FULL OUTER JOIN degrades to dense-only RRF."""
    conn = await asyncpg.connect(pg_url)
    try:
        await register_vector(conn)

        sid = await _insert_source(conn, "DenseTarget")
        sid_other = await _insert_source(conn, "Other")

        # Target's vector at angle 0.0 (aligned with query at angle 0.0 -> distance 0)
        await _insert_chunk(conn, sid, "completely unrelated lexical content", _vec(0.0))
        # Distractor near-orthogonal (distance ~1)
        await _insert_chunk(conn, sid_other, "different stuff entirely", _vec(math.pi / 2))

        rows = await conn.fetch(
            HYBRID_SEARCH_SQL,
            _vec(0.0),  # $1: query vector at angle 0
            "zzz_no_match_keyword",  # $2: query text — won't match any tsvector
            POOL,
            WEIGHT_TAG,
            ["platform"],
            WEIGHT_ORG,
            LIMIT,
            FTS_LANG,
            RRF_K,
        )
        assert [r["source_title"] for r in rows][0] == "DenseTarget"
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_sparse_only_winner(pg_url):
    """Rare identifier query — target's vector is far from query (loses dense
    rank battle), but its text contains the identifier; sparse rank lifts it."""
    conn = await asyncpg.connect(pg_url)
    try:
        await register_vector(conn)

        sid = await _insert_source(conn, "SparseTarget")
        sid_other = await _insert_source(conn, "Other")

        # Target has the rare identifier; vector near-orthogonal to query
        await _insert_chunk(
            conn,
            sid,
            "BackgroundProcessService dispatch strategy is round-robin",
            _vec(math.pi / 2),
        )
        # Distractor: high embedding similarity (distance 0) but no keyword match
        await _insert_chunk(conn, sid_other, "random English prose", _vec(0.0))

        rows = await conn.fetch(
            HYBRID_SEARCH_SQL,
            _vec(0.0),  # query vec aligned with Other
            "BackgroundProcessService dispatch",  # $2: matches Target's text
            POOL,
            WEIGHT_TAG,
            ["platform"],
            WEIGHT_ORG,
            LIMIT,
            FTS_LANG,
            RRF_K,
        )
        titles = [r["source_title"] for r in rows]
        # Target appears in results despite losing the dense ranking
        assert "SparseTarget" in titles
        # SparseTarget: dense rank 2 + sparse rank 1 = 1/62 + 1/61 ~ 0.0327
        # Other:        dense rank 1 + no sparse    = 1/61          ~ 0.0164
        # SparseTarget should rank ABOVE Other.
        assert titles.index("SparseTarget") < titles.index("Other")
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_hybrid_winner_above_single_path_winners(pg_url):
    """A chunk strong on BOTH paths beats chunks strong on only one.

    Setup:
      query at angle 0.0
      DenseOnly  at angle 0.05  -> closest dense neighbor (rank 1)
      HybridTarget at angle 0.10 -> 2nd-closest (rank 2), AND keyword match
      SparseOnly at angle 1.5    -> far dense (rank 3), keyword match

    Sparse:
      HybridTarget text matches "intellix dispatch" -> sparse rank 1 or 2
      SparseOnly   text matches                       -> sparse rank 1 or 2
      DenseOnly    text doesn't match                 -> not in sparse CTE

    Expected RRF (k=60):
      HybridTarget: 1/62 + 1/61 ~ 0.0327
      DenseOnly:    1/61 + 0     ~ 0.0164
      SparseOnly:   1/63 + 1/62 ~ 0.0320
    HybridTarget wins by margin over SparseOnly; DenseOnly third.
    """
    conn = await asyncpg.connect(pg_url)
    try:
        await register_vector(conn)

        sid_hybrid = await _insert_source(conn, "HybridTarget")
        sid_dense = await _insert_source(conn, "DenseOnly")
        sid_sparse = await _insert_source(conn, "SparseOnly")

        await _insert_chunk(conn, sid_dense, "completely off-topic prose", _vec(0.05))
        await _insert_chunk(conn, sid_hybrid, "intellix dispatch strategy with retries", _vec(0.10))
        await _insert_chunk(
            conn, sid_sparse, "intellix dispatch strategy in another context", _vec(1.5)
        )

        rows = await conn.fetch(
            HYBRID_SEARCH_SQL,
            _vec(0.0),  # query vec
            "intellix dispatch",  # matches Hybrid and Sparse
            POOL,
            WEIGHT_TAG,
            ["platform"],
            WEIGHT_ORG,
            LIMIT,
            FTS_LANG,
            RRF_K,
        )
        assert rows[0]["source_title"] == "HybridTarget", (
            f"expected HybridTarget first, got {[r['source_title'] for r in rows]}"
        )
    finally:
        await conn.close()
