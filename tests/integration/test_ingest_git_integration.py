"""End-to-end integration: ingest a git repo and query the DB like the API does.

Uses the FakeEmbedder from tests/conftest.py so we don't need to load the
real 300M model. This exercises the git crawler + parser + chunker + DB
insert path against a real pgvector instance.
"""

from __future__ import annotations

import asyncpg
import numpy as np
import pytest
from pgvector.asyncpg import register_vector

from docforge.config import Settings
from docforge.ingest import ingest_all


@pytest.mark.asyncio
async def test_end_to_end_ingest_and_search(
    tmp_path, pg_url, fake_embedder
):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "README.md").write_text(
        "# Project\n\nThis project does orgs.\n\n## Details\n\nPlatform team owns it."
    )
    (repo / "CLAUDE.md").write_text(
        "# Claude Guide\n\nUse docforge for cross-team knowledge."
    )

    sources_file = tmp_path / "sources.yml"
    sources_file.write_text(
        "sources:\n"
        "  - type: git_repo\n"
        f'    repo_path: "{repo.as_posix()}"\n'
        "    include_patterns: [\"README.md\", \"CLAUDE.md\"]\n"
        "    title: \"TestRepo\"\n"
    )

    settings = Settings(sources_file=str(sources_file), database_url=pg_url)

    await ingest_all(settings)

    conn = await asyncpg.connect(pg_url)
    try:
        await register_vector(conn)

        source_count = await conn.fetchval("SELECT count(*) FROM sources")
        chunk_count = await conn.fetchval("SELECT count(*) FROM chunks")
        assert source_count == 2
        assert chunk_count >= 2

        query_vec = np.zeros(768, dtype=np.float32)
        query_vec[767] = 0.001
        rows = await conn.fetch(
            """
            SELECT c.text, s.title AS source_title,
                   1 - (c.embedding <=> $1::vector) AS similarity
            FROM chunks c JOIN sources s ON c.source_id = s.id
            WHERE s.status = 'active'
            ORDER BY c.embedding <=> $1::vector
            LIMIT 5
            """,
            query_vec,
        )
        assert len(rows) >= 2
        for row in rows:
            assert row["source_title"].startswith("TestRepo")
    finally:
        await conn.close()
