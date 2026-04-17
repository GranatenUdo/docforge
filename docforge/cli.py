from __future__ import annotations

import argparse
import asyncio
import logging


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="knowledge-hub", description="Documentation search service"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("init-db", help="Initialize database schema")
    subparsers.add_parser("ingest", help="Crawl sources and update the search index")

    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    if args.command == "init-db":
        asyncio.run(_init_db())
    elif args.command == "ingest":
        asyncio.run(_ingest())


async def _init_db() -> None:
    from docforge.config import Settings
    from docforge.db import init_db

    settings = Settings()
    print(f"Initializing database: {settings.database_url.split('@')[-1]}")
    await init_db(settings.database_url)
    print("Database initialized successfully.")


async def _ingest() -> None:
    from docforge.config import Settings
    from docforge.db import close_pool
    from docforge.ingest import ingest_all

    settings = Settings()
    try:
        await ingest_all(settings)
    finally:
        await close_pool()


if __name__ == "__main__":
    main()
