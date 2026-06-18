"""Tests for docforge.processors.reranker.

Covers the RemoteReranker HTTP client (mocked httpx — NO network), the
in-process Reranker (mocked sentence_transformers.CrossEncoder — NO model
download), and the reranker_from_settings factory.
"""

from __future__ import annotations

import json
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock

import httpx
import pytest

from docforge.processors.reranker import (
    RemoteReranker,
    Reranker,
    RerankerProtocol,
    reranker_from_settings,
)


class TestConstruction:
    def test_init_does_no_network(self):
        # If __init__ touched the network, this would raise (no transport).
        r = RemoteReranker(url="https://rerank.invalid", token="t")
        assert r._url == "https://rerank.invalid"
        assert r._token == "t"

    def test_url_trailing_slash_stripped(self):
        r = RemoteReranker(url="https://rerank.invalid/", token="t")
        assert r._url == "https://rerank.invalid"


class TestRerankHappyPath:
    @pytest.mark.asyncio
    async def test_arerank_sorts_descending_and_sends_bearer(self):
        captured: dict = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["headers"] = dict(request.headers)
            captured["body"] = json.loads(request.content)
            captured["url"] = str(request.url)
            # Scores in input order; passage index 1 is the best, then 2, then 0.
            return httpx.Response(200, json={"scores": [0.1, 0.9, 0.5]})

        transport = httpx.MockTransport(handler)
        r = RemoteReranker("https://rerank.invalid", "secret-tok")
        r._client = httpx.AsyncClient(transport=transport)

        result = await r.arerank("q", ["a", "b", "c"])
        # (index, score) pairs sorted by descending score: 1 (0.9), 2 (0.5), 0 (0.1).
        assert result == [(1, 0.9), (2, 0.5), (0, 0.1)]
        assert captured["headers"]["authorization"] == "Bearer secret-tok"
        assert captured["body"] == {"query": "q", "texts": ["a", "b", "c"]}
        assert captured["url"].endswith("/rerank")
        await r.aclose()

    @pytest.mark.asyncio
    async def test_arerank_ignores_server_order_and_sorts_itself(self):
        # Even if the server returned scores in a misleading order, the client
        # must sort by the score values, not trust positional ordering.
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"scores": [2.0, 1.0, 3.0]})

        transport = httpx.MockTransport(handler)
        r = RemoteReranker("https://rerank.invalid", "t")
        r._client = httpx.AsyncClient(transport=transport)

        result = await r.arerank("q", ["x", "y", "z"])
        assert result == [(2, 3.0), (0, 2.0), (1, 1.0)]
        await r.aclose()


class TestResponseValidation:
    @pytest.mark.asyncio
    async def test_missing_scores_key_raises_runtimeerror(self):
        # A 200 whose body lacks "scores" is a contract violation, not a
        # transient fault: fail loud (RuntimeError -> RerankerUnavailable/502)
        # rather than letting a KeyError escape as an opaque 503.
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"unexpected": "shape"})

        transport = httpx.MockTransport(handler)
        r = RemoteReranker("https://rerank.invalid", "t")
        r._client = httpx.AsyncClient(transport=transport)

        with pytest.raises(RuntimeError, match="malformed"):
            await r.arerank("q", ["a", "b"])
        await r.aclose()

    @pytest.mark.asyncio
    async def test_wrong_length_scores_raises_runtimeerror(self):
        # Exactly one score per passage is required; a mismatch must fail loud
        # instead of tripping the downstream permutation guard with a confusing
        # error.
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"scores": [0.5]})  # 1 score, 2 passages

        transport = httpx.MockTransport(handler)
        r = RemoteReranker("https://rerank.invalid", "t")
        r._client = httpx.AsyncClient(transport=transport)

        with pytest.raises(RuntimeError, match="malformed"):
            await r.arerank("q", ["a", "b"])
        await r.aclose()

    @pytest.mark.asyncio
    async def test_non_json_body_raises_runtimeerror(self):
        # A 200 with a non-JSON body (proxy/ingress HTML interstitial, partial
        # write) must fail loud as RuntimeError (-> RerankerUnavailable/502),
        # not escape as a JSONDecodeError into the generic 503 handler.
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, text="<html>gateway error</html>")

        transport = httpx.MockTransport(handler)
        r = RemoteReranker("https://rerank.invalid", "t")
        r._client = httpx.AsyncClient(transport=transport)

        with pytest.raises(RuntimeError, match="non-JSON"):
            await r.arerank("q", ["a", "b"])
        await r.aclose()


