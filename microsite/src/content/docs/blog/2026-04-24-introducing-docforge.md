---
title: "docforge — a self-hosted context engine for AI coding assistants"
description: "Why I built it, where it fits, and what's still shaky."
date: 2026-04-24
---

AI coding assistants are extraordinary at general code, and somewhere between helpful and dangerous at *your* code — the code shaped by the Confluence decisions nobody remembers, the CLAUDE.md files scattered across repos, the internal architecture docs that encode five years of scar tissue. The model does not know any of it. The model cannot know any of it. That is a **retrieval problem, not a model problem**.

docforge is a small tool that closes that gap. It points at your Confluence spaces and local git repositories, indexes them, and serves them over [MCP](https://modelcontextprotocol.io/) so Claude Code, Cursor, Copilot, and any assistant with an MCP client can search your team's knowledge. Self-hosted, small enough to read in an afternoon, MIT-licensed.

## What docforge is, in 90 seconds

```bash
pip install docforge-cli
docforge init my-project
# edit sources.yml, .env
docker compose up -d db
docforge init-db
docforge ingest
docforge serve
```

That's the whole thing. `ingest` crawls Confluence via the REST v2 API, crawls local git repos for `README.md` / `CLAUDE.md` / `docs/**/*.md`, chunks the content to ~500 tokens, embeds with [EmbeddingGemma-300M](https://huggingface.co/google/embeddinggemma-300m) (Gemma license, 768-dim, small enough to run on CPU), and stores vectors in Postgres with pgvector. `serve` exposes a single MCP tool — `search_documentation` — that any MCP-capable assistant can call.

When the assistant needs team context, the tool fires, the top chunks come back with source attribution, and the assistant cites real documents instead of inventing plausible ones.

## Where docforge sits vs. alternatives

| Tool | Self-hosted | Integration | Confluence + code | Footprint |
|---|---|---|---|---|
| **docforge** | ✓ | MCP server | ✓ | Minimal (PG + 1 container) |
| [Atlassian Rovo MCP](https://www.atlassian.com/blog/announcements/atlassian-rovo-mcp-ga) | ✗ (Cloud-only) | MCP server | Confluence only | SaaS |
| [zilliztech/claude-context](https://github.com/zilliztech/claude-context) | ✓ | MCP server | Code only | Minimal |
| [Onyx](https://github.com/onyx-dot-app/onyx) | ✓ | MCP + chat UI | ✓ (50+ connectors) | Heavy (Standard) / Minimal (Lite) |
| Cursor codebase index + @Docs | ✗ | Proprietary | Code + public web | SaaS |
| [Copilot Spaces](https://github.com/orgs/community/discussions/180894) | ✗ | Proprietary | Code + attachments | SaaS |
| [Sourcegraph Cody](https://sourcegraph.com/docs/cody/enterprise/features) | ✓ (Enterprise) | OpenCtx / MCP | ✓ | Heavy |

docforge is the narrow, focused option: minimal footprint, MCP-native so it works with every assistant, Confluence + code out of the box. It doesn't compete on connector count (Onyx wins there), visual UX (Cursor and Cody win), or SaaS convenience (Rovo). It competes on being **small, legible, vendor-neutral, and self-hosted** — four properties no commercial option offers together.

If you need fifty connectors, chat UI for non-developers, or per-document ACLs enforced at query time, use Onyx. If you are on Atlassian Cloud and happy with SaaS, the Rovo MCP is free and official. If you already run Sourcegraph, Cody + OpenCtx does the Confluence part. **docforge is for Data Center / self-hosted teams who want one small thing instead.**

## The design choices

**Postgres + pgvector, not a dedicated vector DB.** Teams already know how to back up, monitor, and restore Postgres. Adding a new database is operational tax that buys little at this scale. pgvector's HNSW index handles tens of thousands of chunks comfortably; a full team deployment on Azure (six resources, default SKUs) runs ~$35/month in West Europe — see [deployment](/docforge/deployment/).

**EmbeddingGemma-300M.** Open weights under the Gemma license, 768-dim, strong on the MTEB Code benchmark relative to its size. Runs on CPU. No API dependency, no per-query cost, no data leaving your infrastructure. The Hugging Face gate is the one supply-chain dependency; we cache the weights into a Docker volume so ingest is not network-dependent after first load.

**MCP-first, not vendor-specific.** MCP is the protocol where the assistant ecosystem is consolidating. Claude Code speaks MCP natively. Cursor speaks MCP. Copilot is adding MCP support for actions. Continue.dev leans on MCP servers for `@Docs`-style workflows. Building to the protocol once gets you every current and future assistant rather than chasing each vendor's feature API.

**No ACLs at query time (today).** docforge assumes a single-company trust boundary — every authenticated user can query every indexed source. This is appropriate for internal team tools and explicitly out of scope for multi-tenant SaaS. Per-source ACLs (honoring Confluence space permissions) are on the roadmap.

**Narrow by design.** Fifty connectors and a chat UI would make docforge a much bigger product. They would also make it Onyx. The whole point is to be smaller than Onyx — the tool you reach for when Onyx is more machinery than the job needs.

## What's shaky today

Honesty up front:

- **Dense-only retrieval.** No BM25 / hybrid fusion yet. Works well for natural-language questions; struggles on exact-identifier queries ("what does `ForgeEmbedder` do?"). [Hybrid retrieval](https://github.com/GranatenUdo/docforge/blob/master/ROADMAP.md) is the next feature.
- **No chunk overlap.** Chunks split cleanly at section / paragraph boundaries. An answer that spans a boundary can be missed. Section titles are prepended as context to partially compensate.
- **No per-source ACLs.** Acknowledged above; real gap for any use case where authenticated users shouldn't all see everything.
- **Retrieval quality eval is drift-detection, not a threshold.** `docforge/scripts/eval_search.py` measures recall@k and MRR against a ground-truth set you maintain. Run it after `sources.yml` changes or embedding updates and compare to baseline; there's no "good enough" number.
- **v0.2.0 has one production deployment** (DocuWare CCL). It's been stable for weeks of daily use, but one site is one site.

## Try it in five minutes

```bash
# Fresh Python 3.12+ venv
pip install docforge-cli
docforge init my-project && cd my-project

# Edit the three config files dropped by `init`:
#   docforge.yml  — Confluence base URL, embedding settings
#   sources.yml   — page IDs, local repo paths
#   .env          — CONFLUENCE_EMAIL, CONFLUENCE_API_TOKEN, HF_TOKEN, DATABASE_URL

docker compose up -d db
docforge init-db
docforge ingest               # first run pulls the ~1.2GB embedding model
docforge search "how do we handle retries"
docforge serve                # MCP on stdio — point your assistant at it
```

For team use, host `docforge serve --api` on Azure Container Apps or equivalent with Entra auth; ballpark cost for a full six-resource deployment is ~$35/month at default SKUs. See the [Deploy to Azure](/docforge/deployment/) guide.

## Credits and what's next

docforge stands on open shoulders: [EmbeddingGemma](https://huggingface.co/google/embeddinggemma-300m), [pgvector](https://github.com/pgvector/pgvector), [FastMCP](https://github.com/PrefectHQ/fastmcp), FastAPI, Typer, asyncpg, sentence-transformers. The MCP spec team and the broader MCP ecosystem made building this easy.

Next up: hybrid retrieval, chunk overlap, MCP identity via session (getting `user_name` / `team_name` off the per-call tool signature). Being considered: per-source ACLs, Confluence Data Center auth hardening, incremental `updatedSince` ingest.

[Follow on GitHub](https://github.com/GranatenUdo/docforge). Bug reports through [Issues](https://github.com/GranatenUdo/docforge/issues); open-ended questions and "show and tell" through [Discussions](https://github.com/GranatenUdo/docforge/discussions).
