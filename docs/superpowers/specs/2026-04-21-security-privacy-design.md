# Spec C3 — Security + Privacy

**Date:** 2026-04-21
**Status:** Approved, ready for writing-plans handoff.
**Part of:** Phase 4 Spec C (hardening sprint) — sub-spec 3 of 4. Siblings: C1 (CI + supply-chain, shipped), C2 (quality harnesses, shipped), C4 (operational readiness, pending).
**Scope:** Ship end-to-end Entra ID authentication on `/search` + `/sources` (delegated-user flow, hard-enforced when `auth.mode == entra`), add `user_oid` to `query_log` as an additive migration, and publish two supporting documents (`docforge/docs/threat-model.md` + `knowledge-hub/rag/docs/log-privacy.md`). Closes the headline Security dimension gap identified in Spec D §5.
**Driven by:** Spec D §4 items **C3.1 – C3.5**.

## Context

docforge's `/search` endpoint is currently on the public internet with `external: true` ingress and no authentication. The `user_name` request field is self-declared: anyone with the FQDN can call the API claiming to be anyone. Spec D identifies this as the single largest security gap at L3 target and names Entra ID as the closing mechanism.

Five supporting decisions are locked by the Spec C3 brainstorm (see Q&A trail):

1. **Delegated-user flow only** (not app-identity). Every current caller is a human at a workstation (MCP client through Claude Code, eval harness run interactively).
2. **Hard enforcement** when `auth.mode == entra`; `/health` is the only unauthenticated endpoint (for Container Apps probes). No dev-bypass header.
3. **180-day `query_log` retention** with automated cleanup via `pg_cron` (fallback: app-level cleanup in FastAPI lifespan).
4. **Single threat-model doc in docforge** covering engine code + Bicep template; DocuWare-specific deployment context gets a short section appended to `knowledge-hub/rag/docs/deployment.md` (the Bicep template already lives in the docforge repo, so deployment topology *is* engine-side content).
5. **`auth.mode` in yml; `tenant_id` and `audience` in knowledge-hub's yml with env-var override.** Public identifiers, not secrets. pydantic-settings nested-delimiter pattern.

## Goals

1. Close the "public-internet `/search` with no auth" finding from Spec D §5.
2. Make `query_log` identity trustworthy post-cutover (Entra `oid` claim, not self-declared string).
3. Keep docforge generic: the auth backend is opt-in via config; engine default stays `auth.mode: none`.
4. Ship both supporting documents so the Spec D artifact can cite them at write time.

## Non-goals

- App-identity / service-principal auth (delegated-user-only for C3; future spec if needed).
- Dev-bypass header (rejected as security footgun; local dev uses `auth.mode: none` overlay).
- Rewriting `query_log` history (additive migration; pre-Entra rows keep `user_oid = NULL`).
- Separate consumer-specific threat-model doc (one doc in docforge + paragraph-level context in knowledge-hub `deployment.md`).
- Changes to eval-harness baseline, ranking logic, or `docforge search` CLI (CLI uses asyncpg directly; never traverses the API).

## Design principles

- **Opt-in auth.** Engine default `auth.mode: none`. Deployments opting into Entra install the optional extra (`pip install docforge[entra]`) and set `auth.mode: entra`. Keeps the engine lean for other consumers.
- **Hard enforcement when enabled.** `mode: entra` means every request to `/search` or `/sources` must carry a valid Entra JWT for the configured audience. No fallback, no bypass. One mode per deployment.
- **Additive migrations.** Pre-Entra `query_log` rows keep `user_oid = NULL` permanently. Reports that need trustworthy identity filter on `user_oid IS NOT NULL`. Never destroys history.
- **Engine / consumer split preserved.** Generic auth plumbing in docforge; DocuWare-specific values in knowledge-hub's `docforge.yml` + `docforge.bicepparam`.
- **Honest threat model.** Name what's accepted (bus factor, HF-gated model, 7-day backup window, prompt-injection via indexed content) rather than pretending mitigations cover it.

## Auth integration design

### Library choice

- **`fastapi-azure-auth`** for server-side JWT validation. Thin wrapper over `python-jose` with Entra OpenID discovery; the alternative is ~150 LoC of crypto we'd own. Accept the dep.
- **`azure-identity`** for client-side token acquisition via `DefaultAzureCredential`. Handles refresh transparently; picks up `az login` / VS Code signed-in / env-var credentials without the caller knowing which.
- Both added as an optional extra in `docforge/pyproject.toml`:
  ```toml
  [project.optional-dependencies]
  entra = ["fastapi-azure-auth>=5.0", "azure-identity>=1.19"]
  ```