class TestRetryBehavior:
    @pytest.mark.asyncio
    async def test_transport_error_then_success(self):
        attempts = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            attempts["n"] += 1
            if attempts["n"] == 1:
                raise httpx.ConnectError("transient")
            return httpx.Response(200, json={"scores": [0.5]})

        transport = httpx.MockTransport(handler)
        r = RemoteReranker("https://rerank.invalid", "t")
        r._client = httpx.AsyncClient(transport=transport)

        result = await r.arerank("q", ["only"])
        assert result == [(0, 0.5)]
        assert attempts["n"] == 2
        await r.aclose()

    @pytest.mark.asyncio
    async def test_two_transport_errors_raises(self):
        attempts = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            attempts["n"] += 1
            raise httpx.ConnectError("down")

        transport = httpx.MockTransport(handler)
        r = RemoteReranker("https://rerank.invalid", "t")
        r._client = httpx.AsyncClient(transport=transport)

        with pytest.raises(httpx.ConnectError):
            await r.arerank("q", ["a"])
        assert attempts["n"] == 2
        await r.aclose()

    @pytest.mark.asyncio
    async def test_5xx_then_200_retries_and_succeeds(self):
        attempts = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            attempts["n"] += 1
            if attempts["n"] == 1:
                return httpx.Response(503)
            return httpx.Response(200, json={"scores": [0.1, 0.2]})

        transport = httpx.MockTransport(handler)
        r = RemoteReranker("https://rerank.invalid", "t")
        r._client = httpx.AsyncClient(transport=transport)

        result = await r.arerank("q", ["a", "b"])
        assert result == [(1, 0.2), (0, 0.1)]
        assert attempts["n"] == 2
        await r.aclose()

    @pytest.mark.asyncio
    async def test_4xx_fails_loud_no_retry(self):
        attempts = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            attempts["n"] += 1
            return httpx.Response(401, json={"detail": "invalid token"})

        transport = httpx.MockTransport(handler)
        r = RemoteReranker("https://rerank.invalid", "wrong")
        r._client = httpx.AsyncClient(transport=transport)

        with pytest.raises(httpx.HTTPStatusError):
            await r.arerank("q", ["a"])
        # Failed on first call, no retry.
        assert attempts["n"] == 1
        await r.aclose()


class TestLifecycle:
    @pytest.mark.asyncio
    async def test_aclose_releases_client(self):
        r = RemoteReranker("https://rerank.invalid", "t")
        await r._ensure_client()
        assert r._client is not None
        await r.aclose()
        assert r._client is None


class TestProtocol:
    def test_remote_reranker_satisfies_protocol(self):
        r = RemoteReranker("https://rerank.invalid", "t")
        assert isinstance(r, RerankerProtocol)


class TestLocalReranker:
    def test_score_builds_pairs_and_returns_list_of_floats(self, monkeypatch):
        captured: dict = {}

        class FakeArray:
            def __init__(self, values):
                self._values = values

            def tolist(self):
                return list(self._values)

        class FakeCrossEncoder:
            def __init__(self, model_name, token=None):
                captured["model_name"] = model_name
                captured["token"] = token

            def predict(self, pairs):
                captured["pairs"] = pairs
                # Canned numpy-like return, one score per pair.
                return FakeArray([0.3, 0.8])

        monkeypatch.setitem(
            sys.modules,
            "sentence_transformers",
            type("M", (), {"CrossEncoder": FakeCrossEncoder})(),
        )

        r = Reranker(model_name="some/reranker", hf_token="tok")
        scores = r.score("the query", ["passage one", "passage two"])

        assert scores == [0.3, 0.8]
        assert all(isinstance(s, float) for s in scores)
        # Pairs are (query, passage) tuples in input order.
        assert captured["pairs"] == [
            ("the query", "passage one"),
            ("the query", "passage two"),
        ]
        assert captured["model_name"] == "some/reranker"
        assert captured["token"] == "tok"

    def test_default_model_is_bge_reranker(self):
        import inspect

        sig = inspect.signature(Reranker.__init__)
        default = sig.parameters["model_name"].default
        assert default == "BAAI/bge-reranker-v2-m3", (
            f"Reranker default model_name is {default!r}, expected bge-reranker-v2-m3"
        )

    def test_empty_token_passed_as_none(self, monkeypatch):
        captured: dict = {}

        class FakeCrossEncoder:
            def __init__(self, model_name, token=None):
                captured["token"] = token

            def predict(self, pairs):
                return MagicMock(tolist=lambda: [])

        monkeypatch.setitem(
            sys.modules,
            "sentence_transformers",
            type("M", (), {"CrossEncoder": FakeCrossEncoder})(),
        )

        Reranker(model_name="m", hf_token="")
        assert captured["token"] is None


class TestFactory:
    def _settings(self, url: str = "", token: str = "") -> SimpleNamespace:
        return SimpleNamespace(
            reranker_url=url,
            reranker_token=SimpleNamespace(get_secret_value=lambda: token),
        )

    def test_returns_remote_reranker_when_url_set(self):
        result = reranker_from_settings(
            self._settings(url="https://rerank.internal", token="hunter2")
        )
        assert isinstance(result, RemoteReranker)
        assert result._url == "https://rerank.internal"
        assert result._token == "hunter2"

    def test_returns_none_when_url_empty(self):
        result = reranker_from_settings(self._settings(url=""))
        assert result is None

    def test_raises_when_url_set_but_token_empty(self):
        # Mirror Embedder.from_settings: refuse to construct a remote client
        # without auth, even though the factory is only reached with a URL set.
        with pytest.raises(RuntimeError, match="refusing to construct"):
            reranker_from_settings(self._settings(url="https://rerank.internal", token=""))
