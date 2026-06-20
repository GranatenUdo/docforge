---
title: Deploy to Azure
description: Hosting docforge for team-wide use via Azure Container Apps and Postgres Flexible Server.
---

For a single developer, `docforge serve` on stdio is enough — Claude Code or Cursor spawns the process. For team use, you want a hosted HTTP API so every teammate's assistant can hit the same index.

## Target architecture

Eight Azure resources in one resource group. The template defaults to cheap Consumption/CPU with scale-to-zero (a few dollars/month); a production deployment that keeps the Qwen3-Embedding-4B embedder and the cross-encoder reranker warm on Tesla-T4 GPUs runs ~$930/month per always-warm T4 (≈ €860; ~$1,860 for both — approximate, verify in Azure):

- **Postgres Flexible Server** (Burstable B1ms, 32 GB) with `pgvector` enabled at provisioning time.
- **Container App** running `docforge serve --api` with Entra ID authentication enabled (1 vCPU / 2 GiB).
- **Container App: embedder** running the Qwen3-Embedding-4B model on a GPU workload profile (NC8as_T4). The search API delegates embedding to this service via `EMBEDDER_URL`, keeping the API replicas small and fast to start.
- **Container App: reranker** running the BAAI/bge-reranker-v2-m3 cross-encoder (built from `Dockerfile.reranker`) on a GPU workload profile (NC8as_T4). Off by default; the search API re-scores the top hybrid candidates through it only when both `RERANK_ENABLED=true` and `RERANKER_URL` are set.
- **Container Registry** (Standard — required for the ~13.6 GB embedder image; ACR Basic's 10 GB quota is too small).
- **Key Vault** (Standard) holding `CONFLUENCE_API_TOKEN`, `HF_TOKEN`, and database credentials.
- **Log Analytics workspace** (30-day retention) for Container App logs.
- **Container Apps managed environment** (Consumption plan).

Teammates use a lightweight MCP client that shells out to the hosted API.

## Steps

### 1. Provision

Bicep templates under [`deploy/azure/`](https://github.com/GranatenUdo/docforge/tree/master/deploy/azure) in the repo cover:

- Postgres Flexible Server with `pgvector` installed at provisioning time.
- Container App environment with 1 always-on search-api replica (cold-start ~30 s for container spin-up; the search API no longer loads the model in-process since the v0.3 Phase 4b embedder split). The GPU-backed Qwen3-Embedding-4B embedder runs with `minReplicas: 1` — the ~10 GB model loads into VRAM in 2-3 minutes (Qwen-4B on T4 GPU); always-on avoids this cold start in production.
- Managed identity for pulling from Key Vault.

### 2. Configure authentication

Set `auth.mode: entra` in `docforge.yml` and provide `AZURE_TENANT_ID` + `AZURE_CLIENT_ID` via environment. The FastAPI app validates JWTs against your tenant's OpenID config and logs the authenticated `user_oid` to `query_log`.

See [threat-model.md](https://github.com/GranatenUdo/docforge/blob/master/docs/threat-model.md) in the repo for the full trust model (single-tenant, single-company, authenticated users trusted).

### 3. Ingest

Run `docforge ingest` from anywhere that can reach the database (a jump box, GitHub Actions runner, or the container itself). Ingest is idempotent — safe to schedule on cron.

### 4. Observability

- Query telemetry: the `query_log` table records every search (user_oid, query, request_ms, timestamp). Retention defaults to 180 days; a cleanup loop inside the API deletes rows older than that.
- Latency: `python -m docforge.scripts.latency_report --since '7 days'` prints P50/P95/P99 from `query_log.request_ms`.
- Health: `GET /health` is unauthenticated and DB-independent; wire it to the Container App liveness probe.

## Operating notes

- **Cold-start window.** Search-api with `minReplicas=1` avoids container cold-starts in steady state; post-deployment the first request pays a ~30 s container spin-up cost (no model load — that responsibility moved to the embedder in Phase 4b). The GPU-backed Qwen3-Embedding-4B embedder loads the ~10 GB model into VRAM in 2-3 minutes (Qwen-4B on T4 GPU); run with `minReplicas: 1` to keep the embedder warm. All cold-start latency is included in P95 as honest signal.
- **Orphan pruning.** When you remove a source from `sources.yml`, run `docforge ingest --purge-orphans` (dry-run) and then `--confirm` to delete. No auto-purge.
- **Backups.** Postgres Flexible Server Standard_B1ms gets 7-day PITR by default. Test the restore procedure annually:
  ```bash
  az postgres flexible-server restore \
    --resource-group <rg> \
    --name <new-server-name> \
    --source-server <source-server-name> \
    --restore-time '<ISO-8601 timestamp within last 7 days>'
  ```
  The restore creates a new server; the source is untouched. After verifying the restore, drop the new server.
