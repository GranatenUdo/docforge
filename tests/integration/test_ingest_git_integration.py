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
async def test_end_to_end_ingest_and_search(tmp_path, pg_url, fake_embedder):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "README.md").write_text(
        "# Project\n\nThis project does orgs.\n\n## Details\n\nPlatform team owns it."
    )
    (repo / "CLAUDE.md").write_text("# Claude Guide\n\nUse docforge for cross-team knowledge.")

    sources_file = tmp_path / "sources.yml"
    sources_file.write_text(
        "sources:\n"
        "  - type: git_repo\n"
        f'    repo_path: "{repo.as_posix()}"\n'
        '    include_patterns: ["README.md", "CLAUDE.md"]\n'
        '    title: "TestRepo"\n'
        "    tags: [platform, cloud]\n"
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

        tags_rows = await conn.fetch("SELECT tags FROM sources")
        for row in tags_rows:
            assert row["tags"] == ["platform", "cloud"]

        query_vec = np.zeros(1024, dtype=np.float32)
        query_vec[1023] = 0.001
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


@pytest.mark.asyncio
async def test_ingest_populates_chunk_title_from_source(tmp_path, pg_url, fake_embedder):
    """Production ingest must populate chunks.title at INSERT.

    Migration 008 backfills existing chunks; this test guards the
    forward path so newly ingested chunks don't end up with the
    DEFAULT '' title (which would defeat the title-weighted text_tsv
    introduced in v0.6.0).

    Resets the module-level asyncpg pool first because pytest-asyncio
    creates a fresh event loop per test. The pool cached by an earlier
    test in this file (`test_end_to_end_ingest_and_search`) was bound
    to that loop, so reusing it from this test's loop fails with
    "Event loop is closed" / "another operation is in progress"."""
    from docforge import db as db_module

    db_module._pool = None  # force a fresh pool in this test's event loop

    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "README.md").write_text(
        "# Project\n\nThis project does orgs.\n\n## Details\n\nPlatform team owns it."
    )
    (repo / "CLAUDE.md").write_text("# Claude Guide\n\nUse docforge for cross-team knowledge.")

    sources_file = tmp_path / "sources.yml"
    sources_file.write_text(
        "sources:\n"
        "  - type: git_repo\n"
        f'    repo_path: "{repo.as_posix()}"\n'
        '    include_patterns: ["README.md", "CLAUDE.md"]\n'
        '    title: "TitleProbeRepo"\n'
        "    tags: [platform]\n"
    )

    settings = Settings(sources_file=str(sources_file), database_url=pg_url)

    await ingest_all(settings)

    conn = await asyncpg.connect(pg_url)
    try:
        rows = await conn.fetch(
            """
            SELECT c.title AS chunk_title, s.title AS source_title
            FROM chunks c JOIN sources s ON c.source_id = s.id
            """
        )
        assert len(rows) > 0, "expected at least one chunk after ingest"
        for row in rows:
            assert row["chunk_title"] != "", (
                f"chunks.title is empty for source {row['source_title']!r} — "
                "ingest path is not populating the title column"
            )
            # For git ingests, chunk_title is the relative file path
            # (e.g., 'README.md'), and source_title is 'TitleProbeRepo/README.md'.
            # Both must be non-empty; chunk_title is the more-specific file title.
            assert row["chunk_title"] in row["source_title"], (
                f"chunk_title {row['chunk_title']!r} should be a substring of "
                f"source_title {row['source_title']!r} (git path: file.title in "
                f"f'{{source.title}}/{{file.title}}')"
            )
    finally:
        await conn.close()
