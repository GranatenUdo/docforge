"""Tests for docforge.processors.embedder.

Patches sentence_transformers.SentenceTransformer to avoid loading real
models (which would download ~1.2GB and take >30s).
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from docforge.processors.embedder import MAX_BATCH_SIZE


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

            emb = Embedder("primary/model", hf_token="tok", fp16=False)

        assert emb.model_name == "primary/model"
        assert emb.dimensions == 768
        mock_st.assert_called_once_with("primary/model", token="tok", truncate_dim=None)

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

            Embedder("some/model", hf_token="", fp16=False)

        mock_st.assert_called_once_with("some/model", token="env_tok_123", truncate_dim=None)

    def test_passes_none_when_no_token_available(self, monkeypatch):
        monkeypatch.delenv("HF_TOKEN", raising=False)
        fake = _fake_st_model()
        with patch("sentence_transformers.SentenceTransformer", return_value=fake) as mock_st:
            from docforge.processors.embedder import Embedder

            Embedder("open/model", hf_token="", fp16=False)

        mock_st.assert_called_once_with("open/model", token=None, truncate_dim=None)

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

    def test_embed_rejects_batch_over_max_size(self, embedder):
        """Batch larger than MAX_BATCH_SIZE raises ValueError before reaching the model."""
        with pytest.raises(ValueError, match="exceeds max"):
            embedder.embed(["x"] * (MAX_BATCH_SIZE + 1))


class TestEmbedderAsyncHelpers:
    """Phase 4b: async helpers wrap sync embed/embed_query via to_thread.
    Async callers (api, mcp, ingest) use these instead of the sync forms."""

    @pytest.mark.asyncio
    async def test_aembed_delegates_to_embed(self, monkeypatch):
        from unittest.mock import MagicMock

        import sentence_transformers

        from docforge.processors.embedder import Embedder

        # Avoid actually loading a model — patch encode at the source.
        fake_st = MagicMock()
        fake_st_instance = MagicMock()
        fake_st_instance.get_embedding_dimension.return_value = 768
        fake_st_instance.encode.return_value = MagicMock(tolist=lambda: [[0.1] * 768, [0.2] * 768])
        fake_st.return_value = fake_st_instance
        monkeypatch.setattr(sentence_transformers, "SentenceTransformer", fake_st)

        e = Embedder("test/model", expected_dimensions=768)
        result = await e.aembed(["a", "b"])
        assert result == [[0.1] * 768, [0.2] * 768]

    @pytest.mark.asyncio
    async def test_aembed_query_delegates_to_embed_query(self, monkeypatch):
        from unittest.mock import MagicMock

        import sentence_transformers

        from docforge.processors.embedder import Embedder

        fake_st = MagicMock()
        fake_st_instance = MagicMock()
        fake_st_instance.get_embedding_dimension.return_value = 768
        fake_st_instance.encode.return_value = MagicMock(tolist=lambda: [[0.5] * 768])
        fake_st.return_value = fake_st_instance
        monkeypatch.setattr(sentence_transformers, "SentenceTransformer", fake_st)

        e = Embedder("test/model", expected_dimensions=768)
        result = await e.aembed_query("hello")
        assert result == [0.5] * 768


class TestQwenMigration:
    """Task 2: Qwen-4B default, Matryoshka truncate_dim, instruction-aware query prompt."""

    def test_embedder_default_model_is_qwen(self):
        """The Embedder class default model_name parameter matches Settings default."""
        import inspect

        from docforge.processors.embedder import Embedder

        sig = inspect.signature(Embedder.__init__)
        default = sig.parameters["model_name"].default
        assert default == "Qwen/Qwen3-Embedding-4B", (
            f"Embedder default model_name is {default!r}, expected Qwen-4B"
        )

    def test_embedder_passes_truncate_dim_to_sentence_transformer(self, monkeypatch):
        """Verify Embedder forwards expected_dimensions as truncate_dim so MRL slicing
        happens at the SentenceTransformer layer (not post-hoc in our code)."""
        import sys

        from docforge.processors.embedder import Embedder

        captured = {}

        class FakeST:
            def __init__(self, name, token=None, truncate_dim=None, model_kwargs=None):
                captured["name"] = name
                captured["truncate_dim"] = truncate_dim
                self.prompts = {}

            def get_embedding_dimension(self):
                return captured.get("truncate_dim") or 2560

            def encode(self, texts, **kwargs):
                import numpy as np

                n = len(texts) if isinstance(texts, list) else 1
                return np.zeros((n, self.get_embedding_dimension()), dtype=np.float32)

            @property
            def tokenizer(self):
                class T:
                    def encode(self, s, add_special_tokens=False):
                        return s.split()

                return T()

        monkeypatch.setitem(
            sys.modules, "sentence_transformers", type("M", (), {"SentenceTransformer": FakeST})()
        )

        emb = Embedder(model_name="Qwen/Qwen3-Embedding-4B", expected_dimensions=1024)
        assert captured["truncate_dim"] == 1024
        assert emb.dimensions == 1024

    def test_embed_query_passes_prompt_name_query_for_qwen(self, monkeypatch):
        """Verify Embedder.embed_query forwards prompt_name='query' when model has the template."""
        import sys

        from docforge.processors.embedder import Embedder

        captured_kwargs = []

        class FakeSTQwen:
            def __init__(self, name, token=None, truncate_dim=None, model_kwargs=None):
                self._dim = truncate_dim or 2560
                # Qwen models expose a 'query' prompt template
                self.prompts = {
                    "query": (
                        "Instruct: Given a web search query, retrieve relevant "
                        "passages that answer the query\nQuery: "
                    )
                }

            def get_embedding_dimension(self):
                return self._dim

            def encode(self, texts, **kwargs):
                import numpy as np

                captured_kwargs.append(kwargs)
                n = len(texts) if isinstance(texts, list) else 1
                return np.zeros((n, self._dim), dtype=np.float32)

            @property
            def tokenizer(self):
                class T:
                    def encode(self, s, add_special_tokens=False):
                        return s.split()

                return T()

        monkeypatch.setitem(
            sys.modules,
            "sentence_transformers",
            type("M", (), {"SentenceTransformer": FakeSTQwen})(),
        )

        emb = Embedder(model_name="Qwen/Qwen3-Embedding-4B", expected_dimensions=1024)
        emb.embed_query("test query")
        assert any(kw.get("prompt_name") == "query" for kw in captured_kwargs), (
            f"embed_query did not forward prompt_name='query'; got kwargs={captured_kwargs}"
        )

    def test_embed_query_skips_prompt_name_when_model_has_no_query_prompt(self, monkeypatch):
        """Legacy models (Gemma, all-MiniLM) lack a 'query' prompt — must skip the kwarg."""
        import sys

        from docforge.processors.embedder import Embedder

        captured_kwargs = []

        class FakeSTNoPrompts:
            def __init__(self, name, token=None, truncate_dim=None):
                self._dim = truncate_dim or 384
                self.prompts = {}  # no query template

            def get_embedding_dimension(self):
                return self._dim

            def encode(self, texts, **kwargs):
                import numpy as np

                captured_kwargs.append(kwargs)
                return np.zeros((1, self._dim), dtype=np.float32)

            @property
            def tokenizer(self):
                class T:
                    def encode(self, s, add_special_tokens=False):
                        return s.split()

                return T()

        monkeypatch.setitem(
            sys.modules,
            "sentence_transformers",
            type("M", (), {"SentenceTransformer": FakeSTNoPrompts})(),
        )

        emb = Embedder(model_name="legacy/model", expected_dimensions=384)
        emb.embed_query("q")
        assert "prompt_name" not in captured_kwargs[0], (
            f"prompt_name was passed to a legacy model: {captured_kwargs}"
        )


class TestFp16Loading:
    """Verify Embedder constructor + from_settings handle fp16 flag correctly.

    These tests guard the GPU-OOM fix from regression. If the model_kwargs
    plumbing breaks, the embedder will silently load FP32 again and OOM
    under load on T4 hardware. See spec
    docs/superpowers/specs/2026-05-13-ingest-completion-design.md
    """

    def test_fp16_true_forwards_model_kwargs(self, monkeypatch):
        import sys

        from docforge.processors.embedder import Embedder

        captured: dict = {}

        class FakeST:
            def __init__(self, name, token=None, truncate_dim=None, model_kwargs=None):
                captured["model_kwargs"] = model_kwargs
                self.prompts: dict = {}

            def get_embedding_dimension(self):
                return 1024

            def encode(self, texts, **kwargs):
                import numpy as np

                n = len(texts) if isinstance(texts, list) else 1
                return np.zeros((n, 1024), dtype=np.float32)

            @property
            def tokenizer(self):
                class T:
                    def encode(self, s, add_special_tokens=False):
                        return s.split()

                return T()

        monkeypatch.setitem(
            sys.modules,
            "sentence_transformers",
            type("M", (), {"SentenceTransformer": FakeST})(),
        )

        Embedder(
            model_name="Qwen/Qwen3-Embedding-4B",
            expected_dimensions=1024,
            fp16=True,
        )

        assert captured["model_kwargs"] == {"torch_dtype": "float16"}, (
            f"fp16=True did not forward model_kwargs correctly: {captured}"
        )

    def test_fp16_false_omits_model_kwargs(self, monkeypatch):
        import sys

        from docforge.processors.embedder import Embedder

        captured: dict = {}

        class FakeST:
            def __init__(self, name, token=None, truncate_dim=None, model_kwargs=None):
                captured["model_kwargs"] = model_kwargs
                self.prompts: dict = {}

            def get_embedding_dimension(self):
                return 384

            def encode(self, texts, **kwargs):
                import numpy as np

                return np.zeros((1, 384), dtype=np.float32)

            @property
            def tokenizer(self):
                class T:
                    def encode(self, s, add_special_tokens=False):
                        return s.split()

                return T()

        monkeypatch.setitem(
            sys.modules,
            "sentence_transformers",
            type("M", (), {"SentenceTransformer": FakeST})(),
        )

        Embedder(
            model_name="legacy/model",
            expected_dimensions=384,
            fp16=False,
        )

        assert captured["model_kwargs"] is None, (
            f"fp16=False unexpectedly forwarded model_kwargs={captured['model_kwargs']!r}"
        )

    def test_from_settings_forwards_embedding_fp16(self, monkeypatch):
        import sys

        from docforge.config import Settings
        from docforge.processors.embedder import Embedder

        captured: dict = {}

        class FakeST:
            def __init__(self, name, token=None, truncate_dim=None, model_kwargs=None):
                captured["model_kwargs"] = model_kwargs
                self.prompts: dict = {}

            def get_embedding_dimension(self):
                return 1024

            def encode(self, texts, **kwargs):
                import numpy as np

                return np.zeros((1, 1024), dtype=np.float32)

            @property
            def tokenizer(self):
                class T:
                    def encode(self, s, add_special_tokens=False):
                        return s.split()

                return T()

        monkeypatch.setitem(
            sys.modules,
            "sentence_transformers",
            type("M", (), {"SentenceTransformer": FakeST})(),
        )

        settings = Settings(
            embedding_model="Qwen/Qwen3-Embedding-4B",
            embedding_dimensions=1024,
            embedding_fp16=True,
        )

        Embedder.from_settings(settings)

        assert captured["model_kwargs"] == {"torch_dtype": "float16"}, (
            "from_settings did not propagate settings.embedding_fp16 -> Embedder.fp16"
        )
