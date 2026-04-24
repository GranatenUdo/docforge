---
title: Deploy to Azure
description: Hosting docforge for team-wide use via Azure Container Apps and Postgres Flexible Server.
---

For a single developer, `docforge serve` on stdio is enough — Claude Code or Cursor spawns the process. For team use, you want a hosted HTTP API so every teammate's assistant can hit the same index.

## Target architecture

Six Azure resources in one resource group (~$35/month at default SKUs in West Europe):

- **Postgres Flexible Server** (Burstable B1ms, 32 GB) with `pgvector` enabled at provisioning time.
- **Container App** running `docforge serve --api` with Entra ID authentication enabled.
- **Container Registry** (Basic) hosting the docforge Docker image.
- **Key Vault** (Standard) holding `CONFLUENCE_API_TOKEN`, `HF_TOKEN`, and database credentials.
- **Log Analytics workspace** (30-day retention) for Container App logs.
- **Container Apps managed environment** (Consumption plan).

Teammates use a lightweight MCP client that shells out to the hosted API.

## Steps

### 1. Provision

Bicep templates under [`deploy/azure/`](https://github.com/GranatenUdo/docforge/tree/master/deploy/azure) in the repo cover:

- Postgres Flexible Server with `pgvector` installed at provisioning time.
- Container App environment with 1 always-on replica (warm-up is ~15–30 s for model load on cold starts).
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

- **Cold-start window.** Container App with minReplicas=1 avoids cold starts in steady state, but post-deployment the first request pays a 15–30 s model-load cost. That's included in P95 as honest signal.
- **Orphan pruning.** When you remove a source from `sources.yml`, run `docforge ingest --purge-orphans` (dry-run) and then `--confirm` to delete. No auto-purge.
- **Backups.** Postgres Flexible Server Standard_B1ms gets 7-day PITR by default. Test the restore procedure annually — the [runbook](https://github.com/GranatenUdo/docforge/blob/master/docs/superpowers/specs/2026-04-22-operational-readiness-design.md) has the exact `az postgres flexible-server restore` incantation.
