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
import httpx
import numpy as np
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.security import SecurityScopes
from pydantic import BaseModel, Field

from docforge.config import Settings
from docforge.db import _init_connection  # registers pgvector codec on each new pool conn
from docforge.processors.embedder import Embedder, EmbedderProtocol
from docforge.processors.reranker import RerankerProtocol, reranker_from_settings
from docforge.query_log import log_search

logger = logging.getLogger(__name__)


class RerankerUnavailable(Exception):
    """Raised when the cross-encoder reranker sidecar is unreachable or errors.

    Distinct from DB failures so the /search handler can map it to a 502
    (bad gateway / upstream dependency down) instead of the generic 503
    (database unavailable). The eval --direct path lets it propagate (fail-loud).
    """


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
    # Ensure INFO-level docforge logs reach stdout. Uvicorn configures only
    # its own uvicorn.access / uvicorn.error loggers; the root logger stays
    # at WARNING by default, which silences logger.info() calls from
    # docforge.api (per-phase search_phases timing, query_log cleanup
    # heartbeat, etc.). force=True overrides any handler uvicorn may have
    # already attached. Format mirrors cli._setup_logging for consistency.
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
        force=True,
    )

    settings = Settings()
    embedder: EmbedderProtocol | None = None  # set inside try; outer finally reads it
    # reranker_from_settings returns None when reranker_url is unset; no model
    # load or network here (RemoteReranker construction is lazy/inert).
    reranker = reranker_from_settings(settings)
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
                "reranker": reranker,
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
        if reranker is not None and hasattr(reranker, "aclose"):
            await reranker.aclose()
        await pool.close()


app = FastAPI(title="docforge", lifespan=lifespan)


def get_settings(request: Request) -> Settings:
    return request.state.settings


def get_pool_dep(request: Request) -> asyncpg.Pool:
    return request.state.pool


def get_embedder(request: Request) -> EmbedderProtocol:
    return request.state.embedder


def get_reranker(request: Request) -> RerankerProtocol | None:
    return getattr(request.state, "reranker", None)


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
    limit: int = Field(10, ge=1, le=50)
    debug: bool = Field(
        False,
        description=(
            "When true, response includes per-result dense_rank/sparse_rank/rrf_score "
            "plus envelope-level weights and k. Off by default so the public API "
            "surface is unchanged for normal callers."
        ),
    )


class SearchResultDebug(BaseModel):
    """Per-result diagnostic info — populated only when SearchRequest.debug=true."""

    dense_rank: int | None
    sparse_rank: int | None
    rrf_score: float


class SearchDebugEnvelope(BaseModel):
    """Envelope-level diagnostic info — populated only when SearchRequest.debug=true."""

    weights: dict[str, float]
    k: int


class SearchResult(BaseModel):
    text: str
    section_title: str | None
    source_title: str
    source_url: str
    source_tags: list[str]
    similarity: float
    # Cross-encoder rerank score, present only on reranked head rows. None when
    # reranking is off or for any tail row beyond rerank_top_n. similarity stays
    # the RRF value regardless; this is an additive signal, not a replacement.
    rerank_score: float | None = None
    debug: SearchResultDebug | None = None


class SearchResponse(BaseModel):
    results: list[SearchResult]
    query: str
    count: int
    debug: SearchDebugEnvelope | None = None


@app.get("/health")
async def health(request: Request) -> dict[str, Any]:
    """Health check endpoint."""
    embedder = getattr(request.state, "embedder", None)
    return {
        "status": "ok",
        "model": embedder.model_name if embedder else "not loaded",
    }


