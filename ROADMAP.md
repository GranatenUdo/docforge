# Roadmap

docforge follows a signal-over-ritual roadmap: we list what we're actively
working on and what's explicitly out of scope. Dates are aspirational, not
committed.

## Next up (0.3.x)

- **Hybrid retrieval** (BM25 + dense) — Postgres `tsvector` + weighted fusion.
- **Chunk overlap** — small token overlap between consecutive chunks.
- **MCP identity via session**, not per-call args — remove `user_name` /
  `team_name` from the tool signature.

## Being considered (0.4.x+)

- **Per-source ACLs** — honor Confluence space permissions at query time.
- **Confluence Data Center auth hardening** — SSO / SAML / PAT flows.
- **Incremental Confluence ingest** — `updatedSince` API instead of hash-diff.

## Explicitly out of scope

- A web chat UI (use [Onyx](https://github.com/onyx-dot-app/onyx) or [Glean](https://www.glean.com/) if you need one).
- 50-connector sprawl (Slack, Drive, Notion, Jira, Gmail).
- Multi-tenant SaaS (docforge assumes a single-company trust boundary).
