from __future__ import annotations

import logging
import os
from typing import Callable

logger = logging.getLogger(__name__)


class Embedder:
    """Generates text embeddings using a sentence-transformers model.

    Loads the model once at initialization and reuses it for all calls.
    Default model is EmbeddingGemma-300M (768 dimensions).
    Falls back to all-MiniLM-L6-v2 (384 dimensions) if the primary model fails to load.
    """

    def __init__(
        self, model_name: str = "google/embeddinggemma-300m", hf_token: str = ""
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
            logger.info(
                "Model loaded: %s (%d dimensions)", self.model_name, self.dimensions
            )
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
                logger.error(
                    "Failed to load fallback model %s", fallback, exc_info=True
                )
                raise RuntimeError(
                    f"No embedding model available. "
                    f"Primary ({model_name}) and fallback ({fallback}) both failed."
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
