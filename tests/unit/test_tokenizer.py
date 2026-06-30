"""Tests for docforge.processors.tokenizer.get_chunk_tokenizer_fn.

No model download: transformers.AutoTokenizer is stubbed with a deterministic
subword tokenizer whose counts genuinely differ from a plain word-count, so
the parity claim (real tokenizer != word-count) is actually exercised.
"""

from __future__ import annotations

import sys
from types import SimpleNamespace

# Sample text WITH sentence boundaries (periods) and multiple paragraphs, so a
# subword tokenizer and a word-count tokenizer produce different counts.
_SAMPLE = (
    "DocuWare ingests documentation. It chunks and embeds the content.\n\n"
    "The reranker re-scores candidates. Hybrid retrieval fuses dense and sparse."
)


class _FakeTokenizer:
    """Deterministic subword-ish tokenizer: one token per whitespace word PLUS
    one extra token per period (models punctuation as its own subword). This
    makes encode() counts diverge from a plain word-count on text with periods."""

    def encode(self, text: str, add_special_tokens: bool = False) -> list[int]:
        words = text.split()
        periods = text.count(".")
        # Return a list whose length is words + periods; ids themselves unused.
        return list(range(len(words) + periods))


class _FakeAutoTokenizer:
    captured: dict = {}

    @classmethod
    def from_pretrained(cls, model_name, token=None):
        cls.captured["model_name"] = model_name
        cls.captured["token"] = token
        return _FakeTokenizer()


def _word_count(text: str) -> int:
    return len(text.split())


def test_sample_diverges_between_subword_and_word_count():
    # Guard the premise: if these were equal the parity test below would be
    # vacuous. Subword count = words + periods; word-count = words. The sample
    # has 4 periods, so they MUST differ.
    tok = _FakeTokenizer()
    subword = len(tok.encode(_SAMPLE))
    words = _word_count(_SAMPLE)
    assert subword != words
    assert subword == words + _SAMPLE.count(".")


def test_factory_uses_real_tokenizer_and_passes_model_and_token(monkeypatch):
    monkeypatch.setitem(
        sys.modules,
        "transformers",
        SimpleNamespace(AutoTokenizer=_FakeAutoTokenizer),
    )
    from docforge.processors.tokenizer import get_chunk_tokenizer_fn

    settings = SimpleNamespace(
        embedding_model="Qwen/Qwen3-Embedding-4B",
        hf_token=SimpleNamespace(get_secret_value=lambda: "hf-secret"),
    )
    fn = get_chunk_tokenizer_fn(settings)

    # Wiring: model name + HF token forwarded to from_pretrained.
    assert _FakeAutoTokenizer.captured["model_name"] == "Qwen/Qwen3-Embedding-4B"
    assert _FakeAutoTokenizer.captured["token"] == "hf-secret"

    # Counts match the real (stubbed) tokenizer, NOT the word-count approx.
    assert fn(_SAMPLE) == _word_count(_SAMPLE) + _SAMPLE.count(".")
    assert fn(_SAMPLE) != _word_count(_SAMPLE)


def test_factory_passes_none_token_when_hf_token_empty(monkeypatch):
    monkeypatch.setitem(
        sys.modules,
        "transformers",
        SimpleNamespace(AutoTokenizer=_FakeAutoTokenizer),
    )
    from docforge.processors.tokenizer import get_chunk_tokenizer_fn

    settings = SimpleNamespace(
        embedding_model="some/model",
        hf_token=SimpleNamespace(get_secret_value=lambda: ""),
    )
    get_chunk_tokenizer_fn(settings)
    # Empty secret -> None (AutoTokenizer treats "" and None differently;
    # None means "use cached/anonymous", "" can trip an auth path).
    assert _FakeAutoTokenizer.captured["token"] is None
