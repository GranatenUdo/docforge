"""Unit tests for the cross-encoder rerank seam in docforge.api.perform_search.

No live DB and no network: the asyncpg pool is mocked so the hybrid-search SQL
fetch returns canned dict-like rows, the embedder's query-embed method returns a
canned vector, and a fake RerankerProtocol returns a known reordering.

These tests pin three things:
  1. rerank ON  -> top-`rerank_top_n` head reordered per the fake reranker, the
     un-reranked tail follows, final length == req.limit, and the captured `$6`
     bind value == hybrid_pool_size (pool expansion via the BIND, not the SQL
     literal).
  2. rerank OFF -> output identical to no-rerank, captured `$6` bind == req.limit
     (regression guard for the default-OFF path).
  3. length guard -> a fake reranker returning fewer indices than len(head)
     trips `assert len(order) == len(head)` so rows can't be silently dropped.
"""

from __future__ import annotations

import pytest

from docforge.api import SearchRequest, perform_search
from tests.conftest import FakeEmbedder, fake_settings


def _rerank_settings(*, rerank_enabled: bool, rerank_top_n: int = 50):
    """fake_settings() extended with the reranker knobs perform_search reads."""
    s = fake_settings()
    s.rerank_enabled = rerank_enabled
    s.rerank_top_n = rerank_top_n
    s.reranker_url = "https://rerank.invalid" if rerank_enabled else ""
    return s


class _CapturingFetchConn:
    """asyncpg connection stand-in that records the positional bind args of the
    one read query perform_search issues, and returns canned rows."""

    def __init__(self, rows, captured):
        self._rows = rows
        self._captured = captured

    async def fetch(self, query, *args):
        self._captured["query"] = query
        self._captured["args"] = args
        return self._rows


class _CapturingFetchAcquireCtx:
    def __init__(self, conn):
        self._conn = conn

    async def __aenter__(self):
        return self._conn

    async def __aexit__(self, *a):
        return None


class CapturingFetchPool:
    """asyncpg pool stand-in exposing the captured fetch bind args."""

    def __init__(self, rows):
        self._rows = rows
        self.captured: dict = {}

    def acquire(self):
        return _CapturingFetchAcquireCtx(_CapturingFetchConn(self._rows, self.captured))


class FakeReranker:
    """RerankerProtocol stand-in: arerank returns a preset reordering."""

    def __init__(self, order):
        self._order = order
        self.calls: list[tuple[str, list[str]]] = []

    async def arerank(self, query: str, passages: list[str]) -> list[int]:
        self.calls.append((query, passages))
        return self._order


def _make_rows(n: int):
    """n canned dict rows with the keys perform_search's passage builder reads."""
    return [
        {
            "text": f"body text {i}",
            "section_title": f"section {i}",
            "source_title": f"Doc {i}",
            "source_url": f"https://wiki/{i}",
            "source_tags": ["ccl"],
            "similarity": 1.0 - i / 100.0,
            "dense_rank": i + 1,
            "sparse_rank": i + 1,
        }
        for i in range(n)
    ]


@pytest.mark.asyncio
async def test_rerank_on_reorders_head_keeps_tail_and_expands_pool_bind():
    # rerank_top_n=3 so head is the first 3 rows; tail is rows[3:].
    rows = _make_rows(6)
    pool = CapturingFetchPool(rows)
    settings = _rerank_settings(rerank_enabled=True, rerank_top_n=3)
    # Reorder the 3-row head: 2, 0, 1.
    reranker = FakeReranker([2, 0, 1])
    req = SearchRequest(query="hello", team_name="ccl", limit=5)

    result = await perform_search(
        req=req, settings=settings, pool=pool, embedder=FakeEmbedder(), reranker=reranker
    )

    # Head reordered per the fake reranker, then the original tail, then capped
    # at req.limit. Pre-rerank order is Doc 0..5; head=[0,1,2] -> [2,0,1];
    # tail=[3,4,5]; concat=[2,0,1,3,4,5]; capped to limit 5 -> [2,0,1,3,4].
    titles = [r["source_title"] for r in result]
    assert titles == ["Doc 2", "Doc 0", "Doc 1", "Doc 3", "Doc 4"]
    assert len(result) == req.limit

    # The reranker saw the head's passages, built as title\nsection\ntext.
    assert len(reranker.calls) == 1
    seen_query, seen_passages = reranker.calls[0]
    assert seen_query == "hello"
    assert seen_passages == [
        "Doc 0\nsection 0\nbody text 0",
        "Doc 1\nsection 1\nbody text 1",
        "Doc 2\nsection 2\nbody text 2",
    ]

    # $6 is the 6th positional bind (index 5); ON -> hybrid_pool_size.
    assert pool.captured["args"][5] == settings.hybrid_pool_size


@pytest.mark.asyncio
async def test_rerank_off_via_flag_is_identical_and_binds_req_limit():
    rows = _make_rows(6)
    pool = CapturingFetchPool(rows)
    settings = _rerank_settings(rerank_enabled=False)
    # A reranker is supplied but must be ignored because the flag is off.
    reranker = FakeReranker([5, 4, 3, 2, 1, 0])
    req = SearchRequest(query="hello", team_name="ccl", limit=5)

    result = await perform_search(
        req=req, settings=settings, pool=pool, embedder=FakeEmbedder(), reranker=reranker
    )

    # No reordering; rows returned in DB order, capped at limit.
    titles = [r["source_title"] for r in result]
    assert titles == ["Doc 0", "Doc 1", "Doc 2", "Doc 3", "Doc 4"]
    assert reranker.calls == []  # reranker untouched when flag off
    # $6 bind == req.limit (regression guard for the default-OFF path).
    assert pool.captured["args"][5] == req.limit


@pytest.mark.asyncio
async def test_rerank_none_reranker_is_identical_and_binds_req_limit():
    rows = _make_rows(6)
    pool = CapturingFetchPool(rows)
    # Flag ON but no reranker instance -> the seam must stay dormant.
    settings = _rerank_settings(rerank_enabled=True, rerank_top_n=3)
    req = SearchRequest(query="hello", team_name="ccl", limit=5)

    result = await perform_search(
        req=req, settings=settings, pool=pool, embedder=FakeEmbedder(), reranker=None
    )

    titles = [r["source_title"] for r in result]
    assert titles == ["Doc 0", "Doc 1", "Doc 2", "Doc 3", "Doc 4"]
    # reranker is None -> pool not expanded -> $6 == req.limit.
    assert pool.captured["args"][5] == req.limit


@pytest.mark.asyncio
async def test_rerank_short_order_trips_length_guard():
    rows = _make_rows(6)
    pool = CapturingFetchPool(rows)
    settings = _rerank_settings(rerank_enabled=True, rerank_top_n=3)
    # Returns fewer indices than len(head)=3 -> assert must fire so rows are
    # never silently dropped.
    reranker = FakeReranker([0, 1])
    req = SearchRequest(query="hello", team_name="ccl", limit=5)

    with pytest.raises(AssertionError):
        await perform_search(
            req=req, settings=settings, pool=pool, embedder=FakeEmbedder(), reranker=reranker
        )
