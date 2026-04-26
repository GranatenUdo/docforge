# docforge `query_log` — privacy & retention policy

This document defines what `query_log` stores, how long, who can read it, what gets redacted, and how to honour a delete request. It is the policy a docforge deployer commits to operate by; the implementation in `src/docforge/` and `deploy/azure/main.bicep` should match it.

## Purpose

`query_log` exists to support **retrieval drift signals** — detecting when search quality regresses against real usage. Aggregate metrics on retention, recall@k, and request latency are derived from the `query` text plus the `result_count` and `request_ms` columns.

The table is *not* used for:

- per-user activity surveillance
- billing or quota enforcement
- audit trail for regulatory compliance — `query_log` records search queries, not data-access decisions; it is not a complete or authoritative record of who accessed what content and should not be submitted as one

If your deployment has any of those needs, they require a separate system with appropriate controls. You *may* derive aggregate metrics from `query_log` (e.g. query volume per team for capacity planning) provided this policy's retention and access controls are in place.

## Retention

Default: **60 days**.

Configurable via `Settings.query_log_retention_days` (env: `QUERY_LOG_RETENTION_DAYS`). The application-level cleanup loop in `docforge.api._query_log_cleanup_loop` runs hourly and deletes rows where `created_at < now() - interval '<N> days'`.

Rationale: 60 days is long enough to catch drift across a typical model-swap or chunker-tweak cycle, short enough to limit privacy exposure. Shorter retention is fine (down to 30 days; below that, drift signals become statistically thin); longer retention should be paired with stricter redaction (see below) and a documented operational reason.

## Redaction

The application redacts these patterns from `query` text before insert:

| Pattern | Regex (illustrative) | Replacement |
|---|---|---|
| HuggingFace tokens | `\bhf_[A-Za-z0-9]{30,}\b` | `[REDACTED:HF_TOKEN]` |
| JWTs | `\beyJ[A-Za-z0-9_=-]{40,}\.[A-Za-z0-9_=-]{40,}\.[A-Za-z0-9_=-]{20,}\b` | `[REDACTED:JWT]` |
| Email addresses | `\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b` | `[REDACTED:EMAIL]` |
| Long opaque tokens (heuristic) | `\b[A-Za-z0-9_-]{40,}\b` (when not matching any other category) | `[REDACTED:KEY?]` |

These are the intended patterns; the exact regexes in Phase 5 may differ after testing against real query traffic. Before Phase 5, no redaction runs — see "Implementation status" below.

The redactor is fail-open at the search-handler level: if a regex throws, the redaction step is skipped, the query goes into the table verbatim, and a `WARN` log line is emitted naming the failed pattern. Logging a query is best-effort and must never gate the user's search.

These patterns catch the common cases. Deployments that handle highly sensitive content (PII, medical, legal) should layer additional redaction on top or skip query logging entirely (set `query_log_retention_days = 0` to delete on the next cleanup cycle).

## Access

Two database roles are expected, provisioned by the deployer (e.g. via `deploy/azure/main.bicep`):

- `docforge_app` — the application's identity. **Read + write** on `query_log`. Used by the API to insert rows and by the cleanup loop to delete expired rows.
- `docforge_log_reader` — a separate role for analytics. **Read-only** on `query_log`. Granted to a small named group via Postgres role membership; that group is reviewed quarterly.

Direct queries against `query_log` outside these two roles are not authorised. Operators with break-glass access should use the role grants when answering an erasure request rather than connecting as a superuser.

## Right to erasure

When a user invokes their right to erasure (GDPR Article 17 or equivalent), an authorised operator runs:

```sql
DELETE FROM query_log WHERE user_oid = $1;
```

Where `$1` is the user's Entra `oid` (object ID, immutable). For rows from before migration `005_add_query_log_user_oid.sql` (where `user_oid` is `NULL`), fall back to `user_name`:

```sql
DELETE FROM query_log WHERE user_oid IS NULL AND user_name = $1;
```

Operational runbook:

1. Verify the requester's identity and authority to make the request.
2. Look up their Entra `oid` (`az ad user show --id <upn> --query id`).
3. Connect to the database using the `docforge_app` role (do not use a superuser connection; see "Access" above for the rationale).
4. `BEGIN; DELETE FROM query_log WHERE user_oid = $1; COMMIT;` — confirm rowcount.
5. If a pre-migration `user_name` deletion is also needed, run the second query.
6. Log the operation in the deletion register (operator-side ticket / change log).
7. Notify the requester with the rowcount deleted.

**Note:** if `auth.mode = none`, `user_oid` is always `NULL`. In that configuration, skip steps 2–4 and use the `user_name` query (step 5) for all rows; the `user_oid` query would return zero rows and silently miss every record for the requested user.

## Implementation status (as of v0.3)

| Item | Status |
|---|---|
| Retention configurable, hourly cleanup | ✓ Implemented (`docforge.api._query_log_cleanup_loop`) |
| Default retention 60 days | ✗ Default is 180 days; Phase 5 changes the default |
| Redaction at insert | ✗ Not yet; Phase 5 implements `query_log.log_query` redaction |
| `docforge_app` + `docforge_log_reader` roles | ~ Operator-provided; not enforced by docforge |
| Right-to-erasure SQL | ✓ Works today (manual SQL) |
| Right-to-erasure CLI command | ✗ Not yet; manual SQL is the supported path |

Items marked ✗ ship in v0.3 Phase 5. Until they land, the policy describes the deployer's commitment; the implementation hasn't fully met it. Operators deploying v0.3 between Phase 3 and Phase 5 should assume queries are stored verbatim with 180-day retention by default and adjust `query_log_retention_days` accordingly.

## Review cadence

Reviewed annually or on changes to:

- `Settings.query_log_retention_days` default
- the redaction pattern set
- the role grants in `deploy/azure/main.bicep` (or equivalent)
- the right-to-erasure runbook above
- changes to `auth.mode` (affects how `user_oid` is populated and which erasure query path is primary)

**Last reviewed:** 2026-04-26 (initial authoring alongside v0.3 Phase 3).
