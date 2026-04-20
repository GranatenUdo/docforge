"""Lightweight MCP client for docforge.

Calls a hosted search API over HTTP. No local database or model needed.

Usage:
    pip install httpx fastmcp
    claude mcp add -s user docforge -- python mcp_client.py

Environment:
    DOCFORGE_API_URL: Base URL of the search API
"""

from __future__ import annotations

import os

import httpx
from fastmcp import FastMCP

API_URL = os.environ.get("DOCFORGE_API_URL", "http://localhost:8000")

mcp = FastMCP(
    "docforge",
    instructions=(
        "Search across your team's indexed documentation including architecture, "
        "coding guidelines, and cross-team interfaces. "
        "Use the search_documentation tool when you need information about "
        "other teams, shared practices, or organizational knowledge."
    ),
)


@mcp.tool()
async def search_documentation(query: str, limit: int = 5) -> str:
    """Search across indexed documentation from Confluence pages and git repos.

    Args:
        query: Natural language search query.
        limit: Maximum number of results to return (default 5).
    """
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(
            f"{API_URL}/search",
            json={"query": query, "limit": limit},
        )
        resp.raise_for_status()
        data = resp.json()

    if not data["results"]:
        return "No documentation found matching your query."

    parts: list[str] = []
    for i, result in enumerate(data["results"], 1):
        header = f"**Result {i}** (relevance: {result['similarity']:.2f})"
        header += f" -- {result['source_title']}"
        if result.get("section_title"):
            header += f" > {result['section_title']}"
        header += f"\nSource: {result['source_url']}"
        parts.append(f"{header}\n\n{result['text']}")

    return "\n\n---\n\n".join(parts)


@mcp.tool()
async def list_sources() -> str:
    """List all documentation sources currently indexed."""
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(f"{API_URL}/sources")
        resp.raise_for_status()
        data = resp.json()

    if not data["sources"]:
        return "No sources indexed."

    lines = [f"**{data['count']} indexed sources:**\n"]
    for src in data["sources"]:
        lines.append(f"- **{src['title']}** ({src['chunk_count']} chunks, {src['status']})")

    return "\n".join(lines)


if __name__ == "__main__":
    mcp.run()
