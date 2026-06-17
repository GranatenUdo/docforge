from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Protocol, runtime_checkable

import httpx

from docforge.processors.embedder import _detect_cuda

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

    async def arerank(self, query: str, passages: list[str]) -> list[int]: ...


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
        fp16: bool = True,
    ) -> None:
        from sentence_transformers import CrossEncoder

        self._cuda_available = _detect_cuda()
        logger.info("Loading reranker model: %s (fp16=%s)", model_name, fp16)
        self._model = CrossEncoder(model_name, token=hf_token or None)
        self.model_name = model_name
        if fp16 and self._cuda_available:
            # Mirror the Embedder FP16 path: cast the underlying transformer
            # to half precision so the cross-encoder fits alongside the
            # embedding model on the same GPU.
            self._model.model = self._model.model.half()

    def score(self, query: str, passages: list[str]) -> list[float]:
        """Return one relevance score per passage, in input order."""
        return self._model.predict([(query, p) for p in passages]).tolist()


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
                return resp.json()["scores"]
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

    async def arerank(self, query: str, passages: list[str]) -> list[int]:
        """Return passage indices ordered by descending relevance score.

        The server returns one score per passage in input order; the client
        does its own sort and never trusts the server's positional ordering.
        """
        scores = await self._post_rerank(query, passages)
        return sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)


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
        )
    return None
