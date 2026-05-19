"""Evaluate docforge retrieval quality against a ground-truth query set.

Usage:
    python -m docforge.scripts.eval_search \\
      --api-url https://<fqdn> \\
      --ground-truth path/to/ground_truth.yml \\
      --user tobias.ens --team platform --area cloud \\
      --k 5

Prints per-query detail + summary (recall@1, recall@k, MRR) to stdout. Exits 0
on successful run regardless of retrieval quality — this tool measures, it does
not gate.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from dataclasses import dataclass, field
from pathlib import Path

import httpx
import yaml


@dataclass(frozen=True)
class QueryResult:
    query: str
    expected_substring: str
    returned_titles: list[str]
    returned_scores: list[float]
    match_rank: int | None  # 1-based; None if not in top-k
    # Per-rank debug info — populated only in --direct --debug mode. Same length
    # as returned_titles when populated; empty list otherwise.
    returned_dense_ranks: list[int | None] = field(default_factory=list)
    returned_sparse_ranks: list[int | None] = field(default_factory=list)


def score_query(returned_titles: list[str], expected_substring: str) -> int | None:
    """Return 1-based rank where expected_substring is contained in any title,
    case-insensitively; or None if no match. Pure function."""
    needle = expected_substring.lower()
    for rank, title in enumerate(returned_titles, start=1):
        if needle in title.lower():
            return rank
    return None


def summarize(results: list[QueryResult], k: int) -> dict[str, float | int]:
    """Return {queries, recall@1, recall@k, mrr}. Pure function."""
    total = len(results)
    if total == 0:
        return {"queries": 0, "recall@1": 0.0, f"recall@{k}": 0.0, "mrr": 0.0}
    hits_at_1 = sum(1 for r in results if r.match_rank == 1)
    hits_at_k = sum(1 for r in results if r.match_rank is not None and r.match_rank <= k)
    mrr = sum(1.0 / r.match_rank for r in results if r.match_rank is not None) / total
    return {
        "queries": total,
        "recall@1": hits_at_1 / total,
        f"recall@{k}": hits_at_k / total,
        "mrr": mrr,
    }


async def run_queries(
    api_url: str,
    ground_truth: list[dict],
    user_name: str,
    team_name: str,
    area_name: str | None,
    k: int,
    audience: str | None = None,
) -> list[QueryResult]:
    """POST each query to <api_url>/search via httpx; collect results. Sequential.

    When audience is provided, attach an Entra Bearer token obtained via
    DefaultAzureCredential. When not, send unauthenticated (auth.mode==none path)."""
    results: list[QueryResult] = []
    credential = None
    if audience:
        from azure.identity.aio import DefaultAzureCredential

        credential = DefaultAzureCredential()
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            for entry in ground_truth:
                q: str = entry["q"]
                expected: str = entry["expected_title_contains"]
                headers: dict[str, str] = {}
                if credential is not None:
                    token = await credential.get_token(f"{audience}/.default")
                    headers["Authorization"] = f"Bearer {token.token}"
                try:
                    resp = await client.post(
                        f"{api_url}/search",
                        headers=headers,
                        json={
                            "query": q,
                            "user_name": user_name,
                            "team_name": team_name,
                            "area_name": area_name,
                            "limit": k,
                        },
                    )
                    resp.raise_for_status()
                    payload = resp.json()
                    hits = payload.get("results", [])
                except (httpx.HTTPError, ValueError) as e:
                    print(f"  Query failed ({q!r}): {e}", file=sys.stderr)
                    hits = []
                titles = [h.get("source_title", "") for h in hits]
                scores = [float(h.get("similarity", 0.0)) for h in hits]
                results.append(
                    QueryResult(
                        query=q,
                        expected_substring=expected,
                        returned_titles=titles,
                        returned_scores=scores,
                        match_rank=score_query(titles, expected),
                    )
                )
    finally:
        if credential is not None:
            await credential.close()
    return results


async def run_queries_direct(
    ground_truth: list[dict],
    user_name: str,
    team_name: str,
    area_name: str | None,
    k: int,
    debug: bool = False,
) -> list[QueryResult]:
    """Run each query against docforge.api.perform_search directly (no HTTP).

    Reads Settings from local env/yml, opens an asyncpg pool, constructs an
    Embedder via the factory, then calls perform_search() for each query.
    Returns the same QueryResult shape as run_queries so format_report can
    consume either."""
    import asyncpg
    from docforge.api import perform_search, SearchRequest
    from docforge.config import Settings
    from docforge.db import _init_connection
    from docforge.processors.embedder import Embedder

    settings = Settings()
    # --direct mode is meant for production-DB investigation work; it requires
    # the remote embedder sidecar so the eval uses the SAME embeddings the
    # live API uses. Falling through to the in-process Embedder would download
    # Qwen-4B 4B locally (~7 GiB FP16 RAM, ~10min first-run model download)
    # AND produce embeddings that may differ from prod (different FP precision,
    # different hardware). Hard-fail with a clear message instead.
    if not settings.embedder_url:
        raise SystemExit(
            "eval_search --direct requires settings.embedder_url to be set. "
            "Without it, this command would download Qwen-4B 4B locally. "
            "Set EMBEDDER_URL + EMBEDDER_TOKEN in rag/.env, or export them "
            "in the current shell before re-running."
        )
    pool = await asyncpg.create_pool(
        settings.database_url,
        min_size=1,
        max_size=4,
        init=_init_connection,
    )
    try:
        embedder = await asyncio.to_thread(Embedder.from_settings, settings)
        try:
            results: list[QueryResult] = []
            for entry in ground_truth:
                q: str = entry["q"]
                expected: str = entry["expected_title_contains"]
                req = SearchRequest(
                    query=q,
                    user_name=user_name,
                    team_name=team_name,
                    area_name=area_name,
                    limit=k,
                    debug=debug,
                )
                rows = await perform_search(req=req, settings=settings, pool=pool, embedder=embedder)
                titles = [r["source_title"] for r in rows]
                scores = [float(r["similarity"]) for r in rows]
                dense_ranks = [r["dense_rank"] for r in rows] if debug else []
                sparse_ranks = [r["sparse_rank"] for r in rows] if debug else []
                results.append(
                    QueryResult(
                        query=q,
                        expected_substring=expected,
                        returned_titles=titles,
                        returned_scores=scores,
                        match_rank=score_query(titles, expected),
                        returned_dense_ranks=dense_ranks,
                        returned_sparse_ranks=sparse_ranks,
                    )
                )
            return results
        finally:
            if hasattr(embedder, "aclose"):
                await embedder.aclose()
    finally:
        await pool.close()


def format_report(results: list[QueryResult], summary: dict[str, float | int], k: int) -> str:
    """Per-query detail + summary. Human-readable stdout."""
    lines: list[str] = []
    for r in results:
        lines.append(f"Query: {r.query!r}")
        lines.append(f"  Expected: contains {r.expected_substring!r}")
        if r.returned_titles:
            lines.append(f"  Top {len(r.returned_titles)}:")
            has_debug = bool(r.returned_dense_ranks) and bool(r.returned_sparse_ranks)
            for i, (title, score) in enumerate(
                zip(r.returned_titles, r.returned_scores, strict=False), start=1
            ):
                marker = "  <-- MATCH" if r.match_rank == i else ""
                if has_debug:
                    dr = r.returned_dense_ranks[i - 1]
                    sr = r.returned_sparse_ranks[i - 1]
                    dr_s = f"d#{dr}" if dr is not None else "d#-"
                    sr_s = f"s#{sr}" if sr is not None else "s#-"
                    lines.append(f"    {i}. [{score:.4f}] ({dr_s} {sr_s}) {title}{marker}")
                else:
                    lines.append(f"    {i}. [{score:.2f}] {title}{marker}")
        else:
            lines.append("  Top: (no results)")
        if r.match_rank is not None and r.match_rank <= k:
            lines.append(f"  recall@{k}: HIT  rank: {r.match_rank}")
        else:
            lines.append(f"  recall@{k}: MISS")
        lines.append("")

    lines.append("Summary:")
    lines.append(f"  queries:               {summary['queries']}")
    recall1 = summary["recall@1"]
    recall_k = summary[f"recall@{k}"]
    total = summary["queries"] or 1
    r1_pct = f"{recall1 * 100:.0f}%"
    rk_pct = f"{recall_k * 100:.0f}%"
    lines.append(f"  recall@1:              {int(recall1 * total)}/{total} ({r1_pct})")
    lines.append(f"  recall@{k}:              {int(recall_k * total)}/{total} ({rk_pct})")
    lines.append(f"  mean reciprocal rank:  {summary['mrr']:.3f}")

    misses = [r for r in results if r.match_rank is None or r.match_rank > k]
    if misses:
        lines.append("")
        lines.append(f"  Missed (no match in top {k}):")
        for r in misses:
            lines.append(f"    - {r.query!r}  (expected {r.expected_substring!r})")

    return "\n".join(lines)


def _load_ground_truth(path: Path) -> list[dict]:
    """Load, validate, and return the `queries` list from a ground-truth YAML file."""
    if not path.is_file():
        raise FileNotFoundError(f"Ground truth file not found: {path}")
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    queries = data.get("queries")
    if not isinstance(queries, list) or not queries:
        raise ValueError(f"{path}: missing or empty 'queries' list")
    for i, q in enumerate(queries):
        if "q" not in q or "expected_title_contains" not in q:
            raise ValueError(f"{path}: entry {i} must have 'q' and 'expected_title_contains' keys")
    return queries


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    src_group = parser.add_mutually_exclusive_group(required=True)
    src_group.add_argument(
        "--api-url",
        help="Base URL of the search API (no trailing slash). Mutually exclusive with --direct.",
    )
    src_group.add_argument(
        "--direct",
        action="store_true",
        help=(
            "Bypass the HTTP API and call docforge.api.perform_search directly "
            "against the configured Postgres + Embedder. Reads connection info "
            "from the local docforge.yml / .env. Mutually exclusive with --api-url."
        ),
    )
    parser.add_argument("--ground-truth", required=True, type=Path, help="Path to ground_truth.yml")
    parser.add_argument("--user", required=True, help="Your identity — forwarded as user_name")
    parser.add_argument("--team", required=True, help="Your team tag — forwarded as team_name")
    parser.add_argument("--area", default=None, help="Optional area tag — forwarded as area_name")
    parser.add_argument("--k", type=int, default=5, help="Top-k cutoff for recall@k")
    parser.add_argument(
        "--debug",
        action="store_true",
        help=(
            "Request debug fields (dense_rank, sparse_rank, rrf_score) on each "
            "result and dump them per query. Direct mode passes debug=true to "
            "perform_search; HTTP mode is unaffected (debug data not exposed "
            "via run_queries)."
        ),
    )
    parser.add_argument(
        "--audience",
        default=None,
        help=(
            "Entra API audience (e.g., api://<app-id>). When set, attaches a "
            "Bearer token via DefaultAzureCredential. Omit for auth.mode=none."
        ),
    )
    args = parser.parse_args()

    try:
        ground_truth = _load_ground_truth(args.ground_truth)
    except (FileNotFoundError, ValueError) as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    if args.direct:
        results = asyncio.run(
            run_queries_direct(
                ground_truth=ground_truth,
                user_name=args.user,
                team_name=args.team,
                area_name=args.area,
                k=args.k,
                debug=args.debug,
            )
        )
    else:
        results = asyncio.run(
            run_queries(
                api_url=args.api_url.rstrip("/"),
                ground_truth=ground_truth,
                user_name=args.user,
                team_name=args.team,
                area_name=args.area,
                k=args.k,
                audience=args.audience,
            )
        )
    summary = summarize(results, args.k)
    print(format_report(results, summary, args.k))
    return 0


if __name__ == "__main__":
    sys.exit(main())
