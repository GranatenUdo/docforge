"""Shared fixtures for unit and integration tests."""

from __future__ import annotations

from types import SimpleNamespace

import pytest


class FakeConn:
    """asyncpg connection stand-in: `fetch` returns preset rows; `execute` is a no-op."""

    def __init__(self, rows):
        self._rows = rows

    async def fetch(self, query, *args):
        return self._rows

    async def execute(self, query, *args):
        return None


class _AcquireCtx:
    def __init__(self, rows):
        self._rows = rows

    async def __aenter__(self):
        return FakeConn(self._rows)

    async def __aexit__(self, *a):
        return None


class FakePool:
    """asyncpg pool stand-in for tests that only issue read queries."""

    def __init__(self, rows):
        self._rows = rows

    def acquire(self):
        return _AcquireCtx(self._rows)


class CapturingConn:
    """asyncpg connection stand-in that records executes (query_log INSERTs etc.)."""

    def __init__(self, rows, executes):
        self._rows = rows
        self._executes = executes

    async def fetch(self, query, *args):
        return self._rows

    async def execute(self, query, *args):
        self._executes.append((query, args))


class _CapturingAcquireCtx:
    def __init__(self, conn):
        self._conn = conn

    async def __aenter__(self):
        return self._conn

    async def __aexit__(self, *a):
        return None


class CapturingPool:
    """asyncpg pool stand-in that exposes `executes` for write-side assertions."""

    def __init__(self, rows):
        self.rows = rows
        self.executes = []

    def acquire(self):
        return _CapturingAcquireCtx(CapturingConn(self.rows, self.executes))


def fake_settings():
    """Construct a SimpleNamespace mimicking docforge.config.Settings for tests
    that bypass the lifespan and need to override `get_settings`."""
    return SimpleNamespace(
        database_url="postgresql://fake",
        tag_match_weight=0.1,
        org_tag_weight=0.05,
        pool_min_size=5,
        pool_max_size=25,
        query_log_retention_days=180,
    )


class FakeEmbedder:
    """Deterministic stand-in for docforge.processors.embedder.Embedder.

    Returns fixed vectors without loading the 300M sentence-transformers
    model. Dimensions match EmbeddingGemma-300M (768) so pgvector columns
    defined as vector(768) accept the output in integration tests.
    """

    model_name = "fake/embedder"
    dimensions = 768

    def __init__(self, *args, **kwargs) -> None:
        pass

    @classmethod
    def from_settings(cls, settings) -> "FakeEmbedder":
        return cls()

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [[0.0] * 767 + [float(i + 1) / 1000.0] for i, _ in enumerate(texts)]

    def embed_query(self, text: str) -> list[float]:
        return [0.0] * 767 + [0.001]

    async def aembed(self, texts: list[str]) -> list[list[float]]:
        return self.embed(texts)

    async def aembed_query(self, text: str) -> list[float]:
        return self.embed_query(text)

    def get_tokenizer_fn(self):
        return lambda s: len(s.split())


@pytest.fixture
def fake_embedder(monkeypatch):
    """Patch every consumer module's imported `Embedder` with FakeEmbedder.

    Consumer modules do `from docforge.processors.embedder import Embedder`
    at module load, binding the class into their own namespace. Patching
    the source module does not help — each consumer's binding must be
    replaced.
    """
    targets = [
        "docforge.ingest.Embedder",
        "docforge.mcp_server.Embedder",
        "docforge.api.Embedder",
    ]
    for target in targets:
        monkeypatch.setattr(target, FakeEmbedder)
    # cli.py imports Embedder lazily inside _search; patch the source too
    # so the lazy import resolves to FakeEmbedder.
    monkeypatch.setattr("docforge.processors.embedder.Embedder", FakeEmbedder)
    return FakeEmbedder
