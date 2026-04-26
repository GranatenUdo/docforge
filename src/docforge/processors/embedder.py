from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:
    from docforge.config import Settings

logger = logging.getLogger(__name__)


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
    def from_settings(cls, settings: Settings) -> Embedder:
        """Construct an Embedder from the application Settings.

        All four production callers (API, MCP, ingest, CLI) go through this so
        that the settings-derived construction lives in one place; adding a
        new settings-driven parameter doesn't require updating every site.
        """
        return cls(
            settings.embedding_model,
            hf_token=settings.hf_token.get_secret_value(),
            expected_dimensions=settings.embedding_dimensions,
        )

    def embed(self, texts: list[str]) -> list[list[float]]:
        """Generate embeddings for a list of texts.

        Returns a list of float vectors, one per input text.
        """
        if not texts:
            return []

        embeddings = self._model.encode(texts, show_progress_bar=False, normalize_embeddings=True)
        return embeddings.tolist()

    def embed_query(self, query: str) -> list[float]:
        """Generate embedding for a single search query."""
        result = self.embed([query])
        return result[0]

    def get_tokenizer_fn(self) -> Callable[[str], int]:
        """Return a token-counting function using this model's tokenizer."""
        tokenizer = self._model.tokenizer

        def count_tokens(text: str) -> int:
            return len(tokenizer.encode(text, add_special_tokens=False))

        return count_tokens
