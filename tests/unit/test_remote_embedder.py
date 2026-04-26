"""Tests for docforge.processors.embedder.RemoteEmbedder — HTTP client."""

from __future__ import annotations

import json

import httpx
import pytest

from docforge.processors.embedder import RemoteEmbedder


def _vector(d: int = 768) -> list[float]:
    return [0.0] * d


class TestConstruction:
    def test_init_does_no_network(self):
        # If __init__ touched the network, this would raise (no transport).
        e = RemoteEmbedder(
            url="https://embed.invalid",
            token="t",
            expected_dimensions=768,
        )
        assert e.model_name == "remote"
        assert e.dimensions == 768

    def test_url_trailing_slash_stripped(self):
        e = RemoteEmbedder(
            url="https://embed.invalid/",
            token="t",
            expected_dimensions=768,
        )
        assert e._url == "https://embed.invalid"


class TestEmbedHappyPath:
    @pytest.mark.asyncio
    async def test_aembed_query_succeeds_and_sends_bearer(self):
        captured: dict = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["headers"] = dict(request.headers)
            captured["body"] = json.loads(request.content)
            return httpx.Response(
                200,
                json={"vectors": [_vector()], "dimensions": 768},
            )

        transport = httpx.MockTransport(handler)
        e = RemoteEmbedder("https://embed.invalid", "secret-tok", 768)
        # Inject the mock transport before any call.
        e._client = httpx.AsyncClient(transport=transport)

        result = await e.aembed_query("hello")
        assert result == _vector()
        assert captured["headers"]["authorization"] == "Bearer secret-tok"
        assert captured["body"] == {"texts": ["hello"]}
        await e.aclose()


class TestRetryBehavior:
    @pytest.mark.asyncio
    async def test_transport_error_then_success(self):
        attempts = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            attempts["n"] += 1
            if attempts["n"] == 1:
                raise httpx.ConnectError("transient")
            return httpx.Response(200, json={"vectors": [_vector()], "dimensions": 768})

        transport = httpx.MockTransport(handler)
        e = RemoteEmbedder("https://embed.invalid", "t", 768)
        e._client = httpx.AsyncClient(transport=transport)

        result = await e.aembed_query("x")
        assert result == _vector()
        assert attempts["n"] == 2
        await e.aclose()

    @pytest.mark.asyncio
    async def test_two_transport_errors_raises(self):
        attempts = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            attempts["n"] += 1
            raise httpx.ConnectError("down")

        transport = httpx.MockTransport(handler)
        e = RemoteEmbedder("https://embed.invalid", "t", 768)
        e._client = httpx.AsyncClient(transport=transport)

        with pytest.raises(httpx.ConnectError):
            await e.aembed_query("x")
        assert attempts["n"] == 2
        await e.aclose()

    @pytest.mark.asyncio
    async def test_5xx_retries_once(self):
        attempts = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            attempts["n"] += 1
            if attempts["n"] == 1:
                return httpx.Response(503)
            return httpx.Response(200, json={"vectors": [_vector()], "dimensions": 768})

        transport = httpx.MockTransport(handler)
        e = RemoteEmbedder("https://embed.invalid", "t", 768)
        e._client = httpx.AsyncClient(transport=transport)

        result = await e.aembed_query("x")
        assert result == _vector()
        assert attempts["n"] == 2
        await e.aclose()

    @pytest.mark.asyncio
    async def test_4xx_does_not_retry(self):
        attempts = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            attempts["n"] += 1
            return httpx.Response(401, json={"detail": "invalid token"})

        transport = httpx.MockTransport(handler)
        e = RemoteEmbedder("https://embed.invalid", "wrong", 768)
        e._client = httpx.AsyncClient(transport=transport)

        with pytest.raises(httpx.HTTPStatusError):
            await e.aembed_query("x")
        # Failed on first call, no retry.
        assert attempts["n"] == 1
        await e.aclose()


class TestDimensionGuard:
    @pytest.mark.asyncio
    async def test_dim_mismatch_raises_runtimeerror(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"vectors": [[0.0] * 384], "dimensions": 384})

        transport = httpx.MockTransport(handler)
        e = RemoteEmbedder("https://embed.invalid", "t", expected_dimensions=768)
        e._client = httpx.AsyncClient(transport=transport)

        with pytest.raises(RuntimeError, match="dimension mismatch"):
            await e.aembed_query("x")
        await e.aclose()


class TestLifecycle:
    @pytest.mark.asyncio
    async def test_aclose_releases_client(self):
        e = RemoteEmbedder("https://embed.invalid", "t", 768)
        # Force creation
        await e._ensure_client()
        assert e._client is not None
        await e.aclose()
        assert e._client is None
