# CLAUDE.md

This file provides guidance to Claude Code when working in this repository.

## Project Overview

docforge is a CLI tool that forges searchable context from Confluence and git repos for AI coding assistants. It crawls documentation, chunks and embeds the content, stores it in PostgreSQL with pgvector, and serves it via MCP server.

## Tech Stack

- **Language**: Python 3.13+
- **CLI**: Typer
- **API**: FastAPI (for hosted deployment)
- **Database**: PostgreSQL + pgvector
- **Embeddings**: Qwen3-Embedding-4B (1024-dim, Apache 2.0)
- **MCP**: FastMCP
- **Config**: pydantic-settings + YAML

## Building and Running

```bash
python -m venv .venv
source .venv/bin/activate   # Linux/macOS
.venv/Scripts/activate      # Windows
pip install -e ".[dev]"
```

## Commands

```bash
docforge init my-project      # Scaffold project
docforge init-db              # Apply schema to PostgreSQL
docforge ingest               # Crawl + embed + store
docforge search "query"       # Test search
docforge serve                # Run MCP server
docforge serve --api          # Run FastAPI search API
docforge status               # Show index stats
```

## Coding Conventions

- Pydantic v2 for data models
- pydantic-settings for config (.env + docforge.yml)
- Async by default (async def for endpoints and DB ops)
- httpx for HTTP calls
- Type hints on all function signatures
- ruff for formatting and linting
- pytest + pytest-asyncio for tests

## Package Structure

```
docforge/
    cli.py              # Typer CLI entry point
    config.py           # Settings from docforge.yml + .env
    db.py               # asyncpg pool + pgvector
    api.py              # FastAPI search API
    mcp_server.py       # MCP tools for AI assistants
    ingest.py           # Crawl → parse → chunk → embed → store
    sources.py          # Load sources from YAML
    crawlers/           # Confluence + git crawlers
    processors/         # Parser, chunker, embedder
    templates/          # Files copied during docforge init
```
