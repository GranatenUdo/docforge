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
    Default model is Qwen3-Embedding-4B with Matryoshka truncation to
    1024 dimensions (native 2560). Instruction-aware: queries pass
    prompt_name="query" for the model's query-side template; documents
    use no prompt prefix.

    Falls back to all-MiniLM-L6-v2 (384 dimensions) if the primary
    model fails to load. Raises RuntimeError at init time if
    expected_dimensions is provided and the loaded model reports a
    different dimension. Pass expected_dimensions=settings.embedding_dimensions
    to enable the guard.
    """

    def __init__(
        self,
        model_name: str = "Qwen/Qwen3-Embedding-4B",
        hf_token: str = "",
        expected_dimensions: int | None = None,
        fp16: bool = True,
        batch_size: int = 32,
    ) -> None:
        from sentence_transformers import SentenceTransformer

        # Use provided token, fall back to environment variable
        if not hf_token:
            hf_token = os.environ.get("HF_TOKEN", "")

        self._batch_size = batch_size

        try:
            logger.info("Loading embedding model: %s (fp16=%s)", model_name, fp16)
            st_kwargs: dict = {
                "token": hf_token or None,
                "truncate_dim": expected_dimensions,
            }
            if fp16:
                # Qwen3-Embedding-4B model card recommends FP16 for production
                # inference. Halves VRAM footprint so the T4's 16 GiB
                # accommodates the model plus realistic activation memory.
                # Sentence-transformers forwards model_kwargs to
                # transformers.AutoModel.from_pretrained(); the string
                # "float16" is the documented form.
                st_kwargs["model_kwargs"] = {"torch_dtype": "float16"}
            self._model = SentenceTransformer(model_name, **st_kwargs)
            if fp16:
                # Belt-and-suspenders FP16 enforcement. Empirically, the
                # model_kwargs path above doesn't always reach every submodule
                # for sentence-transformers + Qwen3 + Matryoshka (Dense /
                # projection layers can stay FP32). nvidia-smi on a running
                # replica showed ~14 GiB GPU usage at idle — FP32 model size,
                # not FP16. Force-cast post-init covers that gap.
                try:
                    import torch

                    if torch.cuda.is_available():
                        self._model = self._model.half()
                except Exception:
                    logger.warning("Could not force model.half() — keeping default dtype")
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
            fp16=settings.embedding_fp16,
            batch_size=settings.embedding_batch_size,
        )

    def embed(self, texts: list[str]) -> list[list[float]]:
        """Generate embeddings for a list of texts.

        Returns a list of float vectors, one per input text.

        Internally chunks the input into batches of `self._batch_size` before
        calling SentenceTransformer.encode. This caps GPU activation memory
        per call, which is the difference between fitting in a T4's 16 GiB
        VRAM and OOMing on large sources.

        Raises:
            ValueError: when len(texts) exceeds MAX_BATCH_SIZE. Callers that
                need to embed more than that should chunk before calling
                embed().
        """
        if not texts:
            return []
        if len(texts) > MAX_BATCH_SIZE:
            raise ValueError(
                f"Embedder batch size {len(texts)} exceeds max {MAX_BATCH_SIZE}; "
                f"chunk into smaller batches before calling embed()"
            )

        try:
            import torch

            cuda_available = torch.cuda.is_available()
        except Exception:
            cuda_available = False

        result: list[list[float]] = []
        for start in range(0, len(texts), self._batch_size):
            sub = texts[start : start + self._batch_size]
            embeddings = self._model.encode(sub, show_progress_bar=False, normalize_embeddings=True)
            result.extend(embeddings.tolist())
            if cuda_available:
                # Release PyTorch's CUDA cache between batches. Without this,
                # cached activation buffers from prior sub-batches stay
                # resident, and large sources (e.g., a 100-chunk file with
                # batch_size=8 -> 13 inner encodes) accumulate cache until
                # the next inner call OOMs on a 600 MiB allocation. Calling
                # empty_cache() forces PyTorch to return free blocks to the
                # CUDA driver. Cheap when there's nothing to release.
                torch.cuda.empty_cache()
        return result

    def embed_query(self, query: str) -> list[float]:
        """Generate embedding for a single search query.

        Uses prompt_name="query" when the loaded model has a "query"
        prompt template (Qwen3 family). Legacy models without that
        template (Gemma, all-MiniLM fallback) skip the kwarg.
        """
        if not query:
            raise ValueError("embed_query requires a non-empty query string")
        encode_kwargs: dict = {"show_progress_bar": False, "normalize_embeddings": True}
        if "query" in (getattr(self._model, "prompts", None) or {}):
            encode_kwargs["prompt_name"] = "query"
        result = self._model.encode([query], **encode_kwargs)
        return result.tolist()[0]

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
        # 5s was tuned for the small Gemma-300M embedder where every call
        # is sub-second. With Qwen-4B on a Tesla T4, cold connections + larger
        # batches push p99 past 5s. Default bumped to 60s; the retry loop
        # still bounds total wait to ~120s on the slow path. Callers can
        # override via the constructor if a stricter SLA is needed.
        timeout_seconds: float = 60.0,
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

    async def aembed(self, texts: list[str]) -> list[list[float]]:
        return await self._post_embed(texts)

    async def aembed_query(self, query: str) -> list[float]:
        result = await self._post_embed([query])
        return result[0]

    def get_tokenizer_fn(self) -> Callable[[str], int]:
        return lambda s: len(s.split())
