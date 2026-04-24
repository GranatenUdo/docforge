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
