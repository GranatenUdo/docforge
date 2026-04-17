"""FastAPI search API for knowledge-hub.

Runs on Azure Container Apps. Loads embedding model at startup,
serves search queries over HTTP.

Run locally: uvicorn docforge.api:app --reload
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

import numpy as np
from fastapi import FastAPI
from pydantic import BaseModel

from docforge.config import Settings
from docforge.db import close_pool, get_pool
from docforge.processors.embedder import Embedder

logger = logging.getLogger(__name__)

_embedder: Embedder | None = None
_settings: Settings | None = None


def _get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _embedder
    settings = _get_settings()
    logger.info("Loading embedding model...")
    _embedder = Embedder(
        settings.embedding_model, hf_token=settings.hf_token.get_secret_value()
    )
    logger.info("Model loaded: %s (%dd)", _embedder.model_name, _embedder.dimensions)
    yield
    await close_pool()


app = FastAPI(title="knowledge-hub", lifespan=lifespan)


class SearchRequest(BaseModel):
    query: str
    limit: int = 5


class SearchResult(BaseModel):
    text: str
    section_title: str | None
    source_title: str
    source_url: str
    similarity: float


class SearchResponse(BaseModel):
    results: list[SearchResult]
    query: str
    count: int


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "model": _embedder.model_name if _embedder else "not loaded",
    }


@app.post("/search", response_model=SearchResponse)
async def search(req: SearchRequest):
    settings = _get_settings()
    query_vector = _embedder.embed_query(req.query)

    pool = await get_pool(settings.database_url)
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT
                c.text,
                c.section_title,
                s.title AS source_title,
                s.url AS source_url,
                1 - (c.embedding <=> $1::vector) AS similarity
            FROM chunks c
            JOIN sources s ON c.source_id = s.id
            WHERE s.status = 'active'
            ORDER BY c.embedding <=> $1::vector
            LIMIT $2
            """,
            np.array(query_vector, dtype=np.float32),
            req.limit,
        )

    results = [
        SearchResult(
            text=row["text"],
            section_title=row["section_title"],
            source_title=row["source_title"],
            source_url=row["source_url"],
            similarity=float(row["similarity"]),
        )
        for row in rows
    ]

    return SearchResponse(results=results, query=req.query, count=len(results))


@app.get("/sources")
async def list_sources():
    settings = _get_settings()
    pool = await get_pool(settings.database_url)
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT title, url, status, last_crawled_at,
                   (SELECT count(*) FROM chunks WHERE source_id = s.id) AS chunk_count
            FROM sources s
            ORDER BY title
            """
        )
    return {
        "count": len(rows),
        "sources": [
            {
                "title": row["title"],
                "url": row["url"],
                "status": row["status"],
                "chunk_count": row["chunk_count"],
            }
            for row in rows
        ],
    }
