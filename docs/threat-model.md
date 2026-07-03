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
| Embedder bearer token (`embedder-token`) | Azure Key Vault | Secret (shared with reranker; see threat surface) |
| Confluence API token | Azure Key Vault | Secret |
| DB connection string | Azure Key Vault | Secret |
| HuggingFace token (`hf-token`) | Azure Key Vault | Secret (empty by default — Qwen3-Embedding-4B is ungated; only populated when swapping to a gated embedding model) |
| Embedder GPU Container App (Qwen3-Embedding-4B) | Azure Container Apps (external ingress by default, GPU `gpu-nc8as-t4`) | Internal service (bearer-authed HTTPS endpoint) |
| Reranker GPU Container App (BAAI/bge-reranker-v2-m3) | Azure Container Apps (external ingress by default; can be made internal-only via `rerankerIngressExternal=false`, GPU `gpu-nc8as-t4`) | Internal service (bearer-authed HTTPS endpoint; off the public internet when internal) |
| Container image | Azure Container Registry | Non-secret (distribution-controlled) |

## Threat surfaces and mitigations

| Surface | Threats considered | Mitigations shipped |
|---|---|---|
| Public HTTPS `/search` + `/sources` | Unauthenticated query; credential stuffing against self-declared `user_name`; enumeration of indexed content; **dropped/mis-set auth mode silently serving an unauthenticated surface** | When `auth.mode == entra`: Entra ID delegated auth required on both endpoints (`docforge/api.py`, `_auth_dependency`). `user_oid` from the JWT replaces the self-declared `user_name` in `query_log` (migration `005_add_query_log_user_oid.sql`). **Fail-closed guard (`auth.require`/`AUTH__REQUIRE=true`, since v0.7.19): the app refuses to start unless `auth.mode == entra`, so a dropped/mis-set `AUTH__MODE` crash-loops loudly instead of silently exposing `/search` + `/sources`** (enforced in `AuthSettings`'s validator, at `Settings()` construction). Only `/health` is unauthenticated and returns no index content |
| API docs routes (`/docs`, `/redoc`, `/openapi.json`) | Public advertisement of the full API surface / schema to unauthenticated callers | Disabled in prod via `expose_docs`/`EXPOSE_DOCS=false` (since v0.7.19) — the routes return 404 on all three apps (search-api + both sidecars). Engine default is exposed (OSS/dev); hardened deployments set it false |
| `/health` open endpoint | Endpoint fingerprinting; DoS amplification | Returns static JSON (`{"status": "ok", ...}`); no DB access; Container Apps default ingress rate limits apply |
| FastAPI app code | JWT validation bypass; injection in query text | `fastapi-azure-auth` validates JWTs against Entra OpenID configuration loaded at startup; query text is parameterised via asyncpg bind params; no SQL string concatenation anywhere in the query path |
| MCP client (operator-deployed) | Token exfiltration; stale token reuse | `DefaultAzureCredential` holds tokens in-memory only; token refresh is library-handled; no token logging anywhere in client code |
| Embedder GPU Container App (`/embed`, `/health`) | Unauthenticated embedding requests; GPU resource abuse; public network exposure | Static bearer token required on `/embed` (`embedder-token` Key Vault secret, passed as `EMBEDDER_TOKEN`) — the primary control; `/health` returns static JSON with no model invocation; Container Apps default ingress rate limits apply. The embedder must stay **externally** ingressed (the ingest pipeline reaches it from outside the environment), so it retains a public endpoint. An ingress IP allow-list (`embedderAllowedIps`) is available but **cannot admit the intra-environment search-api caller** — the intra-env hop presents an ingress source IP that isn't reliably allow-listable, so a public-internet-denying allow-list also blocks `/search` (verified 2026-07-03). Token-gating is therefore the control; to remove the public endpoint the embedder would need internal-only ingress plus a reworked ingest path |
| Reranker GPU Container App (`/rerank`, `/health`) | Unauthenticated rerank requests; GPU resource abuse; shared-token blast radius; public network exposure | Static bearer token required on `/rerank`, supplied via `RERANKER_TOKEN` which REUSES the embedder's `embedder-token` Key Vault secret (shared-token blast radius; see risks accepted). Since v0.7.19 the reranker can be **internal-only** (`rerankerIngressExternal=false`): the search-api reaches it via its `.internal.` FQDN (`RERANKER_URL` auto-derived), so it has **no public endpoint** — the recommended hardened posture, since only the intra-env search-api calls it. `/health` returns static JSON with no model invocation |
| Ingest pipeline | Poisoned Confluence or git content injecting prompt-injection payloads that manipulate downstream LLM consumers | Out of scope for this iteration — documented as residual risk below |
| Azure Key Vault | Secret exfiltration via misconfigured RBAC | System-assigned managed identity granted `get-secret` only; no human accounts granted secret access by the Bicep template; secret references resolved at container boot only |
| Azure Postgres Flexible Server | DB compromise via connection-string leak | Connection string held in Key Vault, retrieved only at container boot; container runs as UID 1000 with no write access to files containing the connection string |
| Container image | Supply-chain attack via base image or Python deps | Dependabot runs weekly (`.github/dependabot.yml`); base image pinned to `python:3.12-slim-bookworm`; `pyproject.toml` version floors prevent downgrade to known-vulnerable releases |
| Dependency CVEs | Known vulnerabilities in runtime dependencies | Dependabot opens PRs on CVE disclosure; all merges go through branch protection requiring CI green |

## Risks accepted

- **Bus factor of 1.** Single maintainer. Represents a loss-of-availability risk, not a loss-of-confidentiality risk. Named plainly; mitigation requires onboarding a second maintainer, outside the scope of this threat model.
- **Shared bearer token across GPU sidecars.** The reranker reuses the embedder's `embedder-token` Key Vault secret (`RERANKER_TOKEN` == `EMBEDDER_TOKEN`). A single leaked token therefore grants access to both the embedder `/embed` and reranker `/rerank` GPU endpoints; the blast radius spans both Container Apps. Accepted because both endpoints serve the same trusted search-api caller, hold no indexed content, and rotating one secret rotates both. Split the secrets if either endpoint gains a distinct trust boundary.
- **DB backup window = 7 days.** Azure Postgres Flexible Server `Standard_B1ms` (Burstable tier) default retention. Data older than 7 days cannot be restored via point-in-time recovery. Accepted as cost-appropriate for current scale; raise `backupRetentionDays` in Bicep if SLA requirements change.
- **Prompt-injection via indexed content.** Malicious content in an indexed Confluence page or README could attempt to manipulate the LLM that consumes search results. Mitigation is operational (source-review discipline by the owning team), not code-level in this iteration. Tracked as future work if docforge begins indexing content with lower provenance assurance.
- **No per-source ACLs.** Any authenticated user can query any indexed source. Appropriate for a single-company tool with org-classified content; not a multi-tenant assumption.
- **Self-declared `team_name` and `area_name`.** Even after Entra auth lands, `team_name` and `area_name` remain client-supplied fields in the search request — they are routing hints for relevance boosting, not identity. A caller can set any team/area. The relevance boost gives no access beyond what every authenticated user already has.

## Out of scope

- Multi-tenant isolation. docforge is single-tenant by design; multi-tenant support would require a separate threat model.
- Consumer-specific Entra tenant policies (MFA enforcement, conditional-access rules). These are tenant-admin configuration, not docforge code. Consumers document their tenant posture separately.
- Azure subscription governance (who has owner/contributor rights, break-glass accounts). Consumer-specific.
- Physical security of the Azure Postgres data.

## `--remote-api` mode

The engine in `--remote-api` mode is a thin HTTP proxy: it forwards request bodies and Authorization headers to the remote API and returns Markdown-formatted responses. It does NOT enforce auth itself. Trust boundaries:

- The deployed API enforces auth (e.g., via fastapi-azure-auth in `[entra]` mode) and decides who is authorized.
- With `--auth azure`, the engine sends a Bearer token minted by `DefaultAzureCredential`. The API validates the JWT and binds `user_name` to `preferred_username` server-side. The engineer cannot override `user_name` via env var.
- With `--auth bearer` or `--auth none`, there is no auth subject. The body's `user_name` (from `DOCFORGE_USER` env) is used as-is or defaults to `"anonymous"`. Deployments using these modes should not rely on `user_name` for any security-sensitive decision.

## Review cadence

This threat model is reviewed on major docforge version changes, on changes to the deployment topology (`docforge/deploy/azure/main.bicep`), and at least annually. Reviews that surface new threats or change mitigations update this document and bump the date stamp below.

**Last reviewed:** 2026-07-03 (v0.7.19 API security hardening: added the `AUTH__REQUIRE` fail-closed startup guard, the `EXPOSE_DOCS` docs-disable control + a threat surface for the API docs routes, and internal-only reranker ingress via `rerankerIngressExternal`; documented that the embedder must stay external for ingest and why an ingress IP allow-list can't secure it. Prior: 2026-06-19 — added embedder + reranker GPU Container App assets/surfaces; engine 0.7.16, reranker 0.3.0).
