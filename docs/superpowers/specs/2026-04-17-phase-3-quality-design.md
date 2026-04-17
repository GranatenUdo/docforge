# Phase 3 Quality — Design

**Date:** 2026-04-17
**Status:** Approved, ready for implementation plan
**Scope:** Test coverage, docstrings, type hints, Dockerfile hardening, README troubleshooting

## Context

docforge is a CLI + MCP server that ingests Confluence and git-repo documentation into PostgreSQL+pgvector and serves it to AI coding assistants. Phases 1 and 2 delivered the package structure, CLI, error handling, and DB indexing. Phase 3 brings the project to a baseline quality bar before wider use: a real test safety net, consistent documentation, hardened container image, and user-facing troubleshooting docs.

## Goals

1. Raise meaningful test coverage from **35%** (measured baseline) to **≥60%** with a mix of unit tests and a small number of integration tests against a real pgvector container.
2. Add missing module-level and public-function docstrings (light scope — no exhaustive Google-style bodies).
3. Fix missing / incorrect type hints in code paths flagged during audit.
4. Harden the Dockerfile: `HEALTHCHECK`, non-root user, `.dockerignore`.
5. Add a `## Troubleshooting` section to `README.md` covering the five most common user-facing failures.

Non-goals:
- Full Google-style docstrings on private helpers.
- Refactoring internal APIs.
- Adding new features.
- 100% coverage of `embedder.py` (thin wrapper over `sentence-transformers`; not worth model-loading cost in CI).

## Baseline

Coverage report (`pytest --cov=docforge` as of 2026-04-17):

| Module | Stmts | Miss | Cover |
|---|---:|---:|---:|
| `docforge/__main__.py` | 2 | 2 | 0% |
| `docforge/cli.py` | 132 | 132 | 0% |
| `docforge/ingest.py` | 114 | 114 | 0% |
| `docforge/mcp_server.py` | 63 | 63 | 0% |
| `docforge/crawlers/confluence.py` | 53 | 53 | 0% |
| `docforge/db.py` | 26 | 18 | 31% |
| `docforge/processors/embedder.py` | 39 | 30 | 23% |
| `docforge/config.py` | 33 | 16 | 52% |
| `docforge/api.py` | 71 | 33 | 54% |
| `docforge/crawlers/git.py` | 41 | 6 | 85% |
| `docforge/processors/parser.py` | 82 | 13 | 84% |
| `docforge/processors/chunker.py` | 76 | 9 | 88% |
| `docforge/sources.py` | 22 | 0 | 100% |
| **Total** | **754** | **489** | **35%** |

## Approach

### Testing strategy: hybrid (unit + 1-2 integration)

**Unit tests** cover the bulk of logic using mocks:
- Typer commands tested via `typer.testing.CliRunner` with internal coroutines patched.
- Asyncpg pool mocked for DB-touching code.
- `httpx.MockTransport` for the Confluence crawler.
- `Embedder` replaced with a deterministic fake (fixed-size vectors) anywhere it would otherwise load the 300M model.

**Integration tests** (2 total) use `testcontainers-python` to spin up a `pgvector/pgvector:pg16` container:
1. End-to-end git ingest → DB → search (Embedder still mocked — we are testing DB/crawler integration, not the embedder).
2. `init_db` schema + pgvector extension + vector insert/query round-trip.

This keeps the fast path fast (unit tests run in <2s) while giving us real confidence that schema, pool lifecycle, and pgvector registration work end-to-end.

### Per-module coverage targets

| Module | Target | How |
|---|---:|---|
| `__main__.py` | 100% | Import test |
| `cli.py` | ~75% | `CliRunner` + patched internal coroutines for each subcommand |
| `ingest.py` | ~70% | Mock `get_pool`, `crawl_page`, `crawl_repo`, `Embedder`; integration test covers git flow end-to-end |
| `mcp_server.py` | ~85% | Call `search_documentation` / `list_sources` directly with mocked pool + embedder |
| `crawlers/confluence.py` | ~85% | `httpx.MockTransport` covering success, 401, 404, pagination edge cases |
| `db.py` | ~90% | Integration test covers `init_db`, pool lifecycle, `close_pool` |
| `api.py` | ~85% | Extend existing tests: `/search` success path, `/sources`, DB-error paths |
| `config.py` | ~95% | YAML loading, env-var override precedence, missing-file fallback |
| `embedder.py` | ~40% | Mock `SentenceTransformer` at class level; verify fallback-model logic only |

