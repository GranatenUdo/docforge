# Changelog

All notable changes to docforge are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- Threat model now linked from the "When docforge is the wrong choice" section in both `README.md` and the microsite homepage. External adopters comparing docforge against alternatives can find the explicit trust assumptions without having to dig into `docs/`.
- "License compatibility" section in `README.md` naming the [Gemma Terms of Use](https://ai.google.dev/gemma/terms) restrictions (no harmful use, no Gemma-derivative competitors) for adopters considering redistribution.
- Optional `expected_dimensions` parameter on `Embedder.__init__`. When provided, asserts the loaded model's dimension matches; raises `RuntimeError` with a clear remediation message on mismatch. Defaults to `None` (guard dormant) for backwards compatibility with direct `Embedder()` callers.
- `docs/log-privacy.md` — privacy & retention policy for the `query_log` table. Documents purpose, retention, redaction patterns, access roles, and a right-to-erasure runbook. Partially aspirational as of Phase 3; the "Implementation status" section names which items ship later in v0.3.

### Changed

- MCP server identifier renamed from `knowledge-hub` to `docforge` (the original name was a leftover from the project's original DocuWare-internal incarnation). **Behavior change for MCP clients:** the server name shown in MCP client UIs changes; clients that filter on server name need to update. No protocol or tool surface changes.
- All runtime and dev dependencies in `pyproject.toml` now carry strict-major upper bounds (e.g. `fastapi>=0.115,<1.0`, `pydantic>=2.9,<3.0`, `pytest>=9.0,<10.0`). Floor-only pins previously allowed fresh installs to pull an untested next-major version of any dep. `numpy>=1.26,<3.0` is the documented exception, covering both 1.x and 2.x. Dependabot continues to pick up minors and patches.
- All four `Embedder(...)` construction sites in the API, MCP server, ingest pipeline, and CLI now pass `expected_dimensions=settings.embedding_dimensions`, enabling the new dimension guard in production. **Behavior change:** if your configured `embedding_dimensions` disagrees with the loaded embedding model's actual dimension, the process now fails fast at startup with a clear remediation message ("change `embedding_model` in `docforge.yml`, or update `embedding_dimensions` and migrate the schema"), instead of failing later at INSERT time with a cryptic pgvector error. Adopters with a stale `embedding_dimensions` should update it before upgrading.
- API and MCP search request boundaries are now hard-capped: `query` is rejected over 8000 characters, `limit` is rejected outside `[1, 50]`. **Behavior change:** clients that previously got 200 with `limit=10000` (and a slow response) now get HTTP 422 with a Pydantic-shaped error detail naming the offending field. Internal `Embedder.embed` raises `ValueError` when called with more than 256 texts in one batch.
- API process is now stateless — module globals replaced by a FastAPI lifespan that yields settings, pool, embedder, and azure_scheme into per-request `request.state`; handlers access them via `Depends` getters. **Behavior change for tests:** consumers that monkey-patched `api._embedder`, `api._get_settings`, or `api.get_pool` need to switch to `app.dependency_overrides`. No deployer-facing change.
- Asyncpg pool sizing is tunable per deployment via the new `Settings.pool_min_size` and `pool_max_size` fields (env: `POOL_MIN_SIZE`, `POOL_MAX_SIZE`). Defaults raised from `1`/`5` to `5`/`25` to match the operating profile. Operators on smaller Postgres tiers should lower these explicitly.
- `query_log` cleanup loop now coordinates across replicas via a transaction-scoped Postgres advisory lock (`pg_try_advisory_xact_lock(0xD0CF0001)`). At most one replica runs DELETE per interval; the others log a debug line and skip. Replaces the prior "every replica deletes once per hour" pattern (which was idempotent but wasteful).
- `api.py:search` and `mcp_server.py:search_documentation` now wrap the synchronous `Embedder.embed_query` call in `asyncio.to_thread`. The event loop remains responsive during embedding inference. Closes the original Finding 1 from the v0.2.1 critical review.
- The embedding model can now be hosted as a separate Container App via the new `EMBEDDER_URL` setting (Phase 4b). When set, the search API, MCP server, and ingest worker delegate embedding to that URL instead of loading the model in-process. Search API replicas drop from ~2 GB RSS to ~400 MB and start in <10s. The split is opt-in: leaving `EMBEDDER_URL` empty keeps the in-process behaviour.
- New `Dockerfile.embedder` builds the embedder service image. The EmbeddingGemma-300M model is baked into the image at build time using a BuildKit secret mount (`--mount=type=secret,id=hf_token`); the HuggingFace token never enters any image layer.
- New shared-secret bearer auth between the search API and the embedder service via `EMBEDDER_TOKEN`. The embedder service refuses to start without it; `RemoteEmbedder` raises at construction if `embedder_url` is set without `embedder_token`. **Behavior change for hosted deployments:** Bicep gains a new `embedderToken` parameter (required; operators generate via `openssl rand -hex 32` and rotate by re-deploying with a new value); the embedder service and search API both reference this secret from Key Vault.
- Async-only `RemoteEmbedder` surface; `Embedder` gains `aembed` / `aembed_query` async wrappers via `asyncio.to_thread`; all async call sites (api, mcp_server, ingest) now use `await embedder.aembed_query(...)` / `aembed(...)`. The CLI bypasses the factory and constructs `Embedder(...)` directly so local CLI runs always use the in-process model regardless of `EMBEDDER_URL`.

## [0.2.1] - 2026-04-25

### Added

- `[project.urls]` in `pyproject.toml` (Homepage, Source, Issues, Changelog, Documentation) — populates the PyPI sidebar on next publish.
- `Makefile` at repo root with developer shortcuts: `install`, `test`, `lint`, `format`, `build`, `clean`, plus microsite shortcuts.
- `.editorconfig` at repo root for cross-editor consistency.
- `BACKLOG.md` at repo root tracking in-flight cleanup work and the deferred small/medium/large items.

### Changed

- Internal planning artifacts moved from `docs/superpowers/` to `.superpowers/`. Historical cross-references inside the moved files are preserved as-is. The single current reference in `microsite/.../deployment.md` was updated.
- README's FAQ trimmed to the three install-time issues new users hit most often (HF_TOKEN, first-run slow, Postgres connection); the full FAQ remains canonical on the [microsite](https://GranatenUdo.github.io/docforge/faq/).
- Microsite no longer ships duplicate copies of canonical assets. `microsite/scripts/sync-assets.mjs` runs before `astro dev` / `astro build` and copies from `docs/assets/`. Saves ~70 KB of redundant binaries in git.
- Repository switched to `src/` layout (`docforge/` → `src/docforge/`). Public package and import name (`docforge-cli` / `import docforge`) unchanged. CI ruff paths, Dockerfile COPY (now reordered to copy source before install for proper site-packages installation), and CONTRIBUTING.md / README path examples updated.

## [0.2.0] - 2026-04-24

### Added

- Positioning-led README with comparison table against Onyx, Atlassian Rovo MCP, zilliztech/claude-context, Cursor, Copilot Spaces, Sourcegraph Cody, and LangChain DIY, plus an explicit "when not to use" section.
- `CHANGELOG.md`, `SECURITY.md`, `CODE_OF_CONDUCT.md` (Contributor Covenant 2.1), `ROADMAP.md`.
- GitHub issue templates (bug report, feature request) and pull-request template under `.github/`.
- Tag-triggered release workflow at `.github/workflows/release.yml` using PyPI trusted publishing.
- GitHub Discussions enabled with categories *Announcements*, *Q&A*, *Ideas*, *Show and tell*.
- Visual identity under `docs/assets/`: monogram logo (two variants), favicon set (16×16, 32×32, 180×180 PNG + multi-res ICO), architecture data-flow SVG, 1280×640 social preview card. Graphite (`#1a1a1a`) + amber (`#d97706`) palette.
- Astro + Starlight microsite under `microsite/` with landing, install, architecture, deployment, and FAQ pages, plus a launch blog post. Deployed to GitHub Pages via `.github/workflows/microsite.yml` on every `master` push that touches `microsite/**`.

### Changed

- Repository description and topics updated to reflect the new positioning.
- README "How it works → Architecture" replaces the ASCII diagram with the new SVG.

## [0.1.0] - 2026-04-24

First tagged release. Retroactive tag at commit `491db97`. Covers Phase 1–3
(MVP + Phase 3 quality) and Phase 4 hardening (operational readiness,
security, team tagging).
