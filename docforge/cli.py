"""docforge CLI — forge searchable context from documentation."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

import typer

app = typer.Typer(
    help="Forge searchable context from Confluence and git repos for AI coding assistants.",
)


@app.command()
def init(name: str = typer.Argument(help="Project directory name")):
    """Scaffold a new docforge project with config templates."""
    target = Path(name)
    if target.exists():
        typer.echo(f"Error: directory '{name}' already exists.", err=True)
        raise typer.Exit(1)

    import importlib.resources as resources

    templates_dir = resources.files("docforge") / "templates"
    target.mkdir(parents=True)

    for item in templates_dir.iterdir():
        dest = target / item.name
        if hasattr(item, "read_bytes"):
            dest.write_bytes(item.read_bytes())
            typer.echo(f"  Created {dest}")

    typer.echo(f"\nProject scaffolded in {target}/")
    typer.echo("Next steps:")
    typer.echo(f"  cd {name}")
    typer.echo("  # Edit docforge.yml with your Confluence URL")
    typer.echo("  # Edit sources.yml with your page IDs")
    typer.echo("  # Edit .env with your credentials")
    typer.echo("  docker compose up -d db")
    typer.echo("  docforge init-db")
    typer.echo("  docforge ingest")
    typer.echo("  docforge serve")


@app.command(name="init-db")
def init_db():
    """Initialize the database schema."""
    asyncio.run(_init_db())


@app.command()
def ingest():
    """Crawl all sources, embed, and store in PostgreSQL."""
    _setup_logging()
    asyncio.run(_ingest())


@app.command()
def search(
    query: str = typer.Argument(help="Search query"),
    limit: int = typer.Option(5, help="Max results"),
):
    """Search the documentation index."""
    _setup_logging()
    asyncio.run(_search(query, limit))


@app.command()
def serve(api: bool = typer.Option(False, help="Run FastAPI search API instead of MCP")):
    """Run the MCP server (or FastAPI API with --api)."""
    _setup_logging()
    if api:
        import uvicorn

        from docforge.api import app as fastapi_app

        uvicorn.run(fastapi_app, host="0.0.0.0", port=8000)
    else:
        from docforge.mcp_server import mcp

        mcp.run()


@app.command()
def status():
    """Show index statistics and health."""
    asyncio.run(_status())


def _setup_logging():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


async def _init_db():
    from docforge.config import Settings
    from docforge.db import init_db as do_init_db

    settings = Settings()
    typer.echo(f"Initializing database: {settings.database_url.split('@')[-1]}")
    try:
        await do_init_db(settings.database_url)
    except OSError as e:
        typer.echo(
            f"Error: Cannot connect to database. Is PostgreSQL running?\n{e}",
            err=True,
        )
        raise typer.Exit(1)
    except Exception as e:
        typer.echo(f"Error initializing database: {e}", err=True)
        raise typer.Exit(1)
    typer.echo("Database initialized successfully.")


async def _ingest():
    from docforge.config import Settings
    from docforge.db import close_pool
    from docforge.ingest import ingest_all

    settings = Settings()
    try:
        await ingest_all(settings)
    except OSError as e:
        typer.echo(
            f"Error: Cannot connect to database. Is PostgreSQL running?\n{e}",
            err=True,
        )
        raise typer.Exit(1)
    except RuntimeError as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(1)
    except Exception as e:
        typer.echo(f"Error during ingest: {e}", err=True)
        raise typer.Exit(1)
    finally:
        await close_pool()


async def _search(query: str, limit: int):
    import numpy as np

    from docforge.config import Settings
    from docforge.db import close_pool, get_pool
    from docforge.processors.embedder import Embedder

    settings = Settings()
    try:
        embedder = Embedder(
            settings.embedding_model, hf_token=settings.hf_token.get_secret_value()
        )
    except RuntimeError as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(1)

    query_vector = embedder.embed_query(query)

    try:
        pool = await get_pool(settings.database_url)
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT c.text, c.section_title, s.title AS source_title,
                       1 - (c.embedding <=> $1::vector) AS similarity
                FROM chunks c JOIN sources s ON c.source_id = s.id
                WHERE s.status = 'active'
                ORDER BY c.embedding <=> $1::vector LIMIT $2
                """,
                np.array(query_vector, dtype=np.float32),
                limit,
            )
    except OSError as e:
        typer.echo(
            f"Error: Cannot connect to database. Is PostgreSQL running?\n{e}",
            err=True,
        )
        raise typer.Exit(1)
    finally:
        await close_pool()

    if not rows:
        typer.echo("No results found.")
        return

    for i, row in enumerate(rows, 1):
        sim = row["similarity"]
        src = row["source_title"]
        sec = row["section_title"] or ""
        typer.echo(f"\n--- Result {i} (relevance: {sim:.2f}) --- {src}")
        if sec:
            typer.echo(f"Section: {sec}")
        typer.echo(row["text"][:500])


async def _status():
    from docforge.config import Settings
    from docforge.db import close_pool, get_pool

    settings = Settings()
    try:
        pool = await get_pool(settings.database_url)
        async with pool.acquire() as conn:
            sources = await conn.fetchval("SELECT count(*) FROM sources")
            chunks = await conn.fetchval("SELECT count(*) FROM chunks")
        typer.echo(f"Sources: {sources}")
        typer.echo(f"Chunks:  {chunks}")
        typer.echo(f"DB:      {settings.database_url.split('@')[-1]}")
    except Exception as e:
        typer.echo(f"Error connecting to database: {e}", err=True)
    finally:
        await close_pool()