**Projected total: ~75-80%**, comfortably above the 60% gate.

### Test layout

```
tests/
  conftest.py                         # shared fixtures (mock Embedder factory)
  unit/
    test_api.py                       # extended
    test_chunker.py                   # existing
    test_cli.py                       # new
    test_config.py                    # new
    test_confluence_crawler.py        # new
    test_embedder.py                  # new
    test_git_crawler.py               # existing
    test_ingest.py                    # new
    test_mcp_server.py                # new
    test_parser.py                    # existing
    test_sources.py                   # existing
  integration/
    conftest.py                       # pg_container, pg_url fixtures
    test_db_schema.py                 # new
    test_ingest_git_integration.py    # new
```

### pytest configuration changes

Add to `[project.optional-dependencies].dev` in `pyproject.toml`:
- `pytest-cov>=7.0`
- `testcontainers[postgres]>=4.0`

Update `[tool.pytest.ini_options]`:

```toml
[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
markers = [
    "integration: requires Docker (pgvector container)",
]
addopts = "--cov=docforge --cov-fail-under=60"
```

Note: `addopts` applies `--cov` on every invocation. Integration runs extend the same coverage report rather than run it separately.

Create `.coveragerc`:

```ini
[run]
omit =
    docforge/templates/*

[report]
exclude_also =
    if __name__ == "__main__":
    pragma: no cover
    raise NotImplementedError
```

### Integration test fixtures

`tests/integration/conftest.py`:

```python
import pytest
from testcontainers.postgres import PostgresContainer

@pytest.fixture(scope="session")
def pg_container():
    """One pgvector container for the whole test session."""
    with PostgresContainer("pgvector/pgvector:pg16") as pg:
        yield pg

@pytest.fixture
async def pg_url(pg_container):
    """Fresh schema per test; truncate between tests for isolation."""
    url = pg_container.get_connection_url().replace("postgresql+psycopg2://", "postgresql://")
    from docforge.db import init_db, close_pool
    await init_db(url)
    yield url
    import asyncpg
    conn = await asyncpg.connect(url)
    try:
        await conn.execute("TRUNCATE sources, chunks RESTART IDENTITY CASCADE")
    finally:
        await conn.close()
    await close_pool()
```

Session-scoped container (start once, ~10s cold start), function-scoped URL + truncate for test isolation.

### The two integration tests

1. **`test_ingest_git_integration.py::test_end_to_end_ingest_and_search`**
   - Build a tmp git repo with 2 markdown files with known content.
   - Patch `docforge.processors.embedder.Embedder` with a fake returning deterministic vectors.
   - Run `ingest_all(settings)` pointed at `pg_url`.
   - Assert rows in `sources` and `chunks`.
   - Execute the same SELECT used in `api.py` against the DB and assert semantic ordering (closer fake vector ranks higher).

2. **`test_db_schema.py::test_init_db_creates_schema_and_pgvector`**
   - Run `init_db(pg_url)` (the existing fixture already does this — this test just asserts the post-conditions).
   - Query `information_schema.tables` for `sources`, `chunks`.
   - Query `pg_extension` for `vector`.
   - Insert a row into `chunks` with an embedding, select it back, confirm vector type round-trips.

### Embedder mocking strategy

Add to `tests/conftest.py`:

```python
import pytest

@pytest.fixture
def fake_embedder(monkeypatch):
    """Patch Embedder to return deterministic vectors without loading a model."""
    class FakeEmbedder:
        model_name = "fake/embedder"
        dimensions = 768
        def __init__(self, *args, **kwargs): pass
        def embed(self, texts): return [[0.0] * 767 + [float(i)] for i, _ in enumerate(texts)]
        def embed_query(self, text): return [0.0] * 767 + [1.0]
        def get_tokenizer_fn(self): return lambda s: len(s.split())
    monkeypatch.setattr("docforge.processors.embedder.Embedder", FakeEmbedder)
    monkeypatch.setattr("docforge.ingest.Embedder", FakeEmbedder)
    monkeypatch.setattr("docforge.mcp_server.Embedder", FakeEmbedder)
    monkeypatch.setattr("docforge.api.Embedder", FakeEmbedder)
    monkeypatch.setattr("docforge.cli.Embedder", FakeEmbedder, raising=False)
    return FakeEmbedder
```

