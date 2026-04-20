"""Tests for docforge.mcp_server — search_documentation and list_sources."""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest


class _CapturingConn:
    def __init__(self, rows, executes):
        self._rows = rows
        self._executes = executes

    async def fetch(self, query, *args):
        return self._rows

    async def execute(self, query, *args):
        self._executes.append((query, args))


class _CapturingCtx:
    def __init__(self, conn):
        self._conn = conn

    async def __aenter__(self):
        return self._conn

    async def __aexit__(self, *a):
        return None


class _CapturingPool:
    def __init__(self, rows):
        self.rows = rows
        self.executes = []

    def acquire(self):
        return _CapturingCtx(_CapturingConn(self.rows, self.executes))


@pytest.fixture
def patch_mcp_deps(monkeypatch):
    def _install(rows):
        from docforge import mcp_server as mod

        pool = _CapturingPool(rows)

        async def fake_get_pool(url):
            return pool

        fake_embedder = MagicMock()
        fake_embedder.embed_query.return_value = [0.0] * 768

        monkeypatch.setattr(mod, "get_pool", fake_get_pool)
        monkeypatch.setattr(mod, "_get_embedder", lambda: fake_embedder)
        monkeypatch.setattr(
            mod,
            "_get_settings",
            lambda: SimpleNamespace(
                database_url="postgresql://fake",
                tag_match_weight=0.1,
                org_tag_weight=0.05,
            ),
        )
        return pool, fake_embedder

    return _install


@pytest.mark.asyncio
async def test_search_documentation_formats_results(patch_mcp_deps):
    rows = [
        {
            "text": "Platform team owns orgs.",
            "section_title": "Platform",
            "source_title": "Team Responsibilities",
            "source_url": "https://wiki/page/1",
            "source_tags": ["ccl", "cloud"],
            "similarity": 0.92,
        },
    ]
    pool, fake_embedder = patch_mcp_deps(rows)

    from docforge.mcp_server import search_documentation

    result = await search_documentation(
        "who owns orgs",
        user_name="tobias.ens",
        team_name="ccl",
        area_name="cloud",
        limit=5,
    )

    assert "Platform team owns orgs." in result
    assert "0.92" in result
    assert "Tags: ccl, cloud" in result
    fake_embedder.embed_query.assert_called_once_with("who owns orgs")
    # query_log insert fired
    assert any("INSERT INTO query_log" in q for q, _ in pool.executes)


@pytest.mark.asyncio
async def test_search_documentation_no_tags_no_tag_line(patch_mcp_deps):
    rows = [
        {
            "text": "some text",
            "section_title": None,
            "source_title": "Doc",
            "source_url": "https://x",
            "source_tags": [],
            "similarity": 0.7,
        },
    ]
    patch_mcp_deps(rows)

    from docforge.mcp_server import search_documentation

    result = await search_documentation(
        "q",
        user_name="u",
        team_name="t",
    )
    assert "Tags:" not in result


@pytest.mark.asyncio
async def test_search_documentation_empty_returns_hint(patch_mcp_deps):
    patch_mcp_deps([])

    from docforge.mcp_server import search_documentation

    result = await search_documentation("q", user_name="u", team_name="t")
    assert "No documentation found" in result


@pytest.mark.asyncio
async def test_list_sources_formats_entries(patch_mcp_deps):
    rows = [
        {
            "title": "Doc A",
            "url": "https://wiki/a",
            "status": "active",
            "last_crawled_at": datetime(2026, 4, 17, 9, 30, tzinfo=timezone.utc),
            "chunk_count": 12,
        },
    ]
    patch_mcp_deps(rows)

    from docforge.mcp_server import list_sources

    result = await list_sources()
    assert "Doc A" in result
    assert "12 chunks" in result


@pytest.mark.asyncio
async def test_list_sources_empty_returns_hint(patch_mcp_deps):
    patch_mcp_deps([])

    from docforge.mcp_server import list_sources

    result = await list_sources()
    assert "No sources indexed" in result
