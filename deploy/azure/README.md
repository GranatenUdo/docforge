# docforge on Azure

Bicep template to deploy docforge as a hosted service on Azure Container Apps, backed by Azure Database for PostgreSQL (with pgvector) and Azure Container Registry.

## What gets deployed

Eight resources in a single resource group. Cost depends on the workload
profile (see [Cost](#cost) below): the template **defaults** both GPU-capable
sidecars to the cheap Consumption (CPU) profile, with the reranker scaled to
zero and reranking off — a few dollars/month. **Production** deployments set the
`gpu-nc8as-t4` Tesla-T4 profile and keep replicas warm, which is roughly
~$1,900/month all-in for one warm embedder + one warm reranker — the two
always-warm GPU sidecars are ~$1,860 of that (1 embedder + 1 reranker at ~$930
each) and the rest is Postgres/ACR/Key Vault/logs; it is only a rough estimate.
A deployment that scales the embedder to multiple warm replicas (as the DocuWare
CCL config does, at `embedderMinReplicas=2`) costs one warm T4 more per extra
replica (see Cost; the serverless-GPU meter is not in the Azure pricing
calculator, so
verify against Azure Cost Management).

| Resource | Purpose | Default SKU (template) |
|---|---|---|
| Key Vault | Runtime secrets (`hf-token`, `confluence-api-token`, `database-url`, `embedder-token`) | Standard |
| Container Registry | Hosts the docforge Docker image, the embedder image, **and** the reranker image | Standard (NOT Basic — embedder image exceeds Basic's 10 GB quota) |
| Postgres Flexible Server | Vector store + metadata, pgvector extension enabled | Burstable B1ms, 32 GB |
| Log Analytics workspace | Container App logs | PerGB2018, 30-day retention |
| Container Apps managed environment | Compute host for all container apps; optional `gpu-nc8as-t4` GPU profile for the sidecars (when `enableWorkloadProfiles=true` AND `enableGpuProfile=true`) | Consumption plan |
| Container App: search-api | Runs `docforge serve --api`; `minReplicas=1` by default | 1 CPU, 2 GiB |
| Container App: embedder | Runs the Qwen3-Embedding-4B sidecar; `embedderMinReplicas=0` by default (scale-to-zero) | Consumption (2 CPU, 4 GiB) by default; set `gpu-nc8as-t4` (1 T4) for production — Qwen3-4B is impractically slow on CPU |
| Container App: reranker | Runs the BAAI/bge-reranker-v2-m3 cross-encoder sidecar; **off by default** (`rerankEnabled='false'`, `rerankerUrl` unset), `minReplicas=0` | Consumption by default; for production set `gpu-nc8as-t4` (1 T4) + `minReplicas=1` and turn reranking on with BOTH `rerankEnabled='true'` and `rerankerUrl` |

The split into separate Container Apps is the v0.3 Phase 4b architecture: the
embedder service hosts the model and exposes a `POST /embed` endpoint; the
search API and ingest workers call into it via `EMBEDDER_URL` instead of
loading the model in-process. Search API replicas drop from ~2 GB RSS to
~400 MB and cold-start in ~30s (just container spin-up; no model load).
The embedder runs Qwen3-Embedding-4B (Apache-2.0, ungated). The template
defaults it to the Consumption (CPU) profile and `embedderMinReplicas=0`
(scale-to-zero); production sets the `gpu-nc8as-t4` Tesla-T4 profile (the 4B
model is impractically slow on CPU) and `embedderMinReplicas=1` to keep the
model warm. The model weights are baked into the image (`Dockerfile.embedder`),
so there is no runtime download on cold start.

Since engine 0.7.16 a third Container App, the **reranker**, can complete the
retrieval pipeline. The hybrid pool (dense pgvector + sparse BM25 + RRF + tag
boost) produces candidates, then the reranker cross-encoder re-scores the top
`rerank_top_n` (default 50) of them. The template ships it **off** (reranking
turns on only when BOTH `rerankEnabled='true'` and `rerankerUrl` are set; the
template defaults `rerankEnabled='false'` and `rerankerUrl=''`) and scaled to
zero on the Consumption profile; production runs it as its own GPU sidecar (built
from `Dockerfile.reranker`) on the `gpu-nc8as-t4` Tesla-T4 profile, kept warm at
`minReplicas=1`, with both `rerankEnabled='true'` and `rerankerUrl` set to turn
reranking on. See the
Reranker service section below.

Both Container Apps use a system-assigned managed identity with:
- **Key Vault Secrets User** on the Key Vault — reads secrets at runtime via identity, no connection strings stored in env vars.
- **AcrPull** on the Container Registry — pulls images without admin credentials.

No admin credentials are stored anywhere except Key Vault.

## Embedder service (v0.3 Phase 4b)

The embedder is a separate Container App that hosts the Qwen3-Embedding-4B
model (Apache-2.0, ungated) on a Tesla-T4 GPU and exposes a `POST /embed`
endpoint protected by a shared-secret bearer token. The search API, MCP
server, and ingest worker call this endpoint instead of loading the model
in-process.

**Image build.** A separate `Dockerfile.embedder` at the repo root builds
the embedder image. The Qwen3-Embedding-4B model is ungated (Apache-2.0), so
it is baked in at build time with a plain layer download — no HuggingFace
token or BuildKit secret mount is required:

```bash
docker build \
  -f Dockerfile.embedder \
  -t docforge-embedder:latest .
```

**Using a gated embedding model instead?** `Dockerfile.embedder` reads the
token from a BuildKit secret mount (`--mount=type=secret,id=hf_token`), so the
token never lands in an image layer. The default Qwen3-Embedding-4B needs none
of this; but if you swap in a gated model, export the token and pass the secret
flag at build time, and pass `hfToken=...` at deploy:

```bash
export HF_TOKEN="hf_..."   # ($env:HF_TOKEN / set HF_TOKEN on Windows)
docker build \
  -f Dockerfile.embedder \
  --secret id=hf_token,env=HF_TOKEN \
  -t docforge-embedder:latest .
```

The Bicep template still provisions the `hf-token` Key Vault secret and wires
`HF_TOKEN` into the search-api; it is simply empty by default since the default
embedder is ungated.

**ACR SKU note.** The baked-in model makes the embedder image ~13.6 GB. Azure
Container Registry Basic has a 10 GB storage quota, which means **the
default ACR SKU must be Standard or Premium for this deployment.** The
Bicep parameter `acrSku` defaults to `Standard`. If you previously
provisioned with Basic, you can upgrade in place: `az acr update --name
<acr> --sku Standard`.

**Shared-secret auth.** The search API authenticates to the embedder via a
bearer token (`EMBEDDER_TOKEN`). Generate at deploy time using whichever is
available on your machine:

```bash
openssl rand -hex 32                                              # Linux/macOS
python -c "import secrets; print(secrets.token_hex(32))"          # cross-platform
[Convert]::ToHexString((1..32 | %{[byte](Get-Random -Max 256)}))  # PowerShell
```

Pass the value as a Bicep parameter (`embedderToken=...`); the deploy
template stores it in Key Vault and references it from both Container Apps.
Rotate by re-deploying with a new value.

**Cost.** On the production `gpu-nc8as-t4` Tesla-T4 profile, an always-warm
embedder (`embedderMinReplicas=1`) is on the order of ~$930/month (≈ €860, the
DocuWare CCL production figure) — approximate, since the serverless-GPU meter is
not exposed in the Azure pricing calculator; verify against Azure Cost
Management for your region. The template default (`embedderMinReplicas=0`,
Consumption profile) scales to zero and costs a few dollars/month, at the cost
of a cold-start on the first query after idle (the model weights are baked into
the image, so there is no runtime download).

## Reranker service (engine 0.7.16)

The reranker is a separate GPU Container App that hosts the
**BAAI/bge-reranker-v2-m3** cross-encoder (an xlm-roberta model loaded via the
sentence-transformers `CrossEncoder` API) and exposes a `POST /rerank`
endpoint. After the hybrid pool (dense pgvector + sparse BM25 + RRF + tag
boost) produces candidates, the search API sends the top `rerank_top_n`
(default 50) to the reranker, which re-scores them with the cross-encoder. On
the 60-query org-wide ground truth this lifted recall@1 from 43% to 65%,
recall@20 from 87% to 92%, and MRR from 0.564 to 0.735 (canonical baseline:
`rag/eval/CURRENT_BASELINE.md`).

Reranking is **off until wired up**, and turning it on takes BOTH settings:
`RERANK_ENABLED=true` (the master switch; bicep `rerankEnabled`) AND `RERANKER_URL`
set to the reranker app's FQDN (bicep `rerankerUrl`). With `RERANK_ENABLED` at its
`false` default the search API returns the hybrid ordering unchanged even when
`RERANKER_URL` is set; conversely `RERANK_ENABLED=true` with an empty `RERANKER_URL`
is rejected at startup. (`RERANKER_TOKEN` is also required whenever `RERANKER_URL`
is set.)

**Image build.** A separate `Dockerfile.reranker` at the repo root builds the
reranker image. The default `RERANK_MODEL` (BAAI/bge-reranker-v2-m3) is baked
into the image at build time. You *can* override `RERANK_MODEL` at runtime, but
a non-baked model triggers a multi-GB download on the GPU container at first
request (which can exceed the startup probe and the rerank timeout), so to use
a different model, rebuild the image with it baked in rather than only setting
the env var:

```bash
docker build \
  -f Dockerfile.reranker \
  -t docforge-reranker:latest .
```

**fp32 only.** The reranker runs the model in fp32. The fp16 `.half()` cast
breaks `CrossEncoder.predict` in sentence-transformers 5.x: the model loads (so
`/health` passes) but `/rerank` returns 500. `RERANK_MAX_LENGTH` (512) and
`RERANK_BATCH_SIZE` (8) bound T4 activation memory.

**Shared-secret auth.** The reranker reuses the embedder's bearer token — it
references the same `embedder-token` Key Vault secret, passed as
`RERANKER_TOKEN`. No separate secret to generate.

**GPU quota.** The serverless `gpu-nc8as-t4` Tesla-T4 profile requires the
**NC8as_T4_v3** GPU quota in your subscription/region. Both the embedder and
the reranker run on this profile, so request enough quota for two always-warm
T4 replicas before deploying with reranking enabled.

**Cost.** The template defaults the reranker to the Consumption profile with
`minReplicas=0` and reranking off, so out of the box it costs essentially
nothing. In production (the recommended config), the reranker runs on the
always-warm `gpu-nc8as-t4` Tesla-T4 profile (`minReplicas=1`) — on the order of
~$930/month (≈ €860; a second always-warm T4 alongside the embedder),
approximate as above. Keeping it warm avoids a GPU cold-start on the first query
after idle once reranking is on (`RERANK_ENABLED=true` + `RERANKER_URL`).

## Optional: Entra ID authentication

If the deployment should gate `/search` + `/sources` on Entra ID (delegated user auth), run the one-shot bootstrap script **before first deploy**:

```bash
./bootstrap-entra.sh --name docforge-search-api
# Prints AZURE_TENANT_ID and AZURE_AUDIENCE. Record them.
```

The script is idempotent — safe to re-run. It creates the app registration, exposes a `search` scope, grants tenant-wide admin consent, and configures Azure CLI to auto-issue v2 tokens for the scope. Requires Application Administrator or Global Administrator role on the tenant.

Then set three Bicep params at deploy time:

```
authMode     = 'entra'
authTenantId = '<AZURE_TENANT_ID from the script>'
authAudience = '<AZURE_AUDIENCE from the script>'
```

Deployments that don't need auth can leave these at their defaults (`authMode='none'`).

## Prerequisites

- Azure CLI 2.47+ (`az --version`) — earlier versions lack `.bicepparam` support.
- Subscription with `Microsoft.App`, `Microsoft.KeyVault`, `Microsoft.DBforPostgreSQL`, and `Microsoft.ContainerRegistry` providers registered:
  ```bash
  az provider register --namespace Microsoft.App --wait
  az provider register --namespace Microsoft.KeyVault --wait
  az provider register --namespace Microsoft.DBforPostgreSQL --wait
  az provider register --namespace Microsoft.ContainerRegistry --wait
  ```
- **NC8as_T4_v3** GPU quota in your subscription and region — the embedder and reranker each run on the serverless `gpu-nc8as-t4` Tesla-T4 profile, so deploying both always-warm needs quota for two T4 replicas. No Hugging Face token is required: Qwen3-Embedding-4B (embedder) and BAAI/bge-reranker-v2-m3 (reranker) are both ungated and are baked into their images at build time.
- A Confluence API token (if indexing Confluence pages).
- A strong Postgres admin password.

## Deploy

1. Copy the sample parameters file:
   ```bash
   cp main.sample.bicepparam main.bicepparam
   ```

2. Edit `main.bicepparam`. The only value you **must** change is `acrName` (globally unique, 3-50 lowercase alphanumeric). Check availability:
   ```bash
   az acr check-name -n <yourname>
   ```
   Optionally also add your home/office IP to `postgresAdminIpAddresses` so you can run `docforge ingest` locally against this deployment.

3. Create the resource group and deploy:
   ```bash
   az group create --name <rg-name> --location westeurope

   az deployment group create \
     --resource-group <rg-name> \
     --template-file main.bicep \
     --parameters main.bicepparam \
     --parameters \
       confluenceApiToken="<your-confluence-token>" \
       postgresAdminPassword="<strong-password>"
   ```

   Takes 5-10 minutes. Postgres Flex provisioning is the slowest step.

4. Grab outputs:
   ```bash
   az deployment group show \
     --resource-group <rg-name> --name main \
     --query properties.outputs
   ```
   Note `apiFqdn`, `acrLoginServer`, `databaseHost`.

5. Build and push the docforge image:
   ```bash
   cd <docforge-repo-root>
   docker build -t docforge:latest .

   ACR_SERVER=<from step 4>
   az acr login --name <acrName>
   docker tag docforge:latest $ACR_SERVER/docforge:latest
   docker push $ACR_SERVER/docforge:latest
   ```

6. Build and push the embedder image (Qwen3-Embedding-4B is ungated, so no HF token / secret mount is needed):
   ```bash
   docker build \
     -f Dockerfile.embedder \
     -t docforge-embedder:latest .

   docker tag docforge-embedder:latest $ACR_SERVER/docforge-embedder:latest
   docker push $ACR_SERVER/docforge-embedder:latest
   ```

7. Build and push the reranker image (`RERANK_MODEL` = BAAI/bge-reranker-v2-m3 is baked in at build time):
   ```bash
   docker build \
     -f Dockerfile.reranker \
     -t docforge-reranker:latest .

   docker tag docforge-reranker:latest $ACR_SERVER/docforge-reranker:latest
   docker push $ACR_SERVER/docforge-reranker:latest
   ```

8. Point the Container App at the new image:
   ```bash
   az containerapp update \
     --name docforge-search-api --resource-group <rg-name> \
     --image $ACR_SERVER/docforge:latest
   ```

9. Initialize the database and ingest:
   ```bash
   # Construct DATABASE_URL from Step 4 outputs
   export DATABASE_URL="postgresql://dfadmin:<password>@<databaseHost>:5432/docforge?sslmode=require"

   docforge init-db
   docforge ingest
   ```

10. Smoke test:
   ```bash
   curl -fsS https://<apiFqdn>/health
   # → {"status":"ok", "model":"remote"}
   # (the search-api delegates embedding to the embedder sidecar via
   #  EMBEDDER_URL, so its /health reports model: "remote", not the
   #  underlying model name)

   curl -X POST https://<apiFqdn>/search \
     -H "Content-Type: application/json" \
     -d '{"query":"test","user_name":"me","team_name":"eng","limit":3}'
   ```

## Configuration

| Parameter | Default | Purpose |
|---|---|---|
| `namePrefix` | `docforge` | Prefix for most resources (e.g., `docforge-pg`, `docforge-kv`). |
| `acrName` | *(required)* | ACR name — globally unique. |
| `location` | *(from RG)* | Azure region. |
| `postgresSku` / `postgresTier` | `Standard_B1ms` / `Burstable` | Postgres size. Increase for larger indexes. |
| `postgresStorageGB` | 32 | Storage size. |
| `postgresAdminUser` | `dfadmin` | Postgres admin username. |
| `databaseName` | `docforge` | Database name created on the server. |
| `postgresAdminIpAddresses` | `[]` | Your IPs allowed to connect directly to Postgres (e.g., for local ingest). |
| `logRetentionDays` | 30 | Log Analytics retention. |
| `containerImage` | `''` | Image reference. Leave empty first time; set after you push to ACR. |
| `minReplicas` / `maxReplicas` | 1 / 3 | Search-api scaling. `minReplicas=1` avoids container cold-starts on first request after idle. The 5-minute model-download cold-start was eliminated by the Phase 4b embedder split; search-api no longer loads the model. Set to 0 for dev to save ~$12/mo at the cost of ~30s container spin-up on the first request. |
| `embedderImage` | `''` | Embedder image reference. Leave empty first time; set after pushing. |
| `embedderToken` | *(required)* | Shared-secret bearer for embedder auth. Generate via `openssl rand -hex 32` (Linux/macOS), `python -c "import secrets; print(secrets.token_hex(32))"` (cross-platform), or `[Convert]::ToHexString((1..32 \| %{[byte](Get-Random -Max 256)}))` (PowerShell). |
| `embedderMinReplicas` / `embedderMaxReplicas` | 0 / 5 | Embedder app scaling. Default `0` is scale-to-zero (cheapest; cold-start with the baked model on the first request after idle — a GPU cold-start on the production `gpu-nc8as-t4` profile). Set `embedderMinReplicas=1` for production to keep the embedder warm. |
| `rerankerImage` | `''` | Reranker image reference. Leave empty first time; set after pushing. |
| `rerankEnabled` | `'false'` | Master switch for the reranking stage on the search API (sets `RERANK_ENABLED`). Reranking is on only when this is `'true'` AND `rerankerUrl` is set. |
| `rerankModel` | `BAAI/bge-reranker-v2-m3` | Cross-encoder model (sets `RERANK_MODEL`). The default is **baked into the reranker image**; overriding to a non-baked model triggers a multi-GB runtime download, so rebuild `Dockerfile.reranker` with the new model rather than only overriding it. |
| `rerankTopN` | `'50'` | How many top hybrid candidates the reranker re-scores per query (sets `RERANK_TOP_N`). |
| `rerankerUrl` | `''` | Reranker app FQDN (sets `RERANKER_URL`). Required to rerank but not sufficient alone — reranking is on only when `rerankEnabled='true'` AND this is set (plus `rerankerToken`/`RERANKER_TOKEN`). |
| `acrSku` | `Standard` | ACR pricing tier. **Must be `Standard` or `Premium`** — embedder image exceeds Basic's 10 GB quota. |

The reranker reuses the embedder's bearer token: `RERANKER_TOKEN` is wired from
the same `embedder-token` Key Vault secret, so there is no separate
`rerankerToken` deploy parameter to set. `RERANK_BATCH_SIZE` (8) and
`RERANK_MAX_LENGTH` (512) are runtime env on the reranker app (pydantic
Settings), not Bicep parameters — tune them with
`az containerapp update --set-env-vars` on the reranker Container App.

## Cost

At default SKUs in West Europe Consumption pricing, the rough ballpark is
~$1,900/month all-in with both GPU sidecars always warm (`embedderMinReplicas=1`
plus the reranker at `minReplicas=1` for production traffic) — the two warm T4
sidecars are ~$1,860 of that and the remaining ~$54 is Postgres/ACR/Key
Vault/logs — or ~$55/month with the default `embedderMinReplicas=0` and
reranking disabled (scale-to-zero
embedder, no reranker; you pay only when requests arrive plus a GPU cold-start
on the first request after idle). The two always-warm GPU sidecars dominate the
warm figure and are the most uncertain line items — the serverless-GPU meter is
not in the Azure pricing calculator, so treat the GPU rows below as estimates
and confirm against Azure Cost Management:

| Resource | Monthly |
|---|---|
| Postgres B1ms + 32 GB | ~$19 |
| Container Apps: search-api (1 replica always on, 1 vCPU / 2 GiB) | ~$12 |
| Container Apps: embedder (1 replica always warm, `gpu-nc8as-t4` Tesla-T4) | ~$930 (≈ €860; estimate) |
| Container Apps: reranker (1 replica always warm, `gpu-nc8as-t4` Tesla-T4) | ~$930 (≈ €860; estimate) |
| Container Registry Standard | ~$20 (full month) — note: Basic at $5 is too small for the embedder image |
| Key Vault Standard | <$1 |
| Log Analytics (low volume) | ~$2 |

Setting `minReplicas=0` on search-api drops ~$12/month at the cost of ~30s
container cold-start. Setting `embedderMinReplicas=0` (the default) drops the
embedder's ~$930/month at the cost of a GPU cold-start on the first request
after idle (container spin-up only — the model weights are baked into the
image). Leaving the reranker scaled to zero (its template default
`rerankerMinReplicas=0`, reranking off) avoids the reranker's ~$930/month
entirely. For development and low-volume deployments, scale-to-zero embedder with
reranking off is a reasonable default; for production traffic, set
`embedderMinReplicas=1`, run the reranker warm (`rerankerMinReplicas=1`), and
enable reranking (`rerankEnabled='true'` + `rerankerUrl`) to keep both GPU
sidecars warm and avoid the cold-start hop on every idle period.

## Architecture notes

- **pgvector**: enabled via the `azure.extensions = 'VECTOR'` server parameter. The docforge `init-db` command runs `CREATE EXTENSION vector` inside the `docforge` database.
- **Cold start**: search-api Container App cold-start takes ~30 seconds for the container itself. Since v0.3 Phase 4b, the search API does NOT load the model in-process — embedding is delegated to the embedder Container App. The embedder runs Qwen3-Embedding-4B on a Tesla-T4 GPU and cold-starts with the baked model (`Dockerfile.embedder` bakes Qwen3-Embedding-4B at build time, no runtime download). search-api `minReplicas` defaults to 1 (always warm); embedder `embedderMinReplicas` defaults to 0 (scale-to-zero). Set `embedderMinReplicas=1` to also keep the embedder warm for production deployments. The reranker Container App (BAAI/bge-reranker-v2-m3) is **off in the template** (`rerankerMinReplicas=0`, Consumption); production runs it warm at `minReplicas=1` on a Tesla-T4, and the search API calls it only when reranking is on — i.e. BOTH `RERANK_ENABLED=true` and `RERANKER_URL` are set.
- **Public Postgres**: the server has `publicNetworkAccess: Enabled` with firewall rules restricting access to Azure services + your admin IPs. Private endpoint / VNet integration is out of scope for this template.
- **Secret rotation**: to rotate a secret, update the Key Vault secret value (new version). The Container App references the secret name, not a specific version, so restarting replicas picks up the new value. Trigger a restart via `az containerapp revision restart` or update any non-critical property to force a new revision.

## Testing the template

Dry-run:
```bash
az deployment group what-if \
  --resource-group <rg-name> \
  --template-file main.bicep \
  --parameters main.bicepparam \
  --parameters confluenceApiToken="x" postgresAdminPassword="x"
```

## Limitations

- Single-region. No geo-replication. Postgres backup retention default 7 days.
- No CDN / custom domain. Adopter can add `az containerapp hostname add` after deploy.
- No alerting. Pair with Application Insights or Azure Monitor alerts externally.
- No CI/CD. Deploy is manual; pair with GitHub Actions or ADO for automation.
