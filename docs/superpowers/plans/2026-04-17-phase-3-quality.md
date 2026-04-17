# Phase 3 Quality Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Lift docforge test coverage from 35% to ≥60%, add missing docstrings / type hints, harden the Dockerfile (HEALTHCHECK, non-root, `.dockerignore`), drop build-time HF model pre-download, and add a README troubleshooting section.

**Architecture:** Hybrid testing — unit tests with mocks for most logic, plus 2 integration tests against a `pgvector/pgvector:pg16` testcontainer spun up by pytest. Coverage gate lives in `[tool.coverage.report] fail_under = 60` so single-file runs are not punished.

**Tech Stack:** pytest + pytest-asyncio + pytest-cov, testcontainers-python, httpx.MockTransport, typer.testing.CliRunner, Docker.

---

## File Structure

**New files:**
- `tests/conftest.py` — shared fixtures (fake_embedder)
- `tests/unit/test_embedder.py`
- `tests/unit/test_config.py`
- `tests/unit/test_confluence_crawler.py`
- `tests/unit/test_mcp_server.py`
- `tests/unit/test_ingest.py`
- `tests/unit/test_cli.py`
- `tests/unit/test_main_module.py`
- `tests/integration/conftest.py` — pg_container, pg_url
- `tests/integration/test_db_schema.py`
- `tests/integration/test_ingest_git_integration.py`
- `.dockerignore`

**Modified files:**
- `pyproject.toml` — dev deps, pytest config, coverage config
- `tests/unit/test_api.py` — extend with search-success + /sources + error paths
- `docforge/ingest.py` — type hint fix (`callable` → `Callable[[str], int]`)
- `docforge/api.py` — type hint fix on `/health` and `/sources` return types
- `docforge/config.py` — `__init__ -> None`
- `docforge/processors/embedder.py` — `get_tokenizer_fn() -> Callable[[str], int]`
- Several files — module-level and public-function docstrings added
- `Dockerfile` — HEALTHCHECK, non-root, drop pre-download
- `README.md` — add `## Troubleshooting` section

---

## Task 1: Add dev deps and pytest/coverage config

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 1: Update `pyproject.toml`**

Replace the `[project.optional-dependencies]` and `[tool.pytest.ini_options]` sections, and add a new `[tool.coverage.report]` section. Full replacement for those sections:

```toml
[project.optional-dependencies]
dev = [
    "pytest>=8.0",
    "pytest-asyncio>=0.24",
    "pytest-cov>=7.0",
    "ruff>=0.8",
    "testcontainers[postgres]>=4.0",
]

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
markers = [
    "integration: requires Docker (pgvector container)",
]
addopts = "--cov=docforge"

[tool.coverage.report]
fail_under = 60
exclude_also = [
    "if __name__ == \"__main__\":",
    "pragma: no cover",
    "raise NotImplementedError",
]
```

- [ ] **Step 2: Install new deps**

Run:
```bash
pip install -e ".[dev]"
```
Expected: successfully installs `pytest-cov>=7.0` and `testcontainers[postgres]>=4.0` and their transitive deps (docker, etc.).

- [ ] **Step 3: Verify existing tests still pass with new config**

