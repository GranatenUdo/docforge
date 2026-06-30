# docforge `query_log` — privacy & retention policy

This document defines what `query_log` stores, how long, who can read it, and how to honour a delete request (queries are stored verbatim — there is no redaction). It is the policy a docforge deployer commits to operate by; the implementation in `src/docforge/` and `deploy/azure/main.bicep` should match it.

## Purpose

`query_log` (and, when `LOG_RESPONSES` is enabled, the captured results in `query_result`) exists so maintainers can (1) review real queries and the answers they returned, to validate and improve result quality, and (2) build a corpus of real searches for tuning retrieval ranking. Drift detection — spotting when search quality regresses against real usage — is one downstream use; aggregate metrics on retention, recall@k, and request latency derive from the `query` text plus the `result_count` and `request_ms` columns.

The table is *not* used for:

- per-user activity surveillance
- billing or quota enforcement
- audit trail for regulatory compliance — `query_log` records search queries, not data-access decisions; it is not a complete or authoritative record of who accessed what content and should not be submitted as one

If your deployment has any of those needs, they require a separate system with appropriate controls. You *may* derive aggregate metrics from `query_log` (e.g. query volume per team for capacity planning) provided this policy's retention and access controls are in place.

## Retention

Default: **180 days**.

Configurable via `Settings.query_log_retention_days` (env: `QUERY_LOG_RETENTION_DAYS`). The application-level cleanup loop in `docforge.api._query_log_cleanup_loop` runs hourly and deletes rows where `created_at < now() - interval '<N> days'`.

Rationale: 180 days is long enough to catch drift across several model-swap or chunker-tweak cycles, while bounding privacy exposure. Shorter retention is fine (down to ~30 days; below that, drift signals become statistically thin); longer retention should be paired with a documented operational reason and tighter access controls.

## No redaction — queries are stored verbatim

docforge does NOT redact query text; queries are stored exactly as typed. This is intentional — the review and ranking-tuning purposes above need the real text. Do not assume the query log is sanitized; treat it as containing whatever users enter (including secrets they may accidentally paste).

A deployment handling highly sensitive content should not rely on redaction: lower `query_log_retention_days` (set to `0` to delete on the next cleanup cycle) or disable query logging entirely.

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

## Implementation status (as of v0.7.17)

| Item | Status |
|---|---|
| Retention configurable, hourly cleanup | Implemented (`docforge.api._query_log_cleanup_loop`) |
| Default retention 180 days | Implemented (`Settings.query_log_retention_days = 180`) |
| Redaction at insert | Not implemented; no planned milestone (queries stored verbatim by design — see Purpose) |
| `docforge_app` + `docforge_log_reader` roles | Partial — operator-provided; not enforced by docforge |
| Right-to-erasure SQL | Implemented; works today (manual SQL) |
| Right-to-erasure CLI command | Not yet; manual SQL is the supported path |

Redaction is not implemented and has no planned milestone — queries are stored verbatim, with 180-day retention by default (adjust `query_log_retention_days`; setting it to `0` purges rows on the next hourly cleanup). The role grants and the erasure CLI remain operator-provided / manual as noted above.

## Review cadence

Reviewed annually or on changes to:

- `Settings.query_log_retention_days` default
- the role grants in `deploy/azure/main.bicep` (or equivalent)
- the right-to-erasure runbook above
- changes to `auth.mode` (affects how `user_oid` is populated and which erasure query path is primary)

**Last reviewed:** 2026-06-30 (removed the planned-but-unimplemented redaction section; reconciled Purpose to result-quality review + ranking tuning; de-pinned from v0.3 Phase 5).
