# Reporting security issues

Please do **not** open a public GitHub issue for security concerns.

Instead, email the maintainer: **tobias.ens@proton.me**. Include:

- A description of the issue and its impact.
- Reproduction steps (minimal, please).
- The docforge version (`docforge --version`) and any relevant environment details.

You can expect an acknowledgement within **7 days**. Further communication and
coordination happen over email until a fix is available.

## Supported versions

The **latest minor release** is supported. When a fix ships, it lands in the
next patch release. Users on older minor versions are encouraged to upgrade.

## Scope

This policy covers docforge itself. For issues in dependencies
(sentence-transformers — the Qwen3-Embedding-4B embedder and the
BAAI/bge-reranker-v2-m3 CrossEncoder reranker — FastMCP, pgvector, FastAPI,
etc.), please report upstream first; we will coordinate follow-up.
