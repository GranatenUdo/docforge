"""Real-model smoke test for the Embedder.

Loads the ungated `sentence-transformers/all-MiniLM-L6-v2` (384-d, ~80 MB)
and asserts on the contract the unit-test FakeEmbedder mocks:

- the loaded model reports the dimension we expect,
- two distinct texts produce two distinct vectors.

Catches dim-drift and degenerate-embedding bugs that the mock-based unit
suite (`tests/unit/test_embedder.py`) cannot — without depending on the
HF-gated EmbeddingGemma. No HF token required.
"""

from __future__ import annotations

import pytest

from docforge.processors.embedder import Embedder

UNGATED_MODEL = "sentence-transformers/all-MiniLM-L6-v2"


@pytest.fixture(scope="module")
def real_embedder() -> Embedder:
    """Module-scoped so the model load (~5 s after HF cache) pays once."""
    return Embedder(UNGATED_MODEL, expected_dimensions=384)


def test_real_model_loads_with_expected_dimension(real_embedder: Embedder) -> None:
    """The 384-d ungated model loads and reports dim=384."""
    assert real_embedder.dimensions == 384


def test_real_model_produces_different_embeddings_for_different_text(
    real_embedder: Embedder,
) -> None:
    """Non-degenerate: two distinct texts get two distinct 384-d vectors."""
    a = real_embedder.embed_query("hello")
    b = real_embedder.embed_query("world")
    assert a != b
    assert len(a) == 384
    assert len(b) == 384
