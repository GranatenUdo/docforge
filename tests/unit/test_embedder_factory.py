"""Tests for Embedder.from_settings factory branch (Phase 4b)."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from docforge.processors.embedder import Embedder, RemoteEmbedder


def _settings(url: str = "", token: str = "") -> SimpleNamespace:
    return SimpleNamespace(
        embedding_model="test/model",
        embedding_dimensions=768,
        embedding_fp16=False,
        hf_token=SimpleNamespace(get_secret_value=lambda: ""),
        embedder_url=url,
        embedder_token=SimpleNamespace(get_secret_value=lambda: token),
    )


class TestFactoryBranch:
    def test_returns_in_process_embedder_when_url_empty(self, monkeypatch):
        # Patch SentenceTransformer so construction doesn't load a real model.
        import sentence_transformers

        fake_st_instance = MagicMock()
        fake_st_instance.get_embedding_dimension.return_value = 768
        fake_st = MagicMock(return_value=fake_st_instance)
        monkeypatch.setattr(sentence_transformers, "SentenceTransformer", fake_st)

        result = Embedder.from_settings(_settings(url=""))
        assert isinstance(result, Embedder)
        assert not isinstance(result, RemoteEmbedder)

    def test_returns_remote_embedder_when_url_set(self):
        result = Embedder.from_settings(_settings(url="https://embed.internal", token="hunter2"))
        assert isinstance(result, RemoteEmbedder)
        assert result._url == "https://embed.internal"
        assert result._token == "hunter2"
        assert result._expected_dimensions == 768

    def test_url_set_without_token_raises(self):
        # The Settings model_validator catches this case before from_settings
        # is called in production. The factory has its own guard for direct
        # callers (e.g., a SimpleNamespace settings stub in tests/scripts).
        with pytest.raises(RuntimeError, match="embedder_token"):
            Embedder.from_settings(_settings(url="https://embed", token=""))
