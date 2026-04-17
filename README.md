# docforge

Forge searchable context from Confluence and git repos for AI coding assistants.

docforge crawls your team's documentation, embeds it with a local model, and serves it via MCP — giving Claude Code (and other AI assistants) searchable access to your team's knowledge.

## Quick Start

```bash
pip install docforge-cli
docforge init my-project
cd my-project
# Edit docforge.yml with your Confluence URL
# Edit sources.yml with your page IDs
# Edit .env with your credentials
docker compose up -d db
docforge init-db
docforge ingest
docforge serve
```

## Commands

| Command | Description |
|---------|-------------|
| `docforge init <name>` | Scaffold a new project with config templates |
| `docforge init-db` | Initialize the PostgreSQL database schema |
| `docforge ingest` | Crawl all sources, embed, store in PostgreSQL |
| `docforge search "<query>"` | Test search from terminal |
| `docforge serve` | Run MCP server for AI assistants |
| `docforge serve --api` | Run FastAPI search API (for hosted deployment) |
| `docforge status` | Show index stats and health |

## How It Works

1. **Configure** your Confluence URL and page IDs in `sources.yml`
2. **Ingest** crawls pages, chunks text (~500 tokens), generates vector embeddings (768-dim)
3. **Serve** exposes an MCP server that AI assistants query automatically

When an AI assistant needs cross-team context, it calls docforge's `search_documentation` MCP tool behind the scenes and gets relevant documentation chunks with source attribution.

## Architecture

```
Confluence pages ──┐
                   ├──→ docforge ingest ──→ PostgreSQL + pgvector
Git repo docs ─────┘                              │
                                    docforge serve ←┘
                                          │
                                    MCP Server ──→ AI coding assistants
```

## Deploy to Azure

For team-wide use, deploy the search API to Azure Container Apps (~$24/month):
- PostgreSQL Flexible Server with pgvector
- Container App running the FastAPI search API
- Team members use a lightweight MCP client that calls the hosted API

See `infrastructure/` for Bicep templates and `docs/deploy-azure.md` for instructions.

## Troubleshooting

### "Cannot connect to PostgreSQL"
Check that the database is running: `docker compose up -d db`. Verify `DATABASE_URL` in `.env` points to `postgresql://docforge:localdev@localhost:5432/docforge` (or your custom value).

### "HF_TOKEN required" or model download fails
The embedding model `google/embeddinggemma-300m` requires a Hugging Face token with access to the gated model. Create one at https://huggingface.co/settings/tokens, accept the model license at https://huggingface.co/google/embeddinggemma-300m, and set `HF_TOKEN=hf_...` in `.env`.

### "No results found" after ingest
Run `docforge status` to confirm sources and chunks exist. If counts are zero, check the ingest logs for per-source failures — the summary at the end lists sources that failed.

### First ingest / first container start is very slow
The first run downloads the 300M embedding model (~1.2GB) from Hugging Face. Locally, the model is cached at `~/.cache/huggingface/`. In the Docker image, it is cached at `/app/.cache/huggingface/` — **mount this as a volume** so container restarts don't re-download: `docker run -v docforge-hf-cache:/app/.cache/huggingface ...`.

### "Ingest skipped everything"
docforge skips sources whose `content_hash` matches the stored hash (no changes detected). To force re-ingest, clear the hash: `UPDATE sources SET content_hash = NULL;` then run `docforge ingest`.

## License

MIT
