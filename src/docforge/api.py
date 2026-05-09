"""FastAPI search API for docforge.

Runs on Azure Container Apps. Loads embedding model at startup,
serves search queries over HTTP.

Run locally: uvicorn docforge.api:app --reload
"""

from __future__ import annotations

import asyncio
import logging
import time
from contextlib import asynccontextmanager
from typing import Any

import asyncpg
import numpy as np
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.security import SecurityScopes
from pydantic import BaseModel, Field

from docforge.config import Settings
from docforge.db import _init_connection  # registers pgvector codec on each new pool conn
from docforge.processors.embedder import Embedder, EmbedderProtocol
from docforge.query_log import log_query

logger = logging.getLogger(__name__)

_CLEANUP_INTERVAL_SECONDS = 3600  # one hour — overridable in tests
CLEANUP_LOCK_ID = 0xD0CF0001  # decimal 3,503,226,881 — stable across replicas


async def _query_log_cleanup_loop(pool: asyncpg.Pool, retention_days: int) -> None:
    """Each iteration takes a transaction-scoped advisory lock. A replica
    that can't acquire it skips this iteration. The lock auto-releases at
    COMMIT/ROLLBACK and on connection drop — no manual unlock to forget."""
    # int() coercion makes the f-string SQL below injection-safe; asyncpg's
    # $1::interval parameter binding doesn't accept str, hence the literal.
    days = int(retention_days)
    while True:
        try:
            async with pool.acquire() as conn:
                async with conn.transaction():
                    got_lock = await conn.fetchval(
                        "SELECT pg_try_advisory_xact_lock($1)", CLEANUP_LOCK_ID
                    )
                    if got_lock:
                        result = await conn.execute(
                            f"DELETE FROM query_log "
                            f"WHERE created_at < now() - interval '{days} days'"
                        )
                        logger.info("query_log cleanup: %s", result)
                    else:
                        logger.debug("query_log cleanup: another replica holds the lock")
        except Exception as e:
            logger.exception("query_log cleanup failed: %s", e)
        await asyncio.sleep(_CLEANUP_INTERVAL_SECONDS)


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
    """Build per-process resources at startup; tear them down on shutdown.

    Yields a dict whose entries flow into request.state for handler access
    via the Depends getters below."""
    settings = Settings()
    embedder: EmbedderProtocol | None = None  # set inside try; outer finally reads it
    pool = await asyncpg.create_pool(
        settings.database_url,
        min_size=settings.pool_min_size,
        max_size=settings.pool_max_size,
        init=_init_connection,
    )
    try:
        # Embedder construction can raise (Phase 1 dimension guard); the
        # outer finally still closes the pool in that case. Offloaded to a
        # thread so the model-load file I/O doesn't stall the event loop.
        embedder = await asyncio.to_thread(Embedder.from_settings, settings)
        logger.info("Model loaded: %s (%dd)", embedder.model_name, embedder.dimensions)

        azure_scheme = _build_auth_scheme(settings)
        if azure_scheme is not None:
            await azure_scheme.openid_config.load_config()
            logger.info(
                "Entra auth enabled (tenant=%s, audience=%s)",
                settings.auth.tenant_id,
                settings.auth.audience,
            )

        cleanup_task = asyncio.create_task(
            _query_log_cleanup_loop(pool, settings.query_log_retention_days)
        )
        try:
            yield {
                "settings": settings,
                "pool": pool,
                "embedder": embedder,
                "azure_scheme": azure_scheme,
            }
        finally:
            cleanup_task.cancel()
            try:
                await cleanup_task
            except asyncio.CancelledError:
                pass
    finally:
        if embedder is not None and hasattr(embedder, "aclose"):
            await embedder.aclose()
        await pool.close()


app = FastAPI(title="docforge", lifespan=lifespan)


def get_settings(request: Request) -> Settings:
    return request.state.settings


def get_pool_dep(request: Request) -> asyncpg.Pool:
    return request.state.pool


def get_embedder(request: Request) -> EmbedderProtocol:
    return request.state.embedder


def get_azure_scheme(request: Request):
    return request.state.azure_scheme


async def _auth_dependency(
    request: Request,
    azure_scheme=Depends(get_azure_scheme),
):
    """Return the authenticated User under auth.mode=entra, None otherwise."""
    if azure_scheme is None:
        return None
    return await azure_scheme(request, SecurityScopes())