Run:
```bash
pytest -m "not integration"
```
Expected: 28 existing tests pass. Coverage summary prints (it will fail the gate at 35%, but that's expected until new tests are added — use `--no-cov` or `--cov-fail-under=0` if you need a clean exit during iteration).

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml
git commit -m "chore: add pytest-cov and testcontainers to dev deps; configure coverage gate"
```

---

## Task 2: Shared test fixtures — fake_embedder

**Files:**
- Create: `tests/conftest.py`

- [ ] **Step 1: Create `tests/conftest.py`**

```python
"""Shared fixtures for unit and integration tests."""

from __future__ import annotations

import pytest


class FakeEmbedder:
    """Deterministic stand-in for docforge.processors.embedder.Embedder.

    Returns fixed vectors without loading the 300M sentence-transformers
    model. Dimensions match EmbeddingGemma-300M (768) so pgvector columns
    defined as vector(768) accept the output in integration tests.
    """

    model_name = "fake/embedder"
    dimensions = 768

    def __init__(self, *args, **kwargs) -> None:
        pass

    def embed(self, texts: list[str]) -> list[list[float]]:
        # Unique-ish vector per index so similarity ordering is testable.
        return [
            [0.0] * 767 + [float(i + 1) / 1000.0]
            for i, _ in enumerate(texts)
        ]

    def embed_query(self, text: str) -> list[float]:
        return [0.0] * 767 + [0.001]

    def get_tokenizer_fn(self):
        return lambda s: len(s.split())


@pytest.fixture
def fake_embedder(monkeypatch):
    """Patch every consumer module's imported `Embedder` with FakeEmbedder.

    Consumer modules do `from docforge.processors.embedder import Embedder`
    at module load, binding the class into their own namespace. Patching
    the source module does not help — each consumer's binding must be
    replaced.
    """
    targets = [
        "docforge.ingest.Embedder",
        "docforge.mcp_server.Embedder",
        "docforge.api.Embedder",
    ]
    for target in targets:
        monkeypatch.setattr(target, FakeEmbedder)
    # cli.py imports Embedder lazily inside _search; patch the source too
    # so the lazy import resolves to FakeEmbedder.
    monkeypatch.setattr("docforge.processors.embedder.Embedder", FakeEmbedder)
    return FakeEmbedder
```

- [ ] **Step 2: Commit**

```bash
git add tests/conftest.py
git commit -m "test: add shared FakeEmbedder fixture"
```

---

## Task 3: Unit tests — embedder.py

**Files:**
- Create: `tests/unit/test_embedder.py`

- [ ] **Step 1: Write the tests**

```python
"""Tests for docforge.processors.embedder.

Patches sentence_transformers.SentenceTransformer to avoid loading real
models (which would download ~1.2GB and take >30s).
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import numpy as np
import pytest


def _fake_st_model(dim: int = 768, encode_return=None):
    model = MagicMock()
    model.get_embedding_dimension.return_value = dim
    if encode_return is None:
        encode_return = np.array([[0.1, 0.2, 0.3, 0.4]])
    model.encode.return_value = encode_return
    model.tokenizer.encode.side_effect = lambda text, add_special_tokens=False: text.split()
    return model


class TestEmbedderInit:
    def test_primary_model_loads_successfully(self):
        fake = _fake_st_model(dim=768)
        with patch("sentence_transformers.SentenceTransformer", return_value=fake) as mock_st:
            from docforge.processors.embedder import Embedder

            emb = Embedder("primary/model", hf_token="tok")

        assert emb.model_name == "primary/model"
        assert emb.dimensions == 768
        mock_st.assert_called_once_with("primary/model", token="tok")

    def test_falls_back_when_primary_fails(self):
        fake_fallback = _fake_st_model(dim=384)
        call_count = {"n": 0}

        def side_effect(*args, **kwargs):
            call_count["n"] += 1
            if call_count["n"] == 1:
                raise RuntimeError("primary exploded")
            return fake_fallback

        with patch("sentence_transformers.SentenceTransformer", side_effect=side_effect):
            from docforge.processors.embedder import Embedder

            emb = Embedder("primary/broken")

        assert emb.model_name == "sentence-transformers/all-MiniLM-L6-v2"
        assert emb.dimensions == 384
        assert call_count["n"] == 2

    def test_raises_when_both_models_fail(self):
        with patch("sentence_transformers.SentenceTransformer", side_effect=RuntimeError("gone")):
            from docforge.processors.embedder import Embedder

            with pytest.raises(RuntimeError, match="No embedding model available"):
                Embedder("primary/broken")

    def test_uses_env_token_when_arg_empty(self, monkeypatch):
        monkeypatch.setenv("HF_TOKEN", "env_tok_123")
        fake = _fake_st_model()
        with patch("sentence_transformers.SentenceTransformer", return_value=fake) as mock_st:
            from docforge.processors.embedder import Embedder

            Embedder("some/model", hf_token="")

        mock_st.assert_called_once_with("some/model", token="env_tok_123")

    def test_passes_none_when_no_token_available(self, monkeypatch):
        monkeypatch.delenv("HF_TOKEN", raising=False)
        fake = _fake_st_model()
        with patch("sentence_transformers.SentenceTransformer", return_value=fake) as mock_st:
            from docforge.processors.embedder import Embedder

            Embedder("open/model", hf_token="")

        mock_st.assert_called_once_with("open/model", token=None)


class TestEmbedderMethods:
    @pytest.fixture
    def embedder(self):
        fake = _fake_st_model(
            dim=4,
            encode_return=np.array([[0.1, 0.2, 0.3, 0.4], [0.5, 0.6, 0.7, 0.8]]),
        )
        with patch("sentence_transformers.SentenceTransformer", return_value=fake):
            from docforge.processors.embedder import Embedder

            return Embedder("m")

    def test_embed_empty_list_returns_empty(self, embedder):
        assert embedder.embed([]) == []

    def test_embed_returns_list_of_lists(self, embedder):
        result = embedder.embed(["hello", "world"])
        assert result == [[0.1, 0.2, 0.3, 0.4], [0.5, 0.6, 0.7, 0.8]]

    def test_embed_query_returns_single_vector(self, embedder):
        # With a single input, the fake returns the same 2-row array; embed_query
        # takes result[0].
        result = embedder.embed_query("hello")
        assert result == [0.1, 0.2, 0.3, 0.4]

    def test_get_tokenizer_fn_counts_tokens(self, embedder):
        counter = embedder.get_tokenizer_fn()
        assert counter("one two three four") == 4
        assert counter("") == 0
```

- [ ] **Step 2: Run the tests**

```bash
pytest tests/unit/test_embedder.py -v
```
Expected: all tests pass. If any fail, inspect and fix the test (not the code) — the code is already shipped.

- [ ] **Step 3: Commit**

```bash
git add tests/unit/test_embedder.py
git commit -m "test: add unit tests for Embedder (primary/fallback/failure paths)"
```

---

## Task 4: Unit tests — config.py

**Files:**
- Create: `tests/unit/test_config.py`

- [ ] **Step 1: Write the tests**

```python
"""Tests for docforge.config.Settings — YAML loading, env overrides, precedence."""

from __future__ import annotations

import pytest


class TestSettingsDefaults:
    def test_defaults_when_no_yml_or_env(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        for var in ("DATABASE_URL", "CONFLUENCE_BASE_URL", "HF_TOKEN", "EMBEDDING_MODEL"):
            monkeypatch.delenv(var, raising=False)

        from docforge.config import Settings

        s = Settings()
        assert s.database_url == "postgresql://docforge:localdev@localhost:5432/docforge"
        assert s.confluence_base_url == ""
        assert s.embedding_model == "google/embeddinggemma-300m"
        assert s.embedding_dimensions == 768
        assert s.chunk_max_tokens == 500
        assert s.sources_file == "sources.yml"


class TestYamlLoading:
    def test_loads_flat_keys_from_docforge_yml(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        for var in ("DATABASE_URL", "CONFLUENCE_BASE_URL"):
            monkeypatch.delenv(var, raising=False)
        (tmp_path / "docforge.yml").write_text(
            "database_url: postgresql://u:p@h:5432/db\n"
            "confluence_base_url: https://example.atlassian.net\n"
            "confluence_email: user@example.com\n"
        )

        from docforge.config import Settings

        s = Settings()
        assert s.database_url == "postgresql://u:p@h:5432/db"
        assert s.confluence_base_url == "https://example.atlassian.net"
        assert s.confluence_email == "user@example.com"

    def test_embedding_section_is_flattened(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        (tmp_path / "docforge.yml").write_text(
            "embedding:\n"
            "  model: custom/model\n"
            "  dimensions: 384\n"
            "  chunk_max_tokens: 200\n"
        )

        from docforge.config import Settings

        s = Settings()
        assert s.embedding_model == "custom/model"
        assert s.embedding_dimensions == 384
        assert s.chunk_max_tokens == 200

    def test_empty_yml_file_does_not_crash(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        (tmp_path / "docforge.yml").write_text("")

        from docforge.config import Settings

        s = Settings()
        assert s.embedding_model == "google/embeddinggemma-300m"


class TestPrecedence:
    def test_env_overrides_yml(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        (tmp_path / "docforge.yml").write_text(
            "database_url: postgresql://yml:yml@yml:5432/yml\n"
        )
        monkeypatch.setenv("DATABASE_URL", "postgresql://env:env@env:5432/env")

        from docforge.config import Settings

        s = Settings()
        assert s.database_url == "postgresql://env:env@env:5432/env"

    def test_kwargs_override_env_and_yml(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        (tmp_path / "docforge.yml").write_text("database_url: postgresql://yml\n")
        monkeypatch.setenv("DATABASE_URL", "postgresql://env")

        from docforge.config import Settings

        s = Settings(database_url="postgresql://kwarg")
        assert s.database_url == "postgresql://kwarg"


class TestSecrets:
    def test_secretstr_fields_not_leaked_in_repr(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("HF_TOKEN", "secret_token_shhh")

        from docforge.config import Settings

        s = Settings()
        assert s.hf_token.get_secret_value() == "secret_token_shhh"
        assert "secret_token_shhh" not in repr(s)
```

- [ ] **Step 2: Run the tests**

```bash
pytest tests/unit/test_config.py -v
```
Expected: all tests pass.

- [ ] **Step 3: Commit**

```bash
git add tests/unit/test_config.py
git commit -m "test: add unit tests for Settings YAML loading and precedence"
```

---

## Task 5: Unit tests — Confluence crawler

**Files:**
- Create: `tests/unit/test_confluence_crawler.py`

- [ ] **Step 1: Write the tests**

```python
"""Tests for docforge.crawlers.confluence.crawl_page.

Uses httpx.MockTransport to intercept HTTP calls without hitting Confluence.
The crawl_page function instantiates its own AsyncClient, so we monkeypatch
`docforge.crawlers.confluence.httpx.AsyncClient` to return a pre-configured
client whose transport is our mock.
"""

from __future__ import annotations

import hashlib

import httpx
import pytest

from docforge.crawlers.confluence import crawl_page


@pytest.fixture
def mock_confluence(monkeypatch):
    """Return an installer: `mock_confluence(handler_fn)` patches httpx."""

    def _install(handler):
        def client_factory(**kwargs):
            return httpx.AsyncClient(transport=httpx.MockTransport(handler))

        monkeypatch.setattr(
            "docforge.crawlers.confluence.httpx.AsyncClient", client_factory
        )

    return _install


@pytest.mark.asyncio
async def test_successful_fetch(mock_confluence):
    def handler(request):
        assert "pages/42" in str(request.url)
        return httpx.Response(
            200,
            json={
                "title": "Team Responsibilities",
                "version": {"number": 7},
                "spaceId": "ORG",
                "body": {"storage": {"value": "<h2>Platform</h2><p>Owns X</p>"}},
            },
        )

    mock_confluence(handler)

    page = await crawl_page(
        "42",
        base_url="https://example.atlassian.net",
        email="a@b.c",
        api_token="tok",
    )

    assert page.page_id == "42"
    assert page.title == "Team Responsibilities"
    assert page.version == 7
    assert page.html_content == "<h2>Platform</h2><p>Owns X</p>"
    expected_hash = hashlib.sha256(page.html_content.encode()).hexdigest()
    assert page.content_hash == expected_hash
    assert page.url == "https://example.atlassian.net/wiki/spaces/ORG/pages/42"


@pytest.mark.asyncio
async def test_missing_body_returns_empty_html(mock_confluence):
    def handler(request):
        return httpx.Response(200, json={"title": "Empty"})

    mock_confluence(handler)

    page = await crawl_page("1", base_url="https://x", email="a", api_token="t")
    assert page.html_content == ""


@pytest.mark.asyncio
async def test_auth_error_raises(mock_confluence):
    def handler(request):
        return httpx.Response(401, json={"message": "unauthorized"})

    mock_confluence(handler)

    with pytest.raises(httpx.HTTPStatusError):
        await crawl_page("1", base_url="https://x", email="a", api_token="bad")


@pytest.mark.asyncio
async def test_not_found_raises(mock_confluence):
    def handler(request):
        return httpx.Response(404, json={"message": "not found"})

    mock_confluence(handler)

    with pytest.raises(httpx.HTTPStatusError):
        await crawl_page("missing", base_url="https://x", email="a", api_token="t")


@pytest.mark.asyncio
async def test_retries_on_transient_then_succeeds(mock_confluence, monkeypatch):
    # Skip the real backoff waits.
    async def _noop_sleep(_):
        return None

    monkeypatch.setattr("asyncio.sleep", _noop_sleep)

    call_count = {"n": 0}

    def handler(request):
        call_count["n"] += 1
        if call_count["n"] == 1:
            return httpx.Response(503, headers={"Retry-After": "0"})
        return httpx.Response(
            200,
            json={
                "title": "OK",
                "version": {"number": 1},
                "spaceId": "SP",
                "body": {"storage": {"value": "<p>Ok</p>"}},
            },
        )

    mock_confluence(handler)

    page = await crawl_page("1", base_url="https://x", email="a", api_token="t")
    assert page.title == "OK"
    assert call_count["n"] == 2


@pytest.mark.asyncio
async def test_max_retries_exceeded_raises(mock_confluence, monkeypatch):
    async def _noop_sleep(_):
        return None

    monkeypatch.setattr("asyncio.sleep", _noop_sleep)

    def handler(request):
        return httpx.Response(503, headers={"Retry-After": "0"})

    mock_confluence(handler)

    with pytest.raises(httpx.HTTPStatusError):
        await crawl_page("1", base_url="https://x", email="a", api_token="t")


@pytest.mark.asyncio
async def test_retries_on_timeout(mock_confluence, monkeypatch):
    async def _noop_sleep(_):
        return None

    monkeypatch.setattr("asyncio.sleep", _noop_sleep)

    call_count = {"n": 0}

    def handler(request):
        call_count["n"] += 1
        if call_count["n"] == 1:
            raise httpx.TimeoutException("slow")
        return httpx.Response(
            200,
            json={
                "title": "OK",
                "version": {"number": 1},
                "spaceId": "SP",
                "body": {"storage": {"value": "<p>Ok</p>"}},
            },
        )

    mock_confluence(handler)

    page = await crawl_page("1", base_url="https://x", email="a", api_token="t")
    assert page.title == "OK"
    assert call_count["n"] == 2
```

- [ ] **Step 2: Run the tests**

```bash
pytest tests/unit/test_confluence_crawler.py -v
```
Expected: all tests pass.

- [ ] **Step 3: Commit**

```bash
git add tests/unit/test_confluence_crawler.py
git commit -m "test: add unit tests for Confluence crawler (retry + error paths)"
```

---

## Task 6: Unit tests — mcp_server.py

**Files:**
- Create: `tests/unit/test_mcp_server.py`

- [ ] **Step 1: Write the tests**

```python
"""Tests for docforge.mcp_server — search_documentation and list_sources.

We patch module globals (_get_settings, _get_embedder) and the get_pool
helper so the tests do not need a real DB or model.
"""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest


class _FakeConn:
    def __init__(self, rows):
        self._rows = rows

    async def fetch(self, query, *args):
        return self._rows


class _AcquireCtx:
    def __init__(self, rows):
        self._rows = rows

    async def __aenter__(self):
        return _FakeConn(self._rows)

    async def __aexit__(self, *a):
        return None


class FakePool:
    def __init__(self, rows):
        self._rows = rows

    def acquire(self):
        return _AcquireCtx(self._rows)


@pytest.fixture
def patch_mcp_deps(monkeypatch):
    """Return an installer: patch_mcp_deps(rows) wires up the module."""

    def _install(rows):
        from docforge import mcp_server as mod

        fake_pool = FakePool(rows)

        async def fake_get_pool(url):
            return fake_pool

        fake_embedder = MagicMock()
        fake_embedder.embed_query.return_value = [0.0] * 768

        monkeypatch.setattr(mod, "get_pool", fake_get_pool)
        monkeypatch.setattr(mod, "_get_embedder", lambda: fake_embedder)
        monkeypatch.setattr(
            mod,
            "_get_settings",
            lambda: SimpleNamespace(database_url="postgresql://fake"),
        )
        return fake_embedder

    return _install


@pytest.mark.asyncio
async def test_search_documentation_formats_results(patch_mcp_deps):
    rows = [
        {
            "text": "Platform team owns organization lifecycle.",
            "section_title": "Platform",
            "source_title": "Team Responsibilities",
            "source_url": "https://wiki/page/1",
            "similarity": 0.92,
        },
        {
            "text": "Imaging team owns document rendering.",
            "section_title": None,
            "source_title": "Team Responsibilities",
            "source_url": "https://wiki/page/1",
            "similarity": 0.81,
        },
    ]
    fake_embedder = patch_mcp_deps(rows)

    from docforge.mcp_server import search_documentation

    result = await search_documentation("who owns orgs", limit=5)

    assert "Platform team owns organization lifecycle." in result
    assert "Imaging team owns document rendering." in result
    assert "0.92" in result
    assert "Team Responsibilities" in result
    fake_embedder.embed_query.assert_called_once_with("who owns orgs")


@pytest.mark.asyncio
async def test_search_documentation_empty_returns_hint(patch_mcp_deps):
    patch_mcp_deps([])

    from docforge.mcp_server import search_documentation

    result = await search_documentation("anything")
    assert "No documentation found" in result
    assert "docforge ingest" in result


@pytest.mark.asyncio
async def test_list_sources_formats_entries(patch_mcp_deps):
    rows = [
        {
            "title": "Doc A",
            "url": "https://wiki/a",
            "status": "active",
            "last_crawled_at": datetime(2026, 4, 17, 9, 30, tzinfo=timezone.utc),
            "chunk_count": 12,
        },
        {
            "title": "Doc B",
            "url": "https://wiki/b",
            "status": "active",
            "last_crawled_at": None,
            "chunk_count": 0,
        },
    ]
    patch_mcp_deps(rows)

    from docforge.mcp_server import list_sources

    result = await list_sources()
    assert "Doc A" in result
    assert "12 chunks" in result
    assert "Doc B" in result
    assert "never" in result


@pytest.mark.asyncio
async def test_list_sources_empty_returns_hint(patch_mcp_deps):
    patch_mcp_deps([])

    from docforge.mcp_server import list_sources

    result = await list_sources()
    assert "No sources indexed" in result
```

- [ ] **Step 2: Run the tests**

```bash
pytest tests/unit/test_mcp_server.py -v
```
Expected: all tests pass.

Note: `@mcp.tool()` in FastMCP 2.x returns the original function unchanged, so calling `search_documentation(...)` directly works. If the executor finds this is not the case in the installed FastMCP version, access the underlying callable via `search_documentation.__wrapped__` or `mcp._tools["search_documentation"].fn`.

- [ ] **Step 3: Commit**

```bash
git add tests/unit/test_mcp_server.py
git commit -m "test: add unit tests for MCP server tools (search_documentation, list_sources)"
```

---

## Task 7: Extend test_api.py

**Files:**
- Modify: `tests/unit/test_api.py`

- [ ] **Step 1: Replace the entire file**

```python
"""Tests for docforge.api FastAPI endpoints."""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

from docforge import api as api_module
from docforge.api import app


class _FakeConn:
    def __init__(self, rows):
        self._rows = rows

    async def fetch(self, query, *args):
        return self._rows


class _AcquireCtx:
    def __init__(self, rows):
        self._rows = rows

    async def __aenter__(self):
        return _FakeConn(self._rows)

    async def __aexit__(self, *a):
        return None


class FakePool:
    def __init__(self, rows):
        self._rows = rows

    def acquire(self):
        return _AcquireCtx(self._rows)


async def _client():
    transport = ASGITransport(app=app)
    return AsyncClient(transport=transport, base_url="http://test")


class TestHealthEndpoint:
    @pytest.mark.asyncio
    async def test_health_returns_ok(self):
        async with await _client() as client:
            resp = await client.get("/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"


class TestSearchEndpoint:
    @pytest.mark.asyncio
    async def test_returns_503_when_model_not_loaded(self):
        original = api_module._embedder
        api_module._embedder = None
        try:
            async with await _client() as client:
                resp = await client.post("/search", json={"query": "q", "limit": 1})
            assert resp.status_code == 503
            assert "not loaded" in resp.json()["detail"]
        finally:
            api_module._embedder = original

    @pytest.mark.asyncio
    async def test_returns_results_on_success(self, monkeypatch):
        rows = [
            {
                "text": "Platform owns orgs.",
                "section_title": "Platform",
                "source_title": "Doc A",
                "source_url": "https://wiki/a",
                "similarity": 0.95,
            }
        ]

        fake_embedder = MagicMock()
        fake_embedder.embed_query.return_value = [0.0] * 768
        fake_embedder.model_name = "fake"
        api_module._embedder = fake_embedder

        fake_pool = FakePool(rows)

        async def fake_get_pool(url):
            return fake_pool

        monkeypatch.setattr(api_module, "get_pool", fake_get_pool)
        monkeypatch.setattr(
            api_module,
            "_get_settings",
            lambda: SimpleNamespace(database_url="postgresql://fake"),
        )

        try:
            async with await _client() as client:
                resp = await client.post("/search", json={"query": "q", "limit": 5})
        finally:
            api_module._embedder = None

        assert resp.status_code == 200
        body = resp.json()
        assert body["count"] == 1
        assert body["results"][0]["text"] == "Platform owns orgs."
        assert body["results"][0]["similarity"] == pytest.approx(0.95)

    @pytest.mark.asyncio
    async def test_returns_503_on_db_error(self, monkeypatch):
        fake_embedder = MagicMock()
        fake_embedder.embed_query.return_value = [0.0] * 768
        api_module._embedder = fake_embedder

        async def fake_get_pool(url):
            raise OSError("db down")

        monkeypatch.setattr(api_module, "get_pool", fake_get_pool)
        monkeypatch.setattr(
            api_module,
            "_get_settings",
            lambda: SimpleNamespace(database_url="postgresql://fake"),
        )

        try:
            async with await _client() as client:
                resp = await client.post("/search", json={"query": "q", "limit": 1})
        finally:
            api_module._embedder = None

        assert resp.status_code == 503
        assert "Database unavailable" in resp.json()["detail"]

    @pytest.mark.asyncio
    async def test_returns_500_on_embed_error(self, monkeypatch):
        fake_embedder = MagicMock()
        fake_embedder.embed_query.side_effect = RuntimeError("embed broken")
        api_module._embedder = fake_embedder

        try:
            async with await _client() as client:
                resp = await client.post("/search", json={"query": "q", "limit": 1})
        finally:
            api_module._embedder = None

        assert resp.status_code == 500
        assert "embed" in resp.json()["detail"].lower()


class TestSourcesEndpoint:
    @pytest.mark.asyncio
    async def test_lists_sources(self, monkeypatch):
        rows = [
            {
                "title": "Doc A",
                "url": "https://wiki/a",
                "status": "active",
                "last_crawled_at": datetime(2026, 4, 17, 9, 0, tzinfo=timezone.utc),
                "chunk_count": 4,
            }
        ]
        fake_pool = FakePool(rows)

        async def fake_get_pool(url):
            return fake_pool

        monkeypatch.setattr(api_module, "get_pool", fake_get_pool)
        monkeypatch.setattr(
            api_module,
            "_get_settings",
            lambda: SimpleNamespace(database_url="postgresql://fake"),
        )

        async with await _client() as client:
            resp = await client.get("/sources")

        assert resp.status_code == 200
        body = resp.json()
        assert body["count"] == 1
        assert body["sources"][0]["title"] == "Doc A"
        assert body["sources"][0]["chunk_count"] == 4

    @pytest.mark.asyncio
    async def test_returns_503_on_db_error(self, monkeypatch):
        async def fake_get_pool(url):
            raise OSError("boom")

        monkeypatch.setattr(api_module, "get_pool", fake_get_pool)
        monkeypatch.setattr(
            api_module,
            "_get_settings",
            lambda: SimpleNamespace(database_url="postgresql://fake"),
        )

        async with await _client() as client:
            resp = await client.get("/sources")

        assert resp.status_code == 503
```

- [ ] **Step 2: Run the tests**

```bash
pytest tests/unit/test_api.py -v
```
Expected: all tests pass.

- [ ] **Step 3: Commit**

```bash
git add tests/unit/test_api.py
git commit -m "test: extend API tests with search success, /sources, and error paths"
```

---

## Task 8: Unit tests — ingest.py

**Files:**
- Create: `tests/unit/test_ingest.py`

- [ ] **Step 1: Write the tests**

```python
"""Tests for docforge.ingest — the end-to-end ingest pipeline.

All heavy dependencies are mocked: the Embedder is replaced via the
fake_embedder fixture; asyncpg pool/connection are fakes; crawlers are
monkeypatched to return in-memory objects.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from docforge import ingest as ingest_mod
from docforge.ingest import _parse_markdown, ingest_all


class TestParseMarkdown:
    def test_parses_headings_and_body(self):
        content = "# Title\n\nIntro text.\n\n## Details\n\nBody text."
        sections = _parse_markdown(content)
        assert len(sections) == 2
        assert sections[0].title == "Title"
        assert "Intro text." in sections[0].text
        assert sections[0].level == 1
        assert sections[1].title == "Details"
        assert sections[1].level == 2

    def test_no_headings_produces_single_section_with_empty_title(self):
        sections = _parse_markdown("Just some paragraph text.")
        assert len(sections) == 1
        assert sections[0].title == ""
        assert "paragraph" in sections[0].text

    def test_empty_content_returns_empty(self):
        assert _parse_markdown("") == []

    def test_empty_section_body_dropped(self):
        sections = _parse_markdown("# A\n\n# B\n\nContent.")
        # Section A has no body between its heading and B's heading
        titles = [s.title for s in sections]
        assert "B" in titles
        assert all(s.text.strip() for s in sections)


class _Conn:
    def __init__(self, existing_hash=None):
        self.existing_hash = existing_hash
        self.inserted_sources = []
        self.inserted_chunks = []
        self.executed = []

    async def fetchval(self, query, *args):
        if "source_id" in query.lower() or "RETURNING id" in query:
            self.inserted_sources.append(args)
            return "fake-source-id"
        if "content_hash" in query:
            return self.existing_hash
        return None

    async def fetch(self, query, *args):
        return []

    async def execute(self, query, *args):
        self.executed.append(query)
        if "INSERT INTO chunks" in query:
            self.inserted_chunks.append(args)


class _Tx:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return None


class _AcquireCtx:
    def __init__(self, conn):
        self._conn = conn

    async def __aenter__(self):
        return self._conn

    async def __aexit__(self, *a):
        return None


class _FakePool:
    def __init__(self, conn):
        self._conn = conn
        self._conn.transaction = lambda: _Tx()

    def acquire(self):
        return _AcquireCtx(self._conn)


@pytest.mark.asyncio
async def test_ingest_all_with_empty_sources_list(
    tmp_path, monkeypatch, fake_embedder
):
    sources_file = tmp_path / "sources.yml"
    sources_file.write_text("sources: []\n")

    conn = _Conn()

    async def fake_get_pool(url):
        return _FakePool(conn)

    monkeypatch.setattr(ingest_mod, "get_pool", fake_get_pool)

    from docforge.config import Settings

    settings = Settings(sources_file=str(sources_file))

    # Should return cleanly with no work done
    await ingest_all(settings)
    assert conn.inserted_sources == []


@pytest.mark.asyncio
async def test_ingest_git_source_inserts_chunks(
    tmp_path, monkeypatch, fake_embedder
):
    # Build a fake git repo
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "README.md").write_text("# Title\n\nContent one.\n\n## Sub\n\nContent two.")

    sources_file = tmp_path / "sources.yml"
    sources_file.write_text(
        "sources:\n"
        "  - type: git_repo\n"
        f'    repo_path: "{repo}"\n'
        "    include_patterns: [\"README.md\"]\n"
        "    title: \"RepoX\"\n"
    )

    conn = _Conn(existing_hash=None)

    async def fake_get_pool(url):
        return _FakePool(conn)

    monkeypatch.setattr(ingest_mod, "get_pool", fake_get_pool)

    from docforge.config import Settings

    settings = Settings(sources_file=str(sources_file))

    await ingest_all(settings)

    assert len(conn.inserted_sources) == 1
    assert len(conn.inserted_chunks) >= 1  # at least one chunk stored


