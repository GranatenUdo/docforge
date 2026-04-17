"""MCP server exposing documentation search to AI coding assistants.

Run with: python -m docforge.mcp_server
"""

from __future__ import annotations

import logging

import numpy as np
from fastmcp import FastMCP

from docforge.config import Settings
from docforge.db import get_pool
from docforge.processors.embedder import Embedder

logger = logging.getLogger(__name__)

mcp = FastMCP(
    "knowledge-hub",
    instructions=(
        "Search across your team's indexed documentation including team responsibilities, "
        "coding guidelines, architecture standards, and cross-team interfaces. "
        "Use the search_documentation tool when you need information about other teams, "
        "shared coding practices, or organizational knowledge."
    ),
)

# Initialized lazily on first search
_embedder: Embedder | None = None
_settings: Settings | None = None


def _get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings


def _get_embedder() -> Embedder:
    global _embedder
    if _embedder is None:
        settings = _get_settings()
        logger.info("Loading embedding model (this may take a few seconds)...")
        _embedder = Embedder(
            settings.embedding_model, hf_token=settings.hf_token.get_secret_value()
        )
    return _embedder


@mcp.tool()
async def search_documentation(query: str, limit: int = 5) -> str:
    """Search across indexed documentation from Confluence pages and git repos.

    Returns relevant documentation chunks with source attribution.
    Use this to find information about:
    - Which team owns a particular service or component
    - Coding guidelines and standards (e.g., HTTP error handling)
    - Architecture decisions and responsibilities
    - Cross-team interfaces and dependencies

    Args:
        query: Natural language search query.
        limit: Maximum number of results to return (default 5).
    """
    settings = _get_settings()
    embedder = _get_embedder()

    # Embed the query
    query_vector = embedder.embed_query(query)

    # Search pgvector
    pool = await get_pool(settings.database_url)
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT
                c.text,
                c.section_title,
                s.title AS source_title,
                s.url AS source_url,
                1 - (c.embedding <=> $1::vector) AS similarity
            FROM chunks c
            JOIN sources s ON c.source_id = s.id
            WHERE s.status = 'active'
            ORDER BY c.embedding <=> $1::vector
            LIMIT $2
            """,
            np.array(query_vector, dtype=np.float32),
            limit,
        )

    if not rows:
        return (
            "No documentation found matching your query. "
            "The index may be empty -- run `python -m docforge ingest` to populate it."
        )

    # Format results
    parts: list[str] = []
    for i, row in enumerate(rows, 1):
        similarity = row["similarity"]
        source = row["source_title"]
        url = row["source_url"]
        section = row["section_title"]
        text = row["text"]

        header = f"**Result {i}** (relevance: {similarity:.2f}) — {source}"
        if section:
            header += f" > {section}"
        header += f"\nSource: {url}"

        parts.append(f"{header}\n\n{text}")

    return "\n\n---\n\n".join(parts)


@mcp.tool()
async def list_sources() -> str:
    """List all documentation sources currently indexed in the knowledge hub.

    Returns the title, URL, status, and last crawl time for each source.
    Use this to see what documentation is available for searching.
    """
    settings = _get_settings()
    pool = await get_pool(settings.database_url)

    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT title, url, status, last_crawled_at,
                   (SELECT count(*) FROM chunks WHERE source_id = s.id) AS chunk_count
            FROM sources s
            ORDER BY title
            """
        )

    if not rows:
        return "No sources indexed yet. Run `python -m docforge ingest` to populate."

    lines: list[str] = []
    for row in rows:
        last = row["last_crawled_at"]
        crawled = last.strftime("%Y-%m-%d %H:%M") if last else "never"
        lines.append(
            f"- **{row['title']}** ({row['chunk_count']} chunks, {row['status']})\n"
            f"  Last crawled: {crawled}\n"
            f"  {row['url']}"
        )

    return f"**{len(rows)} indexed sources:**\n\n" + "\n\n".join(lines)


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    mcp.run()


if __name__ == "__main__":
    main()
