# docforge v0.3 Phase 4b — Embedder Sidecar Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move the EmbeddingGemma-300M model out of the FastAPI search
API process into a separate Container App. Search replicas stop loading
the model; an embedder service serves all hosted consumers (search, MCP,
ingest worker). Opt-in via `EMBEDDER_URL` so dev/CI/single-process
deployments keep using in-process embeddings.

**Architecture:** New `RemoteEmbedder` HTTP client (async-only surface)
in `processors/embedder.py`; new `embedder_api.py` FastAPI service that
wraps the existing `Embedder` and authenticates via shared-secret bearer
header. `Embedder.from_settings` factory branches on `EMBEDDER_URL`. All
async call sites (api, mcp, ingest) move to `await
embedder.aembed_query(...)` / `aembed(...)` — `Embedder` gains those
helpers as `to_thread` wrappers so the surface is uniform across
implementations. CLI bypasses the factory and constructs `Embedder(...)`
directly so local CLI runs always use the in-process model. New Bicep
provisions a second Container App; new `Dockerfile.embedder` bakes the
model via BuildKit secret mount so HF_TOKEN never enters an image layer.

**Tech Stack:** Python 3.12, FastAPI 0.136, httpx, sentence-transformers,
Bicep / Azure Container Apps, GitHub Actions / Docker BuildKit.

**Spec mapping:**

| Spec section | Plan task |
|---|---|
| §1 New module `embedder_api.py` | Task 4 |
| §2 New class `RemoteEmbedder` | Task 2 |
| §3 Factory + protocol + async helpers | Task 1 (helpers + Protocol), Task 3 (factory + call-site updates) |
| §4 New settings | Task 1 |
| §5 `Dockerfile.embedder` | Task 5 |
| §6 Bicep changes | Task 7 |
| §7 CI workflow | Task 6 |
| §8 Tests | Tasks 1–4 each ship their own; integration test in Task 4 |
| §9 Migration playbook | Task 8 |
| Behaviour-change CHANGELOG entry | Task 8 |

**Final unit-suite count target:** 168 (after 4a) + ~22 new across
Tasks 1–4 → **~190** passing after 4b. Same coverage gate (60%).
Existing 168 stay green throughout (Task 3 changes call-site code but
the test stubs adapt via Task 1's `FakeEmbedder.aembed_query` /
`aembed`).

**Branch:** `feature/v03-phase-4b` (already created locally; spec commit
is `dcb4d54`).

---

### Task 1: Foundation — settings, async helpers on `Embedder`, `EmbedderProtocol`

Pure additive. Settings get two new fields with a validator. `Embedder`
gains `aembed` / `aembed_query` async wrappers (delegates via
`asyncio.to_thread`). New `EmbedderProtocol` covers both implementations
so the factory's return type is honest. `FakeEmbedder` gains the same
async helpers so existing tests keep passing.

**Files:**
- Modify: `src/docforge/config.py` — add `embedder_url`, `embedder_token` fields + validator.
- Modify: `src/docforge/processors/embedder.py` — add `aembed` / `aembed_query` to `Embedder`; add `EmbedderProtocol`.
- Modify: `tests/conftest.py` — add `aembed` / `aembed_query` to `FakeEmbedder`.
- Modify: `tests/unit/test_config.py` — add settings tests.
- Modify: `tests/unit/test_embedder.py` — add async-helper tests.

- [ ] **Step 1: Write failing tests for the new Settings fields**

Append to `tests/unit/test_config.py` after `TestQueryLogRetention`:

```python
class TestEmbedderSidecarSettings:
    def test_defaults_when_unset(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        for var in ("EMBEDDER_URL", "EMBEDDER_TOKEN"):
            monkeypatch.delenv(var, raising=False)
        from docforge.config import Settings

        s = Settings()
        assert s.embedder_url == ""
        assert s.embedder_token.get_secret_value() == ""

    def test_url_and_token_loadable_from_env(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("EMBEDDER_URL", "https://embed.internal")
        monkeypatch.setenv("EMBEDDER_TOKEN", "hunter2")
        from docforge.config import Settings

        s = Settings()
        assert s.embedder_url == "https://embed.internal"
        assert s.embedder_token.get_secret_value() == "hunter2"

    def test_url_set_without_token_raises(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        (tmp_path / "docforge.yml").write_text(
            "embedder_url: https://embed.example\n",
            encoding="utf-8",
        )
        monkeypatch.delenv("EMBEDDER_TOKEN", raising=False)
        from docforge.config import Settings

        with pytest.raises(ValueError, match="embedder_token"):
            Settings()

    def test_token_secretstr_not_in_repr(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("EMBEDDER_URL", "https://embed.internal")
        monkeypatch.setenv("EMBEDDER_TOKEN", "very-secret-shhh")
        from docforge.config import Settings

        s = Settings()
        assert "very-secret-shhh" not in repr(s)
```

- [ ] **Step 2: Run, verify they fail (no fields yet)**

```bash
python -m pytest tests/unit/test_config.py::TestEmbedderSidecarSettings -v --tb=short --no-cov 2>&1 | tail -15
```

Expected: 4 fails on `AttributeError: 'Settings' object has no attribute 'embedder_url'`.

- [ ] **Step 3: Add the Settings fields + validator**

In `src/docforge/config.py`, after `query_log_retention_days: int = 180`:

```python
    # Embedder sidecar (Phase 4b). When `embedder_url` is set, the API,
    # MCP, and ingest paths delegate embedding to that URL via
    # RemoteEmbedder; when empty, an in-process Embedder is loaded.
    embedder_url: str = ""
    embedder_token: SecretStr = SecretStr("")
```

Add a model_validator on `Settings` (after the existing fields):

```python
    @model_validator(mode="after")
    def _validate_embedder_sidecar(self):
        if self.embedder_url and not self.embedder_token.get_secret_value():
            raise ValueError(
                "embedder_url is set but embedder_token is empty — "
                "RemoteEmbedder requires a bearer token. Set EMBEDDER_TOKEN "
                "via env or docforge.yml, or unset embedder_url."
            )
        return self
```

(Settings already imports `model_validator` from pydantic for the auth
validator — reuse the import.)

- [ ] **Step 4: Run Step 1 tests, verify green**

```bash
python -m pytest tests/unit/test_config.py::TestEmbedderSidecarSettings -v --no-cov 2>&1 | tail -10
```

All 4 should pass.

- [ ] **Step 5: Write failing tests for `Embedder.aembed` / `aembed_query`**

In `tests/unit/test_embedder.py` (existing file; add a new class):

