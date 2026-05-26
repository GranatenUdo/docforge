"""Regression: sparse-leg tsquery must OR-combine tokens (not AND).

`websearch_to_tsquery` combines bare tokens with `&` (AND). For multi-keyword
queries common with AI-coding-assistant clients (5-10 tokens), the AND requires
every token to appear in a chunk. Realistic chunks rarely contain ALL such
tokens, so the sparse CTE returns ~0 rows and RRF fusion collapses to
dense-only retrieval.

The fix wraps the tsquery in `replace(..., '&', '|')::tsquery` so the operator
flips to OR. `ts_rank_cd` then grades chunks by how many query terms match
(plus IDF), exactly what we want for partial-match recall.

These tests call `perform_search` directly (with a stub embedder) so they
exercise the production SQL string in `src/docforge/api.py`. Under AND-tsq
(pre-fix master) they fail; under OR-tsq (post-fix) they pass.
"""

from __future__ import annotations

import math

import asyncpg
import numpy as np
import pytest
from pgvector.asyncpg import register_vector

from docforge.api import SearchRequest, perform_search
from docforge.config import Settings
from docforge.db import _init_connection


def _vec(angle_rad: float) -> np.ndarray:
    """Deterministic 1024-dim unit vector at angle `angle_rad` in axes (0, 1).

    Mirrors the helper in test_search_hybrid.py; duplicated to keep this
    regression test self-contained.
    """
    v = np.zeros(1024, dtype=np.float32)
    v[0] = float(np.cos(angle_rad))
    v[1] = float(np.sin(angle_rad))
    return v


class _StubEmbedder:
    """Returns a pre-set vector regardless of input.

    perform_search() awaits `aembed_query`; we don't care what the query text
    is — these tests vary only the SQL semantics, not the embedder behavior.
    """

    model_name = "stub"
    dimensions = 1024

    def __init__(self, vec: np.ndarray) -> None:
        self._vec = vec

    async def aembed_query(self, _query: str) -> np.ndarray:
        return self._vec


async def _insert_source(conn, title: str) -> str:
    return await conn.fetchval(
        """
        INSERT INTO sources (type, url, title, source_identifier, status, tags,
                             content_hash, last_crawled_at)
        VALUES ('git_repo', $1, $2, $1, 'active', $3, 'h', now())
        RETURNING id
        """,
        f"file:///{title}",
        title,
        [],
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


@pytest.mark.asyncio
async def test_multi_token_query_surfaces_partial_match(pg_url):
    """AI-realistic case: 5+ token query, target chunk shares only ONE token.

    Under AND-tsq (pre-fix bug): sparse CTE returns 0 rows because no chunk
    contains all 5 tokens. RRF collapses to dense-only; the target chunk
    (orthogonal vector) ranks behind the distractor with aligned vector.

    Under OR-tsq (fix): sparse CTE returns the chunk that matches "validation";
    ts_rank_cd grades it; RRF (sparse rank 1) lifts it above the dense-only
    distractor.
    """
    pool = await asyncpg.create_pool(pg_url, min_size=1, max_size=2, init=_init_connection)
    try:
        async with pool.acquire() as conn:
            await register_vector(conn)

            sid_target = await _insert_source(conn, "PartialMatchTarget")
            sid_other = await _insert_source(conn, "Other")

            # Target: rare "validation" only; vector orthogonal to query.
            await _insert_chunk(
                conn,
                sid_target,
                "this chunk discusses validation only, nothing else here",
                _vec(math.pi / 2),
            )
            # Distractor: aligned vector (dense rank 1) but zero keyword matches.
            await _insert_chunk(
                conn,
                sid_other,
                "completely unrelated prose about other topics",
                _vec(0.0),
            )

        settings = Settings()
        embedder = _StubEmbedder(_vec(0.0))  # aligned with "Other"
        # 5 tokens; only "validation" appears in any indexed chunk.
        req = SearchRequest(query="validation foo bar baz quux", limit=5)

        rows = await perform_search(req=req, settings=settings, pool=pool, embedder=embedder)
        titles = [r["source_title"] for r in rows]

        # Target's partial match must surface and rank above the dense-only
        # distractor. Under AND-tsq this assertion fails (target is dense-only
        # rank 2 with no sparse contribution, ranking behind Other).
        assert "PartialMatchTarget" in titles, (
            f"Chunk with partial keyword match must surface, got {titles}"
        )
        assert titles.index("PartialMatchTarget") < titles.index("Other"), (
            f"Target with sparse rank 1 should outrank dense-only Other, got {titles}"
        )
    finally:
        await pool.close()


@pytest.mark.asyncio
async def test_sparse_leg_grades_chunks_by_token_overlap(pg_url):
    """Among chunks with partial matches, more overlap should rank higher.

    Under AND-tsq: only chunks with ALL query tokens qualify (rare for long
    queries — usually zero hits).
    Under OR-tsq + ts_rank_cd: chunks with more matching tokens score higher.

    Uses dense_weight=0 to isolate the sparse leg's grading behavior.
    """
    pool = await asyncpg.create_pool(pg_url, min_size=1, max_size=2, init=_init_connection)
    try:
        async with pool.acquire() as conn:
            await register_vector(conn)

            sid_three = await _insert_source(conn, "ThreeTokens")
            sid_one = await _insert_source(conn, "OneToken")

            # ThreeTokens: 3 of 5 query tokens overlap.
            await _insert_chunk(
                conn,
                sid_three,
                "settings service access strategy for the API",
                _vec(math.pi / 2),
            )
            # OneToken: only 1 of 5 query tokens overlaps.
            await _insert_chunk(
                conn,
                sid_one,
                "settings panel with checkboxes and toggles",
                _vec(math.pi / 2),
            )

        settings = Settings()
        settings.dense_weight = 0.0  # pure-sparse comparison
        settings.sparse_weight = 1.0
        embedder = _StubEmbedder(_vec(0.0))
        req = SearchRequest(query="settings service access strategy authentication", limit=5)

        rows = await perform_search(req=req, settings=settings, pool=pool, embedder=embedder)
        titles = [r["source_title"] for r in rows]
        sims = {r["source_title"]: float(r["similarity"]) for r in rows}

        # Both chunks must surface with non-zero sparse-leg contribution.
        # Under AND-tsq: neither chunk matches all 5 tokens, sparse CTE is
        # empty, similarity collapses to 0 for both — assertion fails.
        # Under OR-tsq: both chunks match partially, sparse CTE ranks them,
        # similarity is > 0.
        assert "ThreeTokens" in titles, f"ThreeTokens missing: {titles}"
        assert "OneToken" in titles, f"OneToken missing: {titles}"
        assert sims["ThreeTokens"] > 0, (
            f"ThreeTokens similarity should be > 0 from sparse leg, got {sims}"
        )
        assert sims["OneToken"] > 0, (
            f"OneToken similarity should be > 0 from sparse leg, got {sims}"
        )
        # More overlap should yield higher sparse rank (ts_rank_cd) -> higher similarity.
        assert sims["ThreeTokens"] > sims["OneToken"], (
            f"ThreeTokens (3 matches) should outscore OneToken (1 match), got {sims}"
        )
    finally:
        await pool.close()
