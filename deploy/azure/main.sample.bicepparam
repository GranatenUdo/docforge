// Sample parameters for deploying docforge on Azure.
//
// 1. Copy this file to a local, gitignored file (e.g., main.bicepparam).
// 2. Replace the placeholder values below.
// 3. Provide the three secure parameters (hfToken, confluenceApiToken,
//    postgresAdminPassword) at deploy time via --parameters on the
//    command line — do NOT commit them to this file.
//
// Deploy:
//   az deployment group create \
//     --resource-group <your-rg> \
//     --template-file main.bicep \
//     --parameters main.bicepparam \
//     --parameters hfToken="<secret>" confluenceApiToken="<secret>" postgresAdminPassword="<secret>"

using 'main.bicep'

param namePrefix = 'docforge'

// ACR name must be globally unique (3-50 alphanumeric, lowercase).
// Check availability: az acr check-name -n <yourname>
param acrName = 'CHANGE_ME_UNIQUE_ACR_NAME'

param location = 'westeurope'

// Postgres sizing — Burstable B1ms is cheapest that supports pgvector.
param postgresSku = 'Standard_B1ms'
param postgresTier = 'Burstable'
param postgresStorageGB = 32
param postgresVersion = '16'

param postgresAdminUser = 'dfadmin'

// IPs allowed to connect to Postgres directly (e.g., for local `docforge ingest`).
// Leave empty [] to allow only Azure services (Container App).
param postgresAdminIpAddresses = []

param databaseName = 'docforge'
param logRetentionDays = 30

// The Container App image reference. Leave empty for initial deployment
// (a placeholder image is used); update to your ACR-pushed image with
// `az containerapp update` or re-deploy this template.
param containerImage = ''

// minReplicas=1 avoids cold-start model download (~5 min). Set to 0
// for dev/test to reduce cost — you'll pay in first-request latency.
param minReplicas = 1
param maxReplicas = 3

// Embedder Container App image reference. Leave empty for initial deployment
// (a placeholder image is used). Deploy both containerImage and embedderImage
// together on the second pass to ensure EMBEDDER_URL is wired correctly.
param embedderImage = ''

// embedderMinReplicas=0 (scale-to-zero) is cheapest for dev/test.
// Set to 1 in production to avoid cold-start latency on the first request
// (embedder cold start ~5–10s with baked model weights).
param embedderMinReplicas = 0
param embedderMaxReplicas = 5

// Bearer token shared between the search API and the embedder service.
// Do NOT commit a real value here. Supply at deploy time:
//   --parameters embedderToken="$(openssl rand -hex 32)"            (Linux/macOS)
//   --parameters embedderToken="$(python -c 'import secrets; print(secrets.token_hex(32))')"  (cross-platform)
//   --parameters embedderToken="$([Convert]::ToHexString((1..32 | %{[byte](Get-Random -Max 256)})))"  (PowerShell)
// Rotate by re-deploying with a new value; the Key Vault secret and both
// Container Apps are updated atomically in the same Bicep apply.
param embedderToken = '__SET_AT_DEPLOY_TIME__'
