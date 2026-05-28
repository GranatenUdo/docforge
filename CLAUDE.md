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

## Testing & Verification (REQUIRED before claiming a change works)

Always verify changes against the **actual user-facing surface**, not just the
nearest internal API. The cheapest mistakes have been:

1. **Retrieval / SQL changes** — run `eval_search` BOTH `--direct` and
   `--api-url <prod>` against the same ground truth. They MUST agree. If they
   diverge, an env var (Bicep deployment param) is silently overriding a
   `Settings` default — inspect with
   `az containerapp show --name <app> --query "properties.template.containers[0].env"`.
   Incident 2026-05-28: `SPARSE_WEIGHT=0.5` from bicepparam masked a 15-query
   quality gap behind a green `--direct` eval.
2. **MCP changes** — call the actual MCP tool (`search_documentation`, as
   registered in `mcp_server.py:@mcp.tool()`) on a representative query and
   confirm the expected page appears. From a Claude Code session this surfaces
   as `mcp__<server-name>__search_documentation`, where `<server-name>` is
   the user's `.claude.json` MCP-server key (e.g. `dw-docforge`). `--direct`
   eval and `curl /search` do NOT exercise the MCP path end-to-end.
3. **Deployment changes** — after `az containerapp update`, check both `/health`
   AND the user surface (MCP + `/search` via `curl`). Revision metadata
   reporting `image: v0.7.13` can be paired with stale env vars from a prior
   deploy.
4. **Bicep param changes** — any `az containerapp update --set-env-vars` is
   ephemeral. The canonical config lives in the downstream consumer's
   bicepparam file (for the CCL deployment that's
   `rag/infrastructure/docforge.bicepparam` in the dw-docforge repo). Update
   it there too, or the next Bicep deploy reverts your fix.
5. **CI changes** — push to a branch and watch CI green before claiming it
   works locally. Local pip extras and Python versions can mask CI-only
   failures. Historic example: until v0.7.11, integration CI installed only
   `[dev,entra]`, so `test_azure_auth_*` tests were silently red until the
   `[dev,azure,entra]` install line landed. Always cross-check `ci.yml`
   against your local extras.

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
