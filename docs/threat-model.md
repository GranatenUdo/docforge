# docforge threat model

**Scope:** This document threat-models the docforge engine code and the reference Azure deployment described in `docforge/deploy/azure/main.bicep`. It does NOT cover consumer-specific Azure subscription governance or tenant-level policies — those are consumer concerns.

**Reader:** Someone evaluating docforge for adoption, or an engineer reviewing a live deployment of docforge.

## Trust model

- **Single-company, single-tenant.** No cross-tenant isolation; no customer data segregation. docforge is intended to index and serve a single operator organisation's internal engineering documentation.
- **Indexed content is non-sensitive corporate documentation.** The `sources` and `chunks` tables hold Confluence pages and git-repo markdown that the operator's organisation has already classified as appropriate for internal engineering sharing. No PII, no customer data, no secrets.
- **`query_log` is the only semi-sensitive datum.** Per-user query history. Governed by the consumer's log-privacy policy.
- **Authenticated users are trusted.** An engineer with a valid Entra token is trusted to query any indexed source. Auth is access control; there is no authorisation layer beyond it — no per-source ACLs.
- **The operator is trusted.** Whoever has Azure subscription admin rights is trusted not to tamper with the deployment.

## Assets

| Asset | Location | Sensitivity |
|---|---|---|
| Indexed docs (sources + chunks) | Azure Postgres Flexible Server | Internal (org-classified) |
| `query_log` rows | Azure Postgres Flexible Server | Semi-sensitive (per-user history) |
| HuggingFace API token | Azure Key Vault | Secret |
| Confluence API token | Azure Key Vault | Secret |
| DB connection string | Azure Key Vault | Secret |
| Container image | Azure Container Registry | Non-secret (distribution-controlled) |

## Threat surfaces and mitigations

| Surface | Threats considered | Mitigations shipped |
|---|---|---|
| Public HTTPS `/search` + `/sources` | Unauthenticated query; credential stuffing against self-declared `user_name`; enumeration of indexed content | When `auth.mode == entra`: Entra ID delegated auth required on both endpoints (`docforge/api.py`, `_auth_dependency`). `user_oid` from the JWT replaces the self-declared `user_name` in `query_log` (migration `005_add_query_log_user_oid.sql`). Only `/health` is unauthenticated and returns no index content |
| `/health` open endpoint | Endpoint fingerprinting; DoS amplification | Returns static JSON (`{"status": "ok", ...}`); no DB access; Container Apps default ingress rate limits apply |
| FastAPI app code | JWT validation bypass; injection in query text | `fastapi-azure-auth` validates JWTs against Entra OpenID configuration loaded at startup; query text is parameterised via asyncpg bind params; no SQL string concatenation anywhere in the query path |
| MCP client (operator-deployed) | Token exfiltration; stale token reuse | `DefaultAzureCredential` holds tokens in-memory only; token refresh is library-handled; no token logging anywhere in client code |
| Ingest pipeline | Poisoned Confluence or git content injecting prompt-injection payloads that manipulate downstream LLM consumers | Out of scope for this iteration — documented as residual risk below |
| Azure Key Vault | Secret exfiltration via misconfigured RBAC | System-assigned managed identity granted `get-secret` only; no human accounts granted secret access by the Bicep template; secret references resolved at container boot only |
| Azure Postgres Flexible Server | DB compromise via connection-string leak | Connection string held in Key Vault, retrieved only at container boot; container runs as UID 1000 with no write access to files containing the connection string |
| Container image | Supply-chain attack via base image or Python deps | Dependabot runs weekly (`.github/dependabot.yml`); base image pinned to `python:3.12-slim-bookworm`; `pyproject.toml` version floors prevent downgrade to known-vulnerable releases |
| Dependency CVEs | Known vulnerabilities in runtime dependencies | Dependabot opens PRs on CVE disclosure; all merges go through branch protection requiring CI green |

## Risks accepted

- **Bus factor of 1.** Single maintainer. Represents a loss-of-availability risk, not a loss-of-confidentiality risk. Named plainly; mitigation requires onboarding a second maintainer, outside the scope of this threat model.
- **HuggingFace-gated embedding model.** EmbeddingGemma-300M requires a HuggingFace token to pull. A model-provider compromise or a change in gating policy would block re-ingest. Re-ingest from a different embedding provider is feasible if the need arises.
- **DB backup window = 7 days.** Azure Postgres Flexible Server `Standard_B1ms` (Burstable tier) default retention. Data older than 7 days cannot be restored via point-in-time recovery. Accepted as cost-appropriate for current scale; raise `backupRetentionDays` in Bicep if SLA requirements change.
- **Prompt-injection via indexed content.** Malicious content in an indexed Confluence page or README could attempt to manipulate the LLM that consumes search results. Mitigation is operational (source-review discipline by the owning team), not code-level in this iteration. Tracked as future work if docforge begins indexing content with lower provenance assurance.
- **No per-source ACLs.** Any authenticated user can query any indexed source. Appropriate for a single-company tool with org-classified content; not a multi-tenant assumption.
- **Self-declared `team_name` and `area_name`.** Even after Entra auth lands, `team_name` and `area_name` remain client-supplied fields in the search request — they are routing hints for relevance boosting, not identity. A caller can set any team/area. The relevance boost gives no access beyond what every authenticated user already has.

## Out of scope

- Multi-tenant isolation. docforge is single-tenant by design; multi-tenant support would require a separate threat model.
- Consumer-specific Entra tenant policies (MFA enforcement, conditional-access rules). These are tenant-admin configuration, not docforge code. Consumers document their tenant posture separately.
- Azure subscription governance (who has owner/contributor rights, break-glass accounts). Consumer-specific.
- Physical security of the Azure Postgres data.

## Review cadence

This threat model is reviewed on major docforge version changes, on changes to the deployment topology (`docforge/deploy/azure/main.bicep`), and at least annually. Reviews that surface new threats or change mitigations update this document and bump the date stamp below.

**Last reviewed:** 2026-04-21 (initial authoring alongside Spec C3 implementation).
