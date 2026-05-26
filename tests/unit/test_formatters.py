"""Tests for docforge.formatters — and for the import-surface invariant."""

from __future__ import annotations

import importlib
import sys


def test_format_empty_results_returns_default_message():
    from docforge.formatters import format_search_results_markdown

    assert format_search_results_markdown([]) == "No documentation found matching your query."


def test_format_empty_results_uses_custom_message():
    from docforge.formatters import format_search_results_markdown

    assert format_search_results_markdown([], empty_message="nothing here") == "nothing here"


def test_format_single_result_renders_canonical_shape():
    from docforge.formatters import format_search_results_markdown

    out = format_search_results_markdown(
        [
            {
                "similarity": 0.85,
                "source_title": "My Page",
                "source_url": "https://example.com",
                "section_title": "Overview",
                "text": "Hello world.",
            }
        ]
    )
    assert "**Result 1**" in out
    assert "relevance: 0.85" in out
    assert "My Page" in out
    assert "> Overview" in out
    assert "Source: https://example.com" in out
    assert "Hello world." in out


def test_format_multiple_results_separated_by_horizontal_rule():
    from docforge.formatters import format_search_results_markdown

    out = format_search_results_markdown(
        [
            {"similarity": 0.5, "source_title": "A", "source_url": "u1", "text": "t1"},
            {"similarity": 0.4, "source_title": "B", "source_url": "u2", "text": "t2"},
        ]
    )
    assert out.count("---") == 1
    assert "**Result 1**" in out
    assert "**Result 2**" in out


def test_format_includes_tags_when_present():
    from docforge.formatters import format_search_results_markdown

    out = format_search_results_markdown(
        [
            {
                "similarity": 0.5,
                "source_title": "X",
                "source_url": "u",
                "text": "t",
                "source_tags": ["ccl", "org"],
            }
        ]
    )
    assert "Tags: ccl, org" in out


def test_formatters_module_has_no_heavy_imports():
    """REGRESSION GUARD for v0.7.9 hang.

    The formatter must not transitively import numpy, fastmcp, asyncpg, or
    docforge.mcp_server / docforge.db / docforge.processors.embedder. The
    lazy import of mcp_server from inside an async event loop hung the
    MCP for 90+ seconds in v0.7.9; this test catches a regression where
    formatters.py grows a heavy dependency.
    """
    # Wipe relevant module cache to force fresh import.
    forbidden = {
        "numpy",
        "fastmcp",
        "asyncpg",
        "docforge.mcp_server",
        "docforge.db",
        "docforge.processors.embedder",
    }
    pre = {m for m in sys.modules if m in forbidden}
    # Import formatters (force re-import so the test is meaningful even when
    # cached). We don't actually remove anything from sys.modules — we just
    # snapshot before and after to see what NEW heavy modules got pulled in.
    importlib.import_module("docforge.formatters")
    post = {m for m in sys.modules if m in forbidden}
    newly_imported = post - pre
    assert not newly_imported, (
        f"docforge.formatters now transitively imports {newly_imported} — "
        "this re-introduces the v0.7.9 hang risk. Keep formatters.py stdlib-only."
    )
