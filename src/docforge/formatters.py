"""Pure-Python formatters for search results.

Extracted from mcp_server.py to keep the import surface tiny — importing
this module must NOT pull in numpy, fastmcp, asyncpg, or anything else
that risks deadlocking when imported lazily from inside an async event
loop. See remote_client.py.search() for the original incident: lazy
`from docforge.mcp_server import format_search_results_markdown` hung
indefinitely inside the FastMCP tool dispatch on first call because
mcp_server's import chain (numpy, embedder, db.get_pool) interacted
badly with the running event loop. Importing from this module at module
level avoids the lazy-import-inside-async pitfall.
"""

from __future__ import annotations


def format_search_results_markdown(
    results: list[dict],
    *,
    empty_message: str = "No documentation found matching your query.",
) -> str:
    """Render a list of search-result dicts as the canonical Markdown shape.

    Each result must have keys: source_title, source_url, text.
    Optional: section_title, source_tags.
    """
    if not results:
        return empty_message

    parts: list[str] = []
    for i, r in enumerate(results, 1):
        header = f"**Result {i}** -- {r['source_title']}"
        if r.get("section_title"):
            header += f" > {r['section_title']}"
        header += f"\nSource: {r['source_url']}"
        tags = r.get("source_tags") or []
        if tags:
            header += f"\nTags: {', '.join(tags)}"
        parts.append(f"{header}\n\n{r['text']}")
    return "\n\n---\n\n".join(parts)
