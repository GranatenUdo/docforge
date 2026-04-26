"""Tests for docforge.processors.embedder.

Patches sentence_transformers.SentenceTransformer to avoid loading real
models (which would download ~1.2GB and take >30s).
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import numpy as np
import pytest


def _fake_st_model(dim: int = 768, encode_return=None):
    model = MagicMock()
    model.get_embedding_dimension.return_value = dim
    if encode_return is None:
        encode_return = np.array([[0.1, 0.2, 0.3, 0.4]])
    model.encode.return_value = encode_return
    model.tokenizer.encode.side_effect = lambda text, add_special_tokens=False: text.split()
    return model


class TestEmbedderInit:
    def test_primary_model_loads_successfully(self):
        fake = _fake_st_model(dim=768)
        with patch("sentence_transformers.SentenceTransformer", return_value=fake) as mock_st:
            from docforge.processors.embedder import Embedder

            emb = Embedder("primary/model", hf_token="tok")

        assert emb.model_name == "primary/model"
        assert emb.dimensions == 768
        mock_st.assert_called_once_with("primary/model", token="tok")

    def test_falls_back_when_primary_fails(self):
        fake_fallback = _fake_st_model(dim=384)
        call_count = {"n": 0}

        def side_effect(*args, **kwargs):
            call_count["n"] += 1
            if call_count["n"] == 1:
                raise RuntimeError("primary exploded")
            return fake_fallback

        with patch("sentence_transformers.SentenceTransformer", side_effect=side_effect):
            from docforge.processors.embedder import Embedder

            emb = Embedder("primary/broken")

        assert emb.model_name == "sentence-transformers/all-MiniLM-L6-v2"
        assert emb.dimensions == 384
        assert call_count["n"] == 2

    def test_raises_when_both_models_fail(self):
        with patch("sentence_transformers.SentenceTransformer", side_effect=RuntimeError("gone")):
            from docforge.processors.embedder import Embedder

            with pytest.raises(RuntimeError, match="No embedding model available"):
                Embedder("primary/broken")

    def test_uses_env_token_when_arg_empty(self, monkeypatch):
        monkeypatch.setenv("HF_TOKEN", "env_tok_123")
        fake = _fake_st_model()
        with patch("sentence_transformers.SentenceTransformer", return_value=fake) as mock_st:
            from docforge.processors.embedder import Embedder

            Embedder("some/model", hf_token="")

        mock_st.assert_called_once_with("some/model", token="env_tok_123")

    def test_passes_none_when_no_token_available(self, monkeypatch):
        monkeypatch.delenv("HF_TOKEN", raising=False)
        fake = _fake_st_model()
        with patch("sentence_transformers.SentenceTransformer", return_value=fake) as mock_st:
            from docforge.processors.embedder import Embedder

            Embedder("open/model", hf_token="")

        mock_st.assert_called_once_with("open/model", token=None)

    def test_raises_when_loaded_dim_does_not_match_expected(self):
        """Guard fires when configured embedding_dimensions disagrees with model."""
        fake = _fake_st_model(dim=384)
        with patch("sentence_transformers.SentenceTransformer", return_value=fake):
            from docforge.processors.embedder import Embedder

            with pytest.raises(RuntimeError, match="dimension mismatch"):
                Embedder("primary/model", hf_token="tok", expected_dimensions=768)

    def test_loads_when_loaded_dim_matches_expected(self):
        """No guard fire when expected dim matches model."""
        fake = _fake_st_model(dim=768)
        with patch("sentence_transformers.SentenceTransformer", return_value=fake):
            from docforge.processors.embedder import Embedder

            emb = Embedder("primary/model", hf_token="tok", expected_dimensions=768)
            assert emb.dimensions == 768

    def test_no_check_when_expected_dim_omitted(self):
        """expected_dimensions defaults to None — guard skipped, backwards compat."""
        fake = _fake_st_model(dim=384)
        with patch("sentence_transformers.SentenceTransformer", return_value=fake):
            from docforge.processors.embedder import Embedder

            emb = Embedder("primary/model", hf_token="tok")
            assert emb.dimensions == 384

    def test_guard_fires_after_fallback_with_wrong_dim(self):
        """Fallback model has dim 384; if config expects 768, guard fires."""
        fake_fallback = _fake_st_model(dim=384)
        call_count = {"n": 0}

        def side_effect(*args, **kwargs):
            call_count["n"] += 1
            if call_count["n"] == 1:
                raise RuntimeError("primary exploded")
            return fake_fallback

        with patch("sentence_transformers.SentenceTransformer", side_effect=side_effect):
            from docforge.processors.embedder import Embedder

            with pytest.raises(RuntimeError, match="dimension mismatch"):
                Embedder("primary/broken", expected_dimensions=768)

            # Confirm both primary and fallback were attempted (and the
            # guard fired only after the fallback loaded successfully).
            assert call_count["n"] == 2


class TestEmbedderMethods:
    @pytest.fixture
    def embedder(self):
        fake = _fake_st_model(
            dim=4,
            encode_return=np.array([[0.1, 0.2, 0.3, 0.4], [0.5, 0.6, 0.7, 0.8]]),
        )
        with patch("sentence_transformers.SentenceTransformer", return_value=fake):
            from docforge.processors.embedder import Embedder

            return Embedder("m")

    def test_embed_empty_list_returns_empty(self, embedder):
        assert embedder.embed([]) == []

    def test_embed_returns_list_of_lists(self, embedder):
        result = embedder.embed(["hello", "world"])
        assert result == [[0.1, 0.2, 0.3, 0.4], [0.5, 0.6, 0.7, 0.8]]

    def test_embed_query_returns_single_vector(self, embedder):
        result = embedder.embed_query("hello")
        assert result == [0.1, 0.2, 0.3, 0.4]

    def test_get_tokenizer_fn_counts_tokens(self, embedder):
        counter = embedder.get_tokenizer_fn()
        assert counter("one two three four") == 4
        assert counter("") == 0
