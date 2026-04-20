"""Tests for docforge.query_log.log_query."""

from __future__ import annotations

import pytest

from docforge.query_log import log_query


class _ConnCapture:
    def __init__(self, raise_on_execute: bool = False):
        self.raise_on_execute = raise_on_execute
        self.executed = []

    async def execute(self, query, *args):
        if self.raise_on_execute:
            raise RuntimeError("boom")
        self.executed.append((query, args))


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
    await log_query(
        pool=pool,
        user_name="tobias.ens",
        team_name="ccl",
        area_name="cloud",
        query="retry policy",
        result_count=3,
    )
    assert len(conn.executed) == 1
    query, args = conn.executed[0]
    assert "INSERT INTO query_log" in query
    assert args == ("tobias.ens", "ccl", "cloud", "retry policy", 3)


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
    await log_query(
        pool=pool,
        user_name="a",
        team_name="b",
        area_name=None,
        query="q",
        result_count=0,
    )
