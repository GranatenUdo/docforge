"""Integration test fixtures — pgvector testcontainer + schema setup.

Container, connection URL, and schema are all session-scoped so the setup
cost (~5s) happens once per pytest run. Per-test isolation is provided by
truncating the tables between tests in `pg_url`.

All tests in this directory are auto-marked with @pytest.mark.integration.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import asyncpg
import pytest
import pytest_asyncio
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


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def _pg_url_session(pg_container):
    """Session-scoped URL with schema applied once.

    The module-level asyncpg pool is not closed here. Its owning event loop
    is the per-test loop (long dead by the time session teardown runs), so
    closing it would fail. The container tears down on session exit and the
    OS reclaims the sockets.
    """
    url = pg_container.get_connection_url(driver=None)

    from docforge.db import init_db

    await init_db(url)
    yield url


@pytest.fixture
async def pg_url(_pg_url_session):
    """Per-test URL: truncate tables so tests are isolated."""
    url = _pg_url_session
    conn = await asyncpg.connect(url)
    try:
        await conn.execute("TRUNCATE sources, chunks RESTART IDENTITY CASCADE")
    finally:
        await conn.close()
    yield url
