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

For the full trust model, accepted risks, and assumptions docforge makes about its operating environment, see [`docs/threat-model.md`](docs/threat-model.md).

## Quick Start

**Prerequisites:**
- Python 3.12+
- Docker (for the local Postgres + pgvector container)
- A [Hugging Face token](https://huggingface.co/settings/tokens) with access to the gated [EmbeddingGemma-300M](https://huggingface.co/google/embeddinggemma-300m) model. Accept the model license on the model page first.

```bash
pip install docforge-cli
docforge init my-project
cd my-project
# Edit docforge.yml with your Confluence URL
# Edit sources.yml with your page IDs and local git repo paths
# Edit .env with your credentials (CONFLUENCE_API_TOKEN, HF_TOKEN, DATABASE_URL)
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

For team-wide use, deploy the search API to Azure (~$90/month at default SKUs with embedder always-on for production; ~$55/month with the default scale-to-zero embedder):

- PostgreSQL Flexible Server (Burstable B1ms, 32 GB) with pgvector.
- Container App running the FastAPI search API.
- Container App running the embedder service (EmbeddingGemma-300M, model baked into the image).
- Container Registry (Standard), Key Vault, Log Analytics, managed environment.
- Team members use a lightweight MCP client that calls the hosted API.

See [`deploy/azure/`](deploy/azure/) for Bicep templates and a full cost breakdown.

## Use a hosted instance (no local DB required)

If your team already operates a docforge deployment and you only want to *use* it from your editor (Claude Code, etc.), you don't need to clone, ingest, or run Postgres locally:

```bash
# Generic (no auth)
pip install docforge-cli
claude mcp add -s user -e DOCFORGE_API_URL=https://docforge.example.com \
  docforge -- docforge serve --remote-api $DOCFORGE_API_URL

# Static Bearer token
pip install docforge-cli
claude mcp add -s user \
  -e DOCFORGE_API_URL=https://docforge.example.com \
  -e DOCFORGE_API_TOKEN=eyJ... \
  -e DOCFORGE_AUTH=bearer \
  docforge -- docforge serve --remote-api $DOCFORGE_API_URL --auth bearer

# Entra (Azure AD)
pip install docforge-cli[azure]
az login --tenant <your-tenant-id>
claude mcp add -s user \
  -e DOCFORGE_API_URL=https://docforge.example.com \
  -e DOCFORGE_AUDIENCE=api://<app-registration-uri> \
  -e DOCFORGE_AUTH=azure \
  -e DOCFORGE_TEAM=your-team \
  docforge -- docforge serve --remote-api $DOCFORGE_API_URL --auth azure
```

With `--auth azure`, `user_name` is bound to your Entra JWT subject — you can't (and don't need to) configure it.

`DOCFORGE_TEAM` is optional but recommended for team-tag relevance boosting in search results.

## Self-hosting / forking

The embedder image bakes the EmbeddingGemma-300M model at build time,
which requires a HuggingFace access token. Forks and adopters need to:

1. Get an HF token at https://huggingface.co/settings/tokens.
2. Accept the EmbeddingGemma license at
   https://huggingface.co/google/embeddinggemma-300m.
3. Add a repo secret `HF_TOKEN` under
   `Settings → Secrets and variables → Actions`.

The CI workflow forwards the secret to BuildKit via
`--mount=type=secret,id=hf_token`; the token never enters any image
layer. If you fork this repo and run the CI workflow, it will build the
embedder image automatically on commits to `master` and PRs (without
pushing unless on `master`). To enable pushes to a registry, also add
secrets `ACR_LOGIN_SERVER`, `ACR_USERNAME`, and `ACR_PASSWORD`.

## Upgrading the embedding model

The dimension-mismatch guard in `RemoteEmbedder` makes an
embedder/search API mismatch loud (`HTTP 503` with a clear log line)
rather than silent. Upgrade procedure:

1. **Pick the new model.** Note its output dimensionality `D` (e.g.
   `768` for EmbeddingGemma, `1024` for many newer models).

2. **Update config.** Set `embedding_model: <new>` and
   `embedding_dimensions: D` in the search API's deployment config
   (Bicep parameters + Key Vault, or `docforge.yml` for self-hosters).

3. **Build the embedder image** with the new model:
   ```bash
   docker build \
     --build-arg EMBEDDING_MODEL=<new> \
     --secret id=hf_token,env=HF_TOKEN \
     -f Dockerfile.embedder \
     -t docforge-embedder:<tag> .
   ```

4. **Apply schema migration.** Add a new vector column:
   ```sql
   ALTER TABLE chunks ADD COLUMN embedding_new vector(D);
   ```
   Re-ingest to populate the new column. Until backfill completes, the
   search API serves from the old column.

5. **Cut over.** Deploy the new embedder image first, then the new
   search API. The dim-mismatch guard ensures search refuses to serve
   wrong-dim vectors.

6. **Drop the old column** after a confidence interval.

## Configuration

See `docs/` for the full configuration reference, including `docforge.yml` and `sources.yml` schemas.

## Contributing

Contributions welcome. See [`CONTRIBUTING.md`](CONTRIBUTING.md) for development setup, branch conventions, and PR expectations. Bug reports and feature requests go through [GitHub Issues](https://github.com/GranatenUdo/docforge/issues); open-ended questions and ideas live in [Discussions](https://github.com/GranatenUdo/docforge/discussions).

## Evaluation & retrieval quality

docforge ships with a retrieval-quality eval harness at [`src/docforge/scripts/eval_search.py`](src/docforge/scripts/eval_search.py). It measures recall@1, recall@k, and MRR against a ground-truth query set you maintain. The harness is designed for **drift detection** — run it after `sources.yml` changes, embedding-model updates, or ranking tweaks, and compare against your baseline. There is no absolute quality threshold; the metric magnitude depends on how closely your ground-truth queries match source titles. See [`src/docforge/scripts/README.md`](src/docforge/scripts/README.md) for details.

## FAQ

The three install-time issues new users hit most often are inline below. The
full FAQ — including "no results found", "ingest skipped everything", removing
sources, swapping embedding models, and where to file issues — lives on the
[microsite FAQ](https://GranatenUdo.github.io/docforge/faq/).

### "HF_TOKEN required" or model download fails

The embedding model `google/embeddinggemma-300m` requires a Hugging Face token with access to the gated model. Create one at https://huggingface.co/settings/tokens, accept the model license at https://huggingface.co/google/embeddinggemma-300m, and set `HF_TOKEN=hf_...` in `.env`.

### First ingest / first container start is very slow

The first run downloads the 300M embedding model (~1.2 GB) from Hugging Face. Locally, the model is cached at `~/.cache/huggingface/`. In the Docker image, it is cached at `/app/.cache/huggingface/` — **mount this as a volume** so container restarts do not re-download: `docker run -v docforge-hf-cache:/app/.cache/huggingface ...`.

### "Cannot connect to PostgreSQL"

Check that the database is running: `docker compose up -d db`. Verify `DATABASE_URL` in `.env` points to `postgresql://docforge:localdev@localhost:5432/docforge` (or your custom value).

## License

MIT. See [LICENSE](LICENSE).

## License compatibility

docforge is MIT-licensed; the default embedding model,
[EmbeddingGemma-300M](https://huggingface.co/google/embeddinggemma-300m), is
distributed under the [Gemma Terms of Use](https://ai.google.dev/gemma/terms),
which restrict harmful use and building products that compete with Gemma. Swap
to a permissively-licensed alternative via `embedding_model` in `docforge.yml`
if those constraints don't fit your use case (see
[microsite FAQ — Can I use a different embedding model?](https://GranatenUdo.github.io/docforge/faq/#can-i-use-a-different-embedding-model)).

## Credits

docforge stands on open shoulders:

- [EmbeddingGemma-300M](https://huggingface.co/google/embeddinggemma-300m) — open-weights embedding model under the Gemma license.
- [pgvector](https://github.com/pgvector/pgvector) — vector similarity for Postgres.
- [FastMCP](https://github.com/PrefectHQ/fastmcp) — MCP server framework.
- [FastAPI](https://fastapi.tiangolo.com/), [Typer](https://typer.tiangolo.com/), [asyncpg](https://magicstack.github.io/asyncpg/), [sentence-transformers](https://www.sbert.net/) — core infrastructure.
