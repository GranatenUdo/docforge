"""Tests for the remote-API MCP client mode."""
from __future__ import annotations

import json

import httpx
import pytest


@pytest.mark.asyncio
async def test_none_auth_returns_empty_headers():
    from docforge.remote_client import NoneAuth
    auth = NoneAuth()
    headers = await auth.headers()
    assert headers == {}


@pytest.mark.asyncio
async def test_bearer_auth_returns_authorization_header(monkeypatch):
    monkeypatch.setenv("DOCFORGE_API_TOKEN", "abc123")
    from docforge.remote_client import BearerAuth
    auth = BearerAuth()
    headers = await auth.headers()
    assert headers == {"Authorization": "Bearer abc123"}


def test_bearer_auth_raises_when_token_unset(monkeypatch):
    monkeypatch.delenv("DOCFORGE_API_TOKEN", raising=False)
    from docforge.remote_client import BearerAuth
    with pytest.raises(RuntimeError, match="DOCFORGE_API_TOKEN"):
        BearerAuth()


import sys


def test_azure_auth_raises_when_audience_unset(monkeypatch):
    monkeypatch.delenv("DOCFORGE_AUDIENCE", raising=False)
    from docforge.remote_client import AzureAuth
    with pytest.raises(RuntimeError, match="DOCFORGE_AUDIENCE"):
        AzureAuth()


def test_azure_auth_raises_when_extra_not_installed(monkeypatch):
    """If azure.identity.aio isn't importable, AzureAuth raises ImportError."""
    monkeypatch.setenv("DOCFORGE_AUDIENCE", "api://test-audience")
    monkeypatch.setitem(sys.modules, "azure.identity.aio", None)
    from docforge.remote_client import AzureAuth
    with pytest.raises(ImportError, match=r"\[azure\]"):
        AzureAuth()


@pytest.mark.asyncio
async def test_azure_auth_returns_bearer_from_credential(monkeypatch):
    monkeypatch.setenv("DOCFORGE_AUDIENCE", "api://test-audience")

    from unittest.mock import AsyncMock, MagicMock
    fake_token = MagicMock(token="fake-jwt-token")
    fake_credential = MagicMock()
    fake_credential.get_token = AsyncMock(return_value=fake_token)

    fake_aio_module = MagicMock()
    fake_aio_module.DefaultAzureCredential = MagicMock(return_value=fake_credential)
    monkeypatch.setitem(sys.modules, "azure.identity.aio", fake_aio_module)

    from docforge.remote_client import AzureAuth
    auth = AzureAuth()
    headers = await auth.headers()
    assert headers == {"Authorization": "Bearer fake-jwt-token"}
    fake_credential.get_token.assert_awaited_once_with("api://test-audience/.default")


def test_make_auth_provider_none():
    from docforge.remote_client import make_auth_provider, NoneAuth
    p = make_auth_provider("none")
    assert isinstance(p, NoneAuth)


def test_make_auth_provider_bearer(monkeypatch):
    monkeypatch.setenv("DOCFORGE_API_TOKEN", "x")
    from docforge.remote_client import make_auth_provider, BearerAuth
    p = make_auth_provider("bearer")
    assert isinstance(p, BearerAuth)


def test_make_auth_provider_unknown_raises():
    from docforge.remote_client import make_auth_provider
    with pytest.raises(ValueError, match="Unknown auth provider"):
        make_auth_provider("oauth")


@pytest.mark.asyncio
async def test_remote_backend_search_happy_path(monkeypatch):
    """search() POSTs to /search and formats the response as Markdown."""
    monkeypatch.delenv("DOCFORGE_USER", raising=False)
    monkeypatch.delenv("DOCFORGE_TEAM", raising=False)
    monkeypatch.delenv("DOCFORGE_AREA", raising=False)

    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "results": [
                    {
                        "text": "Hello world",
                        "section_title": "Intro",
                        "source_title": "Test Page",
                        "source_url": "https://example.com/page",
                        "source_tags": ["org"],
                        "similarity": 0.85,
                    },
                ],
                "query": "hello",
                "count": 1,
            },
        )

    transport = httpx.MockTransport(handler)
    from docforge.remote_client import RemoteBackend, NoneAuth
    backend = RemoteBackend(
        url="https://api.example.com",
        auth=NoneAuth(),
        transport=transport,
    )
    result = await backend.search(query="hello", limit=5)

    assert "Test Page" in result
    assert "**Result 1**" in result
    assert "0.85" in result
    assert "Tags: org" in result
    assert captured["url"] == "https://api.example.com/search"
    assert captured["body"] == {"query": "hello", "limit": 5}


