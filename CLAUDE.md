# CLAUDE.md

This file provides guidance to Claude Code when working in this repository.

## Project Overview

docforge is a CLI tool that forges searchable context from Confluence and git repos for AI coding assistants. It crawls documentation, chunks and embeds the content, stores it in PostgreSQL with pgvector, and serves it via MCP server.

In production the engine runs as three services: the **search-api** plus two GPU Container App sidecars — an **embedder** sidecar (Qwen3-Embedding-4B) and a **reranker** sidecar (BAAI/bge-reranker-v2-m3). Retrieval is hybrid-then-cross-encoder-rerank: the hybrid pool (dense pgvector + sparse BM25 + RRF + tag boost) produces candidates, then the cross-encoder reranker re-scores the top `rerank_top_n` (default 50) of them.

## Tech Stack

- **Language**: Python 3.13+
- **CLI**: Typer
- **API**: FastAPI (for hosted deployment)
- **Database**: PostgreSQL + pgvector
- **Embeddings**: Qwen3-Embedding-4B (1024-dim, Apache 2.0), served by a GPU Container App sidecar (Tesla-T4)
- **Reranker**: BAAI/bge-reranker-v2-m3 (xlm-roberta cross-encoder via sentence-transformers `CrossEncoder`), served by its own GPU Container App sidecar (Tesla-T4, `gpu-nc8as-t4`, built from `Dockerfile.reranker`, kept warm at `minReplicas=1`); runs fp32 (the fp16 `.half()` cast breaks `CrossEncoder.predict` in sentence-transformers 5.x)
- **MCP**: FastMCP
- **Config**: pydantic-settings + YAML

## Building and Running

```bash
python -m venv .venv
# Pick ONE of the following based on your OS — do NOT run both:
source .venv/bin/activate   # macOS/Linux
.venv\Scripts\activate      # Windows  (Git-Bash users: source .venv/Scripts/activate; PowerShell users: .venv\Scripts\Activate.ps1)
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
   quality gap behind a green `--direct` eval. Ranking changes must also confirm
   the **reranker path**: verify `RERANK_ENABLED` and `RERANKER_URL` are set on
   the deployed search-api, and smoke the reranker sidecar's `/rerank` endpoint
   (not just `/health`) on a representative query — the model loads so `/health`
   passes even when `/rerank` 500s (e.g. the fp16 `.half()` regression).
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
    reranker_api.py     # FastAPI cross-encoder reranker (GPU sidecar)
    mcp_server.py       # MCP tools for AI assistants
    ingest.py           # Crawl → parse → chunk → embed → store
    sources.py          # Load sources from YAML
    crawlers/           # Confluence + git crawlers
    processors/         # Parser, chunker, embedder, reranker
    templates/          # Files copied during docforge init
```
