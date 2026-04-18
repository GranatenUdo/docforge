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
