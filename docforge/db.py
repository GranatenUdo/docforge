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


async def init_db(database_url: str, schema_path: str = "schema.sql") -> None:
    """Apply schema.sql and any migrations to the database."""
    from pathlib import Path

    conn = await asyncpg.connect(database_url)
    try:
        with open(schema_path) as f:
            await conn.execute(f.read())

        migrations_dir = Path(schema_path).parent / "migrations"
        if migrations_dir.is_dir():
            for migration in sorted(migrations_dir.glob("*.sql")):
                with open(migration) as f:
                    await conn.execute(f.read())
    finally:
        await conn.close()