### Configuration shape

New nested Pydantic model in `docforge/config.py`:

```python
class AuthSettings(BaseModel):
    mode: Literal["none", "entra"] = "none"
    tenant_id: str = ""       # required if mode == "entra"
    audience: str = ""        # required if mode == "entra"

class Settings(BaseSettings):
    # ... existing fields ...
    auth: AuthSettings = AuthSettings()
```

Loaded from `docforge.yml`:

```yaml
auth:
  mode: entra
  tenant_id: <DocuWare-tenant-guid>
  audience: api://<app-id>
```

Overridable by env (pydantic-settings nested-delimiter `__`):

```
DOCFORGE_AUTH__MODE=entra
DOCFORGE_AUTH__TENANT_ID=...
DOCFORGE_AUTH__AUDIENCE=...
```

Validation: if `mode == "entra"` and `tenant_id` or `audience` is empty, app fails fast at startup with a clear error message (not a 500 at first-request-time).

### Server-side integration (`docforge/api.py`)

Conditional registration of the Entra dependency at app construction:

```python
if settings.auth.mode == "entra":
    from fastapi_azure_auth import SingleTenantAzureAuthorizationCodeBearer

    azure_scheme = SingleTenantAzureAuthorizationCodeBearer(
        app_client_id=settings.auth.audience.removeprefix("api://"),
        tenant_id=settings.auth.tenant_id,
        scopes={f"{settings.auth.audience}/search": "Search docforge"},
    )
    app.add_event_handler("startup", azure_scheme.openid_config.load_config)
    auth_dep = Depends(azure_scheme)
else:
    auth_dep = None  # endpoints register without the dependency
```

Endpoint wiring:

- **`/health`** — no auth dependency; always open. Returns static JSON; no index access.
- **`/search`** — `Depends(azure_scheme)` when `mode == entra`, otherwise no dep.
- **`/sources`** — same as `/search`.

JWT claims passed to the handler:

```python
@app.post("/search", response_model=SearchResponse)
async def search(req: SearchRequest, user=auth_dep) -> SearchResponse:
    ...
    token_user_name = user.preferred_username if user else req.user_name
    token_oid = user.oid if user else None
    await log_query(
        pool, token_user_name, req.team_name, req.area_name,
        req.query, len(rows), user_oid=token_oid,
    )
```

Key design decision: `req.user_name` is **ignored for identity** when a JWT is present. `query_log.user_name` comes from the JWT's `preferred_username`; `user_oid` from `oid`. `req.team_name` and `req.area_name` stay client-supplied (routing hints, not identity).

### Client-side integration

**MCP client** (`knowledge-hub/rag/mcp_client.py`):

```python
from azure.identity.aio import DefaultAzureCredential

_credential = DefaultAzureCredential()
_scope = os.environ["KNOWLEDGE_HUB_AUDIENCE"] + "/.default"

async def _auth_header() -> dict[str, str]:
    token = await _credential.get_token(_scope)
    return {"Authorization": f"Bearer {token.token}"}

@mcp.tool()
async def search_documentation(query: str, limit: int = 5) -> str:
    headers = await _auth_header()
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(f"{API_URL}/search", headers=headers, json={...})
    ...
```

New required env var: `KNOWLEDGE_HUB_AUDIENCE` (documented in team-setup).

**Eval harness** (`docforge/scripts/eval_search.py`): same pattern. New required CLI flag `--audience api://<app-id>` when targeting an Entra-protected endpoint.

**`docforge search` CLI**: unchanged. Uses asyncpg directly; never traverses the API; no auth concerns.

### Bicep changes (`docforge/deploy/azure/main.bicep`)

Three new parameters:

```bicep
param authMode string = 'none'
param authTenantId string = ''
param authAudience string = ''
```

Three new env vars on the container app template:

```bicep
{ name: 'DOCFORGE_AUTH__MODE', value: authMode }
{ name: 'DOCFORGE_AUTH__TENANT_ID', value: authTenantId }
{ name: 'DOCFORGE_AUTH__AUDIENCE', value: authAudience }
```

`knowledge-hub/rag/infrastructure/docforge.bicepparam` populates the DocuWare-specific values.

### Failure modes

| Scenario | Result |
|---|---|
| Missing `Authorization` header | 401 (fastapi-azure-auth default) |
| Invalid JWT signature | 401 |
| Wrong audience | 401 |
| Wrong tenant | 401 |
| Expired token | 401; client `DefaultAzureCredential` auto-refreshes on next call |
| `mode == entra` but `tenant_id`/`audience` empty | App fails at startup with settings-validation error |
| Entra unreachable at startup (`openid_config.load_config` fails) | fastapi-azure-auth retries; app starts but first requests 503 until config loads. Documented in C4.1 runbook |