```python
class TestEmbedderAsyncHelpers:
    """Phase 4b: async helpers wrap sync embed/embed_query via to_thread.
    Async callers (api, mcp, ingest) use these instead of the sync forms."""

    @pytest.mark.asyncio
    async def test_aembed_delegates_to_embed(self, monkeypatch):
        from docforge.processors.embedder import Embedder

        # Avoid actually loading a model — patch encode at the source.
        import sentence_transformers
        from unittest.mock import MagicMock

        fake_st = MagicMock()
        fake_st_instance = MagicMock()
        fake_st_instance.get_embedding_dimension.return_value = 768
        fake_st_instance.encode.return_value = MagicMock(
            tolist=lambda: [[0.1] * 768, [0.2] * 768]
        )
        fake_st.return_value = fake_st_instance
        monkeypatch.setattr(sentence_transformers, "SentenceTransformer", fake_st)

        e = Embedder("test/model", expected_dimensions=768)
        result = await e.aembed(["a", "b"])
        assert result == [[0.1] * 768, [0.2] * 768]

    @pytest.mark.asyncio
    async def test_aembed_query_delegates_to_embed_query(self, monkeypatch):
        from docforge.processors.embedder import Embedder

        import sentence_transformers
        from unittest.mock import MagicMock

        fake_st = MagicMock()
        fake_st_instance = MagicMock()
        fake_st_instance.get_embedding_dimension.return_value = 768
        fake_st_instance.encode.return_value = MagicMock(
            tolist=lambda: [[0.5] * 768]
        )
        fake_st.return_value = fake_st_instance
        monkeypatch.setattr(sentence_transformers, "SentenceTransformer", fake_st)

        e = Embedder("test/model", expected_dimensions=768)
        result = await e.aembed_query("hello")
        assert result == [0.5] * 768
```

- [ ] **Step 6: Run, verify they fail**

```bash
python -m pytest tests/unit/test_embedder.py::TestEmbedderAsyncHelpers -v --no-cov 2>&1 | tail -10
```

Expected: `AttributeError: 'Embedder' object has no attribute 'aembed'`.

- [ ] **Step 7: Add async helpers + `EmbedderProtocol` to embedder.py**

In `src/docforge/processors/embedder.py`, add at module top:

```python
import asyncio
from typing import Protocol, runtime_checkable


@runtime_checkable
class EmbedderProtocol(Protocol):
    """Common surface across Embedder and RemoteEmbedder.

    Async callers (api, mcp_server, ingest) program against this via
    `aembed_query` / `aembed`. Sync callers (cli) use Embedder directly,
    not the protocol.
    """

    model_name: str
    dimensions: int

    async def aembed(self, texts: list[str]) -> list[list[float]]: ...
    async def aembed_query(self, query: str) -> list[float]: ...
    def get_tokenizer_fn(self): ...
```

Add to `Embedder` class (after `embed_query`):

```python
    async def aembed(self, texts: list[str]) -> list[list[float]]:
        """Async wrapper around `embed`; runs the sync model call in a thread."""
        return await asyncio.to_thread(self.embed, texts)

    async def aembed_query(self, query: str) -> list[float]:
        """Async wrapper around `embed_query`; runs the sync model call in a thread."""
        return await asyncio.to_thread(self.embed_query, query)
```

- [ ] **Step 8: Run Step 5 tests, verify green**

```bash
python -m pytest tests/unit/test_embedder.py::TestEmbedderAsyncHelpers -v --no-cov 2>&1 | tail -10
```

Both should pass.

- [ ] **Step 9: Add async helpers to `FakeEmbedder` so existing tests keep working**

In `tests/conftest.py`, in the `FakeEmbedder` class, after `embed_query`:

```python
    async def aembed(self, texts: list[str]) -> list[list[float]]:
        return self.embed(texts)

    async def aembed_query(self, text: str) -> list[float]:
        return self.embed_query(text)
```

These are sync internally (no real model to thread out), but expose the
async surface so the protocol matches.

- [ ] **Step 10: Run full unit suite, confirm green**

```bash
python -m pytest tests/unit -v 2>&1 | tail -8
```

All 168 + 6 new = 174 should pass. No existing test regressions.

- [ ] **Step 11: Lint**

```bash
python -m ruff check src/ tests/ && python -m ruff format --check src/ tests/
```

Both clean.

---

### Task 2: `RemoteEmbedder` class

The HTTP client. Async-only surface (no sync embed). Lazy dim probe.
Bearer-token auth. Retry-once on transport / 5xx; fail-fast on 4xx and
dim mismatch.

**Files:**
- Modify: `src/docforge/processors/embedder.py` — add `RemoteEmbedder` class.
- Add: `tests/unit/test_remote_embedder.py` — full coverage.

- [ ] **Step 1: Write failing tests for `RemoteEmbedder`**

Create `tests/unit/test_remote_embedder.py`:

```python
"""Tests for docforge.processors.embedder.RemoteEmbedder — HTTP client."""

from __future__ import annotations

import json

import httpx
import pytest

from docforge.processors.embedder import RemoteEmbedder


def _vector(d: int = 768) -> list[float]:
    return [0.0] * d


class TestConstruction:
    def test_init_does_no_network(self):
        # If __init__ touched the network, this would raise (no transport).
        e = RemoteEmbedder(
            url="https://embed.invalid",
            token="t",
            expected_dimensions=768,
        )
        assert e.model_name == "remote"
        assert e.dimensions == 768

    def test_url_trailing_slash_stripped(self):
        e = RemoteEmbedder(
            url="https://embed.invalid/",
            token="t",
            expected_dimensions=768,
        )
        assert e._url == "https://embed.invalid"


class TestEmbedHappyPath:
    @pytest.mark.asyncio
    async def test_aembed_query_succeeds_and_sends_bearer(self):
        captured: dict = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["headers"] = dict(request.headers)
            captured["body"] = json.loads(request.content)
            return httpx.Response(
                200,
                json={"vectors": [_vector()], "dimensions": 768},
            )

        transport = httpx.MockTransport(handler)
        e = RemoteEmbedder("https://embed.invalid", "secret-tok", 768)
        # Inject the mock transport before any call.
        e._client = httpx.AsyncClient(transport=transport)

        result = await e.aembed_query("hello")
        assert result == _vector()
        assert captured["headers"]["authorization"] == "Bearer secret-tok"
        assert captured["body"] == {"texts": ["hello"]}
        await e.aclose()


class TestRetryBehavior:
    @pytest.mark.asyncio
    async def test_transport_error_then_success(self):
        attempts = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            attempts["n"] += 1
            if attempts["n"] == 1:
                raise httpx.ConnectError("transient")
            return httpx.Response(
                200, json={"vectors": [_vector()], "dimensions": 768}
            )

        transport = httpx.MockTransport(handler)
        e = RemoteEmbedder("https://embed.invalid", "t", 768)
        e._client = httpx.AsyncClient(transport=transport)

        result = await e.aembed_query("x")
        assert result == _vector()
        assert attempts["n"] == 2
        await e.aclose()

    @pytest.mark.asyncio
    async def test_two_transport_errors_raises(self):
        attempts = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            attempts["n"] += 1
            raise httpx.ConnectError("down")

        transport = httpx.MockTransport(handler)
        e = RemoteEmbedder("https://embed.invalid", "t", 768)
        e._client = httpx.AsyncClient(transport=transport)

        with pytest.raises(httpx.ConnectError):
            await e.aembed_query("x")
        assert attempts["n"] == 2
        await e.aclose()

    @pytest.mark.asyncio
    async def test_5xx_retries_once(self):
        attempts = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            attempts["n"] += 1
            if attempts["n"] == 1:
                return httpx.Response(503)
            return httpx.Response(
                200, json={"vectors": [_vector()], "dimensions": 768}
            )

        transport = httpx.MockTransport(handler)
        e = RemoteEmbedder("https://embed.invalid", "t", 768)
        e._client = httpx.AsyncClient(transport=transport)

        result = await e.aembed_query("x")
        assert result == _vector()
        assert attempts["n"] == 2
        await e.aclose()

    @pytest.mark.asyncio
    async def test_4xx_does_not_retry(self):
        attempts = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            attempts["n"] += 1
            return httpx.Response(401, json={"detail": "invalid token"})

        transport = httpx.MockTransport(handler)
        e = RemoteEmbedder("https://embed.invalid", "wrong", 768)
        e._client = httpx.AsyncClient(transport=transport)

        with pytest.raises(httpx.HTTPStatusError):
            await e.aembed_query("x")
        # Failed on first call, no retry.
        assert attempts["n"] == 1
        await e.aclose()


class TestDimensionGuard:
    @pytest.mark.asyncio
    async def test_dim_mismatch_raises_runtimeerror(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200, json={"vectors": [[0.0] * 384], "dimensions": 384}
            )

        transport = httpx.MockTransport(handler)
        e = RemoteEmbedder("https://embed.invalid", "t", expected_dimensions=768)
        e._client = httpx.AsyncClient(transport=transport)

        with pytest.raises(RuntimeError, match="dimension mismatch"):
            await e.aembed_query("x")
        await e.aclose()


class TestLifecycle:
    @pytest.mark.asyncio
    async def test_aclose_releases_client(self):
        e = RemoteEmbedder("https://embed.invalid", "t", 768)
        # Force creation
        await e._ensure_client()
        assert e._client is not None
        await e.aclose()
        assert e._client is None
```