## Docstrings (Light scope)

- Add module-level docstrings where missing. Audit list: `config.py`, `db.py`, `ingest.py`, `sources.py`, `crawlers/git.py`, `crawlers/confluence.py`, `processors/chunker.py`, `processors/embedder.py`, `processors/parser.py`, `__main__.py`, and the `__init__.py` files that host public API.
- One-line docstrings on public (non-underscore) functions currently missing them.
- Skip private `_helpers` unless they carry non-obvious behavior (none spotted).
- Style: concise first line, no forced Google-style Args/Returns — types already convey that information.

## Type hints

Targeted fixes flagged during audit:

- `docforge/ingest.py`: `tokenizer_fn: callable` → `Callable[[str], int]` (import from `typing`). Applies to `_ingest_confluence_source` and `_ingest_git_source`.
- `docforge/api.py`: `/health` and `/sources` handlers return `-> dict` — retype to `dict[str, Any]` or Pydantic response models. Using `dict[str, Any]` is fine for this phase.
- Check `config.py` `__init__` for missing return type (`-> None`).

No exhaustive audit; these are the concrete issues found while reading the code.

## Dockerfile hardening

Current `Dockerfile` has no HEALTHCHECK, runs as root, has no `.dockerignore`.

Changes:
1. Add `curl` to the apt-get install line (~1MB) for the HEALTHCHECK command.
2. Add `HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 CMD curl -fsS http://localhost:8000/health || exit 1`. The 60s `start-period` covers model loading on cold start.
3. After `COPY docforge/ docforge/`, add:
   ```
   RUN useradd -m -u 1000 docforge && chown -R docforge:docforge /app
   USER docforge
   ```
4. Create `.dockerignore` at repo root excluding `.venv/`, `.git/`, `__pycache__/`, `*.pyc`, `tests/`, `.pytest_cache/`, `.coverage`, `*.egg-info/`, `docs/`, `infrastructure/`. Cuts build context dramatically.

## README troubleshooting section

Append to `README.md` before the `## License` section:

```markdown
## Troubleshooting

### "Cannot connect to PostgreSQL"
Check that the database is running: `docker compose up -d db`. Verify `DATABASE_URL` in `.env` points to `postgresql://docforge:localdev@localhost:5432/docforge` (or your custom value).

### "HF_TOKEN required" or model download fails
The embedding model `google/embeddinggemma-300m` requires a Hugging Face token with access to the gated model. Create one at https://huggingface.co/settings/tokens, accept the model license at https://huggingface.co/google/embeddinggemma-300m, and set `HF_TOKEN=hf_...` in `.env`.

### "No results found" after ingest
Run `docforge status` to confirm sources and chunks exist. If counts are zero, check the ingest logs for per-source failures — the summary at the end lists sources that failed.

### First ingest is very slow
The first run downloads the 300M embedding model (~1.2GB) from Hugging Face. The model is cached at `~/.cache/huggingface/` and subsequent runs skip the download.

### "Ingest skipped everything"
docforge skips sources whose `content_hash` matches the stored hash (no changes detected). To force re-ingest, clear the hash: `UPDATE sources SET content_hash = NULL;` then run `docforge ingest`.
```

## Success criteria

- [ ] `pytest` exit code 0 with `--cov-fail-under=60`.
- [ ] `pytest -m "not integration"` runs in <5s.
- [ ] `pytest -m integration` runs against a pgvector testcontainer and passes.
- [ ] All modules listed in the docstring audit have a module-level docstring.
- [ ] `ingest.py` and `api.py` type-hint issues fixed.
- [ ] `docker build .` succeeds; resulting image has HEALTHCHECK configured (`docker inspect` shows it) and runs as UID 1000.
- [ ] `.dockerignore` exists at repo root.
- [ ] README has a `## Troubleshooting` section with the 5 entries above.

## Risks and open questions

- **Docker in CI**: `testcontainers` needs a Docker daemon. If CI runs on hosts without Docker, integration tests must be gated (`pytest -m "not integration"` as the CI default, run integration separately). The plan should specify CI config if one exists.
- **Baseline mismatch**: User referenced a 12.8% baseline but current measured baseline is 35%. Not blocking — we are still targeting ≥60%.
- **pytest-cov dep**: Need to add `pytest-cov>=7.0` and `testcontainers[postgres]>=4.0` to `[project.optional-dependencies].dev`.
