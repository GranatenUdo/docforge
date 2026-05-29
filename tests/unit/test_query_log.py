"""Tests for docforge.query_log.log_query and log_search."""

from __future__ import annotations

import pytest

from docforge.query_log import log_query, log_search


class _NoopConnTxn:
    async def __aenter__(self):
        return None

    async def __aexit__(self, *a):
        return None


class _ConnCapture:
    def __init__(self, raise_on_execute: bool = False, raise_on_executemany: bool = False):
        self.raise_on_execute = raise_on_execute
        self.raise_on_executemany = raise_on_executemany
        self.executed = []

    async def fetchval(self, query, *args):
        if self.raise_on_execute:
            raise RuntimeError("boom")
        self.executed.append((query, args))
        return "00000000-0000-0000-0000-000000000001"

    async def executemany(self, query, rows):
        if self.raise_on_execute or self.raise_on_executemany:
            raise RuntimeError("boom")
        self.executed.append((query, list(rows)))

    def transaction(self):
        return _NoopConnTxn()


class _AcquireCtx:
    def __init__(self, conn):
        self._conn = conn

    async def __aenter__(self):
        return self._conn

    async def __aexit__(self, *a):
        return None


class _FakePool:
    def __init__(self, conn):
        self._conn = conn

    def acquire(self):
        return _AcquireCtx(self._conn)


@pytest.mark.asyncio
async def test_log_query_inserts_row():
    conn = _ConnCapture()
    pool = _FakePool(conn)
    returned = await log_query(
        pool=pool,
        user_name="tobias.ens",
        team_name="platform",
        area_name="cloud",
        query="retry policy",
        result_count=3,
    )
    assert len(conn.executed) == 1
    query, args = conn.executed[0]
    assert "INSERT INTO query_log" in query and "RETURNING id" in query
    assert args == ("tobias.ens", "platform", "cloud", "retry policy", 3, None, None)
    assert returned == "00000000-0000-0000-0000-000000000001"


@pytest.mark.asyncio
async def test_log_query_accepts_null_area():
    conn = _ConnCapture()
    pool = _FakePool(conn)
    await log_query(
        pool=pool,
        user_name="a",
        team_name="b",
        area_name=None,
        query="q",
        result_count=0,
    )
    _, args = conn.executed[0]
    assert args[2] is None


@pytest.mark.asyncio
async def test_log_query_swallows_failures():
    conn = _ConnCapture(raise_on_execute=True)
    pool = _FakePool(conn)
    # Must not raise
    returned = await log_query(
        pool=pool, user_name="a", team_name="b", area_name=None, query="q", result_count=0
    )
    assert returned is None


@pytest.mark.asyncio
async def test_log_query_accepts_user_oid():
    conn = _ConnCapture()
    pool = _FakePool(conn)
    await log_query(
        pool=pool,
        user_name="tobias.ens",
        team_name="platform",
        area_name="cloud",
        query="q",
        result_count=3,
        user_oid="abc-oid-123",
    )
    _, args = conn.executed[0]
    assert args[5] == "abc-oid-123"


@pytest.mark.asyncio
async def test_log_query_user_oid_defaults_to_none():
    conn = _ConnCapture()
    pool = _FakePool(conn)
    await log_query(
        pool=pool,
        user_name="a",
        team_name="b",
        area_name=None,
        query="q",
        result_count=0,
    )
    _, args = conn.executed[0]
    # user_oid is the 6th positional (index 5); request_ms is 7th.
    assert args[5] is None


@pytest.mark.asyncio
async def test_log_query_accepts_request_ms():
    conn = _ConnCapture()
    pool = _FakePool(conn)
    await log_query(
        pool=pool,
        user_name="tobias.ens",
        team_name="platform",
        area_name="cloud",
        query="q",
        result_count=3,
        user_oid="oid-1",
        request_ms=42,
    )
    _, args = conn.executed[0]
    # args: (user_name, team_name, area_name, query, result_count, user_oid, request_ms)
    # request_ms is the last positional.
    assert args[-1] == 42


@pytest.mark.asyncio
async def test_log_query_request_ms_defaults_to_none():
    conn = _ConnCapture()
    pool = _FakePool(conn)
    await log_query(
        pool=pool,
        user_name="a",
        team_name="b",
        area_name=None,
        query="q",
        result_count=0,
    )
    _, args = conn.executed[0]
    assert args[-1] is None


@pytest.mark.asyncio
async def test_log_search_query_only_when_no_results():
    conn = _ConnCapture()
    pool = _FakePool(conn)
    qid = await log_search(
        pool=pool,
        user_name="u",
        team_name="t",
        area_name=None,
        query="q",
        result_count=0,
        results=None,
    )
    assert qid == "00000000-0000-0000-0000-000000000001"
    assert len(conn.executed) == 1  # only the query_log INSERT
    assert "INSERT INTO query_log" in conn.executed[0][0]


@pytest.mark.asyncio
async def test_log_search_logs_query_and_results():
    conn = _ConnCapture()
    pool = _FakePool(conn)
    qid = await log_search(
        pool=pool,
        user_name="u",
        team_name="t",
        area_name=None,
        query="q",
        result_count=1,
        results=[
            {
                "rank": 1,
                "score": 0.03,
                "source_url": "u1",
                "source_title": "T1",
                "section_title": "S1",
                "chunk_text": "b1",
            }
        ],
    )
    assert qid == "00000000-0000-0000-0000-000000000001"
    joined = " ".join(q for q, _ in conn.executed)
    assert "INSERT INTO query_log" in joined and "INSERT INTO query_result" in joined


@pytest.mark.asyncio
async def test_log_search_swallows_failure():
    conn = _ConnCapture(raise_on_execute=True)
    pool = _FakePool(conn)
    qid = await log_search(
        pool=pool, user_name="u", team_name="t", area_name=None, query="q", result_count=0
    )
    assert qid is None


@pytest.mark.asyncio
async def test_log_search_logs_query_even_when_results_fail():
    conn = _ConnCapture(raise_on_executemany=True)
    pool = _FakePool(conn)
    qid = await log_search(
        pool=pool,
        user_name="u",
        team_name="t",
        area_name=None,
        query="q",
        result_count=1,
        results=[
            {
                "rank": 1,
                "score": 0.03,
                "source_url": "u1",
                "source_title": "T1",
                "section_title": "S1",
                "chunk_text": "b1",
            }
        ],
    )
    # query_log was written (id returned) despite the query_result failure being swallowed
    assert qid == "00000000-0000-0000-0000-000000000001"
    assert any("INSERT INTO query_log" in q for q, _ in conn.executed)