@pytest.mark.asyncio
async def test_ingest_skips_when_hash_unchanged(
    tmp_path, monkeypatch, fake_embedder
):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "README.md").write_text("# Title\n\nUnchanged content.")

    sources_file = tmp_path / "sources.yml"
    sources_file.write_text(
        "sources:\n"
        "  - type: git_repo\n"
        f'    repo_path: "{repo}"\n'
        "    include_patterns: [\"README.md\"]\n"
        "    title: \"RepoX\"\n"
    )

    import hashlib

    content = (repo / "README.md").read_text()
    existing_hash = hashlib.sha256(content.encode()).hexdigest()

    conn = _Conn(existing_hash=existing_hash)

    async def fake_get_pool(url):
        return _FakePool(conn)

    monkeypatch.setattr(ingest_mod, "get_pool", fake_get_pool)

    from docforge.config import Settings

    settings = Settings(sources_file=str(sources_file))

    await ingest_all(settings)

    # No new inserts because hash matches
    assert conn.inserted_chunks == []


@pytest.mark.asyncio
async def test_ingest_continues_on_per_source_failure(
    tmp_path, monkeypatch, fake_embedder, caplog
):
    # Two git sources — first points to a missing path (crawl_repo returns []),
    # second has real content. Pipeline should complete with logs about failure
    # counts.
    repo_ok = tmp_path / "ok"
    repo_ok.mkdir()
    (repo_ok / "README.md").write_text("# OK\n\nContent.")

    sources_file = tmp_path / "sources.yml"
    sources_file.write_text(
        "sources:\n"
        "  - type: git_repo\n"
        '    repo_path: "E:/definitely/missing/repo"\n'
        "    include_patterns: [\"README.md\"]\n"
        "    title: \"Missing\"\n"
        "  - type: git_repo\n"
        f'    repo_path: "{repo_ok}"\n'
        "    include_patterns: [\"README.md\"]\n"
        "    title: \"OK\"\n"
    )

    conn = _Conn()

    async def fake_get_pool(url):
        return _FakePool(conn)

    monkeypatch.setattr(ingest_mod, "get_pool", fake_get_pool)

    from docforge.config import Settings

    settings = Settings(sources_file=str(sources_file))

    await ingest_all(settings)
    # Missing repo yields no files; OK repo yields chunks. Both counted as
    # "succeeded" because crawl_repo returns [] gracefully without raising.
    assert len(conn.inserted_chunks) >= 1
