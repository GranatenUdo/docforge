# docforge on Azure

Bicep template to deploy docforge as a hosted service on Azure Container Apps, backed by Azure Database for PostgreSQL (with pgvector) and Azure Container Registry.

## What gets deployed

Seven resources in a single resource group (~$45/month at default SKUs):

| Resource | Purpose | Default SKU |
|---|---|---|
| Key Vault | Runtime secrets (`hf-token`, `confluence-api-token`, `database-url`, `embedder-token`) | Standard |
| Container Registry | Hosts the docforge Docker image **and** the embedder image (~13.6 GB) | Standard (NOT Basic — embedder image exceeds Basic's 10 GB quota) |
| Postgres Flexible Server | Vector store + metadata, pgvector extension enabled | Burstable B1ms, 32 GB |
| Log Analytics workspace | Container App logs | PerGB2018, 30-day retention |
| Container Apps managed environment | Compute host for both container apps | Consumption plan |
| Container App: search-api | Runs `docforge serve --api`; `minReplicas=1` by default | 1 CPU, 1 GB |
| Container App: embedder | Runs the EmbeddingGemma sidecar; `minReplicas=1` by default | 1 CPU, 1 GB |

The split into two Container Apps is the v0.3 Phase 4b architecture: the
embedder service hosts the model and exposes a `POST /embed` endpoint; the
search API and ingest workers call into it via `EMBEDDER_URL` instead of
loading the model in-process. Search API replicas drop from ~2 GB RSS to
~400 MB and start in <10s. The embedder is bound to a persistent
`minReplicas=1` to avoid 60-120s cold-start on the first query after idle.

Both Container Apps use a system-assigned managed identity with:
- **Key Vault Secrets User** on the Key Vault — reads secrets at runtime via identity, no connection strings stored in env vars.
- **AcrPull** on the Container Registry — pulls images without admin credentials.

No admin credentials are stored anywhere except Key Vault.

## Embedder service (v0.3 Phase 4b)

The embedder is a separate Container App that hosts the EmbeddingGemma-300M
model and exposes a `POST /embed` endpoint protected by a shared-secret
bearer token. The search API, MCP server, and ingest worker call this
endpoint instead of loading the 1.2 GB model in-process.

**Image build.** A separate `Dockerfile.embedder` at the repo root builds
the embedder image. The model is baked in at build time using BuildKit's
secret mount (`--mount=type=secret,id=hf_token`); the HuggingFace token
never enters any image layer. Build with:

```bash
docker build \
  --secret id=hf_token,env=HF_TOKEN \
  -f Dockerfile.embedder \
  -t docforge-embedder:latest .
```

**ACR SKU note.** The baked-in model makes the embedder image ~13.6 GB. Azure
Container Registry Basic has a 10 GB storage quota, which means **the
default ACR SKU must be Standard or Premium for this deployment.** The
Bicep parameter `acrSku` defaults to `Standard`. If you previously
provisioned with Basic, you can upgrade in place: `az acr update --name
<acr> --sku Standard`.

**Shared-secret auth.** The search API authenticates to the embedder via a
bearer token (`EMBEDDER_TOKEN`). Generate at deploy time:

```bash
openssl rand -hex 32
```

Pass the value as a Bicep parameter (`embedderToken=...`); the deploy
template stores it in Key Vault and references it from both Container Apps.
Rotate by re-deploying with a new value.

**Cost.** Embedder Container App at 1 CPU / 1 GB / `minReplicas=1` adds
~$10/month at West Europe Consumption pricing. Setting `embedderMinReplicas=0`
saves the ~$10/month at the cost of 60-120s cold-start latency on the first
query after idle (model load).

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
- A Hugging Face token with access to the gated `google/embeddinggemma-300m` model (accept the license at https://huggingface.co/google/embeddinggemma-300m first).
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
       hfToken="<your-hf-token>" \
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

6. Build and push the embedder image:
   ```bash
   docker build \
     --secret id=hf_token,env=HF_TOKEN \
     -f Dockerfile.embedder \
     -t docforge-embedder:latest .

   docker tag docforge-embedder:latest $ACR_SERVER/docforge-embedder:latest
   docker push $ACR_SERVER/docforge-embedder:latest
   ```

7. Point the Container App at the new image:
   ```bash
   az containerapp update \
     --name docforge-search-api --resource-group <rg-name> \
     --image $ACR_SERVER/docforge:latest
   ```

8. Initialize the database and ingest:
   ```bash
   # Construct DATABASE_URL from Step 4 outputs
   export DATABASE_URL="postgresql://dfadmin:<password>@<databaseHost>:5432/docforge?sslmode=require"

   docforge init-db
   docforge ingest
   ```

9. Smoke test:
   ```bash
   curl -fsS https://<apiFqdn>/health
   # → {"status":"ok", "model":"google/embeddinggemma-300m"}

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
| `minReplicas` / `maxReplicas` | 1 / 3 | App scaling. `minReplicas=1` avoids 5-minute cold starts (model download). Set to 0 for dev to save ~$10/mo at the cost of first-request latency. |
| `embedderImage` | `''` | Embedder image reference. Leave empty first time; set after pushing. |
| `embedderToken` | *(required)* | Shared-secret bearer for embedder auth. Generate via `openssl rand -hex 32`. |
| `embedderMinReplicas` / `embedderMaxReplicas` | 1 / 5 | Embedder app scaling. `embedderMinReplicas=1` keeps the model warm. |
| `acrSku` | `Standard` | ACR pricing tier. **Must be `Standard` or `Premium`** — embedder image exceeds Basic's 10 GB quota. |

## Cost

At default SKUs, ~$45/month in West Europe:

| Resource | Monthly |
|---|---|
| Postgres B1ms + 32 GB | ~$19 |
| Container Apps: search-api (1 replica always on) | ~$12 |
| Container Apps: embedder (1 replica always on) | ~$10 |
| Container Registry Standard | ~$20 (full month) — note: Basic at $5 is too small for the embedder image |
| Key Vault Standard | <$1 |
| Log Analytics (low volume) | ~$2 |

Setting `minReplicas=0` on either Container App drops ~$10-12/month at the
cost of cold-start latency. The embedder cold-start (60-120s for model load)
is the longer of the two, so `embedderMinReplicas=0` is a worse tradeoff
than `minReplicas=0` on search-api.

## Architecture notes

- **pgvector**: enabled via the `azure.extensions = 'VECTOR'` server parameter. The docforge `init-db` command runs `CREATE EXTENSION vector` inside the `docforge` database.
- **Cold start**: Container Apps cold-start takes ~30 seconds for the container itself, but the docforge FastAPI lifespan loads the 1.2 GB embedding model which takes ~2 minutes (~5 minutes the very first time if the model is not cached — there is no persistent model cache in this template). `minReplicas=1` keeps one warm replica to avoid this on every idle period. A future improvement is mounting an Azure Files share at `/app/.cache/huggingface`.
- **Public Postgres**: the server has `publicNetworkAccess: Enabled` with firewall rules restricting access to Azure services + your admin IPs. Private endpoint / VNet integration is out of scope for this template.
- **Secret rotation**: to rotate a secret, update the Key Vault secret value (new version). The Container App references the secret name, not a specific version, so restarting replicas picks up the new value. Trigger a restart via `az containerapp revision restart` or update any non-critical property to force a new revision.

## Testing the template

Dry-run:
```bash
az deployment group what-if \
  --resource-group <rg-name> \
  --template-file main.bicep \
  --parameters main.bicepparam \
  --parameters hfToken="x" confluenceApiToken="x" postgresAdminPassword="x"
```

## Limitations

- Single-region. No geo-replication. Postgres backup retention default 7 days.
- No CDN / custom domain. Adopter can add `az containerapp hostname add` after deploy.
- No alerting. Pair with Application Insights or Azure Monitor alerts externally.
- No CI/CD. Deploy is manual; pair with GitHub Actions or ADO for automation.
