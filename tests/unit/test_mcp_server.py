"""Tests for docforge.mcp_server — search_documentation and list_sources."""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest


class _FakeConn:
    def __init__(self, rows):
        self._rows = rows

    async def fetch(self, query, *args):
        return self._rows


class _AcquireCtx:
    def __init__(self, rows):
        self._rows = rows

    async def __aenter__(self):
        return _FakeConn(self._rows)

    async def __aexit__(self, *a):
        return None


class FakePool:
    def __init__(self, rows):
        self._rows = rows

    def acquire(self):
        return _AcquireCtx(self._rows)


@pytest.fixture
def patch_mcp_deps(monkeypatch):
    """Return an installer: patch_mcp_deps(rows) wires up the module."""

    def _install(rows):
        from docforge import mcp_server as mod

        fake_pool = FakePool(rows)

        async def fake_get_pool(url):
            return fake_pool

        fake_embedder = MagicMock()
        fake_embedder.embed_query.return_value = [0.0] * 768

        monkeypatch.setattr(mod, "get_pool", fake_get_pool)
        monkeypatch.setattr(mod, "_get_embedder", lambda: fake_embedder)
        monkeypatch.setattr(
            mod,
            "_get_settings",
            lambda: SimpleNamespace(database_url="postgresql://fake"),
        )
        return fake_embedder

    return _install


@pytest.mark.asyncio
async def test_search_documentation_formats_results(patch_mcp_deps):
    rows = [
        {
            "text": "Platform team owns organization lifecycle.",
            "section_title": "Platform",
            "source_title": "Team Responsibilities",
            "source_url": "https://wiki/page/1",
            "similarity": 0.92,
        },
        {
            "text": "Imaging team owns document rendering.",
            "section_title": None,
            "source_title": "Team Responsibilities",
            "source_url": "https://wiki/page/1",
            "similarity": 0.81,
        },
    ]
    fake_embedder = patch_mcp_deps(rows)

    from docforge.mcp_server import search_documentation

    result = await search_documentation("who owns orgs", limit=5)

    assert "Platform team owns organization lifecycle." in result
    assert "Imaging team owns document rendering." in result
    assert "0.92" in result
    assert "Team Responsibilities" in result
    fake_embedder.embed_query.assert_called_once_with("who owns orgs")


@pytest.mark.asyncio
async def test_search_documentation_empty_returns_hint(patch_mcp_deps):
    patch_mcp_deps([])

    from docforge.mcp_server import search_documentation

    result = await search_documentation("anything")
    assert "No documentation found" in result
    assert "docforge ingest" in result


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
        {
            "title": "Doc B",
            "url": "https://wiki/b",
            "status": "active",
            "last_crawled_at": None,
            "chunk_count": 0,
        },
    ]
    patch_mcp_deps(rows)

    from docforge.mcp_server import list_sources

    result = await list_sources()
    assert "Doc A" in result
    assert "12 chunks" in result
    assert "Doc B" in result
    assert "never" in result


@pytest.mark.asyncio
async def test_list_sources_empty_returns_hint(patch_mcp_deps):
    patch_mcp_deps([])

    from docforge.mcp_server import list_sources

    result = await list_sources()
    assert "No sources indexed" in result
