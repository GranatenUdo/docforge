"""Integration tests for the sparse-leg OR-tsq combiner (v0.7.8).

Each test calls `perform_search` directly with a stub embedder so the
production SQL string in `src/docforge/api.py` is exercised end-to-end.
"""

from __future__ import annotations

import math

import asyncpg
import numpy as np
import pytest
from _helpers import _insert_chunk, _insert_source, _vec  # noqa: F401
from pgvector.asyncpg import register_vector

from docforge.api import SearchRequest, perform_search
from docforge.config import Settings
from docforge.db import _init_connection


class _StubEmbedder:
    """Returns a pre-set vector regardless of input."""

    model_name = "stub"
    dimensions = 1024

    def __init__(self, vec: np.ndarray) -> None:
        self._vec = vec

    async def aembed_query(self, _query: str) -> np.ndarray:
        return self._vec


@pytest.mark.asyncio
async def test_multi_token_query_surfaces_partial_match(pg_url):
    """5-token query where the target chunk shares only one token must still surface."""
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
    """With dense_weight=0, more token overlap must produce higher similarity."""
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

        # pure-sparse comparison (no dense contribution)
        settings = Settings(dense_weight=0.0, sparse_weight=1.0)
        embedder = _StubEmbedder(_vec(0.0))
        req = SearchRequest(query="settings service access strategy authentication", limit=5)

        rows = await perform_search(req=req, settings=settings, pool=pool, embedder=embedder)
        titles = [r["source_title"] for r in rows]
        sims = {r["source_title"]: float(r["similarity"]) for r in rows}

        # sim > 0 proves the sparse leg fired; under AND-tsq the CTE would
        # collapse to 0 rows because no chunk contains all 5 query tokens.
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
