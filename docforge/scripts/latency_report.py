"""Compute P50 / P95 / P99 latency over recent query_log entries.

Usage:
    python -m docforge.scripts.latency_report --since '7 days' [--database-url ...]

Reads DATABASE_URL from the environment (or --database-url flag) so it can
run against prod with the admin connection string from Key Vault.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from dataclasses import dataclass

import asyncpg


@dataclass(frozen=True)
class LatencySummary:
    n: int
    p50_ms: float | None
    p95_ms: float | None
    p99_ms: float | None
    earliest_request_ms_at: str | None  # ISO timestamp of first post-C4.3 row


async def compute_summary(database_url: str, since: str) -> LatencySummary:
    """Query query_log.request_ms within the given interval. Returns
    percentiles + row count + the earliest-seen request_ms timestamp (the
    effective C4.3 cutover date for this DB)."""
    conn = await asyncpg.connect(database_url)
    try:
        row = await conn.fetchrow(
            """
            SELECT
                percentile_cont(0.50) WITHIN GROUP (ORDER BY request_ms) AS p50,
                percentile_cont(0.95) WITHIN GROUP (ORDER BY request_ms) AS p95,
                percentile_cont(0.99) WITHIN GROUP (ORDER BY request_ms) AS p99,
                count(*)                                                 AS n
              FROM query_log
             WHERE request_ms IS NOT NULL
               AND created_at > now() - $1::interval
            """,
            since,
        )
        earliest = await conn.fetchval(
            "SELECT min(created_at) FROM query_log WHERE request_ms IS NOT NULL"
        )
        return LatencySummary(
            n=int(row["n"]),
            p50_ms=float(row["p50"]) if row["p50"] is not None else None,
            p95_ms=float(row["p95"]) if row["p95"] is not None else None,
            p99_ms=float(row["p99"]) if row["p99"] is not None else None,
            earliest_request_ms_at=earliest.isoformat() if earliest is not None else None,
        )
    finally:
        await conn.close()


def format_summary(summary: LatencySummary, since: str) -> str:
    """Human-readable stdout report."""
    lines = [
        f"Window:                 last {since}",
        f"Queries with timing:    {summary.n}",
    ]
    if summary.n == 0:
        lines.append(
            "No rows with request_ms in the window — has the C4.3 migration been applied "
            "and the /search handler redeployed?"
        )
        return "\n".join(lines)
    lines.extend(
        [
            f"P50:                    {summary.p50_ms:.0f} ms",
            f"P95:                    {summary.p95_ms:.0f} ms",
            f"P99:                    {summary.p99_ms:.0f} ms",
        ]
    )
    if summary.earliest_request_ms_at is not None:
        lines.append(f"request_ms cutover at:  {summary.earliest_request_ms_at}")
    lines.append("")
    lines.append("Note: the earliest ~1-2 rows after each revision deployment include")
    lines.append("the 15-30 s embedding-model warm-up cost; this is kept in the data as")
    lines.append("honest signal. P95 therefore reflects warm-up+steady-state.")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--since",
        default="7 days",
        help="Postgres interval string (e.g., '7 days', '24 hours'). Default: 7 days.",
    )
    parser.add_argument(
        "--database-url",
        default=None,
        help="Postgres URL. Falls back to DATABASE_URL env var.",
    )
    args = parser.parse_args()

    db_url = args.database_url or os.environ.get("DATABASE_URL")
    if not db_url:
        print("Error: DATABASE_URL not set (and --database-url not provided)", file=sys.stderr)
        return 1

    summary = asyncio.run(compute_summary(db_url, args.since))
    print(format_summary(summary, args.since))
    return 0


if __name__ == "__main__":
    sys.exit(main())