async def perform_search(
    *,
    req: SearchRequest,
    settings: Settings,
    pool: asyncpg.Pool,
    embedder: EmbedderProtocol,
    reranker: RerankerProtocol | None = None,
) -> list[asyncpg.Record]:
    """Embed query, run the hybrid-retrieval SQL, return rows.

    This is the pure search path — no FastAPI types, no auth, no query logging.
    Used by the /search endpoint AND by eval_search.py --direct mode so both
    paths exercise identical SQL + ranking.
    """
    t_embed_start = time.perf_counter()
    try:
        query_vector = await embedder.aembed_query(req.query)
    except Exception as e:
        logger.error("Embedding failed: %s", e)
        raise RuntimeError("Failed to embed query") from e
    t_embed_ms = int((time.perf_counter() - t_embed_start) * 1000)

    user_tags = [t for t in (req.team_name, req.area_name) if t]

    # Single predicate for the whole rerank path: drives BOTH the $6 fetch-size
    # bind below and the rerank seam after the fetch. When off, both collapse to
    # the byte-identical rerank-OFF behavior (SQL caps at req.limit, no seam).
    do_rerank = settings.rerank_enabled and reranker is not None

    t_db_start = time.perf_counter()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            WITH q_tsq AS (
                     SELECT replace(websearch_to_tsquery($7::regconfig, $2::text)::text,
                                    '&', '|')::tsquery AS q
                 ),
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
                 q_weights AS (
                     SELECT ARRAY[
                         0.1 / $13::float4,
                         0.2 / $13::float4,
                         0.4 / $13::float4,
                         1.0
                     ]::float4[] AS w
                 ),
                 sparse AS (
                     SELECT id, source_id, text, section_title,
                            ROW_NUMBER() OVER (ORDER BY rk DESC) AS rank
                     FROM (
                         SELECT c.id, c.source_id, c.text, c.section_title,
                                ts_rank_cd(
                                    (SELECT w FROM q_weights),
                                    c.text_tsv,
                                    (SELECT q FROM q_tsq)
                                ) AS rk
                         FROM chunks c JOIN sources s ON c.source_id = s.id
                         WHERE s.status = 'active'
                           AND c.text_tsv @@ (SELECT q FROM q_tsq)
                         ORDER BY ts_rank_cd(
                             (SELECT w FROM q_weights),
                             c.text_tsv,
                             (SELECT q FROM q_tsq)
                         ) DESC
                         LIMIT $3
                     ) AS t
                 ),
                 pool_sizes AS (
                     SELECT (SELECT COUNT(*) FROM dense)  AS dense_count,
                            (SELECT COUNT(*) FROM sparse) AS sparse_count
                 ),
                 weights AS (
                     SELECT
                         $9::float AS effective_dense_weight,
                         CASE
                             WHEN (SELECT sparse_count FROM pool_sizes)
                                  > (SELECT dense_count FROM pool_sizes) * $11::float
                               THEN $10::float * $12::float
                             ELSE $10::float
                         END AS effective_sparse_weight
                 ),
                 fused AS (
                     SELECT COALESCE(d.id, sp.id) AS id,
                            COALESCE(d.source_id, sp.source_id) AS source_id,
                            COALESCE(d.text, sp.text) AS text,
                            COALESCE(d.section_title, sp.section_title) AS section_title,
                            d.rank AS dense_rank,
                            sp.rank AS sparse_rank,
                            COALESCE(
                                (SELECT effective_dense_weight FROM weights) / ($8 + d.rank),
                                0
                            )
                              + COALESCE(
                                  (SELECT effective_sparse_weight FROM weights) / ($8 + sp.rank),
                                  0
                              ) AS rrf
                     FROM dense d FULL OUTER JOIN sparse sp ON d.id = sp.id
                 )
            SELECT f.text, f.section_title,
                   s.title AS source_title, s.url AS source_url, s.tags AS source_tags,
                   f.dense_rank, f.sparse_rank,
                   f.rrf AS similarity,
                   f.rrf * (1
                            + $4::float * cardinality(
                                ARRAY(SELECT unnest(s.tags) INTERSECT SELECT unnest($5::text[]))
                              )
                   ) AS boosted_score
            FROM fused f JOIN sources s ON f.source_id = s.id
            ORDER BY boosted_score DESC, f.id
            LIMIT $6
            """,
            np.array(query_vector, dtype=np.float32),
            req.query,
            settings.hybrid_pool_size,
            settings.tag_match_weight,
            user_tags,
            # $6 — LIMIT on the SQL fetch. When reranking, fetch enough rows for
            # the cross-encoder to score its head (rerank_top_n) while still
            # honoring a larger req.limit; don't over-fetch the full pool when
            # only that many rows can ever be returned. Off -> the SQL caps at
            # req.limit (rerank-OFF path is byte-identical).
            max(req.limit, settings.rerank_top_n) if do_rerank else req.limit,
            settings.fts_language,
            settings.rrf_k,
            settings.dense_weight,
            settings.sparse_weight,
            settings.sparse_flood_ratio,
            settings.sparse_flood_dampening,
            settings.title_weight_a,
        )
    t_db_ms = int((time.perf_counter() - t_db_start) * 1000)

    t_rerank_ms = 0
    if do_rerank and rows:
        head = rows[: settings.rerank_top_n]
        # Join only non-empty fields so a missing section_title (NULL in SQL ->
        # None here) doesn't inject a literal "None" line into the passage.
        passages = [
            "\n".join(s for s in (r["source_title"], r["section_title"], r["text"]) if s)
            for r in head
        ]
        _rr_start = time.perf_counter()
        # Fail-open seam (covers BOTH reranker raise sites). When
        # settings.rerank_fail_open is True, any reranker failure — transport/
        # timeout/5xx/malformed (the arerank except below) OR an invalid
        # permutation (the guard below) — is swallowed: log a WARNING carrying
        # the `search_rerank_fallback` token (the Log Analytics alert signal)
        # and fall back to the pre-rerank RRF/boosted-ordered pool (rows,
        # untouched, no rerank_score). When False (engine default), the original
        # fail-closed behavior is preserved: RerankerUnavailable -> 502 (/search)
        # and the permutation RuntimeError -> 500. The eval --direct path keeps
        # fail_open=False so it fails loud.
        try:
            ranked = await reranker.arerank(req.query, passages)
            # Fail loud on a malformed permutation (survives `python -O`, unlike
            # a bare assert): indices must be EXACTLY the set range(len(head)) —
            # same length AND no dropped/duplicated index. Mirrors the embedder's
            # dimension guard.
            indices = [i for i, _ in ranked]
            if len(indices) != len(head) or set(indices) != set(range(len(head))):
                raise RuntimeError(
                    f"reranker returned an invalid permutation: got {len(indices)} "
                    f"indices {sorted(indices)}, expected a permutation of "
                    f"range({len(head)})"
                )
        except (httpx.HTTPError, RuntimeError) as e:
            if settings.rerank_fail_open:
                # search_rerank_fallback: the monitoring token. The pre-rerank
                # pool `rows` is already in boosted/RRF order, so returning it
                # degrades gracefully to hybrid-only retrieval.
                logger.warning(
                    "search_rerank_fallback: reranker unavailable, returning "
                    "RRF order without rerank: %s",
                    e,
                )
                return rows[: req.limit]
            # Fail-closed: re-raise as before. httpx.HTTPError and the
            # permutation/contract RuntimeError both flow through here — the
            # /search handler maps RerankerUnavailable -> 502 and a bare
            # RuntimeError -> 500.
            if isinstance(e, httpx.HTTPError):
                raise RerankerUnavailable("reranker unavailable") from e
            raise
        # Carry the cross-encoder score back onto each reranked row WITHOUT
        # touching `similarity`: similarity stays the RRF value (preserving its
        # scale and the debug.rrf_score readout), and the CE score lands under a
        # new `rerank_score` key. Consumers trust the returned ORDER (nothing
        # re-sorts by score downstream), so the two scores can coexist. asyncpg
        # Records are read-only, so rebuild head rows as dicts; tail rows keep
        # their RRF similarity and have no rerank_score (None on read via .get).
        reranked = [{**dict(head[i]), "rerank_score": float(score)} for i, score in ranked]
        rows = reranked + rows[settings.rerank_top_n :]
        t_rerank_ms = int((time.perf_counter() - _rr_start) * 1000)
    # NOTE: positions beyond rerank_top_n are raw RRF, so rerank_top_n should be
    # >= the largest expected req.limit or the tail mixes rank regimes.
    rows = rows[: req.limit]

    logger.info(
        "search_phases query_len=%d t_embed_ms=%d t_db_ms=%d t_rerank_ms=%d rows=%d",
        len(req.query),
        t_embed_ms,
        t_db_ms,
        t_rerank_ms,
        len(rows),
    )
    return rows


@app.post("/search", response_model=SearchResponse)
async def search(
    req: SearchRequest,
    settings: Settings = Depends(get_settings),
    pool: asyncpg.Pool = Depends(get_pool_dep),
    embedder: EmbedderProtocol = Depends(get_embedder),
    reranker: RerankerProtocol | None = Depends(get_reranker),
    user=Depends(_auth_dependency),
) -> SearchResponse:
    """Search indexed documentation by semantic similarity."""
    start = time.perf_counter()

    try:
        rows = await perform_search(
            req=req, settings=settings, pool=pool, embedder=embedder, reranker=reranker
        )
    except RerankerUnavailable as e:
        # Reranker sidecar down — an upstream dependency, not the DB. Map to 502
        # so callers/monitoring don't misread it as a database outage (503).
        logger.error("Reranker unavailable during search: %s", e)
        raise HTTPException(status_code=502, detail="reranker unavailable")
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:
        logger.error("Database error during search: %s", e)
        raise HTTPException(status_code=503, detail="Database unavailable")

    t_total_ms = int((time.perf_counter() - start) * 1000)

    effective_user_name = user.preferred_username if user else (req.user_name or "anonymous")
    results_payload = (
        [
            {
                "rank": i,
                # `score` stays the RRF (similarity) for historical continuity in
                # the feedback loop; `rerank_score` carries the new CE score (None
                # for non-reranked rows). .get — rows may be Records without it.
                "score": float(row["similarity"]),
                "rerank_score": row.get("rerank_score"),
                "source_url": row["source_url"],
                "source_title": row["source_title"],
                "section_title": row["section_title"],
                "chunk_text": row["text"],
            }
            for i, row in enumerate(rows, 1)
        ]
        if settings.log_responses
        else None
    )
    await log_search(
        pool,
        effective_user_name,
        req.team_name,
        req.area_name,
        req.query,
        len(rows),
        results=results_payload,
        user_oid=user.oid if user else None,
        request_ms=t_total_ms,
    )

    results = [
        SearchResult(
            text=row["text"],
            section_title=row["section_title"],
            source_title=row["source_title"],
            source_url=row["source_url"],
            source_tags=list(row["source_tags"] or []),
            similarity=float(row["similarity"]),
            # rows are a mix of asyncpg.Record (off-path / tail) and dict
            # (reranked head); both honor the mapping .get() protocol, returning
            # None when the key is absent. Use .get, NOT row["rerank_score"] —
            # the latter would KeyError on a Record that has no such column.
            rerank_score=row.get("rerank_score"),
            debug=(
                SearchResultDebug(
                    dense_rank=row["dense_rank"],
                    sparse_rank=row["sparse_rank"],
                    # similarity is always the RRF value (the rerank seam no
                    # longer overwrites it), so rrf_score reads it directly.
                    rrf_score=float(row["similarity"]),
                )
                if req.debug
                else None
            ),
        )
        for row in rows
    ]
    envelope_debug = (
        SearchDebugEnvelope(
            weights={"dense": settings.dense_weight, "sparse": settings.sparse_weight},
            k=req.limit,
        )
        if req.debug
        else None
    )
    return SearchResponse(
        results=results, query=req.query, count=len(results), debug=envelope_debug
    )


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
