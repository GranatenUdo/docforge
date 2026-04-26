"""End-to-end integration: spawn the embedder service, point a RemoteEmbedder
at it, exercise the auth + dim-guard contracts.

Uses the ungated all-MiniLM-L6-v2 (384-d) so this runs without HF_TOKEN —
matching the existing tests/integration/test_embedder_real_model.py pattern."""

from __future__ import annotations

import asyncio
import os
import socket
import threading
import time

import httpx
import pytest
import uvicorn

UNGATED_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
UNGATED_DIM = 384


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def embedder_service():
    """Spawn docforge.embedder_api on a free port with the ungated model;
    yield (url, token)."""
    port = _free_port()
    token = "integration-test-token"
    # Override settings via env vars so the spawned process picks up
    # the ungated model and matching dims.
    os.environ["EMBEDDER_TOKEN"] = token
    os.environ["EMBEDDING_MODEL"] = UNGATED_MODEL
    os.environ["EMBEDDING_DIMENSIONS"] = str(UNGATED_DIM)

    config = uvicorn.Config(
        "docforge.embedder_api:app",
        host="127.0.0.1",
        port=port,
        log_level="warning",
    )
    server = uvicorn.Server(config)

    thread = threading.Thread(target=lambda: asyncio.run(server.serve()))
    thread.start()

    # Wait for /health to respond
    url = f"http://127.0.0.1:{port}"
    for _ in range(60):  # up to 60s for cold start
        try:
            with httpx.Client(timeout=1.0) as c:
                if c.get(f"{url}/health").status_code == 200:
                    break
        except (httpx.ConnectError, httpx.TimeoutException):
            time.sleep(1)
    else:
        server.should_exit = True
        thread.join(timeout=10)
        raise RuntimeError("embedder service did not start")

    yield (url, token)

    server.should_exit = True
    thread.join(timeout=10)
    for var in ("EMBEDDER_TOKEN", "EMBEDDING_MODEL", "EMBEDDING_DIMENSIONS"):
        os.environ.pop(var, None)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_remote_embedder_against_real_service(embedder_service):
    from docforge.processors.embedder import RemoteEmbedder

    url, token = embedder_service
    e = RemoteEmbedder(url=url, token=token, expected_dimensions=UNGATED_DIM)
    try:
        result = await e.aembed_query("hello world")
        assert len(result) == UNGATED_DIM
        assert all(isinstance(v, float) for v in result)
    finally:
        await e.aclose()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_remote_embedder_rejects_wrong_token(embedder_service):
    import httpx

    from docforge.processors.embedder import RemoteEmbedder

    url, _ = embedder_service
    e = RemoteEmbedder(url=url, token="wrong-token", expected_dimensions=UNGATED_DIM)
    try:
        with pytest.raises(httpx.HTTPStatusError) as exc_info:
            await e.aembed_query("x")
        assert exc_info.value.response.status_code == 401
    finally:
        await e.aclose()
