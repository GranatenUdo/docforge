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
4. **Embed.** Sentence-transformers loads [Qwen3-Embedding-4B](https://huggingface.co/Qwen/Qwen3-Embedding-4B) (Apache 2.0, 1024-dim). Falls back to `all-MiniLM-L6-v2` (384-dim) if the primary load fails.
5. **Store.** `sources` (metadata + hash) and `chunks` (text + embedding + HNSW index) tables in Postgres. `ON DELETE CASCADE` keeps `chunks` consistent with `sources`.

Per-source errors are isolated: one bad Confluence page does not abort the run; a summary lists failures at the end.

### 3. Storage — Postgres + pgvector

- `sources` table: metadata (type, URL, title, tags, `content_hash`, `last_crawled_at`, status).
- `chunks` table: text, section title, 1024-dim `embedding`, foreign key to source.
- HNSW index on `embedding` for cosine-similarity search (`vector_cosine_ops`).

The whole index fits in a Standard_B1ms Postgres Flexible Server for a corpus under ~50K chunks.

### 4. Serve

Two surfaces, one in-process (CLI) and one hosted (multi-user team deployment):

- **`docforge serve`** — FastMCP server over stdio. Local single-user use (Claude Code, Cursor with MCP). Loads the embedding model in-process.
- **`docforge serve --api`** — FastAPI over HTTP. Hosted deployment with multiple users via Entra ID authentication. Since v0.3 Phase 4b, the API offloads embedding to a separate **embedder Container App** by setting `EMBEDDER_URL`. Search API replicas drop from ~2 GB RSS to ~400 MB and cold-start in ~30 s (just container spin-up; no model load). The embedder hosts the model behind a shared-secret bearer token (`EMBEDDER_TOKEN`); the GPU-backed Qwen3-Embedding-4B embedder loads the ~10 GB model into VRAM in 2-3 minutes — run with `minReplicas: 1` to keep it warm and avoid cold starts in production.

Both surfaces expose a single primary tool: `search_documentation(query, user_name, team_name, area_name?, limit?)`. Results include source URL + title + section attribution.

### 5. Retrieval and reranking

A query runs a **hybrid** retrieval pass: dense pgvector similarity (HNSW, cosine) plus sparse BM25 full-text, fused with Reciprocal Rank Fusion (RRF) and a small tag boost. The top `rerank_top_n` (default 50) candidates from that pool are then re-scored by a **cross-encoder reranker** ([BAAI/bge-reranker-v2-m3](https://huggingface.co/BAAI/bge-reranker-v2-m3)), served by its own GPU `/rerank` sidecar in the hosted deployment. Reranking is opt-in: the search API only calls the sidecar when `RERANKER_URL` is set, otherwise it returns the fused hybrid ordering.

## What docforge is **not**

- A chat UI. docforge has no frontend; it hands context to whatever assistant calls it.
- A multi-tenant SaaS. docforge assumes a single-company trust boundary — authenticated users can query any indexed source.
- A permission-aware RAG. There are no per-document ACLs at query time.

These are conscious scope decisions. If you need any of them, [Onyx](https://github.com/onyx-dot-app/onyx) is likely a better fit.
