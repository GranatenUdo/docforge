from __future__ import annotations

import asyncio
import logging
import os
from typing import TYPE_CHECKING, Callable, Protocol, runtime_checkable

import httpx

if TYPE_CHECKING:
    from docforge.config import Settings

logger = logging.getLogger(__name__)

MAX_BATCH_SIZE = 256  # typical sentence-transformers per-call ceiling; chunk above this


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
    def get_tokenizer_fn(self) -> Callable[[str], int]: ...


class Embedder:
    """Generates text embeddings using a sentence-transformers model.

    Loads the model once at initialization and reuses it for all calls.
    Default model is EmbeddingGemma-300M (768 dimensions).
    Falls back to all-MiniLM-L6-v2 (384 dimensions) if the primary model fails to load.

    Raises RuntimeError at init time if expected_dimensions is provided and
    the loaded model (primary or fallback) reports a different dimension.
    Pass expected_dimensions=settings.embedding_dimensions to enable the guard.
    """

    def __init__(
        self,
        model_name: str = "google/embeddinggemma-300m",
        hf_token: str = "",
        expected_dimensions: int | None = None,
    ) -> None:
        from sentence_transformers import SentenceTransformer

        # Use provided token, fall back to environment variable
        if not hf_token:
            hf_token = os.environ.get("HF_TOKEN", "")

        try:
            logger.info("Loading embedding model: %s", model_name)
            self._model = SentenceTransformer(model_name, token=hf_token or None)
            self.model_name = model_name
            self.dimensions = self._model.get_embedding_dimension()
            logger.info("Model loaded: %s (%d dimensions)", self.model_name, self.dimensions)
        except Exception:
            fallback = "sentence-transformers/all-MiniLM-L6-v2"
            logger.warning(
                "Failed to load %s, falling back to %s",
                model_name,
                fallback,
                exc_info=True,
            )
            try:
                self._model = SentenceTransformer(fallback)
                self.model_name = fallback
                self.dimensions = self._model.get_embedding_dimension()
                logger.info(
                    "Fallback model loaded: %s (%d dimensions)",
                    self.model_name,
                    self.dimensions,
                )
            except Exception:
                logger.error("Failed to load fallback model %s", fallback, exc_info=True)
                raise RuntimeError(
                    f"No embedding model available. "
                    f"Primary ({model_name}) and fallback ({fallback}) both failed."
                )

        # Catches the silent-mismatch case where the fallback model loads
        # with a different dimensionality than the schema expects.
        if expected_dimensions is not None and self.dimensions != expected_dimensions:
            raise RuntimeError(
                f"Embedding dimension mismatch: model {self.model_name!r} reports "
                f"{self.dimensions}-d, but config requires {expected_dimensions}-d. "
                f"Either change embedding_model in docforge.yml to a "
                f"{expected_dimensions}-d model, or update embedding_dimensions "
                f"and run a schema migration to vector({self.dimensions})."
            )

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

    def embed(self, texts: list[str]) -> list[list[float]]:
        """Generate embeddings for a list of texts.

        Returns a list of float vectors, one per input text.

        Raises:
            ValueError: when len(texts) exceeds MAX_BATCH_SIZE. Callers that
                need to embed more than that should chunk before calling.
        """
        if not texts:
            return []
        if len(texts) > MAX_BATCH_SIZE:
            raise ValueError(
                f"Embedder batch size {len(texts)} exceeds max {MAX_BATCH_SIZE}; "
                f"chunk into smaller batches before calling embed()"
            )

        embeddings = self._model.encode(texts, show_progress_bar=False, normalize_embeddings=True)
        return embeddings.tolist()

    def embed_query(self, query: str) -> list[float]:
        """Generate embedding for a single search query."""
        result = self.embed([query])
        return result[0]

    async def aembed(self, texts: list[str]) -> list[list[float]]:
        """Async wrapper around `embed`; runs the sync model call in a thread."""
        return await asyncio.to_thread(self.embed, texts)

    async def aembed_query(self, query: str) -> list[float]:
        """Async wrapper around `embed_query`; runs the sync model call in a thread."""
        return await asyncio.to_thread(self.embed_query, query)

    def get_tokenizer_fn(self) -> Callable[[str], int]:
        """Return a token-counting function using this model's tokenizer."""
        tokenizer = self._model.tokenizer

        def count_tokens(text: str) -> int:
            return len(tokenizer.encode(text, add_special_tokens=False))

        return count_tokens


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
        self.model_name: str = "remote"
        self.dimensions: int = expected_dimensions

    async def _ensure_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=self._timeout_seconds)
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
                resp = await client.post(
                    f"{self._url}/embed",
                    json={"texts": texts},
                    headers={"Authorization": f"Bearer {self._token}"},
                )
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

    def get_tokenizer_fn(self) -> Callable[[str], int]:
        return lambda s: len(s.split())