### What does NOT change

- Eval-harness baseline (retrieval logic untouched; same queries → same results).
- Ranking logic, tag weights, HNSW index parameters.
- `docforge search`, `docforge ingest`, `docforge init-db`, `docforge init`, `docforge status`, `docforge lint-docs` (none traverse the API).
- `/health` behavior — probes continue working unauthenticated.
- `list_sources` as an MCP tool — still works; now requires the client to be authenticated.

## `threat-model.md` outline

Single doc at `docforge/docs/threat-model.md`, ~3 pages rendered. Covers engine code + Bicep template threats. DocuWare-specific deployment context gets a short section appended to `knowledge-hub/rag/docs/deployment.md`.

### Section breakdown

1. **Purpose and scope** (~¼ page). What this doc is (threat model for docforge code + reference Bicep); what it is not (a consumer's Azure-subscription threat model). Reader: someone evaluating docforge for adoption, or a DocuWare engineer reviewing the deployed system.

2. **Trust model** (~½ page). Single-company, single-tenant. Indexed content is non-sensitive corporate documentation. `query_log` is the only semi-sensitive datum. Authenticated users are trusted (access control; no authorization layer beyond). The operator is trusted.

3. **Assets** (~¼ page, small table). Indexed docs · `query_log` rows · HF API token · Confluence API token · DB connection string · container image. Each gets a sensitivity label.

4. **Threat surfaces + mitigations** (~1 page, table). Public HTTPS endpoints · `/health` open endpoint · FastAPI app code · MCP client · ingest pipeline · Azure Key Vault · Postgres Flexible Server · container image · dependency CVEs. Each row: surface · threats considered · mitigations shipped (cite files/commits).

5. **Risks accepted** (~¼ page). Bus-factor-1 · HF-gated embedding model · DB backup window = 7 days · prompt-injection via indexed content · no per-source ACLs. Named plainly with rationale.

6. **Out of scope** (~¼ page). Multi-tenant isolation · DocuWare-specific Entra tenant policies · Azure subscription governance · physical security.

7. **Review cadence** (~⅛ page). Review on major version changes, deployment-topology changes, and at least annually.

### Writing rules

- Concrete threats, not categories. "Credential stuffing against self-declared `user_name`" — specific. "Weak authentication" — banned.
- Every mitigation cites a file or commit (traceable).
- Don't invent threats that don't apply (no SSRF section if app doesn't fetch user-supplied URLs; no XXE section if no XML parsing).

### DocuWare-context appendix in `knowledge-hub/rag/docs/deployment.md`

A new section titled **"DocuWare deployment context for threat modelling"** listing: Azure subscription name + owner-level access · resource group · Entra tenant · relevant tenant-level policies (MFA, conditional access) · runtime Key Vault · who can merge to each repo's master · backup retention override if changed.

## `log-privacy.md` outline + migration

Single doc at `knowledge-hub/rag/docs/log-privacy.md`, ~2 pages rendered. DocuWare-specific (retention windows and access rules are DocuWare policy calls).

### Section breakdown

1. **Purpose and scope** (~⅛ page). What `query_log` is; what this doc defines (retention, access, aggregation, purpose-of-use); who it applies to.

2. **What `query_log` contains** (~⅓ page, schema table). Columns · types · source · sensitivity. Defines "semi-sensitive" as internal-to-DocuWare-only; not exported in aggregate that would re-identify individuals.

3. **Retention** (~¼ page). 180 days rolling. Cleanup via `pg_cron`: `DELETE FROM query_log WHERE created_at < now() - interval '180 days'` daily at 02:00 UTC. Rationale: operational window for multi-quarter adoption trends; not longer because single-team scope doesn't need YoY comparisons; not shorter because adoption signals emerge over multi-sprint cycles. Pre-Entra rows subject to the same 180-day retention.

4. **Access** (~¼ page). Read: Tobias via admin DB connection. Write: only the FastAPI app. Audit: Key Vault logs + Postgres connection logs, review-on-incident.

5. **Aggregation + reporting** (~¼ page). Reports aggregate by team/area/month. Minimum cell size: 3 distinct users (anti-reidentification). Raw query strings never in aggregate reports. Example queries in appendix.

6. **Purpose limitation** (~⅛ page). Used for operational debugging, adoption evidence, Spec D metrics. Not used for individual performance evaluation or user-level profiling.

7. **Deletion on request** (~⅛ page). Any DocuWare engineer can request deletion of their rows by OID; email-to-maintainer path; 5 business day SLA.

8. **GDPR posture** (~⅛ page). Data controller: DocuWare. Lawful basis: legitimate interests (internal operational telemetry). Subjects: DocuWare engineers using the MCP client. Data stays in West Europe. References DocuWare's GDPR framework as the umbrella.

9. **Appendix — example queries** (~¼ page). "Distinct users in last 30 days" (with ≥3-user guard). "Teams that have adopted" (aggregated). "Find a user's history for deletion" (by OID or `user_name`).

### `query_log` migration (C3.5)

Migration file: `docforge/sql/migrations/005_add_query_log_user_oid.sql`

```sql
ALTER TABLE query_log ADD COLUMN user_oid TEXT;
CREATE INDEX IF NOT EXISTS query_log_user_oid_idx ON query_log (user_oid);
```

**No backfill.** Pre-Entra rows keep `user_oid = NULL` permanently — no trustworthy OID to fill. Reports requiring cryptographic identity filter `WHERE user_oid IS NOT NULL`.

`query_log.py`: `log_query()` gains an optional `user_oid: str | None = None` parameter. Callers pass the OID from the JWT when `auth.mode == entra`; otherwise `None`.

**Cutover date** captured in `log-privacy.md` §3 at write time. Reports spanning the cutover either filter to post-cutover data or annotate the cutover in narrative.

### `pg_cron` enablement

`pg_cron` is enabled on Azure Postgres Flexible Server by adding it to the `azure.extensions` server parameter (Bicep update or portal). Acceptance criterion: extension enabled before scheduling the cleanup job.

**Fallback** (if `pg_cron` unavailable, unexpected): app-level cleanup called hourly from FastAPI's lifespan. Documented in `log-privacy.md` §3 as the alternate mechanism.

## File summary

| Path | Status | Purpose | Approx LoC / length |
|---|---|---|---|
| `docforge/docforge/config.py` | MODIFY | Nested `AuthSettings` model | +~15 |
| `docforge/docforge/api.py` | MODIFY | Conditional `fastapi-azure-auth`; `/health` open; `/search`+`/sources` gated; pass JWT claims into `log_query` | +~40 |
| `docforge/docforge/query_log.py` | MODIFY | Accept optional `user_oid` | +~5 |
| `docforge/docforge/sql/migrations/005_add_query_log_user_oid.sql` | NEW | Additive migration | ~3 |
| `docforge/pyproject.toml` | MODIFY | `[project.optional-dependencies] entra = ...` | +~4 |
| `docforge/deploy/azure/main.bicep` | MODIFY | 3 params + 3 env vars + `pg_cron` in `azure.extensions` | +~25 |
| `docforge/tests/unit/test_auth.py` | NEW | Mock-JWT validation; `mode=none` path; `mode=entra` path | ~120 |
| `docforge/tests/unit/test_api.py` | MODIFY | Auth-enabled + auth-disabled paths | +~40 |
| `docforge/docs/threat-model.md` | NEW | Per outline above | ~3 pages / ~400 lines |
| `knowledge-hub/rag/mcp_client.py` | MODIFY | `DefaultAzureCredential` + auth header | +~15 |
| `knowledge-hub/rag/infrastructure/docforge.bicepparam` | MODIFY | Populate `authMode`/`authTenantId`/`authAudience` | +~3 |
| `knowledge-hub/rag/docforge.yml` | MODIFY | Set `auth.mode: entra` + tenant_id + audience | +~4 |
| `knowledge-hub/rag/docs/deployment.md` | MODIFY | Append "DocuWare deployment context for threat modelling" | +~30 |
| `knowledge-hub/rag/docs/log-privacy.md` | NEW | Per outline above | ~2 pages / ~300 lines |
| `knowledge-hub/rag/docs/team-setup-azure.md` | MODIFY | `az login` step; correct stale "scales to zero" | +~20 |
| `knowledge-hub/rag/docs/team-setup.md` | MODIFY | Same as team-setup-azure.md | +~20 |
| `docforge/scripts/eval_search.py` | MODIFY | `DefaultAzureCredential` + `--audience` flag | +~25 |
| `docforge/scripts/README.md` | MODIFY | Document `--audience` + `az login` prereq | +~10 |

**Totals:** 4 new files + 13 modifications across both repos; ~1000 LoC/docs including tests.

## Success criteria

- [ ] `docforge[entra]` extra pulls in `fastapi-azure-auth` + `azure-identity`; plain `docforge` install does not.
- [ ] With `auth.mode=none` (default), `/search` and `/sources` accept unauthenticated requests (backward-compatible for local dev).
- [ ] With `auth.mode=entra`, `/search` and `/sources` return 401 on missing/invalid/expired/wrong-audience/wrong-tenant JWT.
- [ ] With `auth.mode=entra`, `/health` accepts unauthenticated requests (probes work).
- [ ] App fails fast at startup if `auth.mode=entra` and `tenant_id`/`audience` are empty.
- [ ] `query_log` has `user_oid TEXT NULL` column; pre-Entra rows NULL; post-Entra rows populated from JWT `oid`.
- [ ] `log_query()` accepts `user_oid` and writes it.
- [ ] MCP client + eval harness authenticate against Entra; live end-to-end query from Claude Code returns results.
- [ ] Azure deployment updated: new env vars flow from `docforge.bicepparam` through `main.bicep` to container.
- [ ] `pg_cron` extension enabled; scheduled cleanup job deletes rows older than 180 days (verified with a dated-past-180d test row).
- [ ] `docforge/docs/threat-model.md` committed per outline; all table entries populated; banned-vague-terms audit passes.
- [ ] `knowledge-hub/rag/docs/log-privacy.md` committed per outline.
- [ ] `knowledge-hub/rag/docs/deployment.md` DocuWare-context section populated with real names.
- [ ] Team-setup docs updated: `az login` step added; stale "scales to zero" paragraph corrected.
- [ ] Full unit suite passes; coverage gate ≥60% preserved (projected ~76–80% after additions).
- [ ] Eval-harness baseline reproduces (recall@1 40%, recall@5 76%, MRR 0.533) with the harness running authenticated — verifies auth doesn't regress retrieval.
- [ ] CI green on both repos.

## Risks

- **R1 — `fastapi-azure-auth` behavior surprises.** Library is Entra-specific but well-trodden. Mitigation: implement C3.2 (app registration) first so we have a real tenant to test against; auth is flagged behind `auth.mode` so existing local dev is unbroken; PR lands against master only after end-to-end manual test.
- **R2 — `DefaultAzureCredential` picks up the wrong identity.** E.g., az CLI signed into a personal account rather than DocuWare's tenant. Symptom: 401 from `/search`. Mitigation: team-setup docs explicitly say `az login --tenant <DocuWare-tenant-id>`; the 401 error surfaces in the MCP client response with actionable text.
- **R3 — `pg_cron` not available on Flexible Server.** Low probability; officially supported. Mitigation: fallback to app-level cleanup in FastAPI lifespan, documented in `log-privacy.md` §3.
- **R4 — Token-acquisition latency.** First `DefaultAzureCredential.get_token()` may take 100–500 ms. Subsequent calls use cached tokens. Mitigation: library handles caching; flag for observation once C4.3 timing middleware lands.
- **R5 — Entra app registration misconfigured.** Wrong scope name, wrong redirect URL, wrong audience. Symptom: 401 everywhere. Mitigation: C3.2 has explicit acceptance criteria; test against a throwaway user before team rollout.
- **R6 — `preferred_username` collisions.** If two engineers share a `preferred_username` somehow, `query_log.user_name` is ambiguous. Mitigation: `user_oid` is the canonical identity post-Entra; reports use OID, not `user_name`.
- **R7 — Spec D baseline re-run mid-C3.5.** Running eval harness between the migration and the Entra cutover could yield inconsistent `user_oid` fill. Mitigation: sequence in the C3 plan — migration runs before first authenticated live query; document in plan handoff.

## Follow-up items (tracked, not in C3)

- **App-identity auth flow** for un-attended callers (CI-run eval, batch jobs). Slots in as a future spec if the need materialises.
- **Per-source ACLs.** Out of scope per trust model. Future work if docforge adopts multi-tenant use cases.
- **MFA enforcement via conditional access.** Tenant-admin setting, not docforge code. Residual knob documented in DocuWare deployment context.
- **`team_name` / `area_name` trustworthiness.** Still self-declared post-C3. Threat model accepts this explicitly (routing hints, not identity).

## Out of scope (deferred, explicitly)

- Moving `tenant_id` + `audience` into Key Vault — they are public identifiers, not secrets.
- Adding query-text redaction or hashing in `query_log` — operational debugging requires raw queries; 180-day retention + access controls are the privacy mechanism.
- Rate limiting `/search` — Container Apps provides default ingress limits; custom rate limits are future work once C4.3 latency data shows whether they are needed.
