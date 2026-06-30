from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Protocol, runtime_checkable

import httpx

if TYPE_CHECKING:
    from docforge.config import Settings

logger = logging.getLogger(__name__)


@runtime_checkable
class RerankerProtocol(Protocol):
    """Common surface for cross-encoder rerankers.

    Async callers (the search path via perform_search) program against this
    via `arerank`. Only the remote variant is wired into the engine; the
    in-process Reranker is constructed exclusively by the future
    reranker_api.py sidecar, not by `reranker_from_settings`.
    """

    async def arerank(self, query: str, passages: list[str]) -> list[tuple[int, float]]: ...


# NOTE: consumed by the reranker sidecar (reranker_api.py), not by the in-engine
# search path. reranker_from_settings never builds this; the sidecar wraps it.
class Reranker:
    """Re-scores (query, passage) pairs with an in-process cross-encoder.

    Loads a sentence-transformers CrossEncoder once at initialization and
    reuses it. Default model is BAAI/bge-reranker-v2-m3. This class is used
    only by the reranker sidecar service (reranker_api.py); the engine's
    search path talks to that sidecar over HTTP via RemoteReranker.
    """

    def __init__(
        self,
        model_name: str = "BAAI/bge-reranker-v2-m3",
        hf_token: str = "",
        batch_size: int = 8,
        max_length: int = 512,
    ) -> None:
        from sentence_transformers import CrossEncoder

        logger.info(
            "Loading reranker model: %s (batch_size=%d, max_length=%d)",
            model_name,
            batch_size,
            max_length,
        )
        # max_length truncates each (query, passage) pair. bge-reranker-v2-m3
        # allows up to 8192 tokens, whose O(n^2) attention activations OOM the
        # T4 on a realistic top-N batch; 512 is the standard reranker window.
        self._model = CrossEncoder(model_name, token=hf_token or None, max_length=max_length)
        self.model_name = model_name
        self._batch_size = batch_size
        # Runs in fp32 — do NOT re-add an fp16 `.half()` cast. It silently
        # breaks CrossEncoder.predict in sentence-transformers 5.x (the
        # xlm-roberta position-id path raises AttributeError under half
        # precision; the model still LOADS, so /health passes while /rerank
        # 500s). It was also unnecessary: the reranker has its own dedicated
        # T4 (16 GiB), so bge-reranker-v2-m3 (~2.3 GB) fits in full precision.

    def score(self, query: str, passages: list[str]) -> list[float]:
        """Return one relevance score per passage, in input order."""
        scores = self._model.predict(
            [(query, p) for p in passages], batch_size=self._batch_size
        ).tolist()
        # Release cached GPU blocks between requests so fragmentation from a
        # large batch doesn't OOM a later one on the shared-capacity T4. No-op
        # on CPU. torch is imported lazily (sync path, runs via to_thread) so
        # the search-api process — which only uses RemoteReranker — never loads it.
        import torch

        if torch.cuda.is_available():
            torch.cuda.empty_cache()
        return scores


class RemoteReranker:
    """HTTP client for the docforge reranker sidecar service.

    Async-only surface. Mirrors RemoteEmbedder: lazy client creation,
    bearer auth, retry-twice with 4xx-fail-loud / 5xx-and-transport-retry.
    """

    def __init__(
        self,
        url: str,
        token: str,
        # Match RemoteEmbedder's 60s default: a cross-encoder GPU round-trip
        # over ~50 pairs can exceed the small embedder's sub-second budget,
        # especially on a cold connection. The retry loop bounds total wait.
        timeout_seconds: float = 60.0,
    ) -> None:
        self._url = url.rstrip("/")
        self._token = token
        self._timeout_seconds = timeout_seconds
        self._client: httpx.AsyncClient | None = None

    async def _ensure_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=self._timeout_seconds)
        return self._client

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def _post_rerank(self, query: str, passages: list[str]) -> list[float]:
        client = await self._ensure_client()
        for attempt in (1, 2):
            try:
                resp = await client.post(
                    f"{self._url}/rerank",
                    json={"query": query, "texts": passages},
                    headers={"Authorization": f"Bearer {self._token}"},
                )
                resp.raise_for_status()
                try:
                    payload = resp.json()
                except ValueError as e:
                    # A 200 with a non-JSON body (e.g. a proxy/ingress HTML
                    # interstitial, or a partial write) is a contract violation,
                    # not a transient fault. Fail loud as RuntimeError so it
                    # routes through perform_search -> RerankerUnavailable/502
                    # like the wrong-shape case below, instead of escaping as
                    # a JSONDecodeError that lands in the generic 503 handler.
                    raise RuntimeError(f"reranker returned a non-JSON body: {e}") from e
                scores = payload.get("scores") if isinstance(payload, dict) else None
                # A 200 with a malformed/wrong-length body is a contract
                # violation, not a transient fault — fail loud (RuntimeError,
                # which perform_search maps to RerankerUnavailable/502) instead
                # of letting a KeyError/length mismatch escape as an opaque 503
                # or trip the downstream permutation guard.
                if not isinstance(scores, list) or len(scores) != len(passages):
                    raise RuntimeError(
                        f"reranker returned a malformed response: expected a list "
                        f"of {len(passages)} scores, got "
                        f"{type(scores).__name__}"
                        + (f" of length {len(scores)}" if isinstance(scores, list) else "")
                    )
                return scores
            except (httpx.TimeoutException, httpx.TransportError):
                if attempt == 1:
                    await asyncio.sleep(0.15)
                    continue
                raise
            except httpx.HTTPStatusError as e:
                # 4xx is config / auth — fail loud, do not retry.
                if e.response.status_code < 500 or attempt == 2:
                    raise
                await asyncio.sleep(0.15)
        # The for-loop's two attempts always either return or raise; this
        # line is unreachable but keeps mypy happy about implicit None.
        raise RuntimeError("unreachable")

    async def arerank(self, query: str, passages: list[str]) -> list[tuple[int, float]]:
        """Return (original_index, score) pairs ordered by descending score.

        The server returns one score per passage in input order; the client
        does its own sort and never trusts the server's positional ordering.
        Carrying the score back lets callers surface the cross-encoder score
        (instead of the stale RRF similarity) on reranked rows.
        """
        scores = await self._post_rerank(query, passages)
        order = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)
        return [(i, scores[i]) for i in order]


def reranker_from_settings(settings: Settings) -> RerankerProtocol | None:
    """Construct a reranker from Settings.

    Returns a RemoteReranker when settings.reranker_url is set; otherwise
    None (reranking disabled). The in-process Reranker is never built here —
    only the reranker_api.py sidecar instantiates it.
    """
    if settings.reranker_url:
        token = settings.reranker_token.get_secret_value()
        if not token:
            raise RuntimeError(
                "reranker_url is set but reranker_token is empty — "
                "refusing to construct a RemoteReranker without auth"
            )
        return RemoteReranker(
            settings.reranker_url,
            token,
            timeout_seconds=settings.rerank_timeout_seconds,
        )
    return None
