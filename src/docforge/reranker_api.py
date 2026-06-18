"""docforge reranker service — exposes the cross-encoder Reranker over HTTP.

Runs as its own Container App. The search API and MCP server delegate to this
service when RERANKER_URL is set, via RemoteReranker."""

from __future__ import annotations

import asyncio
import logging
import secrets
from contextlib import asynccontextmanager
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from pydantic import BaseModel, Field

from docforge.config import Settings
from docforge.processors.reranker import MAX_RERANK_BATCH, Reranker

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = Settings()
    if not settings.reranker_token.get_secret_value():
        raise RuntimeError(
            "reranker service requires RERANKER_TOKEN to be set "
            "(via Key Vault secret or env var) — refusing to start with no auth"
        )
    reranker = await asyncio.to_thread(Reranker, settings.rerank_model)
    logger.info("Reranker ready: %s", reranker.model_name)
    yield {"reranker": reranker, "settings": settings}


app = FastAPI(title="docforge-reranker", lifespan=lifespan)


def get_reranker(request: Request) -> Reranker | None:
    return getattr(request.state, "reranker", None)


def get_settings(request: Request) -> Settings:
    return request.state.settings


async def _require_token(
    settings: Settings = Depends(get_settings),
    authorization: str | None = Header(default=None),
) -> None:
    expected = settings.reranker_token.get_secret_value()
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="missing bearer token")
    presented = authorization.removeprefix("Bearer ").strip()
    if not secrets.compare_digest(presented, expected):
        raise HTTPException(status_code=401, detail="invalid bearer token")


class RerankRequest(BaseModel):
    query: str
    texts: list[str] = Field(..., min_length=1, max_length=MAX_RERANK_BATCH)


class RerankResponse(BaseModel):
    scores: list[float]


@app.get("/health")
async def health(reranker: Reranker | None = Depends(get_reranker)) -> dict[str, Any]:
    if reranker is None:
        raise HTTPException(status_code=503, detail="model not loaded")
    return {
        "status": "ok",
        "model": reranker.model_name,
    }


@app.post("/rerank", response_model=RerankResponse)
async def rerank(
    req: RerankRequest,
    reranker: Reranker = Depends(get_reranker),
    _: None = Depends(_require_token),
) -> RerankResponse:
    # Reranker.score is synchronous and GPU/CPU-bound (CrossEncoder.predict),
    # so wrap it in a thread to avoid blocking the event loop — mirroring how
    # the Embedder's aembed offloads its sync embed() via asyncio.to_thread.
    scores = await asyncio.to_thread(reranker.score, req.query, req.texts)
    return RerankResponse(scores=scores)
