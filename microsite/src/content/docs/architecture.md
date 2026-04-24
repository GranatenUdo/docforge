---
title: Architecture
description: How docforge crawls, embeds, stores, and serves your team's context.
---

![docforge architecture: Confluence and local git repos flow through docforge ingest into Postgres with pgvector, then docforge serve exposes an MCP server consumed by Claude Code, Cursor, and Copilot](/docforge/assets/architecture.svg)

## The data flow

### 1. Sources

docforge ingests from two source types:

- **Confluence spaces** via the REST API v2. Pages are fetched by ID (configured in `sources.yml`), authenticated with an email + API token. Content is pulled as Confluence storage-format HTML.
- **Local git repositories** on disk. The crawler matches configured glob patterns (default: `README.md`, `CLAUDE.md`, `docs/**/*.md`). It does not clone remote URLs — clone first, then point docforge at the checkout.

Each source gets a stable identifier (`confluence_page_id` or file path) and a SHA-256 `content_hash` computed from the raw content.

### 2. Ingest — `docforge ingest`

1. **Deduplicate.** Compare `content_hash` against what's stored. Matching hashes skip re-processing.
2. **Parse.** BeautifulSoup splits HTML into semantic sections (`<h1>`, `<h2>`, paragraphs, code blocks). Confluence macros are handled where meaningful.
3. **Chunk.** Token-aware splitter (default 500 tokens). Respects section boundaries; splits paragraphs only when a section exceeds the limit. Section titles are prepended to each chunk for context.
4. **Embed.** Sentence-transformers loads [EmbeddingGemma-300M](https://huggingface.co/google/embeddinggemma-300m) (Gemma license, 768-dim). Falls back to `all-MiniLM-L6-v2` (384-dim) if the primary load fails.
5. **Store.** `sources` (metadata + hash) and `chunks` (text + embedding + HNSW index) tables in Postgres. `ON DELETE CASCADE` keeps `chunks` consistent with `sources`.

Per-source errors are isolated: one bad Confluence page does not abort the run; a summary lists failures at the end.

### 3. Storage — Postgres + pgvector

- `sources` table: metadata (type, URL, title, tags, `content_hash`, `last_crawled_at`, status).
- `chunks` table: text, section title, 768-dim `embedding`, foreign key to source.
- HNSW index on `embedding` for cosine-similarity search (`vector_cosine_ops`).

The whole index fits in a Standard_B1ms Postgres Flexible Server for a corpus under ~50K chunks.

### 4. Serve

Two modes:

- **`docforge serve`** — FastMCP server over stdio. Ideal for local assistants (Claude Code, Cursor with MCP).
- **`docforge serve --api`** — FastAPI over HTTP. Ideal for hosted deployment with multiple users via Entra ID authentication.

Both expose a single primary tool: `search_documentation(query, user_name, team_name, area_name?, limit?)`. Results include source URL + title + section attribution.

## What docforge is **not**

- A chat UI. docforge has no frontend; it hands context to whatever assistant calls it.
- A multi-tenant SaaS. docforge assumes a single-company trust boundary — authenticated users can query any indexed source.
- A hybrid retrieval engine. Retrieval is dense-only today (cosine similarity on embeddings). BM25 fusion is on the [roadmap](https://github.com/GranatenUdo/docforge/blob/master/ROADMAP.md).
- A permission-aware RAG. There are no per-document ACLs at query time.

These are conscious scope decisions. If you need any of them, [Onyx](https://github.com/onyx-dot-app/onyx) is likely a better fit.
