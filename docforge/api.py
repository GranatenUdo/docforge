"""FastAPI search API for docforge.

Runs on Azure Container Apps. Loads embedding model at startup,
serves search queries over HTTP.

Run locally: uvicorn docforge.api:app --reload
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import Any

import numpy as np
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.security import SecurityScopes
from pydantic import BaseModel

from docforge.config import Settings
from docforge.db import close_pool, get_pool
from docforge.processors.embedder import Embedder

logger = logging.getLogger(__name__)

_embedder: Embedder | None = None
_settings: Settings | None = None
_azure_scheme = None  # Populated in lifespan when auth.mode == "entra"


def _get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings


def _build_auth_scheme(settings: Settings):
    """Return a SingleTenantAzureAuthorizationCodeBearer if mode==entra, else None."""
    if settings.auth.mode != "entra":
        return None
    from fastapi_azure_auth import SingleTenantAzureAuthorizationCodeBearer

    app_client_id = settings.auth.audience.removeprefix("api://")
    return SingleTenantAzureAuthorizationCodeBearer(
        app_client_id=app_client_id,
        tenant_id=settings.auth.tenant_id,
        scopes={f"{settings.auth.audience}/search": "Search docforge"},
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Load the embedding model at startup; close the DB pool on shutdown."""
    global _embedder, _azure_scheme
    settings = _get_settings()
    _azure_scheme = _build_auth_scheme(settings)
    if _azure_scheme is not None:
        await _azure_scheme.openid_config.load_config()
        logger.info("Entra auth enabled (tenant=%s, audience=%s)",
                    settings.auth.tenant_id, settings.auth.audience)
    logger.info("Loading embedding model...")
    _embedder = Embedder(settings.embedding_model, hf_token=settings.hf_token.get_secret_value())
    logger.info("Model loaded: %s (%dd)", _embedder.model_name, _embedder.dimensions)
    yield
    await close_pool()


app = FastAPI(title="docforge", lifespan=lifespan)


async def _auth_dependency(request: Request):
    """Resolve the current user from the auth scheme when auth.mode==entra.
    Returns None when auth.mode==none (so endpoint handlers can still read
    req.user_name for the legacy unauthenticated path).

    Manual invocation of the Entra scheme avoids FastAPI's Security() pattern,
    which would make auth unconditionally required. Passing an empty
    SecurityScopes lets the scheme's signature match what it expects from
    FastAPI's security dependency resolution."""
    if _azure_scheme is None:
        return None
    return await _azure_scheme(request, SecurityScopes())


class SearchRequest(BaseModel):
    query: str
    user_name: str
    team_name: str
    area_name: str | None = None
    limit: int = 5


class SearchResult(BaseModel):
    text: str
    section_title: str | None
    source_title: str
    source_url: str
    source_tags: list[str]
    similarity: float


class SearchResponse(BaseModel):
    results: list[SearchResult]
    query: str
    count: int


@app.get("/health")
async def health() -> dict[str, Any]:
    """Health check endpoint."""
    return {
        "status": "ok",
        "model": _embedder.model_name if _embedder else "not loaded",
    }


@app.post("/search", response_model=SearchResponse)
async def search(req: SearchRequest, user=Depends(_auth_dependency)) -> SearchResponse:
    """Search indexed documentation by semantic similarity."""
    if not _embedder:
        raise HTTPException(status_code=503, detail="Embedding model not loaded yet")

    try:
        query_vector = _embedder.embed_query(req.query)
    except Exception as e:
        logger.error("Embedding failed: %s", e)
        raise HTTPException(status_code=500, detail="Failed to embed query")

    settings = _get_settings()
    user_tags = [req.team_name] + ([req.area_name] if req.area_name else [])

    try:
        pool = await get_pool(settings.database_url)
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT
                    c.text,
                    c.section_title,
                    s.title AS source_title,
                    s.url AS source_url,
                    s.tags AS source_tags,
                    1 - (c.embedding <=> $1::vector) AS similarity,
                    (1 - (c.embedding <=> $1::vector)) *
                        (1
                         + $2::float * cardinality(
                             ARRAY(SELECT unnest(s.tags) INTERSECT SELECT unnest($3::text[]))
                           )
                         + $4::float * (CASE WHEN 'org' = ANY(s.tags) THEN 1 ELSE 0 END)
                        ) AS boosted_score
                FROM chunks c
                JOIN sources s ON c.source_id = s.id
                WHERE s.status = 'active'
                ORDER BY boosted_score DESC
                LIMIT $5
                """,
                np.array(query_vector, dtype=np.float32),
                settings.tag_match_weight,
                user_tags,
                settings.org_tag_weight,
                req.limit,
            )
    except Exception as e:
        logger.error("Database error during search: %s", e)
        raise HTTPException(status_code=503, detail="Database unavailable")

    from docforge.query_log import log_query

    # When auth.mode==entra, trust the JWT claims over the self-declared
    # user_name request field. team_name and area_name remain self-declared
    # (they are routing hints, not identity).
    effective_user_name = user.preferred_username if user else req.user_name
    effective_user_oid = user.oid if user else None
    await log_query(
        pool,
        effective_user_name,
        req.team_name,
        req.area_name,
        req.query,
        len(rows),
        user_oid=effective_user_oid,
    )

    results = [
        SearchResult(
            text=row["text"],
            section_title=row["section_title"],
            source_title=row["source_title"],
            source_url=row["source_url"],
            source_tags=list(row["source_tags"] or []),
            similarity=float(row["similarity"]),
        )
        for row in rows
    ]

    return SearchResponse(results=results, query=req.query, count=len(results))


@app.get("/sources")
async def list_sources(user=Depends(_auth_dependency)) -> dict[str, Any]:
    """List all indexed documentation sources."""
    settings = _get_settings()
    try:
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
    except Exception as e:
        logger.error("Database error listing sources: %s", e)
        raise HTTPException(status_code=503, detail="Database unavailable")

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
