"""docforge embedder service — exposes Embedder over HTTP.

Runs as its own Container App. The search API, MCP server, and ingest
worker delegate to this service when EMBEDDER_URL is set."""

from __future__ import annotations

import asyncio
import logging
import secrets
from contextlib import asynccontextmanager
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from pydantic import BaseModel, Field

from docforge.config import Settings
from docforge.processors.embedder import MAX_BATCH_SIZE, Embedder

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = Settings()
    if not settings.embedder_token.get_secret_value():
        raise RuntimeError(
            "embedder service requires EMBEDDER_TOKEN to be set "
            "(via Key Vault secret or env var) — refusing to start with no auth"
        )
    embedder = await asyncio.to_thread(Embedder.from_settings, settings)
    logger.info("Embedder ready: %s (%dd)", embedder.model_name, embedder.dimensions)
    yield {"embedder": embedder, "settings": settings}


app = FastAPI(title="docforge-embedder", lifespan=lifespan)


def get_embedder(request: Request) -> Embedder | None:
    return getattr(request.state, "embedder", None)


def get_settings(request: Request) -> Settings:
    return request.state.settings


async def _require_token(
    settings: Settings = Depends(get_settings),
    authorization: str | None = Header(default=None),
) -> None:
    expected = settings.embedder_token.get_secret_value()
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="missing bearer token")
    presented = authorization.removeprefix("Bearer ").strip()
    if not secrets.compare_digest(presented, expected):
        raise HTTPException(status_code=401, detail="invalid bearer token")


class EmbedRequest(BaseModel):
    texts: list[str] = Field(..., min_length=1, max_length=MAX_BATCH_SIZE)


class EmbedResponse(BaseModel):
    vectors: list[list[float]]
    dimensions: int


@app.get("/health")
async def health(embedder: Embedder | None = Depends(get_embedder)) -> dict[str, Any]:
    if embedder is None:
        raise HTTPException(status_code=503, detail="model not loaded")
    return {
        "status": "ok",
        "model": embedder.model_name,
        "dimensions": embedder.dimensions,
    }


@app.post("/embed", response_model=EmbedResponse)
async def embed(
    req: EmbedRequest,
    embedder: Embedder = Depends(get_embedder),
    _: None = Depends(_require_token),
) -> EmbedResponse:
    vectors = await asyncio.to_thread(embedder.embed, req.texts)
    return EmbedResponse(vectors=vectors, dimensions=embedder.dimensions)
