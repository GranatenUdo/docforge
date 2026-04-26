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
def ingest(
    purge_orphans: bool = typer.Option(
        False,
        "--purge-orphans",
        help="Report DB sources absent from sources.yml. Dry-run; use --confirm to delete.",
    ),
    confirm: bool = typer.Option(
        False,
        "--confirm",
        help="Required alongside --purge-orphans to actually delete orphans.",
    ),
):
    """Crawl all sources, embed, and store in PostgreSQL."""
    _setup_logging()
    if confirm and not purge_orphans:
        typer.echo("Error: --confirm only applies to --purge-orphans", err=True)
        raise typer.Exit(1)
    asyncio.run(_ingest(purge_orphans=purge_orphans, confirm=confirm))


@app.command()
def search(
    query: str = typer.Argument(help="Search query"),
    user_name: str = typer.Option(
        None,
        "--user",
        help="Your name (required; falls back to default_user_name setting)",
    ),
    team_name: str = typer.Option(
        None,
        "--team",
        help="Your team tag (required; falls back to default_team_name setting)",
    ),
    area_name: str = typer.Option(
        None,
        "--area",
        help="Your area tag (optional; falls back to default_area_name setting)",
    ),
    limit: int = typer.Option(5, help="Max results"),
):
    """Search the documentation index."""
    _setup_logging()
    from docforge.config import Settings

    settings = Settings()
    resolved_user = user_name or settings.default_user_name
    resolved_team = team_name or settings.default_team_name
    resolved_area = area_name or (settings.default_area_name or None) or None

    if not resolved_user:
        typer.echo(
            "Error: --user is required (or set default_user_name in docforge.yml).",
            err=True,
        )
        raise typer.Exit(1)
    if not resolved_team:
        typer.echo(
            "Error: --team is required (or set default_team_name in docforge.yml).",
            err=True,
        )
        raise typer.Exit(1)

    asyncio.run(_search(query, resolved_user, resolved_team, resolved_area, limit))


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


@app.command(name="lint-docs")
def lint_docs(
    repo_path: Path = typer.Argument(..., help="Path to the repo root to lint"),
) -> None:
    """Lint a repo's README + CLAUDE.md + docs/ for banned-content rules."""
    from docforge.lint import format_report, lint_repo

    if not repo_path.is_dir():
        typer.echo(f"Error: {repo_path} is not a directory", err=True)
        raise typer.Exit(1)

    report = lint_repo(repo_path)
    typer.echo(format_report(report, repo_path))
    if report.findings:
        raise typer.Exit(1)


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


async def _ingest(purge_orphans: bool = False, confirm: bool = False):
    from docforge.config import Settings
    from docforge.db import close_pool
    from docforge.ingest import ingest_all

    settings = Settings()
    try:
        await ingest_all(settings, purge_orphans=purge_orphans, confirm=confirm)
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


async def _search(query: str, user_name: str, team_name: str, area_name: str | None, limit: int):
    import numpy as np

    from docforge.config import Settings
    from docforge.db import close_pool, get_pool
    from docforge.processors.embedder import Embedder
    from docforge.query_log import log_query

    settings = Settings()
    try:
        embedder = Embedder.from_settings(settings)
    except RuntimeError as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(1)

    query_vector = embedder.embed_query(query)
    user_tags = [team_name] + ([area_name] if area_name else [])

    try:
        pool = await get_pool(
            settings.database_url,
            min_size=settings.pool_min_size,
            max_size=settings.pool_max_size,
        )
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT c.text, c.section_title, s.title AS source_title,
                       s.tags AS source_tags,
                       1 - (c.embedding <=> $1::vector) AS similarity,
                       (1 - (c.embedding <=> $1::vector)) *
                         (1
                          + $2::float * cardinality(
                              ARRAY(SELECT unnest(s.tags) INTERSECT SELECT unnest($3::text[]))
                            )
                          + $4::float * (CASE WHEN 'org' = ANY(s.tags) THEN 1 ELSE 0 END)
                         ) AS boosted_score
                FROM chunks c JOIN sources s ON c.source_id = s.id
                WHERE s.status = 'active'
                ORDER BY boosted_score DESC LIMIT $5
                """,
                np.array(query_vector, dtype=np.float32),
                settings.tag_match_weight,
                user_tags,
                settings.org_tag_weight,
                limit,
            )
        await log_query(pool, user_name, team_name, area_name, query, len(rows))
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
        tags = list(row["source_tags"] or [])
        typer.echo(f"\n--- Result {i} (relevance: {sim:.2f}) --- {src}")
        if sec:
            typer.echo(f"Section: {sec}")
        if tags:
            typer.echo(f"Tags: {', '.join(tags)}")
        typer.echo(row["text"][:500])


async def _status():
    from docforge.config import Settings
    from docforge.db import close_pool, get_pool

    settings = Settings()
    try:
        pool = await get_pool(
            settings.database_url,
            min_size=settings.pool_min_size,
            max_size=settings.pool_max_size,
        )
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
