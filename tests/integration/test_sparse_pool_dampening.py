"""Integration tests for sparse-pool-size dampening (sub-project D).

The v0.7.8 OR-tsq change made the sparse leg recall partial-match chunks
for long queries with rare tokens — good. For short queries with very common
tokens (`team`, `developer`, `role`, `Domain`), it floods the sparse pool
with weakly-relevant chunks and dilutes the dense ranking — bad.

The fix: when sparse_count > dense_count * sparse_flood_ratio (default 3.0),
scale the sparse RRF weight by sparse_flood_dampening (default 0.5). The
signal is per-query, so legitimately rare long-tail queries (where OR-tsq is
the only thing saving them) keep their full sparse contribution.
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
from tests.integration._helpers import _insert_chunk, _insert_source, _vec


class _StubEmbedder:
    model_name = "stub"
    dimensions = 1024

    def __init__(self, vec: np.ndarray) -> None:
        self._vec = vec

    async def aembed_query(self, _query: str) -> np.ndarray:
        return self._vec


@pytest.mark.asyncio
async def test_flooded_sparse_pool_does_not_drown_dense_winner(pg_url):
    """30 noise chunks all containing 'Domain' or 'domains' (the flood);
    1 target chunk that semantically matches AND contains all 4 query terms.
    Without dampening: sparse pool has 31 rows, dense has ~1 strong hit;
    fused RRF boosts noise. With dampening (sparse_count >> dense_count
    triggers weight scale-down): target wins.
    """
    pool = await asyncpg.create_pool(pg_url, min_size=1, max_size=2, init=_init_connection)
    try:
        async with pool.acquire() as conn:
            target_id = await _insert_source(conn, "Domain Catalog")
            await _insert_chunk(
                conn,
                target_id,
                "The Domain Catalog enumerates DocuWare domains and their owners.",
                _vec(0.0),
            )
            for i in range(30):
                src = await _insert_source(conn, f"Noise Page {i}")
                await _insert_chunk(
                    conn,
                    src,
                    f"Some unrelated content mentioning Domain or domains chunk {i}.",
                    _vec(math.pi / 2),
                )

        embedder = _StubEmbedder(_vec(0.01))  # very close to the target
        settings = Settings(sparse_flood_ratio=3.0, sparse_flood_dampening=0.5)
        req = SearchRequest(
            query="Domain Catalog DocuWare domains",
            team_name="ccl",
            area_name="cloud",
            limit=5,
        )
        rows = await perform_search(req=req, settings=settings, pool=pool, embedder=embedder)
        titles = [r["source_title"] for r in rows]
        assert "Domain Catalog" in titles, f"Expected target in top-5, got: {titles}"
        assert titles.index("Domain Catalog") < 3, (
            f"Target should be top-3 once sparse flooding is dampened; "
            f"was at rank {titles.index('Domain Catalog') + 1}"
        )
    finally:
        await pool.close()


@pytest.mark.asyncio
async def test_balanced_pools_keep_full_sparse_weight(pg_url):
    """Regression guard for sub-project B's gains. When a query has rare
    tokens and the sparse pool returns FEWER rows than the dense pool, the
    dampening must NOT fire — the sparse leg is doing its job. A 7-token
    AI-realistic query where only ~1 chunk has any token overlap:
    sparse pool size = 1, dense pool size = ~50 -> ratio << 1, no dampening,
    OR-tsq's recall stays intact.
    """
    pool = await asyncpg.create_pool(pg_url, min_size=1, max_size=2, init=_init_connection)
    try:
        async with pool.acquire() as conn:
            target_id = await _insert_source(conn, "ADR-002")
            await _insert_chunk(
                conn,
                target_id,
                "Task dispatch strategy for the CIS BackgroundProcessService host.",
                _vec(0.5),  # not the closest dense match — sparse needs to carry it
            )
            for i in range(50):
                src = await _insert_source(conn, f"Unrelated Page {i}")
                await _insert_chunk(
                    conn,
                    src,
                    f"Completely unrelated content about other topics {i}.",
                    _vec(0.0),  # closer dense match than the target
                )

        embedder = _StubEmbedder(_vec(0.05))  # dense favors the unrelated chunks
        settings = Settings(sparse_flood_ratio=3.0, sparse_flood_dampening=0.5)
        req = SearchRequest(
            query="CIS BackgroundProcessService dispatch strategy ADR architecture rationale design",
            team_name="ccl",
            area_name="cloud",
            limit=5,
        )
        rows = await perform_search(req=req, settings=settings, pool=pool, embedder=embedder)
        titles = [r["source_title"] for r in rows]
        assert "ADR-002" in titles, (
            f"Sub-project B regression: long-rare-token query lost ADR-002. "
            f"Got: {titles}. Dampening fired when it shouldn't have."
        )
    finally:
        await pool.close()