- [ ] **Step 2: Run, verify they fail**

```bash
python -m pytest tests/unit/test_remote_embedder.py -v --no-cov 2>&1 | tail -10
```

Expected: `ImportError: cannot import name 'RemoteEmbedder'`.

- [ ] **Step 3: Implement `RemoteEmbedder`**

In `src/docforge/processors/embedder.py`, after the `Embedder` class:

```python
import httpx


class RemoteEmbedder:
    """HTTP client for the docforge embedder service.

    Async-only surface. Sync callers (the CLI) construct Embedder
    directly and bypass the factory.
    """

    def __init__(
        self,
        url: str,
        token: str,
        expected_dimensions: int,
        timeout_seconds: float = 5.0,
    ) -> None:
        self._url = url.rstrip("/")
        self._token = token
        self._expected_dimensions = expected_dimensions
        self._timeout_seconds = timeout_seconds
        self._client: httpx.AsyncClient | None = None
        self._probed = False
        self.model_name: str = "remote"
        self.dimensions: int = expected_dimensions

    async def _ensure_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=self._timeout_seconds,
                headers={"Authorization": f"Bearer {self._token}"},
            )
        return self._client

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def _post_embed(self, texts: list[str]) -> list[list[float]]:
        client = await self._ensure_client()
        last_exc: Exception | None = None
        for attempt in (1, 2):
            try:
                resp = await client.post(f"{self._url}/embed", json={"texts": texts})
                resp.raise_for_status()
                payload = resp.json()
                got_dims = payload["dimensions"]
                if got_dims != self._expected_dimensions:
                    raise RuntimeError(
                        f"Embedder dimension mismatch: service at {self._url} "
                        f"returned {got_dims}-d, but config requires "
                        f"{self._expected_dimensions}-d. Either roll the "
                        f"embedder service to a {self._expected_dimensions}-d "
                        f"model, or update embedding_dimensions and migrate "
                        f"the schema."
                    )
                if not self._probed:
                    self._probed = True
                    self.dimensions = got_dims
                return payload["vectors"]
            except (httpx.TimeoutException, httpx.TransportError) as e:
                last_exc = e
                if attempt == 1:
                    await asyncio.sleep(0.15)
                    continue
                raise
            except httpx.HTTPStatusError as e:
                # 4xx is config / auth — fail loud, do not retry.
                if e.response.status_code < 500:
                    raise
                last_exc = e
                if attempt == 1:
                    await asyncio.sleep(0.15)
                    continue
                raise
        raise last_exc  # type: ignore[misc]

    async def aembed(self, texts: list[str]) -> list[list[float]]:
        return await self._post_embed(texts)

    async def aembed_query(self, query: str) -> list[float]:
        result = await self._post_embed([query])
        return result[0]

    def get_tokenizer_fn(self):
        return lambda s: len(s.split())
```

- [ ] **Step 4: Run Step 1 tests, verify green**

```bash
python -m pytest tests/unit/test_remote_embedder.py -v --no-cov 2>&1 | tail -15
```

All 8 should pass.

- [ ] **Step 5: Run full suite, confirm no regressions + lint**

```bash
python -m pytest tests/unit -v 2>&1 | tail -8
python -m ruff check src/ tests/ && python -m ruff format --check src/ tests/
```

---

### Task 3: Factory branch + call-site updates + lifespan `aclose`

Wires `Embedder.from_settings` to return `RemoteEmbedder` when
`embedder_url` is set; updates the four async call sites to use
`aembed_query` / `aembed`; the API lifespan calls `aclose` on shutdown
(guarded by `hasattr` so `Embedder` instances skip it cleanly); CLI
bypasses the factory and constructs `Embedder(...)` directly.

**Files:**
- Modify: `src/docforge/processors/embedder.py` — `from_settings` factory branch.
- Modify: `src/docforge/api.py` — `search` uses `aembed_query`; lifespan calls `aclose`.
- Modify: `src/docforge/mcp_server.py` — `search_documentation` uses `aembed_query`.
- Modify: `src/docforge/ingest.py` — both call sites use `aembed`.
- Modify: `src/docforge/cli.py` — `_search` constructs `Embedder` directly (bypasses factory).
- Add: `tests/unit/test_embedder_factory.py` — factory branch tests.

- [ ] **Step 1: Write failing tests for the factory branch**

Create `tests/unit/test_embedder_factory.py`:

