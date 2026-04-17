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

## License

MIT
