---
title: Install
description: Five-minute quick start for docforge.
---

## Prerequisites

- Python 3.12+
- Docker (for the local Postgres + pgvector container)
- A [Hugging Face token](https://huggingface.co/settings/tokens) with access to the gated [EmbeddingGemma-300M](https://huggingface.co/google/embeddinggemma-300m) model

## Install and initialize

```bash
pip install docforge-cli
docforge init my-project
cd my-project
```

## Configure

Edit the three files the scaffolder drops in:

- `docforge.yml` — your Confluence base URL and embedding settings.
- `sources.yml` — the Confluence pages and local git repo paths to index.
- `.env` — credentials (`CONFLUENCE_EMAIL`, `CONFLUENCE_API_TOKEN`, `HF_TOKEN`, `DATABASE_URL`).

:::note
The git crawler indexes **local filesystem paths** — docforge does not clone GitHub URLs. Clone the repo first, then point docforge at the checkout path in `sources.yml`.
:::

## Bring up the database

```bash
docker compose up -d db
docforge init-db
```

## Ingest your sources

```bash
docforge ingest
```

First ingest downloads the ~1.2 GB EmbeddingGemma model into `~/.cache/huggingface/`. Subsequent runs are fast — `content_hash` deduplication skips unchanged sources.

## Serve to your AI assistant

```bash
docforge serve       # MCP server on stdio
docforge serve --api # FastAPI search API instead
```

Point your MCP-capable assistant (Claude Code, Cursor, Copilot) at the running server. The `search_documentation` tool is discovered automatically.

## Verify

```bash
docforge status
docforge search "how do we handle retries"
```

`status` shows indexed source + chunk counts. `search` runs a test query against the index and prints top results with source attribution.

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

:::note
With `--auth azure`, `user_name` is bound to your Entra JWT subject — you can't (and don't need to) configure it.

`DOCFORGE_TEAM` is optional but recommended for team-tag relevance boosting in search results.
:::
