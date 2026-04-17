"""Integration test fixtures — pgvector testcontainer + schema setup.

Session-scoped container (one startup per pytest run, ~10s cold start)
with a function-scoped URL fixture that applies the schema and truncates
between tests for isolation.

All tests in this directory are auto-marked with @pytest.mark.integration.
"""

from __future__ import annotations

import pytest
from testcontainers.postgres import PostgresContainer


def pytest_collection_modifyitems(config, items):
    """Auto-mark all tests in this directory as integration."""
    for item in items:
        if "tests/integration" in str(item.fspath).replace("\\", "/"):
            item.add_marker(pytest.mark.integration)


@pytest.fixture(scope="session")
def pg_container():
    """One pgvector container for the whole test session."""
    with PostgresContainer("pgvector/pgvector:pg16") as pg:
        yield pg


@pytest.fixture
async def pg_url(pg_container):
    """Fresh schema per test; truncate between tests for isolation."""
    # driver=None gives a plain postgresql:// URL (no +psycopg2 suffix),
    # which is what asyncpg expects. Verified against testcontainers 4.14.
    url = pg_container.get_connection_url(driver=None)

    from docforge.db import close_pool, init_db

    await init_db(url)
    yield url

    import asyncpg

    conn = await asyncpg.connect(url)
    try:
        await conn.execute("TRUNCATE sources, chunks RESTART IDENTITY CASCADE")
    finally:
        await conn.close()
    await close_pool()