class SearchRequest(BaseModel):
    query: str = Field(..., max_length=8000)
    user_name: str | None = None
    team_name: str | None = None
    area_name: str | None = None
    limit: int = Field(5, ge=1, le=50)


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
async def health(request: Request) -> dict[str, Any]:
    """Health check endpoint."""
    embedder = getattr(request.state, "embedder", None)
    return {
        "status": "ok",
        "model": embedder.model_name if embedder else "not loaded",
    }


@app.post("/search", response_model=SearchResponse)
async def search(
    req: SearchRequest,
    settings: Settings = Depends(get_settings),
    pool: asyncpg.Pool = Depends(get_pool_dep),
    embedder: EmbedderProtocol = Depends(get_embedder),
    user=Depends(_auth_dependency),
) -> SearchResponse:
    """Search indexed documentation by semantic similarity."""
    start = time.perf_counter()

    try:
        query_vector = await embedder.aembed_query(req.query)
    except Exception as e:
        logger.error("Embedding failed: %s", e)
        raise HTTPException(status_code=500, detail="Failed to embed query")

    user_tags = [t for t in (req.team_name, req.area_name) if t]

    try:
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                WITH q_tsq AS (SELECT websearch_to_tsquery($8::regconfig, $2::text) AS q),
                     dense AS (
                         SELECT id, source_id, text, section_title,
                                ROW_NUMBER() OVER (ORDER BY dist) AS rank
                         FROM (
                             SELECT c.id, c.source_id, c.text, c.section_title,
                                    c.embedding <=> $1::vector AS dist
                             FROM chunks c JOIN sources s ON c.source_id = s.id
                             WHERE s.status = 'active'
                             ORDER BY c.embedding <=> $1::vector
                             LIMIT $3
                         ) AS t
                     ),
                     sparse AS (
                         SELECT id, source_id, text, section_title,
                                ROW_NUMBER() OVER (ORDER BY rk DESC) AS rank
                         FROM (
                             SELECT c.id, c.source_id, c.text, c.section_title,
                                    ts_rank_cd(c.text_tsv, (SELECT q FROM q_tsq)) AS rk
                             FROM chunks c JOIN sources s ON c.source_id = s.id
                             WHERE s.status = 'active'
                               AND c.text_tsv @@ (SELECT q FROM q_tsq)
                             ORDER BY ts_rank_cd(c.text_tsv, (SELECT q FROM q_tsq)) DESC
                             LIMIT $3
                         ) AS t
                     ),
                     fused AS (
                         SELECT COALESCE(d.id, sp.id) AS id,
                                COALESCE(d.source_id, sp.source_id) AS source_id,
                                COALESCE(d.text, sp.text) AS text,
                                COALESCE(d.section_title, sp.section_title) AS section_title,
                                COALESCE(1.0/($9 + d.rank), 0) + COALESCE(1.0/($9 + sp.rank), 0) AS rrf
                         FROM dense d FULL OUTER JOIN sparse sp ON d.id = sp.id
                     )
                SELECT f.text, f.section_title,
                       s.title AS source_title, s.url AS source_url, s.tags AS source_tags,
                       f.rrf AS similarity,
                       f.rrf * (1
                                + $4::float * cardinality(
                                    ARRAY(SELECT unnest(s.tags) INTERSECT SELECT unnest($5::text[]))
                                  )
                                + $6::float * (CASE WHEN 'org' = ANY(s.tags) THEN 1 ELSE 0 END)
                       ) AS boosted_score
                FROM fused f JOIN sources s ON f.source_id = s.id
                ORDER BY boosted_score DESC
                LIMIT $7
                """,
                np.array(query_vector, dtype=np.float32),  # $1
                req.query,                                  # $2
                settings.hybrid_pool_size,                  # $3
                settings.tag_match_weight,                  # $4
                user_tags,                                  # $5
                settings.org_tag_weight,                    # $6
                req.limit,                                  # $7
                settings.fts_language,                      # $8
                settings.rrf_k,                             # $9
            )
    except Exception as e:
        logger.error("Database error during search: %s", e)
        raise HTTPException(status_code=503, detail="Database unavailable")

    request_ms = int((time.perf_counter() - start) * 1000)

    effective_user_name = user.preferred_username if user else (req.user_name or "anonymous")
    await log_query(
        pool,
        effective_user_name,
        req.team_name,
        req.area_name,
        req.query,
        len(rows),
        user_oid=user.oid if user else None,
        request_ms=request_ms,
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
async def list_sources(
    pool: asyncpg.Pool = Depends(get_pool_dep),
    user=Depends(_auth_dependency),
) -> dict[str, Any]:
    """List all indexed documentation sources."""
    try:
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
