"""MCP server exposing documentation search to AI coding assistants.

Run with: python -m docforge.mcp_server
"""

from __future__ import annotations

import logging
from typing import Annotated

import numpy as np
from fastmcp import FastMCP
from pydantic import Field

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
        _embedder = Embedder.from_settings(settings)
    return _embedder


@mcp.tool()
async def search_documentation(
    query: Annotated[str, Field(max_length=8000)],
    user_name: str,
    team_name: str,
    area_name: str | None = None,
    limit: Annotated[int, Field(ge=1, le=50)] = 5,
) -> str:
    """Search across indexed documentation from Confluence pages and git repos.

    Returns relevant documentation chunks with source attribution. Use this to find
    information about team ownership, coding guidelines, architecture decisions,
    and cross-team interfaces.

    Args:
        query: Natural language search query.
        user_name: Your name (e.g., "tobias.ens"). Used for usage telemetry.
        team_name: Your team tag (e.g., "platform"). Boosts team-tagged docs.
        area_name: Your area tag (e.g., "cloud"). Optional; boosts area-tagged docs.
        limit: Maximum number of results to return. Must be between 1 and 50, default 5.
    """
    settings = _get_settings()
    embedder = _get_embedder()

    query_vector = embedder.embed_query(query)
    user_tags = [team_name] + ([area_name] if area_name else [])

    pool = await get_pool(settings.database_url)
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT
                c.text,
                c.section_title,
                s.title AS source_title,
                s.url AS source_url,
                s.tags AS source_tags,
                1 - (c.embedding <=> $1::vector) AS similarity,
                (1 - (c.embedding <=> $1::vector)) *
                    (1
                     + $2::float * cardinality(
                         ARRAY(SELECT unnest(s.tags) INTERSECT SELECT unnest($3::text[]))
                       )
                     + $4::float * (CASE WHEN 'org' = ANY(s.tags) THEN 1 ELSE 0 END)
                    ) AS boosted_score
            FROM chunks c
            JOIN sources s ON c.source_id = s.id
            WHERE s.status = 'active'
            ORDER BY boosted_score DESC
            LIMIT $5
            """,
            np.array(query_vector, dtype=np.float32),
            settings.tag_match_weight,
            user_tags,
            settings.org_tag_weight,
            limit,
        )

    from docforge.query_log import log_query

    await log_query(pool, user_name, team_name, area_name, query, len(rows))

    if not rows:
        return (
            "No documentation found matching your query. "
            "The index may be empty -- run `python -m docforge ingest` to populate it."
        )

    parts: list[str] = []
    for i, row in enumerate(rows, 1):
        similarity = row["similarity"]
        source = row["source_title"]
        url = row["source_url"]
        section = row["section_title"]
        text = row["text"]
        tags = list(row["source_tags"] or [])

        header = f"**Result {i}** (relevance: {similarity:.2f}) — {source}"
        if section:
            header += f" > {section}"
        header += f"\nSource: {url}"
        if tags:
            header += f"\nTags: {', '.join(tags)}"

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
    """Configure logging and start the FastMCP server on stdio transport."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    mcp.run()


if __name__ == "__main__":
    main()
