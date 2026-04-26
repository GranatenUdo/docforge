# docforge v0.3 Phase 4b — Embedder Sidecar — design

**Status:** Draft 2026-04-26 (revised after self-review)
**Author:** Tobias Ens
**Scope:** Second half of v0.3 Phase 4 per the umbrella spec at
`docs/superpowers/specs/2026-04-25-v03-hardening-design.md`. Phase 4a
landed the in-process correctness fixes (lifespan, advisory lock, to_thread
wrapping). 4b moves the embedder out of the API process into its own
Container App so search replicas no longer carry the model.

## Goal

Search API replicas stop loading the EmbeddingGemma-300M model. A separate
embedder Container App owns model lifecycle. The split is opt-in via
`EMBEDDER_URL`: unset = in-process (current behavior, used by
dev/CI/single-process deployments); set = remote.

After 4b:

- Search API replica startup time drops from ~30–60s (model load) to
  <5s (process start + DB pool warm-up).
- Search API replica memory footprint drops from ~2–4 GB to ~200–400 MB.
- The embedder is sized independently (CPU/memory tuned for inference)
  and shared across all hosted consumers (search API, MCP server, ingest
  worker, any future bulk re-embedding job).
- Operators upgrading the embedding model can roll the embedder service
  independently of the search API.

## Context

After Phase 4a, every FastAPI replica still calls `Embedder.from_settings`
in its lifespan. At the v0.3 operating target (30 teams / 500 engineers,
AI-agent burst traffic), that means N replicas each loading a 1.2 GB model
into ~2–4 GB of RAM. HPA scaling on the search API multiplies that cost
linearly. Memory is wasted on redundant model copies; CPU autoscale signals
are confused by inference spikes mixed with request handling.

The umbrella v0.3 design recognized this from the start; Phase 4 was always
intended to ship the sidecar. 4a was the in-process refactor that's a
prerequisite (clean lifespan boundary, no module globals making the embedder
hard to swap). 4b is the rollout.

## Design decisions (resolved during brainstorm + self-review)

1. **Scope** — end-to-end. Code abstraction + new Container App + Bicep
   wiring. The search API in production runs against the sidecar after
   this PR merges and Bicep is applied.
2. **API shape** — single batch endpoint:
   `POST /embed { "texts": [str] } → { "vectors": [[float]], "dimensions": int }`.
   Search wraps a single query in a one-item list; ingest passes batches
   directly. No separate query/document endpoints; no `mode` field
   (EmbeddingGemma is symmetric).
3. **Service-to-service auth** — **shared-secret bearer header**. The
   embedder requires `Authorization: Bearer <token>` on `/embed`; the
   search API and ingest worker read the same token from Key Vault and
   send it. **(Revised from "no auth, trust VNet" after self-review found
   that internal-only ingress requires recreating the existing
   Container Apps Environment with VNet integration — significantly more
   operational pain than the brainstorm assumed. Shared-secret is enough
   given the threat model: the embedder is reachable on a public FQDN
   but rejects unauthenticated requests with 401.)**
4. **Failure mode** — `RemoteEmbedder` retries once with ~150ms backoff,
   5s overall timeout. On final failure, raises; the existing handler
   wrapping in api.py / mcp_server.py maps to HTTP 503 (matches the
   existing DB-down convention).
5. **Dimension coordination** — every `/embed` response carries
   `dimensions`; `RemoteEmbedder` validates each response's dimension
   against `expected_dimensions` and raises `RuntimeError` on mismatch.
   Probe happens lazily on first call (not in `__init__`) so construction
   doesn't block on network. Brief upgrade-the-model playbook in docs.
6. **Local dev** — stays in-process. `EMBEDDER_URL` unset is the default.
   No docker-compose addition. CI integration tests exercise the sidecar
   path end-to-end.
7. **Model packaging** — baked into the embedder image at build time
   using BuildKit secret mount (`--mount=type=secret,id=hf_token`) so the
   token does not appear in any image layer. Slower CI builds, faster
   cold starts, reproducible deploys, no runtime HuggingFace dependency.
