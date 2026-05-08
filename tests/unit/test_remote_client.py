"""Tests for the remote-API MCP client mode."""
from __future__ import annotations

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
