"""asyncpg connection pool + pgvector registration.

Module-level `_pool` is created lazily on first `get_pool()` call and
shared across all callers. `init_db()` applies the packaged schema.sql
and any migration scripts.
"""

from __future__ import annotations

import asyncpg
from pgvector.asyncpg import register_vector

_pool: asyncpg.Pool | None = None


async def get_pool(
    database_url: str,
    *,
    min_size: int = 5,  # keep in sync with Settings.pool_min_size
    max_size: int = 25,  # keep in sync with Settings.pool_max_size
) -> asyncpg.Pool:
    """Return the module-level asyncpg pool, creating it on first call.

    Note: the cache is first-call-wins. min_size/max_size on subsequent calls
    are ignored — these helpers serve single-process callers (mcp_server,
    cli, ingest). The FastAPI app creates its pool directly inside the
    lifespan and does not go through this helper.
    """
    global _pool
    if _pool is None:
        _pool = await asyncpg.create_pool(
            database_url,
            min_size=min_size,
            max_size=max_size,
            init=_init_connection,
        )
    return _pool


async def _init_connection(conn: asyncpg.Connection) -> None:
    await register_vector(conn)


async def close_pool() -> None:
    """Close and clear the module-level asyncpg pool if it exists."""
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None


async def init_db(database_url: str) -> None:
    """Apply schema and migrations from the docforge package."""
    import importlib.resources as resources

    sql_dir = resources.files("docforge") / "sql"
    schema_sql = (sql_dir / "schema.sql").read_text(encoding="utf-8")

    conn = await asyncpg.connect(database_url)
    try:
        await conn.execute(schema_sql)

        migrations_dir = sql_dir / "migrations"
        for migration in sorted(migrations_dir.iterdir()):
            if str(migration).endswith(".sql"):
                await conn.execute(migration.read_text(encoding="utf-8"))
    finally:
        await conn.close()