8. **Embedder min_replicas** — `0` (scale-to-zero). First request after
   idle eats a ~5–10s cold start; subsequent requests are warm. Cost
   over correctness for the bursty AI-agent traffic profile.

## Detailed design

### 1. New module: `src/docforge/embedder_api.py`

Minimal FastAPI service wrapping the existing `Embedder`. One endpoint
plus `/health`. Uses the lifespan pattern from 4a; model loads once at
startup, offloaded to `to_thread`. Token auth gates `/embed` only —
`/health` stays open so Container Apps healthchecks don't need to know
the token.

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
    # Constant-time compare so timing doesn't leak token characters.
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

Notes:
- The lifespan refuses to start without `EMBEDDER_TOKEN`. This is a
  deploy-time guard: a misconfigured Container App fails fast at startup
  rather than serving anonymous requests.
- `secrets.compare_digest` for constant-time string comparison.
- `Pydantic max_length=MAX_BATCH_SIZE` (256) returns 422 for oversized
  batches before reaching the model.
- `/health` is unauthenticated so Container Apps' built-in healthcheck
  works without the token. The endpoint exposes only model name and
  dimension — no embedding ability without auth.

### 2. New class: `RemoteEmbedder` (in `src/docforge/processors/embedder.py`)

HTTP client. **Async-only surface** (no sync `embed` / `embed_query`).
Sync callers (the CLI's `_search`, which runs outside any event loop)
get `Embedder` directly via the factory branch. Async callers (api.py,
mcp_server.py, ingest.py) use the `aembed`/`aembed_query` helper which
works for either implementation.

```python
class RemoteEmbedder:
    """HTTP client for the docforge embedder service.

    Async-only surface. Sync callers should not receive a RemoteEmbedder
    from the factory; the CLI's sync paths route to the in-process
    Embedder instead. The factory enforces this.
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
        # Set after the first successful request — populated lazily so
        # __init__ stays non-blocking and not network-dependent.
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
                # 4xx is a configuration / auth error — don't retry, fail loud.
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
        # Whitespace-split approximation. The chunker uses this only on
        # the ingest path, where the factory selects the in-process
        # Embedder for local CLI runs (real tokenizer) and the remote
        # path for hosted ingest jobs (approximate). The chunker treats
        # this as a soft budget, not a hard ceiling.
        return lambda s: len(s.split())
```

Notes:
- Sync `embed` / `embed_query` are intentionally absent. Async-only
  surface forces async call sites to use `aembed`/`aembed_query`,
  preventing the `asyncio.run()`-from-running-loop footgun.
- Dimension probe is lazy: `__init__` does no network. The first
  `/embed` call validates dimensions; subsequent calls re-validate
  (cheap dict lookup) so a mid-flight rollover surfaces loudly.
- `aclose` is owned by the lifespan that constructs the embedder. The
  search API's lifespan calls `await embedder.aclose()` in its `finally`
  block (see §3).
- 4xx errors fail fast (auth / dim mismatch are deterministic; retrying
  doesn't help and adds latency). 5xx and transport errors retry once.

### 3. `Embedder.from_settings` factory selects the implementation

The factory picks the impl. Sync callers (CLI) bypass the factory in
their own paths so they always get an `Embedder` regardless of
`EMBEDDER_URL` being set — the CLI is interactive and a developer who
runs `docforge search` from their laptop usually doesn't have access
to the hosted embedder.

```python
# In src/docforge/processors/embedder.py
from typing import Protocol


class EmbedderProtocol(Protocol):
    """Surface common to Embedder and RemoteEmbedder.

    Async callers (api, mcp_server, ingest) should program against this
    protocol via the `aembed_query` / `aembed` helpers below — those work
    for both implementations.
    """

    model_name: str
    dimensions: int

    async def aembed(self, texts: list[str]) -> list[list[float]]: ...
    async def aembed_query(self, query: str) -> list[float]: ...
    def get_tokenizer_fn(self): ...


# Embedder gains async methods that wrap the sync ones via to_thread:
class Embedder:
    # ... existing sync methods ...

    async def aembed(self, texts: list[str]) -> list[list[float]]:
        return await asyncio.to_thread(self.embed, texts)

    async def aembed_query(self, query: str) -> list[float]:
        return await asyncio.to_thread(self.embed_query, query)


# Factory:
@classmethod
def from_settings(cls, settings: Settings) -> EmbedderProtocol:
    if settings.embedder_url:
        token = settings.embedder_token.get_secret_value()
        if not token:
            raise RuntimeError(
                "embedder_url is set but embedder_token is empty — refusing "
                "to construct a RemoteEmbedder without auth credentials"
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

The two async call sites in `api.py` and `mcp_server.py` change from
`await asyncio.to_thread(embedder.embed_query, req.query)` (Phase 4a's
form) to `await embedder.aembed_query(req.query)`. `Embedder.aembed_query`
is the new `to_thread` wrapper; `RemoteEmbedder.aembed_query` is the
HTTP path. Identical surface to callers.

`ingest.py` changes its in-loop `embedder.embed(texts)` call to
`await embedder.aembed(texts)`. Same pattern.

`mcp_server.py:_get_embedder` (the lazy sync getter) stays sync but the
lazy probe in `RemoteEmbedder.__init__` was eliminated (§2), so the sync
construction is non-blocking even when it returns a `RemoteEmbedder`.

`cli.py:_search` and any other sync CLI paths bypass the factory
explicitly: they call `Embedder.from_settings(settings)` only after
clearing `EMBEDDER_URL` from a copy of settings, OR they construct
`Embedder(...)` directly. **Resolution: change CLI to call
`Embedder(settings.embedding_model, hf_token=...)` directly without
going through the factory.** This is the "CLI is always local" rule.

### 4. New settings

Add to `src/docforge/config.py`:

```python
# Embedder service URL (Phase 4b). When set, the API/MCP/ingest paths
# delegate embedding to this URL instead of loading the model in-process.
embedder_url: str = ""

# Bearer token for the embedder service. Required when embedder_url is
# set; the embedder service refuses to start without it.
embedder_token: SecretStr = SecretStr("")
```

Env vars: `EMBEDDER_URL` and `EMBEDDER_TOKEN`. Both flow through Key
Vault when running in Azure (see §6). `embedder_token` is a `SecretStr`
so it doesn't leak in `repr(settings)` (consistent with `hf_token`,
`confluence_api_token`).

A `model_validator` rejects the misconfiguration where `embedder_url`
is set but `embedder_token` is empty — same intent as the existing
auth.mode=entra validator.

### 5. Build pipeline: separate Dockerfile for the embedder

`Dockerfile.embedder` at repo root, using BuildKit secrets so HF_TOKEN
never enters an image layer:

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

# Pre-download the embedding model at build time. HF_TOKEN comes from a
# BuildKit secret mount and never lands in any image layer.
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

Notes:
- `# syntax=docker/dockerfile:1.6` enables BuildKit secret mount.
- `--mount=type=secret,id=hf_token` exposes the token to one
  `RUN` only; it's not in the image, not in `docker history`, not in
  any layer.
- `HF_HOME=/app/.cache/huggingface` is set both during the model-download
  RUN and as the runtime ENV so the cached model is at the same path
  during build and at runtime.
- `start-period=60s` (down from the spec's earlier 120s — model load
  with baked weights is ~5–10s, healthcheck retries cover the tail).

CI build invocation:
```bash
docker build \
  --secret id=hf_token,env=HF_TOKEN \
  -f Dockerfile.embedder \
  -t docforge-embedder:${{ github.sha }} .
```

### 6. Bicep changes

`deploy/azure/main.bicep` adds:

- A second Container App `${namePrefix}-embedder`, **external ingress**
  (same as the API), targetPort 8001. External-with-auth, not
  internal-without-auth.
- Scale: `minReplicas: 0`, `maxReplicas: 5` (parameter
  `embedderMaxReplicas`), HTTP scale rule `concurrentRequests: 5`.
- Resources: `cpu: 2.0`, `memory: 4Gi` — embedding inference is
  CPU-bound; doubled vs. the API.
- A new Key Vault secret `embedder-token` — generated via
  `[guid(deployment().name, 'embedder-token')]` in Bicep so it's stable
  across re-deploys but unique per deployment. (Or: passed in as a
  `@secure() param embedderToken string` so the operator owns rotation.
  Resolution: parameter, not auto-generate, so rotation is explicit.)
- Embedder Container App env: `EMBEDDER_TOKEN` from `embedder-token`
  Key Vault secret reference.
- Search API Container App env additions:
  - `EMBEDDER_URL=https://${embedderApp.properties.configuration.ingress.fqdn}`
  - `EMBEDDER_TOKEN` from the same Key Vault secret reference.
- Both Container Apps get Key Vault Secrets User role (the embedder is
  new; the search API already has it from 4a).
- Two-pass deploy preserved: `embedderImage string = ''` parameter for
  first-pass placeholder, real image on second pass.

The first-pass placeholder behavior is the same as the search API today:
hello-world image, no probes, no env, no secrets — provisions the
resource shell so the second pass can hydrate it once the real image is
pushed. The `EMBEDDER_URL` env on the search API is only set on the
second pass when the embedder app's FQDN is real.

### 7. CI workflow changes

`.github/workflows/ci.yml`:

- Add an `embedder-image` build job that runs after `test` passes,
  uses BuildKit secret mount for HF_TOKEN, builds with
  `Dockerfile.embedder`, pushes to ACR with the same git-sha tag.
- The existing image-build job continues building from `Dockerfile`.
- Both build jobs run in parallel after `test`.
- Repo secret `HF_TOKEN` must be set under
  `Settings → Secrets → Actions`. The CI workflow declares
  `secrets: hf_token: ${{ secrets.HF_TOKEN }}` and forwards via
  `--secret id=hf_token,env=HF_TOKEN`. The README needs an "adopters
  forking the repo" note explaining this dependency.
- Integration test job (existing) gains a new test-only step that
  spawns `docforge.embedder_api:app` on a free port (with a generated
  `EMBEDDER_TOKEN`), exports `EMBEDDER_URL` and `EMBEDDER_TOKEN`, and
  re-runs the search/ingest paths. This exercises `RemoteEmbedder`
  end-to-end.

### 8. Tests

#### Unit tests (new):

- `tests/unit/test_embedder_api.py` — the FastAPI service:
  - `/health` returns model + dimensions when ready, 503 before
  - `/embed` rejects empty / oversized batches (Pydantic 422)
  - `/embed` rejects missing bearer token (401)
  - `/embed` rejects wrong bearer token (401)
  - `/embed` returns vectors + dimensions with valid token
  - Lifespan refuses to start with empty `EMBEDDER_TOKEN`
  ~6 tests.

- `tests/unit/test_remote_embedder.py` — `RemoteEmbedder`:
  - Construction does no network (lazy probe)
  - `aembed_query` succeeds, sends bearer header
  - First-call timeout → retry → second succeeds
  - Both calls fail (transport) → raises after second attempt
  - 4xx response (e.g. 401) does not retry, raises immediately
  - 5xx response retries once
  - Mid-flight dimension drift raises `RuntimeError`
  - `aclose` releases the underlying `httpx.AsyncClient`
  ~8 tests.

- `tests/unit/test_embedder_factory.py` — `Embedder.from_settings`:
  - Returns `Embedder` when `embedder_url` is empty
  - Returns `RemoteEmbedder` when `embedder_url` is set
  - Raises when `embedder_url` is set but `embedder_token` is empty
  ~3 tests.

- `tests/unit/test_config.py` — extended for the two new fields:
  - `embedder_url` defaults to empty
  - `embedder_token` defaults to SecretStr("")
  - Both env-overridable
  - Validator: setting `embedder_url` without `embedder_token` raises
  ~3 tests.

- `tests/unit/test_embedder.py` — `Embedder` async methods:
  - `aembed` matches `embed` (delegates via to_thread)
  - `aembed_query` matches `embed_query`
  ~2 tests.

#### Integration tests (new):

- `tests/integration/test_embedder_sidecar.py` — spawn
  `docforge.embedder_api:app` via uvicorn on a free port with a
  generated token, set `EMBEDDER_URL` + `EMBEDDER_TOKEN`, run a
  `/search` against the API and assert results match in-process
  baseline. ~2 tests (one for /search, one verifying ingest path
  via `await embedder.aembed(texts)`).

#### Refactored:

- `tests/conftest.py`:
  - `FakeEmbedder` gains `aembed` / `aembed_query` async methods
    (mirroring the new `Embedder` methods) so it duck-types as the
    Protocol. The `from_settings` classmethod stays the same — it
    returns `FakeEmbedder` directly, bypassing the factory branch.
  - The `fake_embedder` fixture also patches
    `docforge.processors.embedder.RemoteEmbedder` to a stub class
    that mirrors `FakeEmbedder` — so any code path that constructs
    `RemoteEmbedder` directly (rare; only the factory test) gets the
    stub.

- Existing tests in `test_api.py`, `test_mcp_server.py`,
  `test_auth.py`: zero functional changes. The autouse fixture
  `_no_lifespan_defaults` already overrides `get_embedder` with a stub;
  the stub's `aembed_query` (now exposed on `FakeEmbedder`) is what the
  handlers will call after the api.py change.

- `test_ingest.py`: the `fake_embedder` fixture currently patches
  `docforge.ingest.Embedder`. After 4b, ingest.py changes its in-loop
  call to `await embedder.aembed(texts)`. `FakeEmbedder.aembed` is
  added in conftest; the fixture line stays the same.

Estimate: ~22 new tests + ~2 fixture lines updated; total unit suite
~190 passing after 4b.

### 9. Migration playbook (added to docs)

New section in `docs/operations.md` (or `README.md`) — "Upgrading the
embedding model":

1. Pick the new model. Note its dimensionality `D`.
2. Update `embedding_model` and `embedding_dimensions: D` in the
   search API and embedder Container App configs (Bicep parameters or
   Key Vault).
3. Build the embedder image with `EMBEDDING_MODEL=<new>` build arg and
   push.
4. Apply schema migration: add `embedding_new vector(D)` column to
   `chunks`. Run a re-ingest to populate.
5. Cut over: deploy the new embedder image. Search API revisions roll
   over to the new column.
6. After confidence interval: drop the old column.

The dim-mismatch guard means step 2-5 mismatches surface as loud
`RuntimeError` (at first request, not at startup, since `__init__` is
lazy now). Operators see clear log lines and HTTP 503s on `/search`,
not silent bad results.

## Test refactor footprint

Honest count after self-review (the earlier "1-2 lines" was wrong):

- `tests/conftest.py` — ~10 lines: add `aembed`/`aembed_query` to
  `FakeEmbedder`; extend `fake_embedder` fixture to also patch
  `RemoteEmbedder`.
- `src/docforge/api.py:search` — 1 line: change `to_thread(embedder.embed_query, ...)` to `await embedder.aembed_query(...)`.
- `src/docforge/mcp_server.py:search_documentation` — 1 line: same change.
- `src/docforge/ingest.py` — 2 sites: change `embedder.embed(texts)` to
  `await embedder.aembed(texts)`.
- `src/docforge/cli.py:_search` (and any other sync CLI paths) — switch
  from `Embedder.from_settings(settings)` to direct `Embedder(...)`
  construction so the CLI always uses the in-process model regardless
  of `EMBEDDER_URL` being set.
- API lifespan in `api.py` — 2 lines: add `await embedder.aclose()` to
  the `finally` block (only effective when embedder is `RemoteEmbedder`;
  `Embedder` doesn't have `aclose`, so guard with `hasattr`).

Total: ~20 lines of production code change + ~10 lines of test infra +
~22 new tests + 1 new module + 1 new Dockerfile.

## Risks & mitigations

- **Cold-start latency on first request after idle.** With
  `min_replicas=0`, the first `/embed` call after idle eats ~5–10s of
  cold start. Tracked via `request_ms` in `query_log`; outliers visible
  in `latency_report`. Mitigation: bump to `minReplicas=1` via Bicep
  param if cost analysis shows the savings aren't worth it.

- **Embedder image build pipeline doubles CI time.** Two images,
  parallel build helps but the embedder build dominates due to model
  download. Mitigation: BuildKit layer caching means repeated builds
  with unchanged pyproject reuse the model layer. Cache the
  `pip install` and `python -c SentenceTransformer(...)` layers
  separately so model layer survives unrelated `pyproject` edits.

- **Deploy ordering during model upgrades.** New search API expecting
  N-d vectors must wait for the embedder rolling to N-d to complete
  before its requests can succeed. Mitigation: dim-mismatch guard
  fires loud (503), runbook spells out "embedder first, then search,"
  and the migration playbook walks through the column-add → backfill
  → cutover sequence.

- **HF_TOKEN at build pipeline.** The org's GitHub secret must exist
  under name `HF_TOKEN`. Adopters forking the repo need their own.
  Documented in README under "Self-hosting / forking."

- **`asyncio.run()`-from-running-loop footgun is gone.** Removing sync
  `embed`/`embed_query` from `RemoteEmbedder` makes the misuse
  impossible at the type level. Async callers use the helpers; sync
  CLI uses `Embedder` directly.

- **`httpx.AsyncClient` lifecycle.** The lifespan owns construction and
  destruction. The `finally` block in `api.py:lifespan` calls
  `await embedder.aclose()` (guarded by `hasattr(embedder, "aclose")`).
  No file-descriptor leaks across replica restarts.

- **Token rotation.** Operators rotate the `embedder-token` Key Vault
  secret; both Container Apps pull the new value on next revision
  restart. Documentation includes the rotation steps. Bicep parameter
  is the operator-supplied source of truth (so rotation is explicit,
  not implicit-on-redeploy via auto-generated GUIDs).

- **Tokenizer surface degradation in `RemoteEmbedder`.** Whitespace
  approximation in `get_tokenizer_fn`. Used only by the chunker during
  ingest. The hosted ingest worker uses the real tokenizer when run
  with `EMBEDDER_URL` unset (recommended for local CLI ingest), and
  the approximate one when run hosted (acceptable — chunks are
  conservatively sized). Documented in the migration playbook.

- **Type narrowing for callers.** The factory returns
  `EmbedderProtocol`, a `Protocol`. Callers that import `Embedder`
  directly for type annotation see `EmbedderProtocol` after this
  change. mypy users update their annotations once; callers that
  use `Embedder.from_settings(...)` and access `.aembed_query(...)`
  type-check cleanly via the protocol.

## Out of scope

- Authentication via Entra (managed identity) — adopters can layer on
  top; shared-secret is the docforge baseline.
- Internal-only ingress + VNet integration — defer to a hardening
  follow-up if/when adopter feedback shows the public FQDN with
  shared-secret is insufficient.
- Eval-harness gating of model upgrades (Phase 5).
- Per-tenant or per-user embedding models.
- Multiple embedder pools (e.g. one per query type) — defer until
  evidence of a real workload need.
- Caching embeddings at the embedder service.
- GPU-based embedder (CPU sufficient at v0.3 scale).
- Streaming responses for batch embed.

## Success criteria

- All pre-existing unit + integration tests pass after the change.
- New tests cover: embedder service endpoints, `RemoteEmbedder` retry
  + dim-mismatch + auth + lifecycle, factory selection, integration
  end-to-end with a spawned embedder.
- Search API replica memory footprint (RSS at startup) drops from
  ~2 GB to <500 MB on a deployed Container App with `EMBEDDER_URL`
  set. Verified via Container App's metrics post-deploy.
- Search API replica startup time drops to <10s (verified via Log
  Analytics during a deploy).
- Embedder image does not contain HF_TOKEN — verified via
  `docker history docforge-embedder | grep -i token` returning no
  matches.
- A deliberate dim-mismatch test (deploy embedder with a 384-d model
  while search expects 768-d) fires a clean 503 with a clear log line;
  no silent bad results.
- p95 `/search` latency at warm steady state degrades by <20ms vs. the
  in-process baseline (one HTTP hop intra-region). Cold-start
  outliers expected and acceptable.

## Implementation plan

Drafted next via the `superpowers:writing-plans` skill. Saved to
`docs/superpowers/plans/2026-04-26-v03-phase-4b-embedder-sidecar.md`.
