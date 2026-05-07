# docforge on Azure

Bicep template to deploy docforge as a hosted service on Azure Container Apps, backed by Azure Database for PostgreSQL (with pgvector) and Azure Container Registry.

## What gets deployed

Seven resources in a single resource group (~$90/month at default SKUs with embedder always-on; less with `embedderMinReplicas=0`):

| Resource | Purpose | Default SKU |
|---|---|---|
| Key Vault | Runtime secrets (`hf-token`, `confluence-api-token`, `database-url`, `embedder-token`) | Standard |
| Container Registry | Hosts the docforge Docker image **and** the embedder image (~13.6 GB) | Standard (NOT Basic — embedder image exceeds Basic's 10 GB quota) |
| Postgres Flexible Server | Vector store + metadata, pgvector extension enabled | Burstable B1ms, 32 GB |
| Log Analytics workspace | Container App logs | PerGB2018, 30-day retention |
| Container Apps managed environment | Compute host for both container apps | Consumption plan |
| Container App: search-api | Runs `docforge serve --api`; `minReplicas=1` by default | 1 CPU, 1 GiB |
| Container App: embedder | Runs the EmbeddingGemma sidecar; `embedderMinReplicas=0` by default (set 1 for production) | 2 CPU, 4 GiB |

The split into two Container Apps is the v0.3 Phase 4b architecture: the
embedder service hosts the model and exposes a `POST /embed` endpoint; the
search API and ingest workers call into it via `EMBEDDER_URL` instead of
loading the model in-process. Search API replicas drop from ~2 GB RSS to
~400 MB and cold-start in ~30s (just container spin-up; no model load).
The embedder defaults to `embedderMinReplicas=0` (scale-to-zero); on cold
start it spins up in ~5–10s with the baked model weights (the
`Dockerfile.embedder` bakes EmbeddingGemma at build time, so there is no
runtime model download). For production traffic, set `embedderMinReplicas=1`
to keep the model warm and avoid that 5–10s on the first request after idle.

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
never enters any image layer. Export your token before running the build
(`export HF_TOKEN="hf_..."` on Linux/macOS; `$env:HF_TOKEN = "hf_..."` in
PowerShell; `set HF_TOKEN=hf_...` in cmd), then:

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

**Cost.** Embedder Container App at 2 CPU / 4 GiB always-on
(`embedderMinReplicas=1`) adds ~$35/month at West Europe Consumption pricing
(roughly $25/mo for 2 vCPU-month plus ~$10/mo for 4 GiB-month, before
request-driven CPU scaling). The default `embedderMinReplicas=0` scales to
zero between requests — saves the full ~$35/month, at the cost of a ~5–10s
cold-start on the first query after idle (just container spin-up; the model
weights are baked into the image so there is no runtime download).

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
- A Hugging Face token with access to the gated `google/embeddinggemma-300m` model (accept the license at https://huggingface.co/google/embeddinggemma-300m first). **Export this token in your shell before running the `docker build` commands below**: `export HF_TOKEN="hf_..."` (Linux/macOS), `$env:HF_TOKEN = "hf_..."` (PowerShell), or `set HF_TOKEN=hf_...` (cmd). The BuildKit `--secret id=hf_token,env=HF_TOKEN` flag reads from this environment variable and never persists the token in any image layer.
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
| `minReplicas` / `maxReplicas` | 1 / 3 | Search-api scaling. `minReplicas=1` avoids container cold-starts on first request after idle. The 5-minute model-download cold-start was eliminated by the Phase 4b embedder split; search-api no longer loads the model. Set to 0 for dev to save ~$12/mo at the cost of ~30s container spin-up on the first request. |
| `embedderImage` | `''` | Embedder image reference. Leave empty first time; set after pushing. |
| `embedderToken` | *(required)* | Shared-secret bearer for embedder auth. Generate via `openssl rand -hex 32` (Linux/macOS), `python -c "import secrets; print(secrets.token_hex(32))"` (cross-platform), or `[Convert]::ToHexString((1..32 \| %{[byte](Get-Random -Max 256)}))` (PowerShell). |
| `embedderMinReplicas` / `embedderMaxReplicas` | 0 / 5 | Embedder app scaling. Default `0` is scale-to-zero (cheapest; ~5–10s cold-start with baked model). Set `embedderMinReplicas=1` for production to keep the embedder warm. |
| `acrSku` | `Standard` | ACR pricing tier. **Must be `Standard` or `Premium`** — embedder image exceeds Basic's 10 GB quota. |

## Cost

At default SKUs in West Europe Consumption pricing, the rough ballpark is
~$90/month if you set `embedderMinReplicas=1` (always-on embedder for
production traffic), or ~$55/month with the default `embedderMinReplicas=0`
(scale-to-zero embedder; you pay only when requests arrive plus a ~5–10s
cold-start on the first request after idle):

| Resource | Monthly |
|---|---|
| Postgres B1ms + 32 GB | ~$19 |
| Container Apps: search-api (1 replica always on, 1 vCPU / 1 GiB) | ~$12 |
| Container Apps: embedder (1 replica always on, 2 vCPU / 4 GiB) | ~$35 |
| Container Registry Standard | ~$20 (full month) — note: Basic at $5 is too small for the embedder image |
| Key Vault Standard | <$1 |
| Log Analytics (low volume) | ~$2 |

Setting `minReplicas=0` on search-api drops ~$12/month at the cost of ~30s
container cold-start. Setting `embedderMinReplicas=0` (the default) drops
~$35/month at the cost of a ~5–10s cold-start on the first request after
idle (container spin-up only — the model weights are baked into the image).
For development and low-volume deployments, scale-to-zero on both is a
reasonable default; for production traffic, set `embedderMinReplicas=1` to
avoid the cold-start hop on every idle period.

## Architecture notes

- **pgvector**: enabled via the `azure.extensions = 'VECTOR'` server parameter. The docforge `init-db` command runs `CREATE EXTENSION vector` inside the `docforge` database.
- **Cold start**: search-api Container App cold-start takes ~30 seconds for the container itself. Since v0.3 Phase 4b, the search API does NOT load the model in-process — embedding is delegated to the embedder Container App. The embedder cold-starts in ~5–10s with the baked model (`Dockerfile.embedder` bakes EmbeddingGemma at build time, no runtime download). search-api `minReplicas` defaults to 1 (always warm); embedder `embedderMinReplicas` defaults to 0 (scale-to-zero). Set `embedderMinReplicas=1` to also keep the embedder warm for production deployments.
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
