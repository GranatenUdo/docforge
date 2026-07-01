"""Standalone chunk tokenizer factory.

Chunk sizing must use the REAL model tokenizer regardless of which embedder
backend is in use. The in-process Embedder exposes the model's tokenizer via
get_tokenizer_fn(); the RemoteEmbedder only has a word-count approximation
(embedder.py:329-330), which produces oversized chunks. This factory loads the
tokenizer directly from HuggingFace so the ingest path gets accurate counts
even when embedding is delegated to the remote sidecar (the only weights it
pulls are the tokenizer's few MB — no 8 GB model, no torch GPU load).

`transformers` is already an engine dependency (transitive via
sentence-transformers), so AutoTokenizer imports without a new requirement.
The Qwen tokenizer files download at runtime and need HF_TOKEN (gated model).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:
    from docforge.config import Settings


def get_chunk_tokenizer_fn(settings: Settings) -> Callable[[str], int]:
    """Return a token-counting function backed by the embedding model's real
    tokenizer.

    Loads AutoTokenizer.from_pretrained(settings.embedding_model) once and
    returns a closure counting encoded tokens with add_special_tokens=False
    (mirrors Embedder.get_tokenizer_fn so chunk boundaries match in-process
    ingest exactly).
    """
    from transformers import AutoTokenizer

    tok = AutoTokenizer.from_pretrained(
        settings.embedding_model,
        token=settings.hf_token.get_secret_value() or None,
    )

    def count_tokens(text: str) -> int:
        return len(tok.encode(text, add_special_tokens=False))

    return count_tokens
