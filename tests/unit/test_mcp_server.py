"""Tests for docforge.mcp_server — search_documentation and list_sources."""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from tests.conftest import CapturingPool


@pytest.fixture
def patch_mcp_deps(monkeypatch):
    def _install(rows):
        from docforge import mcp_server as mod
        from tests.conftest import FakeEmbedder

        pool = CapturingPool(rows)

        async def fake_get_pool(url, **kwargs):
            return pool

        fake_embedder = FakeEmbedder()

        monkeypatch.setattr(mod, "get_pool", fake_get_pool)
        monkeypatch.setattr(mod, "_get_embedder", lambda: fake_embedder)
        monkeypatch.setattr(
            mod,
            "_get_settings",
            lambda: SimpleNamespace(
                database_url="postgresql://fake",
                tag_match_weight=0.1,
                org_tag_weight=0.05,
                pool_min_size=5,
                pool_max_size=25,
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
            "source_tags": ["platform", "cloud"],
            "similarity": 0.92,
        },
    ]
    pool, fake_embedder = patch_mcp_deps(rows)

    from docforge.mcp_server import search_documentation

    result = await search_documentation(
        "who owns orgs",
        user_name="tobias.ens",
        team_name="platform",
        area_name="cloud",
        limit=5,
    )

    assert "Platform team owns orgs." in result
    assert "Tags: platform, cloud" in result
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


@pytest.mark.asyncio
async def test_search_documentation_rejects_limit_over_max():
    """FastMCP enforces the Annotated le=50 constraint at the protocol layer."""
    from fastmcp.client import Client
    from fastmcp.exceptions import ToolError

    from docforge.mcp_server import mcp

    async with Client(mcp) as client:
        with pytest.raises(ToolError, match="less_than_equal"):
            await client.call_tool(
                "search_documentation",
                {
                    "query": "q",
                    "user_name": "u",
                    "team_name": "t",
                    "limit": 51,
                },
            )


@pytest.mark.asyncio
async def test_search_documentation_rejects_query_over_max_length():
    """FastMCP enforces the Annotated max_length=8000 constraint."""
    from fastmcp.client import Client
    from fastmcp.exceptions import ToolError

    from docforge.mcp_server import mcp

    async with Client(mcp) as client:
        with pytest.raises(ToolError, match="string_too_long"):
            await client.call_tool(
                "search_documentation",
                {
                    "query": "x" * 8001,
                    "user_name": "u",
                    "team_name": "t",
                    "limit": 5,
                },
            )


@pytest.mark.asyncio
async def test_search_documentation_runs_embed_via_to_thread(monkeypatch, patch_mcp_deps):
    """The search_documentation handler calls aembed_query on the embedder,
    which (for in-process Embedder) delegates to asyncio.to_thread internally.
    This test verifies aembed_query is called with the correct query string."""
    from unittest.mock import AsyncMock

    rows = [
        {
            "text": "x",
            "section_title": None,
            "source_title": "S",
            "source_url": "https://x",
            "source_tags": [],
            "similarity": 0.9,
        },
    ]
    pool, fake_embedder = patch_mcp_deps(rows)

    # Wrap aembed_query in an AsyncMock so we can assert on the call.
    spy = AsyncMock(return_value=[0.0] * 768)
    fake_embedder.aembed_query = spy

    from docforge.mcp_server import search_documentation

    await search_documentation("hello", user_name="u", team_name="t")

    spy.assert_called_once_with("hello")