```python
"""Tests for Embedder.from_settings factory branch (Phase 4b)."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from docforge.processors.embedder import Embedder, RemoteEmbedder


def _settings(url: str = "", token: str = "") -> SimpleNamespace:
    return SimpleNamespace(
        embedding_model="test/model",
        embedding_dimensions=768,
        hf_token=SimpleNamespace(get_secret_value=lambda: ""),
        embedder_url=url,
        embedder_token=SimpleNamespace(get_secret_value=lambda: token),
    )


class TestFactoryBranch:
    def test_returns_in_process_embedder_when_url_empty(self, monkeypatch):
        # Patch SentenceTransformer so construction doesn't load a real model.
        import sentence_transformers
        fake_st_instance = MagicMock()
        fake_st_instance.get_embedding_dimension.return_value = 768
        fake_st = MagicMock(return_value=fake_st_instance)
        monkeypatch.setattr(sentence_transformers, "SentenceTransformer", fake_st)

        result = Embedder.from_settings(_settings(url=""))
        assert isinstance(result, Embedder)
        assert not isinstance(result, RemoteEmbedder)

    def test_returns_remote_embedder_when_url_set(self):
        result = Embedder.from_settings(
            _settings(url="https://embed.internal", token="hunter2")
        )
        assert isinstance(result, RemoteEmbedder)
        assert result._url == "https://embed.internal"
        assert result._token == "hunter2"
        assert result._expected_dimensions == 768

    def test_url_set_without_token_raises(self):
        # The Settings model_validator catches this case before from_settings
        # is called in production. The factory has its own guard for direct
        # callers (e.g., a SimpleNamespace settings stub in tests/scripts).
        with pytest.raises(RuntimeError, match="embedder_token"):
            Embedder.from_settings(_settings(url="https://embed", token=""))
```

- [ ] **Step 2: Run, verify they fail**

```bash
python -m pytest tests/unit/test_embedder_factory.py -v --no-cov 2>&1 | tail -10
```

Expected: 2nd and 3rd fail because `from_settings` doesn't branch yet.

- [ ] **Step 3: Update `Embedder.from_settings` factory**

In `src/docforge/processors/embedder.py`, replace the existing
`from_settings` classmethod:

```python
    @classmethod
    def from_settings(cls, settings: Settings) -> EmbedderProtocol:
        """Construct an embedder from Settings.

        Returns RemoteEmbedder when settings.embedder_url is set;
        otherwise returns an in-process Embedder. The CLI bypasses this
        factory and constructs Embedder(...) directly so local CLI
        runs always use the in-process model regardless of EMBEDDER_URL.
        """
        if settings.embedder_url:
            token = settings.embedder_token.get_secret_value()
            if not token:
                raise RuntimeError(
                    "embedder_url is set but embedder_token is empty — "
                    "refusing to construct a RemoteEmbedder without auth"
                )
            return RemoteEmbedder(
                url=settings.embedder_url,
                token=token,
                expected_dimensions=settings.embedding_dimensions,
            )
        return cls(
            settings.embedding_model,
            hf_token=settings.hf_token.get_secret_value(),
            expected_dimensions=settings.embedding_dimensions,
        )
```

- [ ] **Step 4: Run Step 1 tests, verify green**

- [ ] **Step 5: Update `api.py:search` to use `aembed_query`**

In `src/docforge/api.py:search`, replace:

```python
        query_vector = await asyncio.to_thread(embedder.embed_query, req.query)
```

with:

```python
        query_vector = await embedder.aembed_query(req.query)
```

(`Embedder.aembed_query` does the `to_thread` wrapping internally now;
`RemoteEmbedder.aembed_query` is a native HTTP call.)

- [ ] **Step 6: Update `api.py:lifespan` to call `aclose` on shutdown**

