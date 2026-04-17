from __future__ import annotations

import asyncpg
from pgvector.asyncpg import register_vector

_pool: asyncpg.Pool | None = None


async def get_pool(database_url: str) -> asyncpg.Pool:
    global _pool
    if _pool is None:
        _pool = await asyncpg.create_pool(
            database_url,
            min_size=1,
            max_size=5,
            init=_init_connection,
        )
    return _pool


async def _init_connection(conn: asyncpg.Connection) -> None:
    await register_vector(conn)


async def close_pool() -> None:
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
