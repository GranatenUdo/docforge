# docforge

**The self-hosted context engine for AI coding assistants.**

Point docforge at your Confluence spaces and local git repositories. It indexes, embeds, and serves them over MCP — so Claude Code, Cursor, Copilot, and any assistant that speaks MCP can search your team's knowledge without your data leaving your infrastructure.

docforge doesn't replace your AI assistant. It feeds it — turning Claude Code, Cursor, Copilot, and anything else that speaks MCP into tools that actually know your team's docs and code.

[![CI](https://github.com/GranatenUdo/docforge/actions/workflows/ci.yml/badge.svg)](https://github.com/GranatenUdo/docforge/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/docforge-cli.svg)](https://pypi.org/project/docforge-cli/)
[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)

## Why docforge

| Tool | Self-hosted | Integration | Confluence + code | Footprint | Complements AI assistants? |
|---|---|---|---|---|---|
| **docforge** | ✓ | MCP server | ✓ (Confluence + local git) | Minimal (PG + 1 container) | ✓ (any MCP client) |
| [Atlassian Rovo MCP](https://www.atlassian.com/blog/announcements/atlassian-rovo-mcp-ga) | ✗ (Cloud-only) | MCP server | Confluence only (Cloud) | SaaS | ✓ |
| [zilliztech/claude-context](https://github.com/zilliztech/claude-context) | ✓ | MCP server | Code only | Minimal | ✓ |
| [Onyx](https://github.com/onyx-dot-app/onyx) | ✓ | MCP + chat UI | ✓ (50+ connectors) | Heavy (Standard) / Minimal (Lite) | ✓ (+ its own UI) |
| Cursor codebase index + @Docs | ✗ | Proprietary | Code + public web docs | SaaS | — (built into Cursor only) |
| [Copilot Spaces](https://github.com/orgs/community/discussions/180894) | ✗ | Proprietary (MCP for actions) | Code + attachments | SaaS | — (built into Copilot only) |
| [Sourcegraph Cody](https://sourcegraph.com/docs/cody/enterprise/features) | ✓ (Enterprise) | OpenCtx / MCP | ✓ (via OpenCtx) | Heavy (Sourcegraph platform) | — (built into Cody only) |
| LangChain / LlamaIndex DIY | ✓ | Whatever you build | You wire it | Depends | Depends |

docforge is the narrow, focused option in this landscape: minimal footprint, MCP-native so it works with every assistant, and combines Confluence + code out of the box. It doesn't compete on connector count (Onyx wins there), visual UX (Cursor and Cody win), or SaaS convenience (Rovo). It competes on being **small, legible, vendor-neutral, and self-hosted** — four properties no commercial option offers together.

### ✅ When docforge fits

- You run Confluence Data Center/Server, or you want to self-host.
- Your team uses MCP-capable assistants (Claude Code, Cursor with MCP, Copilot with MCP, etc.).
- You want Confluence + git repos indexed together with one tool.
- Operational simplicity matters — one Postgres, one container, MIT-licensed code you can audit in an afternoon.

### ❌ When docforge is the wrong choice

- You need 50+ connectors (Slack, Jira, Gmail, Drive, Notion) → use **[Onyx](https://github.com/onyx-dot-app/onyx)** or **[Glean](https://www.glean.com/)**.
- You need per-document ACLs enforced at query time → not yet supported; use **Onyx**.
- You need a chat UI for non-developers → docforge has no UI; use **Onyx**, **Glean**, or **Cody**.
- You're on Atlassian Cloud and happy with SaaS → **[Atlassian Rovo MCP](https://www.atlassian.com/blog/announcements/atlassian-rovo-mcp-ga)** is free and official.
- You need SSO / SCIM / RBAC → out of scope; docforge authenticates but doesn't authorize per-resource.
- Your corpus is very large (>100K pages/chunks) → dense-only retrieval without hybrid starts to degrade; on the [roadmap](ROADMAP.md).
- You need near-real-time updates → ingest is batch; no webhook-driven continuous sync yet.
- You need multilingual search evaluated → EmbeddingGemma is multilingual, but docforge has no eval coverage on non-English corpora yet.

## Quick Start

```bash
pip install docforge-cli
docforge init my-project
cd my-project
# Edit docforge.yml with your Confluence URL
# Edit sources.yml with your page IDs and local git repo paths
# Edit .env with your credentials
docker compose up -d db
docforge init-db
docforge ingest
docforge serve
```

**Note:** The git crawler indexes **local filesystem paths** — docforge does not clone GitHub URLs. Clone first, then point docforge at the checkout path in `sources.yml`.

## How It Works

1. **Configure** your Confluence URL, page IDs, and local git repo paths in `sources.yml`.
2. **Ingest** crawls pages and files, chunks text (~500 tokens), generates vector embeddings (768-dim).
3. **Serve** exposes an MCP server that AI assistants query automatically.

When an AI assistant needs cross-team context, it calls docforge's `search_documentation` MCP tool behind the scenes and gets relevant documentation chunks with source attribution.

### Architecture

![docforge architecture: Confluence and local git repos flow through docforge ingest into Postgres with pgvector, then docforge serve exposes an MCP server consumed by Claude Code, Cursor, and Copilot](docs/assets/architecture.svg)

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

## Deploy to your infrastructure

For team-wide use, deploy the search API to Azure Container Apps (~$24/month):

- PostgreSQL Flexible Server with pgvector.
- Container App running the FastAPI search API.
- Team members use a lightweight MCP client that calls the hosted API.

See `infrastructure/` for Bicep templates and `docs/deploy-azure.md` for instructions.

## Configuration

See `docs/` for the full configuration reference, including `docforge.yml` and `sources.yml` schemas.

## Contributing

Contributions welcome. See [`CONTRIBUTING.md`](CONTRIBUTING.md) for development setup, branch conventions, and PR expectations. Bug reports and feature requests go through [GitHub Issues](https://github.com/GranatenUdo/docforge/issues); open-ended questions and ideas live in [Discussions](https://github.com/GranatenUdo/docforge/discussions).

## Evaluation & retrieval quality

docforge ships with a retrieval-quality eval harness at [`docforge/scripts/eval_search.py`](docforge/scripts/eval_search.py). It measures recall@1, recall@k, and MRR against a ground-truth query set you maintain. The harness is designed for **drift detection** — run it after `sources.yml` changes, embedding-model updates, or ranking tweaks, and compare against your baseline. There is no absolute quality threshold; the metric magnitude depends on how closely your ground-truth queries match source titles. See [`docforge/scripts/README.md`](docforge/scripts/README.md) for details.

## FAQ

### "Cannot connect to PostgreSQL"

Check that the database is running: `docker compose up -d db`. Verify `DATABASE_URL` in `.env` points to `postgresql://docforge:localdev@localhost:5432/docforge` (or your custom value).

### "HF_TOKEN required" or model download fails

The embedding model `google/embeddinggemma-300m` requires a Hugging Face token with access to the gated model. Create one at https://huggingface.co/settings/tokens, accept the model license at https://huggingface.co/google/embeddinggemma-300m, and set `HF_TOKEN=hf_...` in `.env`.

### "No results found" after ingest

Run `docforge status` to confirm sources and chunks exist. If counts are zero, check the ingest logs for per-source failures — the summary at the end lists sources that failed.

### First ingest / first container start is very slow

The first run downloads the 300M embedding model (~1.2 GB) from Hugging Face. Locally, the model is cached at `~/.cache/huggingface/`. In the Docker image, it is cached at `/app/.cache/huggingface/` — **mount this as a volume** so container restarts do not re-download: `docker run -v docforge-hf-cache:/app/.cache/huggingface ...`.

### "Ingest skipped everything"

docforge skips sources whose `content_hash` matches the stored hash (no changes detected). To force re-ingest, clear the hash: `UPDATE sources SET content_hash = NULL;` then run `docforge ingest`.

## License

MIT. See [LICENSE](LICENSE).

## Credits

docforge stands on open shoulders:

- [EmbeddingGemma-300M](https://huggingface.co/google/embeddinggemma-300m) — Apache 2.0 embedding model.
- [pgvector](https://github.com/pgvector/pgvector) — vector similarity for Postgres.
- [FastMCP](https://github.com/PrefectHQ/fastmcp) — MCP server framework.
- [FastAPI](https://fastapi.tiangolo.com/), [Typer](https://typer.tiangolo.com/), [asyncpg](https://magicstack.github.io/asyncpg/), [sentence-transformers](https://www.sbert.net/) — core infrastructure.