```

- [ ] **Step 2: Run the tests**

```bash
pytest tests/unit/test_ingest.py -v
```
Expected: all tests pass. If `test_ingest_git_source_inserts_chunks` fails on the `fetchval` mock, inspect the SQL the ingest actually runs and adjust the fake's `fetchval` branching.

- [ ] **Step 3: Commit**

```bash
git add tests/unit/test_ingest.py
git commit -m "test: add unit tests for ingest pipeline (git source, hash skip, per-source failures)"
```

---

## Task 9: Unit tests — cli.py

**Files:**
- Create: `tests/unit/test_cli.py`

- [ ] **Step 1: Write the tests**

```python
"""Tests for docforge.cli Typer commands via CliRunner.

The CLI commands delegate to async helpers (_init_db, _ingest, _search,
_status) which we patch so tests never touch a real DB or model.
"""

from __future__ import annotations

import pytest
from typer.testing import CliRunner

from docforge.cli import app

runner = CliRunner()


class TestInit:
    def test_init_creates_project_directory(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        result = runner.invoke(app, ["init", "myproj"])
        assert result.exit_code == 0
        assert (tmp_path / "myproj").is_dir()
        assert "scaffolded" in result.stdout.lower() or "created" in result.stdout.lower()

    def test_init_fails_if_directory_exists(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        (tmp_path / "exists").mkdir()
        result = runner.invoke(app, ["init", "exists"])
        assert result.exit_code == 1
        assert "already exists" in result.stdout


class TestInitDb:
    def test_success(self, monkeypatch):
        async def fake(): return None
        monkeypatch.setattr("docforge.cli._init_db", fake)
        result = runner.invoke(app, ["init-db"])
        assert result.exit_code == 0


class TestIngestCommand:
    def test_success(self, monkeypatch):
        called = {"n": 0}

        async def fake():
            called["n"] += 1

        monkeypatch.setattr("docforge.cli._ingest", fake)
        result = runner.invoke(app, ["ingest"])
        assert result.exit_code == 0
        assert called["n"] == 1


class TestSearchCommand:
    def test_success(self, monkeypatch):
        captured = {}

        async def fake(query, limit):
            captured["query"] = query
            captured["limit"] = limit

        monkeypatch.setattr("docforge.cli._search", fake)
        result = runner.invoke(app, ["search", "how do migrations work", "--limit", "3"])
        assert result.exit_code == 0
        assert captured == {"query": "how do migrations work", "limit": 3}


class TestStatusCommand:
    def test_success(self, monkeypatch):
        async def fake(): return None
        monkeypatch.setattr("docforge.cli._status", fake)
        result = runner.invoke(app, ["status"])
        assert result.exit_code == 0


class TestServeCommand:
    def test_serve_mcp_calls_mcp_run(self, monkeypatch):
        calls = {"mcp": 0, "uvicorn": 0}

        class FakeMCP:
            def run(self):
                calls["mcp"] += 1

        monkeypatch.setattr("docforge.mcp_server.mcp", FakeMCP())
        result = runner.invoke(app, ["serve"])
        assert result.exit_code == 0
        assert calls["mcp"] == 1

    def test_serve_api_calls_uvicorn(self, monkeypatch):
        calls = {"n": 0}

        def fake_run(app, **kwargs):
            calls["n"] += 1

        monkeypatch.setattr("uvicorn.run", fake_run)
        result = runner.invoke(app, ["serve", "--api"])
        assert result.exit_code == 0
        assert calls["n"] == 1


class TestHelperCoroutines:
    """Drive the private _init_db / _ingest / _search helpers directly with
    mocked dependencies to exercise their error-handling branches."""

    @pytest.mark.asyncio
    async def test_init_db_os_error_exits_with_1(self, monkeypatch, capsys):
        async def fake_init_db(url):
            raise OSError("no db")

        monkeypatch.setattr("docforge.db.init_db", fake_init_db)

        import typer

        from docforge.cli import _init_db

        with pytest.raises(typer.Exit) as ex:
            await _init_db()
        assert ex.value.exit_code == 1

    @pytest.mark.asyncio
    async def test_ingest_os_error_exits_with_1(self, monkeypatch):
        async def fake_ingest_all(settings):
            raise OSError("no db")

        async def fake_close():
            return None

        monkeypatch.setattr("docforge.ingest.ingest_all", fake_ingest_all)
        monkeypatch.setattr("docforge.db.close_pool", fake_close)

        import typer

        from docforge.cli import _ingest

        with pytest.raises(typer.Exit) as ex:
            await _ingest()
        assert ex.value.exit_code == 1
```

- [ ] **Step 2: Run the tests**

```bash
pytest tests/unit/test_cli.py -v
```
Expected: all tests pass. If `test_init_creates_project_directory` fails because the template files reference absolute paths, fall back to asserting only that the directory was created.

- [ ] **Step 3: Commit**

```bash
git add tests/unit/test_cli.py
git commit -m "test: add CLI tests for all Typer commands and key error branches"
```

---

## Task 10: Unit test — __main__.py

**Files:**
- Create: `tests/unit/test_main_module.py`

- [ ] **Step 1: Write the test**

```python
"""Tests that `python -m docforge` dispatches to the Typer app."""

from __future__ import annotations

import subprocess
import sys


def test_module_entrypoint_help_exits_zero():
    result = subprocess.run(
        [sys.executable, "-m", "docforge", "--help"],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0
    assert "Forge searchable context" in result.stdout or "Usage" in result.stdout
```

- [ ] **Step 2: Run the test**

```bash
pytest tests/unit/test_main_module.py -v
```
Expected: passes.

- [ ] **Step 3: Commit**

```bash
git add tests/unit/test_main_module.py
git commit -m "test: add smoke test for python -m docforge entrypoint"
```

---

## Task 11: Integration test fixtures — pg_container, pg_url

**Files:**
- Create: `tests/integration/conftest.py`

- [ ] **Step 1: Write the conftest**

```python
"""Integration test fixtures — pgvector testcontainer + schema setup.

Session-scoped container (one startup per pytest run, ~10s cold start)
with a function-scoped URL fixture that applies the schema and truncates
between tests for isolation.

All tests in this directory are auto-marked with @pytest.mark.integration.
"""

from __future__ import annotations

import pytest
from testcontainers.postgres import PostgresContainer


def pytest_collection_modifyitems(config, items):
    """Auto-mark all tests in this directory as integration."""
    for item in items:
        if "tests/integration" in str(item.fspath).replace("\\", "/"):
            item.add_marker(pytest.mark.integration)


@pytest.fixture(scope="session")
def pg_container():
    """One pgvector container for the whole test session."""
    with PostgresContainer("pgvector/pgvector:pg16") as pg:
        yield pg


@pytest.fixture
async def pg_url(pg_container):
    """Fresh schema per test; truncate between tests for isolation."""
    url = pg_container.get_connection_url()
    # asyncpg uses postgresql://, not postgresql+psycopg2://
    if url.startswith("postgresql+psycopg2://"):
        url = url.replace("postgresql+psycopg2://", "postgresql://")
    elif url.startswith("postgresql+psycopg://"):
        url = url.replace("postgresql+psycopg://", "postgresql://")

    from docforge.db import close_pool, init_db

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

- [ ] **Step 2: Verify Docker is running and try to start the container manually**

```bash
docker ps
docker pull pgvector/pgvector:pg16
```
Expected: Docker responds; image pulls successfully.

- [ ] **Step 3: Run a quick smoke that the fixture works**

Create a temporary scratch file `tests/integration/test_smoke.py`:

```python
import asyncpg
import pytest


@pytest.mark.asyncio
async def test_container_starts_and_url_connects(pg_url):
    conn = await asyncpg.connect(pg_url)
    try:
        ver = await conn.fetchval("SELECT version()")
        assert "PostgreSQL" in ver
    finally:
        await conn.close()
```

Run:
```bash
pytest tests/integration/test_smoke.py -v -m integration
```
Expected: test passes. Delete `test_smoke.py` afterward.

- [ ] **Step 4: Remove smoke test and commit**

```bash
rm tests/integration/test_smoke.py
git add tests/integration/conftest.py
git commit -m "test: add testcontainers pgvector fixture for integration tests"
```

---

## Task 12: Integration test — db schema

**Files:**
- Create: `tests/integration/test_db_schema.py`

- [ ] **Step 1: Write the test**

```python
"""Integration test: verify init_db creates the expected schema and pgvector."""

from __future__ import annotations

import asyncpg
import numpy as np
import pytest
from pgvector.asyncpg import register_vector


@pytest.mark.asyncio
async def test_init_db_creates_schema_and_pgvector(pg_url):
    conn = await asyncpg.connect(pg_url)
    try:
        # pgvector extension present
        ext = await conn.fetchval(
            "SELECT extname FROM pg_extension WHERE extname = 'vector'"
        )
        assert ext == "vector"

        # Expected tables exist
        tables = await conn.fetch(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = 'public' AND table_name IN ('sources', 'chunks')"
        )
        names = {row["table_name"] for row in tables}
        assert names == {"sources", "chunks"}

        # Vector column round-trips
        await register_vector(conn)
        source_id = await conn.fetchval(
            """
            INSERT INTO sources (type, url, title, status)
            VALUES ('git_repo', 'file:///tmp/a', 'A', 'active')
            RETURNING id
            """
        )
        vec = np.zeros(768, dtype=np.float32)
        vec[0] = 1.0
        await conn.execute(
            """
            INSERT INTO chunks (source_id, chunk_index, text, embedding, section_title)
            VALUES ($1, 0, 'some text', $2, 'sec')
            """,
            source_id,
            vec,
        )
        returned = await conn.fetchval(
            "SELECT embedding FROM chunks WHERE source_id = $1", source_id
        )
        assert returned is not None
        assert len(returned) == 768
    finally:
        await conn.close()
```

- [ ] **Step 2: Run the test**

```bash
pytest tests/integration/test_db_schema.py -v -m integration
```
Expected: passes.

- [ ] **Step 3: Commit**

```bash
git add tests/integration/test_db_schema.py
git commit -m "test(integration): verify db schema + pgvector extension + vector round-trip"
```

---

## Task 13: Integration test — end-to-end git ingest + search

**Files:**
- Create: `tests/integration/test_ingest_git_integration.py`

- [ ] **Step 1: Write the test**

```python
"""End-to-end integration: ingest a git repo and query the DB like the API does.

Uses the FakeEmbedder from tests/conftest.py so we don't need to load the
real 300M model. This exercises the git crawler + parser + chunker + DB
insert path against a real pgvector instance.
"""

from __future__ import annotations

import asyncpg
import numpy as np
import pytest
from pgvector.asyncpg import register_vector

from docforge import ingest as ingest_mod
from docforge.config import Settings
from docforge.ingest import ingest_all


@pytest.mark.asyncio
async def test_end_to_end_ingest_and_search(
    tmp_path, pg_url, fake_embedder, monkeypatch
):
    # Build a fake git repo with two markdown files
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "README.md").write_text(
        "# Project\n\nThis project does orgs.\n\n## Details\n\nPlatform team owns it."
    )
    (repo / "CLAUDE.md").write_text(
        "# Claude Guide\n\nUse docforge for cross-team knowledge."
    )

    sources_file = tmp_path / "sources.yml"
    sources_file.write_text(
        "sources:\n"
        "  - type: git_repo\n"
        f'    repo_path: "{repo.as_posix()}"\n'
        "    include_patterns: [\"README.md\", \"CLAUDE.md\"]\n"
        "    title: \"TestRepo\"\n"
    )

    settings = Settings(sources_file=str(sources_file), database_url=pg_url)

    await ingest_all(settings)

    # Verify data landed
    conn = await asyncpg.connect(pg_url)
    try:
        await register_vector(conn)

        source_count = await conn.fetchval("SELECT count(*) FROM sources")
        chunk_count = await conn.fetchval("SELECT count(*) FROM chunks")
        assert source_count == 2
        assert chunk_count >= 2

        # Run the same query shape that api.py /search issues
        query_vec = np.zeros(768, dtype=np.float32)
        query_vec[767] = 0.001
        rows = await conn.fetch(
            """
            SELECT c.text, s.title AS source_title,
                   1 - (c.embedding <=> $1::vector) AS similarity
            FROM chunks c JOIN sources s ON c.source_id = s.id
            WHERE s.status = 'active'
            ORDER BY c.embedding <=> $1::vector
            LIMIT 5
            """,
            query_vec,
        )
        assert len(rows) >= 2
        for row in rows:
            assert row["source_title"].startswith("TestRepo")
    finally:
        await conn.close()
```

- [ ] **Step 2: Run the test**

```bash
pytest tests/integration/test_ingest_git_integration.py -v -m integration
```
Expected: passes.

- [ ] **Step 3: Commit**

```bash
git add tests/integration/test_ingest_git_integration.py
git commit -m "test(integration): end-to-end git ingest + search against pgvector"
```

---

## Task 14: Checkpoint — full test run and coverage report

- [ ] **Step 1: Run everything**

```bash
pytest
```
Expected: all tests (unit + integration) pass. Coverage report prints. Gate `fail_under = 60` is satisfied.

- [ ] **Step 2: If coverage <60%, inspect and extend**

Review which modules fall short. Likely candidates for quick wins:
- `parser.py` (84%) and `chunker.py` (88%) — add tests for uncovered branches reported by coverage.
- `cli.py` helper coroutines — `_search` and `_status` branches.

Do not proceed until the gate passes.

- [ ] **Step 3: Record current coverage in a commit-amend-safe way**

Just commit any additional tests you added:
```bash
git add tests/
git commit -m "test: backfill tests for coverage gate"
```
Skip this commit if no new tests were needed.

---

## Task 15: Fix type hints

**Files:**
- Modify: `docforge/ingest.py`
- Modify: `docforge/api.py`
- Modify: `docforge/config.py`
- Modify: `docforge/processors/embedder.py`

- [ ] **Step 1: Fix `ingest.py` — replace `callable` with `Callable[[str], int]`**

At the top of `docforge/ingest.py`, add to imports:

```python
from typing import Callable
```

Replace each occurrence of `tokenizer_fn: callable,` with `tokenizer_fn: Callable[[str], int],` in `_ingest_confluence_source` and `_ingest_git_source` signatures.

- [ ] **Step 2: Fix `docforge/processors/embedder.py` — `get_tokenizer_fn` return type**

At the top add:
```python
from typing import Callable
```

Change the signature:
```python
def get_tokenizer_fn(self) -> Callable[[str], int]:
```

- [ ] **Step 3: Fix `docforge/api.py` — typed dict returns**

At the top add:
```python
from typing import Any
```

Change `/health` and `/sources` handler signatures:
```python
async def health() -> dict[str, Any]:
    ...

async def list_sources() -> dict[str, Any]:
    ...
```

- [ ] **Step 4: Fix `docforge/config.py` — `__init__` return type**

Change:
```python
def __init__(self, **kwargs) -> None:
```

- [ ] **Step 5: Run tests to ensure nothing broke**

```bash
pytest -m "not integration"
```
Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add docforge/ingest.py docforge/api.py docforge/config.py docforge/processors/embedder.py
git commit -m "types: replace 'callable' with Callable[[str], int]; add missing return types"
```

---

## Task 16: Add module-level and public-function docstrings

**Files:**
- Modify: `docforge/__main__.py`
- Modify: `docforge/config.py`
- Modify: `docforge/db.py`
- Modify: `docforge/ingest.py`
- Modify: `docforge/sources.py`
- Modify: `docforge/crawlers/__init__.py`
- Modify: `docforge/crawlers/confluence.py`
- Modify: `docforge/processors/__init__.py`
- Modify: `docforge/processors/chunker.py`
- Modify: `docforge/processors/parser.py`

The following modules already have module-level docstrings: `cli.py`, `api.py`, `mcp_server.py`, `crawlers/git.py`, `processors/embedder.py`. Do not duplicate those.

- [ ] **Step 1: Add module docstring to `docforge/__main__.py`**

Prepend to the file:
```python
"""Module entrypoint — `python -m docforge` dispatches to the Typer app."""

from docforge.cli import app

app()
```

- [ ] **Step 2: Add module docstring to `docforge/config.py`**

Prepend (before `from __future__ import ...`):
```python
"""Settings loading — merges defaults, docforge.yml, .env, env vars, and kwargs.

Precedence (lowest to highest): defaults → docforge.yml → .env → env vars → kwargs.
"""

from __future__ import annotations
```

- [ ] **Step 3: Add module docstring to `docforge/db.py`**

```python
"""asyncpg connection pool + pgvector registration.

Module-level `_pool` is created lazily on first `get_pool()` call and
shared across all callers. `init_db()` applies the packaged schema.sql
and any migration scripts.
"""

from __future__ import annotations
```

- [ ] **Step 4: Add module docstring to `docforge/ingest.py`**

```python
"""Ingest pipeline — crawl → parse → chunk → embed → store.

`ingest_all` loads the sources list and runs the appropriate crawler for
each source type (Confluence page or local git repo). Per-source failures
are logged but do not abort the run.
"""

from __future__ import annotations
```

- [ ] **Step 5: Add module docstring to `docforge/sources.py`**

```python
"""Source configuration — pydantic models + YAML loader.

Each entry in `sources.yml` is a ConfluenceSourceConfig or a
GitRepoSourceConfig, discriminated by the `type` field.
"""

from __future__ import annotations
```

- [ ] **Step 6: Add module docstring to `docforge/crawlers/__init__.py`**

```python
"""Source crawlers — Confluence REST API and local git repo file walkers."""
```

- [ ] **Step 7: Add module docstring to `docforge/crawlers/confluence.py`**

Prepend:
```python
"""Confluence REST API v2 page crawler with retry logic for transient errors."""

from __future__ import annotations
```

- [ ] **Step 8: Add module docstring to `docforge/processors/__init__.py`**

```python
"""Text processors — HTML parser, token-aware chunker, embedder."""
```

- [ ] **Step 9: Add module docstring to `docforge/processors/chunker.py`**

Prepend:
```python
"""Token-aware chunker — splits sections into chunks under a token limit."""

from __future__ import annotations
```

- [ ] **Step 10: Add module docstring to `docforge/processors/parser.py`**

Prepend:
```python
"""Confluence storage-format HTML parser — yields Section objects."""

from __future__ import annotations
```

- [ ] **Step 11: Audit public functions lacking docstrings**

Run:
```bash
python -c "
import ast, pathlib
for p in pathlib.Path('docforge').rglob('*.py'):
    tree = ast.parse(p.read_text(encoding='utf-8'))
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name.startswith('_'): continue
            if not (node.body and isinstance(node.body[0], ast.Expr) and isinstance(node.body[0].value, ast.Constant) and isinstance(node.body[0].value.value, str)):
                print(f'{p}:{node.lineno}: {node.name}')
"
```

Add a concise one-line docstring to any public function listed. Keep it to one sentence describing behavior, no Args/Returns sections.

- [ ] **Step 12: Run tests**

```bash
pytest -m "not integration"
```
Expected: all pass.

- [ ] **Step 13: Commit**

```bash
git add docforge/
git commit -m "docs: add module-level and public-function docstrings"
```

---

## Task 17: Rewrite Dockerfile

**Files:**
- Modify: `Dockerfile`

- [ ] **Step 1: Replace the entire file**

```dockerfile
FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc libpq-dev && \
    rm -rf /var/lib/apt/lists/*

COPY pyproject.toml .
RUN pip install --no-cache-dir "."

COPY docforge/ docforge/

RUN useradd -m -u 1000 docforge && \
    mkdir -p /app/.cache/huggingface && \
    chown -R docforge:docforge /app

USER docforge

ENV HF_HOME=/app/.cache/huggingface

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=300s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8000/health').read() else 1)"

CMD ["uvicorn", "docforge.api:app", "--host", "0.0.0.0", "--port", "8000"]
```

Key differences from the previous Dockerfile:
- Dropped `ARG HF_TOKEN` and the model pre-download step
- Added non-root user (UID 1000) with proper `/app` chown
- Added `ENV HF_HOME=/app/.cache/huggingface` for mountable cache
- Added HEALTHCHECK using Python stdlib (no curl install)
- 300s `start-period` covers first-start model download

- [ ] **Step 2: Build the image**

```bash
docker build -t docforge:phase3 .
```
Expected: build succeeds without requiring `--build-arg HF_TOKEN=...`.

- [ ] **Step 3: Verify HEALTHCHECK and user**

```bash
docker inspect docforge:phase3 --format '{{json .Config.Healthcheck}}'
docker inspect docforge:phase3 --format 'User: {{.Config.User}}'
```
Expected: HEALTHCHECK JSON with `Test` array containing `python -c ...`; `User: docforge`.

- [ ] **Step 4: Commit**

```bash
git add Dockerfile
git commit -m "docker: add HEALTHCHECK, non-root user, HF_HOME; drop build-time model pre-download"
```

---

## Task 18: Create .dockerignore

**Files:**
- Create: `.dockerignore`

- [ ] **Step 1: Create `.dockerignore` at repo root**

```
.venv/
.git/
__pycache__/
*.pyc
*.pyo
tests/
.pytest_cache/
.coverage
*.egg-info/
docs/
infrastructure/
.ruff_cache/
*.log
```

- [ ] **Step 2: Verify build context size dropped**

```bash
docker build -t docforge:phase3-ignored . 2>&1 | grep "transferring context"
```
Expected: context size dramatically smaller than the pre-ignore build (was ~300MB with `.venv/`, should be ~1MB now).

- [ ] **Step 3: Commit**

```bash
git add .dockerignore
git commit -m "docker: add .dockerignore to cut build context"
```

---

## Task 19: Add README troubleshooting section

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Insert troubleshooting section before `## License`**

Open `README.md`. Find the `## License` line. Insert the following block immediately above it (with a blank line separator):

```markdown
## Troubleshooting

### "Cannot connect to PostgreSQL"
Check that the database is running: `docker compose up -d db`. Verify `DATABASE_URL` in `.env` points to `postgresql://docforge:localdev@localhost:5432/docforge` (or your custom value).

### "HF_TOKEN required" or model download fails
The embedding model `google/embeddinggemma-300m` requires a Hugging Face token with access to the gated model. Create one at https://huggingface.co/settings/tokens, accept the model license at https://huggingface.co/google/embeddinggemma-300m, and set `HF_TOKEN=hf_...` in `.env`.

### "No results found" after ingest
Run `docforge status` to confirm sources and chunks exist. If counts are zero, check the ingest logs for per-source failures — the summary at the end lists sources that failed.

### First ingest / first container start is very slow
The first run downloads the 300M embedding model (~1.2GB) from Hugging Face. Locally, the model is cached at `~/.cache/huggingface/`. In the Docker image, it is cached at `/app/.cache/huggingface/` — **mount this as a volume** so container restarts don't re-download: `docker run -v docforge-hf-cache:/app/.cache/huggingface ...`.

### "Ingest skipped everything"
docforge skips sources whose `content_hash` matches the stored hash (no changes detected). To force re-ingest, clear the hash: `UPDATE sources SET content_hash = NULL;` then run `docforge ingest`.

```

- [ ] **Step 2: Commit**

```bash
git add README.md
git commit -m "docs: add troubleshooting section to README"
```

---

## Task 20: Final verification

- [ ] **Step 1: Run the full test suite**

```bash
pytest
```
Expected: all unit + integration tests pass. Coverage ≥60%. Gate satisfied.

- [ ] **Step 2: Run fast-path only (sanity check)**

```bash
pytest -m "not integration"
```
Expected: all unit tests pass in <5s.

- [ ] **Step 3: Build and healthcheck the Docker image**

```bash
docker build -t docforge:phase3-final .
docker inspect docforge:phase3-final --format '{{json .Config.Healthcheck}}'
docker inspect docforge:phase3-final --format '{{.Config.User}}'
```
Expected: healthcheck config present; user `docforge`.

- [ ] **Step 4: Verify no `--build-arg HF_TOKEN` was needed**

Previous step built without one. Good.

- [ ] **Step 5: Quick smoke — `python -m docforge --help`**

```bash
python -m docforge --help
```
Expected: exit 0, usage banner prints.

- [ ] **Step 6: Final commit (if any straggler changes)**

```bash
git status
```
If clean: done. If not: commit whatever's left with a clear message.

---

## Done

Phase 3 complete. You should now have:
- Test coverage ≥60% with hybrid unit + integration tests
- Module-level and public-function docstrings where they were missing
- Targeted type-hint fixes (`callable` → `Callable`, typed dict returns, `__init__ -> None`)
- Dockerfile with HEALTHCHECK, non-root user, mountable HF cache, no build-time model download
- `.dockerignore` to cut build context
- README `## Troubleshooting` section