@pytest.mark.asyncio
async def test_remote_backend_search_includes_set_identity(monkeypatch):
    monkeypatch.setenv("DOCFORGE_USER", "tobias.ens")
    monkeypatch.setenv("DOCFORGE_TEAM", "ccl")
    monkeypatch.setenv("DOCFORGE_AREA", "cloud")

    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json={"results": [], "query": "x", "count": 0})

    transport = httpx.MockTransport(handler)
    from docforge.remote_client import RemoteBackend, NoneAuth
    backend = RemoteBackend(url="https://api.example.com", auth=NoneAuth(), transport=transport)
    await backend.search(query="x", limit=5)

    assert captured["body"] == {
        "query": "x",
        "limit": 5,
        "user_name": "tobias.ens",
        "team_name": "ccl",
        "area_name": "cloud",
    }


@pytest.mark.asyncio
async def test_remote_backend_search_empty_results_no_ingest_hint(monkeypatch):
    """Empty-result message must not say 'run docforge ingest' — remote users can't."""
    monkeypatch.delenv("DOCFORGE_USER", raising=False)
    monkeypatch.delenv("DOCFORGE_TEAM", raising=False)
    monkeypatch.delenv("DOCFORGE_AREA", raising=False)

    transport = httpx.MockTransport(
        lambda req: httpx.Response(200, json={"results": [], "query": "x", "count": 0})
    )
    from docforge.remote_client import RemoteBackend, NoneAuth
    backend = RemoteBackend(url="https://api.example.com", auth=NoneAuth(), transport=transport)
    result = await backend.search(query="x", limit=5)

    assert "No documentation found" in result
    assert "ingest" not in result.lower()


@pytest.mark.asyncio
async def test_remote_backend_search_401_returns_friendly_error(monkeypatch):
    monkeypatch.delenv("DOCFORGE_USER", raising=False)
    transport = httpx.MockTransport(
        lambda req: httpx.Response(401, json={"detail": "Unauthorized"})
    )
    from docforge.remote_client import RemoteBackend, NoneAuth
    backend = RemoteBackend(url="https://api.example.com", auth=NoneAuth(), transport=transport)
    result = await backend.search(query="x", limit=5)
    assert "Auth failed" in result
    assert "401" in result


@pytest.mark.asyncio
async def test_remote_backend_search_500_returns_friendly_error(monkeypatch):
    monkeypatch.delenv("DOCFORGE_USER", raising=False)
    transport = httpx.MockTransport(
        lambda req: httpx.Response(500, json={"detail": "Server error"})
    )
    from docforge.remote_client import RemoteBackend, NoneAuth
    backend = RemoteBackend(url="https://api.example.com", auth=NoneAuth(), transport=transport)
    result = await backend.search(query="x", limit=5)
    assert "Remote API error" in result
    assert "5" in result


@pytest.mark.asyncio
async def test_remote_backend_search_network_error_returns_friendly_error(monkeypatch):
    monkeypatch.delenv("DOCFORGE_USER", raising=False)

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    transport = httpx.MockTransport(handler)
    from docforge.remote_client import RemoteBackend, NoneAuth
    backend = RemoteBackend(url="https://api.example.com", auth=NoneAuth(), transport=transport)
    result = await backend.search(query="x", limit=5)
    assert "Could not reach" in result
    assert "https://api.example.com" in result


@pytest.mark.asyncio
async def test_remote_backend_list_sources_happy_path(monkeypatch):
    monkeypatch.setenv("DOCFORGE_USER", "tobias.ens")  # should NOT appear in body

    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["method"] = request.method
        captured["body"] = request.content
        return httpx.Response(
            200,
            json={
                "sources": [
                    {"title": "Test Page", "chunk_count": 5, "status": "active"},
                ],
                "count": 1,
            },
        )

    transport = httpx.MockTransport(handler)
    from docforge.remote_client import RemoteBackend, NoneAuth
    backend = RemoteBackend(url="https://api.example.com", auth=NoneAuth(), transport=transport)
    result = await backend.list_sources()

    assert "1 indexed sources" in result
    assert "Test Page" in result
    assert "5 chunks" in result
    assert captured["url"] == "https://api.example.com/sources"
    assert captured["method"] == "GET"
    assert captured["body"] == b""