In `src/docforge/api.py:lifespan`, initialize `embedder = None` *before*
the outer `try` block (so a startup failure in `Embedder.from_settings`
doesn't leave `embedder` undefined), and add the `aclose` call to the
outer `finally`:

```python
    embedder: EmbedderProtocol | None = None  # set inside try; outer finally reads it
    pool = await asyncpg.create_pool(...)
    try:
        embedder = await asyncio.to_thread(Embedder.from_settings, settings)
        # ... rest of lifespan body unchanged ...
    finally:
        if embedder is not None and hasattr(embedder, "aclose"):
            await embedder.aclose()
        await pool.close()
```

The `is not None` check covers the startup-failure path (where
`Embedder.from_settings` raised before `embedder` was bound); the
`hasattr` guard means an in-process `Embedder` (no `aclose`) is a no-op,
while `RemoteEmbedder` releases its `httpx.AsyncClient`.

(The handler signature `embedder: Embedder = Depends(get_embedder)` in
`search` is now technically loose — at runtime `embedder` may be a
`RemoteEmbedder`. Python doesn't enforce annotations at runtime, so
this is cosmetic. If the project starts running mypy in CI later, the
annotation can change to `EmbedderProtocol`. No runtime fix needed
now.)

- [ ] **Step 7: Update `mcp_server.py:search_documentation`**

Same change as Step 5 — `await asyncio.to_thread(embedder.embed_query, ...)` → `await embedder.aembed_query(...)`.

- [ ] **Step 8: Update `ingest.py` to use `aembed`**

Find the two `embedder.embed(texts)` call sites (in
`_ingest_confluence_source` and `_ingest_git_source`). Change each to:

```python
        vectors = await embedder.aembed(texts)
```

These are already inside `async def` functions, so the `await` is valid.

- [ ] **Step 9: Update `cli.py:_search` to bypass the factory**

In `src/docforge/cli.py:_search` (the sync function that constructs an
Embedder lazily), change:

```python
    from docforge.processors.embedder import Embedder
    embedder = Embedder.from_settings(settings)
```

to:

```python
    from docforge.processors.embedder import Embedder
    # CLI is sync and runs locally — always use in-process Embedder
    # even when EMBEDDER_URL is set (operators set EMBEDDER_URL for
    # hosted services, not for local CLI invocations).
    embedder = Embedder(
        settings.embedding_model,
        hf_token=settings.hf_token.get_secret_value(),
        expected_dimensions=settings.embedding_dimensions,
    )
```

Audit any other sync paths in cli.py for the same pattern. (Likely just
one site — `_search` is the only handler that needs an embedder
synchronously.)

- [ ] **Step 10: Run full suite, confirm green**

```bash
python -m pytest tests/unit -v 2>&1 | tail -8
```

Expected count: 168 (after 4a) + 6 (Task 1) + 8 (Task 2) + 3 (Task 3) =
**185** passing. Existing api/mcp/ingest tests pass because
`FakeEmbedder.aembed_query` (added in Task 1 Step 9) duck-types as the
new call signature.

- [ ] **Step 11: Lint**

---

### Task 4: New module `embedder_api.py` — the FastAPI service

Standalone FastAPI app. Lifespan loads the model. `/embed` requires a
bearer token. `/health` is open. Used both in production (via
`Dockerfile.embedder` + Bicep) and in CI integration tests (spawned
in-test).

**Files:**
- Add: `src/docforge/embedder_api.py` — the service module.
- Add: `tests/unit/test_embedder_api.py` — endpoint tests.
- Add: `tests/integration/test_embedder_sidecar.py` — end-to-end via spawned uvicorn.

- [ ] **Step 1: Write failing tests for `embedder_api`**

Create `tests/unit/test_embedder_api.py`:

```python
"""Tests for docforge.embedder_api FastAPI service (Phase 4b)."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from httpx import ASGITransport, AsyncClient


def _settings_with_token(token: str = "secret-tok"):
    return SimpleNamespace(
        embedder_token=SimpleNamespace(get_secret_value=lambda: token),
        embedding_model="test/model",
        embedding_dimensions=768,
        hf_token=SimpleNamespace(get_secret_value=lambda: ""),
        embedder_url="",
    )


@pytest.fixture(autouse=True)
def _stub_lifespan_resources(monkeypatch):
    """Override the embedder-app lifespan dependencies with stubs so tests
    don't load the real model."""
    from docforge.embedder_api import app, get_embedder, get_settings

    fake_embedder = MagicMock()
    fake_embedder.embed.return_value = [[0.1] * 768]
    fake_embedder.model_name = "test/model"
    fake_embedder.dimensions = 768

    app.dependency_overrides[get_embedder] = lambda: fake_embedder
    app.dependency_overrides[get_settings] = _settings_with_token
    yield
    app.dependency_overrides.clear()


def _client(app):
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


class TestHealth:
    @pytest.mark.asyncio
    async def test_health_returns_model_and_dimensions(self):
        from docforge.embedder_api import app

        async with _client(app) as c:
            resp = await c.get("/health")
        assert resp.status_code == 200
        body = resp.json()
        assert body["model"] == "test/model"
        assert body["dimensions"] == 768


class TestEmbedAuth:
    @pytest.mark.asyncio
    async def test_missing_token_returns_401(self):
        from docforge.embedder_api import app

        async with _client(app) as c:
            resp = await c.post("/embed", json={"texts": ["hello"]})
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_wrong_token_returns_401(self):
        from docforge.embedder_api import app

        async with _client(app) as c:
            resp = await c.post(
                "/embed",
                json={"texts": ["hello"]},
                headers={"Authorization": "Bearer wrong-token"},
            )
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_correct_token_returns_200(self):
        from docforge.embedder_api import app

        async with _client(app) as c:
            resp = await c.post(
                "/embed",
                json={"texts": ["hello"]},
                headers={"Authorization": "Bearer secret-tok"},
            )
        assert resp.status_code == 200
        body = resp.json()
        assert body["dimensions"] == 768
        assert len(body["vectors"]) == 1


class TestEmbedValidation:
    @pytest.mark.asyncio
    async def test_empty_texts_returns_422(self):
        from docforge.embedder_api import app

        async with _client(app) as c:
            resp = await c.post(
                "/embed",
                json={"texts": []},
                headers={"Authorization": "Bearer secret-tok"},
            )
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_oversized_batch_returns_422(self):
        from docforge.embedder_api import app

        async with _client(app) as c:
            resp = await c.post(
                "/embed",
                json={"texts": ["x"] * 257},  # MAX_BATCH_SIZE + 1
                headers={"Authorization": "Bearer secret-tok"},
            )
        assert resp.status_code == 422


class TestLifespanGuard:
    @pytest.mark.asyncio
    async def test_lifespan_refuses_empty_token(self, monkeypatch):
        """Phase 4b: the embedder service refuses to start with empty
        EMBEDDER_TOKEN. Direct unit test of the lifespan."""
        from docforge.embedder_api import lifespan
        from fastapi import FastAPI

        app = FastAPI()

        # Build a Settings-like stub with empty token.
        from docforge.config import Settings
        monkeypatch.setattr(
            "docforge.embedder_api.Settings",
            lambda: SimpleNamespace(
                embedder_token=SimpleNamespace(get_secret_value=lambda: ""),
                embedding_model="test",
                embedding_dimensions=768,
                hf_token=SimpleNamespace(get_secret_value=lambda: ""),
                embedder_url="",
            ),
        )

        with pytest.raises(RuntimeError, match="EMBEDDER_TOKEN"):
            async with lifespan(app):
                pass
```

- [ ] **Step 2: Run, verify they fail**

```bash
python -m pytest tests/unit/test_embedder_api.py -v --no-cov 2>&1 | tail -10
```

Expected: `ImportError: No module named 'docforge.embedder_api'`.

- [ ] **Step 3: Implement `src/docforge/embedder_api.py`**

```python
"""docforge embedder service — exposes Embedder over HTTP.

Runs as its own Container App. The search API, MCP server, and ingest
worker delegate to this service when EMBEDDER_URL is set."""

from __future__ import annotations

import asyncio
import logging
import secrets
from contextlib import asynccontextmanager
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from pydantic import BaseModel, Field

from docforge.config import Settings
from docforge.processors.embedder import MAX_BATCH_SIZE, Embedder

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = Settings()
    if not settings.embedder_token.get_secret_value():
        raise RuntimeError(
            "embedder service requires EMBEDDER_TOKEN to be set "
            "(via Key Vault secret or env var) — refusing to start with no auth"
        )
    embedder = await asyncio.to_thread(Embedder.from_settings, settings)
    logger.info("Embedder ready: %s (%dd)", embedder.model_name, embedder.dimensions)
    yield {"embedder": embedder, "settings": settings}


app = FastAPI(title="docforge-embedder", lifespan=lifespan)


def get_embedder(request: Request) -> Embedder:
    return request.state.embedder


def get_settings(request: Request) -> Settings:
    return request.state.settings


async def _require_token(
    settings: Settings = Depends(get_settings),
    authorization: str | None = Header(default=None),
) -> None:
    expected = settings.embedder_token.get_secret_value()
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="missing bearer token")
    presented = authorization.removeprefix("Bearer ").strip()
    if not secrets.compare_digest(presented, expected):
        raise HTTPException(status_code=401, detail="invalid bearer token")


class EmbedRequest(BaseModel):
    texts: list[str] = Field(..., min_length=1, max_length=MAX_BATCH_SIZE)


class EmbedResponse(BaseModel):
    vectors: list[list[float]]
    dimensions: int


@app.get("/health")
async def health(request: Request) -> dict[str, Any]:
    embedder = getattr(request.state, "embedder", None)
    if embedder is None:
        raise HTTPException(status_code=503, detail="model not loaded")
    return {
        "status": "ok",
        "model": embedder.model_name,
        "dimensions": embedder.dimensions,
    }


@app.post("/embed", response_model=EmbedResponse)
async def embed(
    req: EmbedRequest,
    embedder: Embedder = Depends(get_embedder),
    _: None = Depends(_require_token),
) -> EmbedResponse:
    vectors = await asyncio.to_thread(embedder.embed, req.texts)
    return EmbedResponse(vectors=vectors, dimensions=embedder.dimensions)
```

- [ ] **Step 4: Run Step 1 tests, verify green**

```bash
python -m pytest tests/unit/test_embedder_api.py -v --no-cov 2>&1 | tail -10
```

All 7 should pass.

- [ ] **Step 5: Add an integration test that spawns the embedder**

The CI integration job has no `HF_TOKEN` secret and caches only the
ungated `sentence-transformers/all-MiniLM-L6-v2` (384-d). To stay
consistent with `tests/integration/test_embedder_real_model.py`,
override `EMBEDDING_MODEL` and `EMBEDDING_DIMENSIONS` in the fixture
and assert against 384-d output. The marker `integration` keeps the
test out of the unit run.

Create `tests/integration/test_embedder_sidecar.py`:

```python
"""End-to-end integration: spawn the embedder service, point a RemoteEmbedder
at it, exercise the auth + dim-guard contracts.

Uses the ungated all-MiniLM-L6-v2 (384-d) so this runs without HF_TOKEN —
matching the existing tests/integration/test_embedder_real_model.py pattern."""

from __future__ import annotations

import asyncio
import os
import socket
import threading
import time

import httpx
import pytest
import uvicorn

UNGATED_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
UNGATED_DIM = 384


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def embedder_service():
    """Spawn docforge.embedder_api on a free port with the ungated model;
    yield (url, token)."""
    port = _free_port()
    token = "integration-test-token"
    # Override settings via env vars so the spawned process picks up
    # the ungated model and matching dims.
    os.environ["EMBEDDER_TOKEN"] = token
    os.environ["EMBEDDING_MODEL"] = UNGATED_MODEL
    os.environ["EMBEDDING_DIMENSIONS"] = str(UNGATED_DIM)

    config = uvicorn.Config(
        "docforge.embedder_api:app",
        host="127.0.0.1",
        port=port,
        log_level="warning",
    )
    server = uvicorn.Server(config)

    thread = threading.Thread(target=lambda: asyncio.run(server.serve()))
    thread.start()

    # Wait for /health to respond
    url = f"http://127.0.0.1:{port}"
    for _ in range(60):  # up to 60s for cold start
        try:
            with httpx.Client(timeout=1.0) as c:
                if c.get(f"{url}/health").status_code == 200:
                    break
        except (httpx.ConnectError, httpx.TimeoutException):
            time.sleep(1)
    else:
        server.should_exit = True
        thread.join()
        raise RuntimeError("embedder service did not start")

    yield (url, token)

    server.should_exit = True
    thread.join()
    for var in ("EMBEDDER_TOKEN", "EMBEDDING_MODEL", "EMBEDDING_DIMENSIONS"):
        os.environ.pop(var, None)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_remote_embedder_against_real_service(embedder_service):
    from docforge.processors.embedder import RemoteEmbedder

    url, token = embedder_service
    e = RemoteEmbedder(url=url, token=token, expected_dimensions=UNGATED_DIM)
    try:
        result = await e.aembed_query("hello world")
        assert len(result) == UNGATED_DIM
        assert all(isinstance(v, float) for v in result)
    finally:
        await e.aclose()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_remote_embedder_rejects_wrong_token(embedder_service):
    from docforge.processors.embedder import RemoteEmbedder
    import httpx

    url, _ = embedder_service
    e = RemoteEmbedder(url=url, token="wrong-token", expected_dimensions=UNGATED_DIM)
    try:
        with pytest.raises(httpx.HTTPStatusError) as exc_info:
            await e.aembed_query("x")
        assert exc_info.value.response.status_code == 401
    finally:
        await e.aclose()
```

- [ ] **Step 6: Run integration test**

```bash
python -m pytest -m integration tests/integration/test_embedder_sidecar.py -v -s --no-cov 2>&1 | tail -15
```

The CI integration job runs `pytest -m integration --no-cov` over the
whole `tests/integration/` directory (see `.github/workflows/ci.yml`),
so the new test is picked up automatically. Local runs need the same
`-m integration` flag because the marker is excluded from the default
collection.

- [ ] **Step 7: Lint + full unit suite**

```bash
python -m pytest tests/unit -v 2>&1 | tail -8
python -m ruff check src/ tests/ && python -m ruff format --check src/ tests/
```

---

### Task 5: `Dockerfile.embedder` with BuildKit secret mount

Pre-bakes the EmbeddingGemma model. HF_TOKEN comes via
`--mount=type=secret,id=hf_token` so it never lands in any image layer.

**Files:**
- Add: `Dockerfile.embedder` at repo root.

- [ ] **Step 1: Write the Dockerfile**

```dockerfile
# syntax=docker/dockerfile:1.6
FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc libpq-dev && \
    rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md ./
COPY src/ src/

RUN pip install --no-cache-dir "."

# Pre-download the embedding model. HF_TOKEN comes from a BuildKit
# secret mount and never lands in any image layer.
ARG EMBEDDING_MODEL=google/embeddinggemma-300m
RUN --mount=type=secret,id=hf_token,uid=0,gid=0 \
    HF_TOKEN="$(cat /run/secrets/hf_token 2>/dev/null || true)" \
    HF_HOME=/app/.cache/huggingface \
    python -c "import os; from sentence_transformers import SentenceTransformer; \
    SentenceTransformer('${EMBEDDING_MODEL}', token=os.environ.get('HF_TOKEN') or None)"

RUN useradd -m -u 1000 docforge && \
    chown -R docforge:docforge /app

USER docforge

ENV HF_HOME=/app/.cache/huggingface

EXPOSE 8001

HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8001/health').read() else 1)"

CMD ["uvicorn", "docforge.embedder_api:app", "--host", "0.0.0.0", "--port", "8001"]
```

- [ ] **Step 2: Verify locally that the build doesn't bake the token**

Pre-req: `HF_TOKEN` must be exported in the shell. Confirm with
`echo ${HF_TOKEN:+set} ${HF_TOKEN:-unset}` — should print `set`. If
empty, the build will silently fail to download the gated EmbeddingGemma
model (the Dockerfile's `cat .. || true` swallows the missing-secret
error to support optional models).

```bash
DOCKER_BUILDKIT=1 docker build \
  --secret id=hf_token,env=HF_TOKEN \
  -f Dockerfile.embedder \
  -t docforge-embedder:test .

# Confirm the token doesn't appear in any layer:
docker history --no-trunc docforge-embedder:test | grep -i "$HF_TOKEN" || echo "OK: token not in image"
```

If `docker history` returns the token, the Dockerfile is wrong. The
expected output is "OK: token not in image".

(`--secret id=hf_token,env=HF_TOKEN` reads from the env var directly,
matching the form used by the CI workflow in Task 6. The
`src=/dev/stdin` form works on Linux but adds a trailing newline and is
silently empty if the var isn't exported.)

- [ ] **Step 3: Verify the embedder starts and serves /health**

```bash
docker run --rm -d -p 8001:8001 -e EMBEDDER_TOKEN=test-token \
  --name docforge-embedder-test docforge-embedder:test
sleep 30  # generous for first start; baked model loads in ~5–10s
curl -s http://localhost:8001/health
docker stop docforge-embedder-test
```

Expected output: `{"status":"ok","model":"google/embeddinggemma-300m","dimensions":768}`.

---

### Task 6: CI workflow — embedder image build + integration test wiring

Build both images in parallel after `test` passes. Spawn the embedder
during integration tests so `RemoteEmbedder` is exercised end-to-end.

**Files:**
- Modify: `.github/workflows/ci.yml`.

- [ ] **Step 1: Add the embedder image-build job**

After the existing `test` job, add a new job (parallel with the existing
image-push):

```yaml
  build-embedder-image:
    needs: test
    runs-on: ubuntu-latest
    if: github.ref == 'refs/heads/master' || github.event_name == 'pull_request'
    steps:
      - uses: actions/checkout@v6
      - uses: docker/setup-buildx-action@v3
      - name: Login to ACR
        # ... (same as the existing image build)
      - name: Build and push embedder image
        uses: docker/build-push-action@v6
        with:
          context: .
          file: ./Dockerfile.embedder
          push: ${{ github.ref == 'refs/heads/master' }}
          tags: |
            ${{ secrets.ACR_LOGIN_SERVER }}/docforge-embedder:${{ github.sha }}
            ${{ secrets.ACR_LOGIN_SERVER }}/docforge-embedder:latest
          secrets: |
            "hf_token=${{ secrets.HF_TOKEN }}"
```

- [ ] **Step 2: Document the required `HF_TOKEN` repo secret**

In `README.md` (or `CONTRIBUTING.md` if it exists), under a new
"Self-hosting / forking" section:

```markdown
## Self-hosting / forking

The embedder image bakes the EmbeddingGemma-300M model at build time,
which requires a HuggingFace access token. Forks/adopters need to:

1. Get an HF token at https://huggingface.co/settings/tokens.
2. Accept the EmbeddingGemma license at
   https://huggingface.co/google/embeddinggemma-300m.
3. Add a repo secret `HF_TOKEN` under
   `Settings → Secrets and variables → Actions`.

The CI workflow forwards the secret to BuildKit via
`--mount=type=secret,id=hf_token`; the token never enters any image
layer.
```

- [ ] **Step 3: Confirm integration job picks up the new test**

The existing `integration` job in `.github/workflows/ci.yml` runs
`pytest -m integration --no-cov` over the whole `tests/` tree. The
Phase 4b integration test (Task 4 Step 5) is marked
`@pytest.mark.integration` and uses the ungated MiniLM model, so it
runs without `HF_TOKEN` and gets picked up automatically — no workflow
change needed beyond the embedder image-build job in Step 1.

The HuggingFace cache key in the integration job
(`hf-${{ runner.os }}-all-minilm-l6-v2`) already covers this test's
model. No cache change needed.

- [ ] **Step 4: Verify the workflow syntax**

```bash
# If gh-cli with workflow validation is available:
gh workflow view ci.yml
```

Manual review for now: confirm both image-build jobs run in parallel,
both depend on `test`, and the integration job has access to
`HF_TOKEN` via the test cache.

---

### Task 7: Bicep — second Container App + secret wiring

New `${namePrefix}-embedder` Container App. Operator-supplied
`embedderToken` parameter. Both Container Apps get the secret via Key
Vault reference. Search API gains `EMBEDDER_URL` + `EMBEDDER_TOKEN`
env vars on its second-pass (real-image) deploy.

**Files:**
- Modify: `deploy/azure/main.bicep`.
- Modify: `deploy/azure/main.sample.bicepparam` (if the existing param file documents new params).

- [ ] **Step 1: Add new parameters**

Near the existing `containerImage` / `minReplicas` block:

```bicep
@description('Full image reference for the embedder Container App. Empty string defers to "hello-world" placeholder, update post-deploy.')
param embedderImage string = ''

@description('Min replicas for the embedder Container App. 0 = scale-to-zero (cheapest, eats cold start); 1 = always warm.')
@minValue(0)
@maxValue(10)
param embedderMinReplicas int = 0

@description('Max replicas for the embedder Container App.')
@minValue(1)
@maxValue(30)
param embedderMaxReplicas int = 5

@description('Bearer token shared between the search API and the embedder service. Generate via `openssl rand -hex 32` or similar; rotate by re-deploying with a new value.')
@secure()
param embedderToken string
```

- [ ] **Step 2: Add the Key Vault secret for the token**

After the existing `secretConfluenceToken` block:

```bicep
resource secretEmbedderToken 'Microsoft.KeyVault/vaults/secrets@2024-04-01-preview' = {
  parent: keyVault
  name: 'embedder-token'
  properties: {
    value: embedderToken
  }
}
```

- [ ] **Step 3: Add the embedder Container App**

After the existing `containerApp` resource (the search API), add:

```bicep
var embedderAppName = '${namePrefix}-embedder'
var hasRealEmbedderImage = !empty(embedderImage)
var defaultEmbedderImage = 'mcr.microsoft.com/azuredocs/containerapps-helloworld:latest'
var effectiveEmbedderImage = hasRealEmbedderImage ? embedderImage : defaultEmbedderImage

var embedderProbes = hasRealEmbedderImage ? [
  {
    type: 'Startup'
    httpGet: { path: '/health', port: 8001 }
    initialDelaySeconds: 10
    periodSeconds: 10
    timeoutSeconds: 5
    failureThreshold: 30
  }
  {
    type: 'Liveness'
    httpGet: { path: '/health', port: 8001 }
    initialDelaySeconds: 30
    periodSeconds: 30
    timeoutSeconds: 5
    failureThreshold: 3
  }
] : []

var embedderRealSecrets = [
  {
    name: 'embedder-token'
    keyVaultUrl: '${keyVault.properties.vaultUri}secrets/embedder-token'
    identity: 'system'
  }
]

var embedderRealEnv = [
  {
    name: 'EMBEDDER_TOKEN'
    secretRef: 'embedder-token'
  }
]

resource embedderApp 'Microsoft.App/containerApps@2024-03-01' = {
  name: embedderAppName
  location: location
  tags: tags
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    managedEnvironmentId: containerAppsEnv.id
    configuration: {
      ingress: {
        external: true
        targetPort: hasRealEmbedderImage ? 8001 : 80
        allowInsecure: false
        transport: 'http'
      }
      registries: hasRealEmbedderImage ? [
        {
          server: acr.properties.loginServer
          identity: 'system'
        }
      ] : []
      secrets: hasRealEmbedderImage ? embedderRealSecrets : []
    }
    template: {
      containers: [
        {
          name: 'docforge-embedder'
          image: effectiveEmbedderImage
          resources: {
            cpu: json('2.0')
            memory: '4Gi'
          }
          env: hasRealEmbedderImage ? embedderRealEnv : []
          probes: embedderProbes
        }
      ]
      scale: {
        minReplicas: embedderMinReplicas
        maxReplicas: embedderMaxReplicas
        rules: [
          {
            name: 'http-rule'
            http: {
              metadata: {
                concurrentRequests: '5'
              }
            }
          }
        ]
      }
    }
  }
}

resource embedderKvSecretsUser 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: keyVault
  name: guid(keyVault.id, embedderApp.id, keyVaultSecretsUserRoleId)
  properties: {
    principalId: embedderApp.identity.principalId
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', keyVaultSecretsUserRoleId)
    principalType: 'ServicePrincipal'
  }
}

resource embedderAcrPull 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: acr
  name: guid(acr.id, embedderApp.id, acrPullRoleId)
  properties: {
    principalId: embedderApp.identity.principalId
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', acrPullRoleId)
    principalType: 'ServicePrincipal'
  }
}
```

**Deploy ordering note:** the second-pass deploy must push BOTH images
before applying Bicep — search API and embedder. If `embedderImage` is
empty (placeholder) but `containerImage` is set (real search API), the
search API gets `EMBEDDER_URL` pointing at the hello-world placeholder's
FQDN, which has no `/embed` endpoint. The runbook order is: build both
images → push to ACR → deploy with both `containerImage` and
`embedderImage` set in the same Bicep apply.

- [ ] **Step 4: Wire `EMBEDDER_URL` + `EMBEDDER_TOKEN` into the search API**

Modify `realContainerSecrets` (the search API's secrets array) to add
the embedder token:

```bicep
var realContainerSecrets = [
  // ... existing entries ...
  {
    name: 'embedder-token'
    keyVaultUrl: '${keyVault.properties.vaultUri}secrets/embedder-token'
    identity: 'system'
  }
]
```

Modify `realContainerEnv` to add EMBEDDER_URL and EMBEDDER_TOKEN:

```bicep
var realContainerEnv = [
  // ... existing entries ...
  {
    name: 'EMBEDDER_URL'
    value: 'https://${embedderApp.properties.configuration.ingress.fqdn}'
  }
  {
    name: 'EMBEDDER_TOKEN'
    secretRef: 'embedder-token'
  }
]
```

- [ ] **Step 5: Add outputs for the embedder app**

Near the existing outputs block:

```bicep
output embedderFqdn string = embedderApp.properties.configuration.ingress.fqdn
output embedderAppName string = embedderApp.name
```

- [ ] **Step 6: Update the sample param file**

In `deploy/azure/main.sample.bicepparam` (if present), add a placeholder
for `embedderToken`:

```bicep
param embedderToken = '__SET_AT_DEPLOY_TIME__'
```

With a comment noting that operators should pass it via
`--parameters embedderToken="$(openssl rand -hex 32)"` and rotate by
re-deploying with a new value.

- [ ] **Step 7: Validate Bicep syntax**

```bash
az bicep build --file deploy/azure/main.bicep
# Should produce a main.json with no errors.
```

If the bicep CLI is not available locally, this step is gated to CI
or a deploy attempt; document the validation command in
`deploy/README.md`.

---

### Task 8: Migration playbook + CHANGELOG

Final docs polish. Documents how to upgrade the embedding model and
captures the Phase 4b behaviour-change entries.

**Files:**
- Modify: `README.md` (or new `docs/operations.md`) — add migration playbook.
- Modify: `CHANGELOG.md` — add Phase 4b entries to `[Unreleased]`.

- [ ] **Step 1: Add the migration playbook**

In `README.md`, add a new section "Upgrading the embedding model" (or
create `docs/operations.md` if there's preference for keeping the README
small):

```markdown
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
```

- [ ] **Step 2: Add CHANGELOG entries**

In `CHANGELOG.md`, under `[Unreleased] → ### Changed` (after the Phase
4a entries):

```markdown
- The embedding model can now be hosted as a separate Container App via the new `EMBEDDER_URL` setting (Phase 4b). When set, the search API, MCP server, and ingest worker delegate embedding to that URL instead of loading the model in-process. Search API replicas drop from ~2 GB RSS to ~400 MB and start in <10s. The split is opt-in: leaving `EMBEDDER_URL` empty keeps the in-process behaviour.
- New `Dockerfile.embedder` builds the embedder service image. The EmbeddingGemma-300M model is baked into the image at build time using a BuildKit secret mount (`--mount=type=secret,id=hf_token`); the HuggingFace token never enters any image layer.
- New shared-secret bearer auth between the search API and the embedder service via `EMBEDDER_TOKEN`. The embedder service refuses to start without it; `RemoteEmbedder` raises at construction if `embedder_url` is set without `embedder_token`. **Behavior change for hosted deployments:** Bicep gains a new `embedderToken` parameter; operators generate (e.g. `openssl rand -hex 32`) and rotate via re-deploy.
- Async-only `RemoteEmbedder` surface; `Embedder` gains `aembed` / `aembed_query` async wrappers via `asyncio.to_thread`; all async call sites (api, mcp_server, ingest) now use `await embedder.aembed_query(...)` / `aembed(...)`. The CLI bypasses the factory and constructs `Embedder(...)` directly so local CLI runs always use the in-process model regardless of `EMBEDDER_URL`.
- Embedder image cold-start ~5–10s (baked weights); `min_replicas=0` for the embedder Container App by default. Operators can bump to 1 via the `embedderMinReplicas` Bicep parameter to eliminate cold-start latency at the cost of a constant floor.
```

- [ ] **Step 3: Verify CHANGELOG renders cleanly**

```bash
# Just confirm Markdown is well-formed:
python -c "import markdown; markdown.markdown(open('CHANGELOG.md').read())"
```

(Optional — if the project doesn't lint markdown.)

---

## Cross-task verification (after Task 8)

Run the full suite + lint as a smoke test before opening the PR:

```bash
source .venv/Scripts/activate
python -m pytest tests/unit -v 2>&1 | tail -8
python -m ruff check src/ tests/ && python -m ruff format --check src/ tests/
```

Expected: ~190 unit tests passing, ruff clean.

If a real Azure deploy is part of the merge gate (it isn't today, per
the v0.3 design — the project ships code in PRs and Bicep is applied
manually), document the deploy steps in the PR description rather than
running them as part of CI.

## Risks during execution

- **Task 3 has a wide blast radius** — touches api, mcp_server, ingest,
  cli, and the api lifespan. Run the full suite after Task 1 (FakeEmbedder
  async helpers added) and again after Task 3 to catch any test that
  hard-coded the old `await asyncio.to_thread(embedder.embed_query, ...)`
  form.
- **Task 5 (`Dockerfile.embedder`) needs BuildKit** — confirm the local
  Docker daemon supports BuildKit (Docker 23+). On older Docker, set
  `DOCKER_BUILDKIT=1` or the secret mount silently no-ops.
- **Task 7 (Bicep) is harder to verify locally.** A plan reviewer can
  read the Bicep but full validation requires `az bicep build` or a
  deploy attempt. The test-pass workflow doesn't catch Bicep typos.
  Document validation as a manual step in the PR description.

## Recommended execution mode

Subagent-driven, with model selection per task:

- **Task 1** (foundation): haiku — small mechanical change (settings,
  2 async wrappers, Protocol).
- **Task 2** (RemoteEmbedder): sonnet — ~120 LoC of class with retry
  semantics + 8 tests. Detailed enough that subtle bugs hide easily.
- **Task 3** (factory + call sites): sonnet — wide blast radius across
  4 files; reviewer needs to spot regressions.
- **Task 4** (embedder_api.py): sonnet — new module with auth
  middleware + 7 unit tests + integration test.
- **Task 5** (Dockerfile): haiku — small file, mostly mechanical.
- **Task 6** (CI workflow): haiku — YAML edits + README note.
- **Task 7** (Bicep): sonnet — careful review needed; Bicep typos are
  expensive (failed deploy).
- **Task 8** (docs + changelog): haiku — text only.

Each task gets two-stage review: spec-compliance (haiku) → code-quality
(sonnet for Tasks 2, 3, 4, 7; haiku for the others).
