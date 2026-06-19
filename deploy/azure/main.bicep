// docforge — Azure deployment
//
// Provisions everything needed to run docforge as a hosted service on Azure:
//   * Key Vault (secrets: HF_TOKEN, CONFLUENCE_API_TOKEN, postgres admin password)
//   * Azure Container Registry (hosts the docforge image)
//   * Postgres Flexible Server (pgvector extension enabled, `docforge` database)
//   * Log Analytics workspace
//   * Container Apps managed environment
//   * Container App running the docforge FastAPI image
//
// The Container App gets a system-assigned managed identity. That identity has:
//   * Key Vault Secrets User role on the Key Vault (reads secrets at runtime)
//   * AcrPull role on the Container Registry (pulls the image without admin creds)
//
// Deploy:
//   az deployment group create \
//     --resource-group <rg> \
//     --template-file main.bicep \
//     --parameters main.sample.bicepparam \
//     --parameters hfToken="<secret>" confluenceApiToken="<secret>" postgresAdminPassword="<secret>"
//
// Outputs: apiFqdn, acrLoginServer, databaseHost.

targetScope = 'resourceGroup'

// ─── Parameters ─────────────────────────────────────────────────────────

@description('Short prefix for resource names (e.g., "docforge"). Used for all resources except ACR.')
param namePrefix string = 'docforge'

@description('Container Registry name. Must be globally unique (3-50 alphanumeric). Lowercase required.')
param acrName string

@description('Container Registry SKU. Basic is cheapest (10 GB included, low throughput); Standard (100 GB, higher throughput) suits multi-image deployments; Premium adds geo-replication.')
@allowed(['Basic', 'Standard', 'Premium'])
// Standard required: the v0.3 Phase 4b embedder image (~13.6 GB) exceeds Basic's 10 GB quota.
param acrSku string = 'Standard'

@description('Azure region for all resources.')
param location string = resourceGroup().location

@description('Postgres SKU (e.g., Standard_B1ms for Burstable tier).')
param postgresSku string = 'Standard_B1ms'

@description('Postgres SKU tier.')
@allowed(['Burstable', 'GeneralPurpose', 'MemoryOptimized'])
param postgresTier string = 'Burstable'

@description('Postgres storage in GB.')
param postgresStorageGB int = 32

@description('Postgres server version.')
param postgresVersion string = '16'

@description('Postgres admin username.')
param postgresAdminUser string = 'dfadmin'

@description('Postgres admin password. Must be strong.')
@secure()
param postgresAdminPassword string

@description('Database name created on the Postgres server.')
param databaseName string = 'docforge'

@description('List of IPv4 addresses allowed to connect to Postgres (in addition to Azure services). Useful for running docforge ingest from a local machine.')
param postgresAdminIpAddresses array = []

@description('Log Analytics retention in days.')
param logRetentionDays int = 30

@description('Full image reference for the Container App. Empty string defers to the default "hello-world" image, update post-deploy.')
param containerImage string = ''

@description('Min replicas for the Container App. Set to 1 to avoid cold-start model download (~5 min) on every idle period.')
@minValue(0)
@maxValue(10)
param minReplicas int = 1

@description('Max replicas for the Container App.')
@minValue(1)
@maxValue(30)
param maxReplicas int = 3

@description('HuggingFace token. The default embedder Qwen3-Embedding-4B is Apache-2.0 (ungated), so this is optional and defaults to empty; only needed if an operator swaps to a gated embedding model.')
@secure()
param hfToken string = ''

@description('Confluence API token for page crawling.')
@secure()
param confluenceApiToken string

@description('Auth mode for /search + /sources: "none" or "entra".')
param authMode string = 'none'

@description('Entra tenant ID (required when authMode=entra).')
param authTenantId string = ''

@description('Entra API audience, e.g. api://<app-id> (required when authMode=entra).')
param authAudience string = ''

@description('Tags applied to every created resource. Useful for cost allocation or org policies that require specific tags.')
param tags object = {}

@description('Full image reference for the embedder Container App. Empty string defers to "hello-world" placeholder, update post-deploy.')
param embedderImage string = ''

@description('Min replicas for the embedder Container App. 0 = scale-to-zero (cheapest, eats cold start); 1 = always warm.')
@minValue(0)
@maxValue(10)
param embedderMinReplicas int = 0

@description('Max replicas for the embedder Container App.')
@minValue(1)
@maxValue(30)
param embedderMaxReplicas int = 5

@description('Bearer token shared between the search API and the embedder service. Generate via `openssl rand -hex 32` or similar; rotate by re-deploying with a new value.')
@secure()
param embedderToken string

@description('Per-retriever multiplier on the dense path RRF contribution. Default 1.0 = classic RRF. Container Apps env values are strings; pydantic-settings parses to float at runtime.')
param denseWeight string = '1.0'

@description('Per-retriever multiplier on the sparse path RRF contribution. Default 1.0 = classic RRF. Bruch et al. 2023 (ACM TOIS) shows weight tuning is dataset-specific — adjust via bicepparam per deployment, not by changing this default.')
param sparseWeight string = '1.0'

@description('Server-side capture of /search result rows into query_result, gated default-off. Container Apps env values are strings; pydantic-settings parses LOG_RESPONSES to bool at runtime.')
param logResponses string = 'false'

@description('Optional suffix appended to the managed environment name + Container App names. Lets a new Workload-Profiles environment coexist with an existing Consumption-only one during a migration. Leave empty for legacy single-env deployments.')
param nameSuffix string = ''

@description('Workload profile name for the search-api Container App. Only relevant when enableWorkloadProfiles=true. "Consumption" stays on the consumption-style profile within the WP env.')
param searchApiWorkloadProfileName string = 'Consumption'

@description('Workload profile name for the embedder Container App. Only relevant when enableWorkloadProfiles=true. Set "gpu-nc8as-t4" for Tesla T4 GPU; "Consumption" for CPU-only.')
param embedderWorkloadProfileName string = 'Consumption'

@description('vCPUs allocated to the embedder Container App. GPU workload profiles require the full SKU vCPU count (NC8as_T4 = 8). Consumption-profile callers use fractional cpu (json("2.0")) via the conditional below.')
@minValue(1)
@maxValue(16)
param embedderCpu int = 2

@description('Memory (Gi) allocated to the embedder Container App. GPU workload profiles require the full SKU memory (NC8as_T4 = 56). Consumption-profile callers typically use 4.')
@minValue(1)
@maxValue(64)
param embedderMemoryGi int = 4

@description('Per-call embedding sub-batch size on the embedder (EMBEDDING_BATCH_SIZE). Lower values cut peak GPU VRAM per forward pass — Qwen3-4B leaves little headroom on a T4, so 8 avoids CUDA OOM on long-chunk batches; higher reduces Python overhead. Default 32 matches the engine default.')
@minValue(1)
@maxValue(256)
param embedderEmbeddingBatchSize int = 32

@description('When true, the managed environment is provisioned as a Workload-Profiles env (with a workloadProfiles array). When false (default), it stays Consumption-only — preserves backward compatibility for OSS / non-CCL deployments.')
param enableWorkloadProfiles bool = false

@description('When true, adds the gpu-nc8as-t4 workload profile to the env. Only honored when enableWorkloadProfiles=true.')
param enableGpuProfile bool = false

@description('Cross-encoder reranking toggle for the search API (RERANK_ENABLED). Default "false" = off. Container Apps env values are strings; pydantic-settings parses to bool at runtime.')
param rerankEnabled string = 'false'

@description('Cross-encoder model loaded by the reranker sidecar (RERANK_MODEL / settings.rerank_model). Only the default is baked into Dockerfile.reranker; setting any other model triggers a multi-GB runtime download on the GPU container at first request, which can exceed the cold-start probe and the search API rerank timeout. To change the model, rebuild the reranker image with the new model baked in rather than only overriding this param.')
param rerankModel string = 'BAAI/bge-reranker-v2-m3'

@description('Number of top hybrid candidates the search API re-scores via the reranker sidecar (RERANK_TOP_N). Must not exceed HYBRID_POOL_SIZE. Container Apps env values are strings; pydantic-settings parses to int at runtime.')
param rerankTopN string = '50'

@description('URL of the reranker sidecar the search API delegates to (RERANKER_URL). Empty string = reranking disabled, regardless of rerankEnabled. Wire to the reranker app FQDN when flipping reranking on.')
param rerankerUrl string = ''

@description('Full image reference for the reranker Container App. Empty string defers to "hello-world" placeholder, update post-deploy.')
param rerankerImage string = ''

@description('Workload profile name for the reranker Container App. Only relevant when enableWorkloadProfiles=true. Set "gpu-nc8as-t4" for Tesla T4 GPU; "Consumption" for CPU-only.')
param rerankerWorkloadProfileName string = 'Consumption'

@description('Min replicas for the reranker Container App. 0 = scale-to-zero (cheapest, eats cold start); 1 = always warm.')
@minValue(0)
@maxValue(10)
param rerankerMinReplicas int = 0

@description('Max replicas for the reranker Container App.')
@minValue(1)
@maxValue(30)
param rerankerMaxReplicas int = 5

@description('vCPUs allocated to the reranker Container App. GPU workload profiles require the full SKU vCPU count (NC8as_T4 = 8). Consumption-profile callers use fractional cpu (json("2.0")) via the conditional below.')
@minValue(1)
@maxValue(16)
param rerankerCpu int = 2

@description('Memory (Gi) allocated to the reranker Container App. GPU workload profiles require the full SKU memory (NC8as_T4 = 56). Consumption-profile callers typically use 4.')
@minValue(1)
@maxValue(64)
param rerankerMemoryGi int = 4

@description('Bearer token shared between the search API and the reranker service. The reranker reuses the embedder-token Key Vault secret today (single shared sidecar token), so this param is currently unwired — reserved for a future split where the reranker gets its own KV secret. Rotate the shared token via embedderToken until then.')
@secure()
#disable-next-line no-unused-params
param rerankerToken string = ''

// ─── Derived names ──────────────────────────────────────────────────────

var keyVaultName = '${namePrefix}-kv'
var postgresServerName = '${namePrefix}-pg'
var logAnalyticsName = '${namePrefix}-law'
var containerAppsEnvName = '${namePrefix}-env${nameSuffix}'
var containerAppName = '${namePrefix}-search-api${nameSuffix}'

// ─── Key Vault ──────────────────────────────────────────────────────────

resource keyVault 'Microsoft.KeyVault/vaults@2024-04-01-preview' = {
  name: keyVaultName
  location: location
  tags: tags
  properties: {
    tenantId: subscription().tenantId
    sku: {
      family: 'A'
      name: 'standard'
    }
    enableRbacAuthorization: true
    enableSoftDelete: true
    softDeleteRetentionInDays: 7
    enablePurgeProtection: true
  }
}

resource secretHfToken 'Microsoft.KeyVault/vaults/secrets@2024-04-01-preview' = {
  parent: keyVault
  name: 'hf-token'
  properties: {
    value: hfToken
  }
}

resource secretConfluenceToken 'Microsoft.KeyVault/vaults/secrets@2024-04-01-preview' = {
  parent: keyVault
  name: 'confluence-api-token'
  properties: {
    value: confluenceApiToken
  }
}

resource secretEmbedderToken 'Microsoft.KeyVault/vaults/secrets@2024-04-01-preview' = {
  parent: keyVault
  name: 'embedder-token'
  properties: {
    value: embedderToken
  }
}

resource secretPostgresPassword 'Microsoft.KeyVault/vaults/secrets@2024-04-01-preview' = {
  parent: keyVault
  name: 'postgres-admin-password'
  properties: {
    value: postgresAdminPassword
  }
}

// ─── Postgres Flexible Server ───────────────────────────────────────────

resource postgres 'Microsoft.DBforPostgreSQL/flexibleServers@2024-08-01' = {
  name: postgresServerName
  location: location
  tags: tags
  sku: {
    name: postgresSku
    tier: postgresTier
  }
  properties: {
    version: postgresVersion
    administratorLogin: postgresAdminUser
    administratorLoginPassword: postgresAdminPassword
    storage: {
      storageSizeGB: postgresStorageGB
    }
    backup: {
      backupRetentionDays: 7
      geoRedundantBackup: 'Disabled'
    }
    highAvailability: {
      mode: 'Disabled'
    }
    network: {
      publicNetworkAccess: 'Enabled'
    }
  }
}

resource postgresExtensions 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-08-01' = {
  parent: postgres
  name: 'azure.extensions'
  properties: {
    value: 'VECTOR'
    source: 'user-override'
  }
}

resource postgresFirewallAzure 'Microsoft.DBforPostgreSQL/flexibleServers/firewallRules@2024-08-01' = {
  parent: postgres
  name: 'AllowAzureServices'
  properties: {
    startIpAddress: '0.0.0.0'
    endIpAddress: '0.0.0.0'
  }
}

resource postgresFirewallAdminIps 'Microsoft.DBforPostgreSQL/flexibleServers/firewallRules@2024-08-01' = [for (ip, i) in postgresAdminIpAddresses: {
  parent: postgres
  name: 'AdminIp${i}'
  properties: {
    startIpAddress: ip
    endIpAddress: ip
  }
}]

resource database 'Microsoft.DBforPostgreSQL/flexibleServers/databases@2024-08-01' = {
  parent: postgres
  name: databaseName
  properties: {
    charset: 'UTF8'
    collation: 'en_US.utf8'
  }
  dependsOn: [
    postgresExtensions
  ]
}

// ─── Container Registry ─────────────────────────────────────────────────

resource acr 'Microsoft.ContainerRegistry/registries@2023-11-01-preview' = {
  name: acrName
  location: location
  tags: tags
  sku: {
    name: acrSku
  }
  properties: {
    adminUserEnabled: false
    publicNetworkAccess: 'Enabled'
  }
}

// ─── Log Analytics ──────────────────────────────────────────────────────

resource logAnalytics 'Microsoft.OperationalInsights/workspaces@2023-09-01' = {
  name: logAnalyticsName
  location: location
  tags: tags
  properties: {
    sku: {
      name: 'PerGB2018'
    }
    retentionInDays: logRetentionDays
  }
}

// ─── Container Apps managed environment ────────────────────────────────

var workloadProfilesArray = enableGpuProfile ? [
  {
    name: 'Consumption'
    workloadProfileType: 'Consumption'
  }
  {
    // Verified via pre-flight probe (2026-05-12): serverless GPU profiles
    // do NOT accept minimumCount or maximumCount — Azure errors with
    // WorkloadProfilePropertyNotSupported. Scale is governed by the
    // Container App's scale rule (concurrentRequests + minReplicas/maxReplicas).
    name: 'gpu-nc8as-t4'
    workloadProfileType: 'Consumption-GPU-NC8as-T4'
  }
] : [
  {
    name: 'Consumption'
    workloadProfileType: 'Consumption'
  }
]

resource containerAppsEnv 'Microsoft.App/managedEnvironments@2024-03-01' = {
  name: containerAppsEnvName
  location: location
  tags: tags
  properties: union(
    {
      appLogsConfiguration: {
        destination: 'log-analytics'
        logAnalyticsConfiguration: {
          customerId: logAnalytics.properties.customerId
          sharedKey: logAnalytics.listKeys().primarySharedKey
        }
      }
    },
    enableWorkloadProfiles ? { workloadProfiles: workloadProfilesArray } : {}
  )
}

// ─── Container App ──────────────────────────────────────────────────────

// If containerImage is empty (first-pass deploy before the docforge image
// is pushed to ACR), use a hello-world placeholder and omit the probes —
// hello-world has no /health endpoint, so probes would fail-loop and kill
// the revision. After pushing the real image, re-deploy with containerImage
// set to enable the probes.
var defaultImage = 'mcr.microsoft.com/azuredocs/containerapps-helloworld:latest'
var hasRealImage = !empty(containerImage)
var effectiveImage = hasRealImage ? containerImage : defaultImage
var probes = hasRealImage ? [
  {
    type: 'Startup'
    httpGet: {
      path: '/health'
      port: 8000
    }
    initialDelaySeconds: 10
    periodSeconds: 10
    timeoutSeconds: 5
    failureThreshold: 60
  }
  {
    type: 'Liveness'
    httpGet: {
      path: '/health'
      port: 8000
    }
    initialDelaySeconds: 30
    periodSeconds: 30
    timeoutSeconds: 5
    failureThreshold: 3
  }
] : []

var databaseUrl = 'postgresql://${postgresAdminUser}:${postgresAdminPassword}@${postgres.properties.fullyQualifiedDomainName}:5432/${databaseName}?sslmode=require'

resource secretDatabaseUrl 'Microsoft.KeyVault/vaults/secrets@2024-04-01-preview' = {
  parent: keyVault
  name: 'database-url'
  properties: {
    value: databaseUrl
  }
}

// First-pass (no real image): minimal Container App — no ACR registries,
// no KV secrets, no probes, port 80 (hello-world default). This avoids
// identity/role-propagation races that block revision provisioning.
// Second-pass (containerImage set): full config with KV-backed secrets,
// ACR pull via identity, HTTP probes on /health, port 8000.
var realContainerSecrets = [
  {
    name: 'hf-token'
    keyVaultUrl: '${keyVault.properties.vaultUri}secrets/hf-token'
    identity: 'system'
  }
  {
    name: 'confluence-api-token'
    keyVaultUrl: '${keyVault.properties.vaultUri}secrets/confluence-api-token'
    identity: 'system'
  }
  {
    name: 'database-url'
    keyVaultUrl: '${keyVault.properties.vaultUri}secrets/database-url'
    identity: 'system'
  }
  {
    name: 'embedder-token'
    keyVaultUrl: '${keyVault.properties.vaultUri}secrets/embedder-token'
    identity: 'system'
  }
]

var realContainerEnv = [
  {
    name: 'HF_TOKEN'
    secretRef: 'hf-token'
  }
  {
    name: 'CONFLUENCE_API_TOKEN'
    secretRef: 'confluence-api-token'
  }
  {
    name: 'DATABASE_URL'
    secretRef: 'database-url'
  }
  {
    name: 'AUTH__MODE'
    value: authMode
  }
  {
    name: 'AUTH__TENANT_ID'
    value: authTenantId
  }
  {
    name: 'AUTH__AUDIENCE'
    value: authAudience
  }
  {
    name: 'EMBEDDER_URL'
    value: 'https://${embedderApp.properties.configuration.ingress.fqdn}'
  }
  {
    name: 'EMBEDDER_TOKEN'
    secretRef: 'embedder-token'
  }
  {
    name: 'DENSE_WEIGHT'
    value: denseWeight
  }
  {
    name: 'SPARSE_WEIGHT'
    value: sparseWeight
  }
  {
    name: 'LOG_RESPONSES'
    value: logResponses
  }
  {
    name: 'RERANK_ENABLED'
    value: rerankEnabled
  }
  {
    name: 'RERANK_MODEL'
    value: rerankModel
  }
  {
    name: 'RERANK_TOP_N'
    value: rerankTopN
  }
  {
    // Default-OFF: rerankerUrl defaults to '' so the search API leaves
    // reranking disabled until the flip. When enabling, set rerankerUrl to
    // 'https://${rerankerApp.properties.configuration.ingress.fqdn}' — the
    // same FQDN-output wiring EMBEDDER_URL uses for the embedder app.
    name: 'RERANKER_URL'
    value: rerankerUrl
  }
  {
    // Reuses the embedder-token secret — the search API authenticates to both
    // sidecars with the same shared bearer token; no separate KV secret.
    name: 'RERANKER_TOKEN'
    secretRef: 'embedder-token'
  }
]

resource containerApp 'Microsoft.App/containerApps@2024-03-01' = {
  name: containerAppName
  location: location
  tags: tags
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    managedEnvironmentId: containerAppsEnv.id
    workloadProfileName: enableWorkloadProfiles ? searchApiWorkloadProfileName : null
    configuration: {
      ingress: {
        external: true
        targetPort: hasRealImage ? 8000 : 80
        allowInsecure: false
        transport: 'http'
      }
      registries: hasRealImage ? [
        {
          server: acr.properties.loginServer
          identity: 'system'
        }
      ] : []
      secrets: hasRealImage ? realContainerSecrets : []
    }
    template: {
      containers: [
        {
          name: 'docforge'
          image: effectiveImage
          resources: {
            cpu: json('1.0')
            memory: '2Gi'
          }
          env: hasRealImage ? realContainerEnv : []
          probes: probes
        }
      ]
      scale: {
        minReplicas: minReplicas
        maxReplicas: maxReplicas
        rules: [
          {
            name: 'http-rule'
            http: {
              metadata: {
                concurrentRequests: '10'
              }
            }
          }
        ]
      }
    }
  }
}

// ─── Embedder Container App ─────────────────────────────────────────────

var embedderAppName = '${namePrefix}-embedder${nameSuffix}'
var hasRealEmbedderImage = !empty(embedderImage)
var defaultEmbedderImage = 'mcr.microsoft.com/azuredocs/containerapps-helloworld:latest'
var effectiveEmbedderImage = hasRealEmbedderImage ? embedderImage : defaultEmbedderImage

var embedderProbes = hasRealEmbedderImage ? [
  {
    type: 'Startup'
    httpGet: { path: '/health', port: 8001 }
    initialDelaySeconds: 10
    periodSeconds: 10
    timeoutSeconds: 5
    failureThreshold: 30
  }
  {
    type: 'Liveness'
    httpGet: { path: '/health', port: 8001 }
    initialDelaySeconds: 30
    periodSeconds: 30
    timeoutSeconds: 5
    failureThreshold: 3
  }
] : []

var embedderRealSecrets = [
  {
    name: 'embedder-token'
    keyVaultUrl: '${keyVault.properties.vaultUri}secrets/embedder-token'
    identity: 'system'
  }
]

var embedderRealEnv = [
  {
    name: 'EMBEDDER_TOKEN'
    secretRef: 'embedder-token'
  }
  {
    name: 'EMBEDDING_BATCH_SIZE'
    value: string(embedderEmbeddingBatchSize)
  }
  {
    name: 'PYTORCH_CUDA_ALLOC_CONF'
    value: 'expandable_segments:True'
  }
]

resource embedderApp 'Microsoft.App/containerApps@2024-03-01' = {
  name: embedderAppName
  location: location
  tags: tags
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    managedEnvironmentId: containerAppsEnv.id
    workloadProfileName: enableWorkloadProfiles ? embedderWorkloadProfileName : null
    configuration: {
      ingress: {
        external: true
        targetPort: hasRealEmbedderImage ? 8001 : 80
        allowInsecure: false
        transport: 'http'
      }
      registries: hasRealEmbedderImage ? [
        {
          server: acr.properties.loginServer
          identity: 'system'
        }
      ] : []
      secrets: hasRealEmbedderImage ? embedderRealSecrets : []
    }
    template: {
      containers: [
        {
          name: 'docforge-embedder'
          image: effectiveEmbedderImage
          resources: {
            // GPU profile requires integer CPU equal to the full SKU vCPU count;
            // Consumption profile uses fractional CPU via json(). Branch on the
            // active workload profile name.
            cpu: (enableWorkloadProfiles && embedderWorkloadProfileName == 'gpu-nc8as-t4') ? embedderCpu : json('2.0')
            memory: (enableWorkloadProfiles && embedderWorkloadProfileName == 'gpu-nc8as-t4') ? '${embedderMemoryGi}Gi' : '4Gi'
          }
          env: hasRealEmbedderImage ? embedderRealEnv : []
          probes: embedderProbes
        }
      ]
      scale: {
        minReplicas: embedderMinReplicas
        maxReplicas: embedderMaxReplicas
        rules: [
          {
            name: 'http-rule'
            http: {
              metadata: {
                concurrentRequests: '5'
              }
            }
          }
        ]
      }
    }
  }
}

// ─── Reranker Container App ─────────────────────────────────────────────

var rerankerAppName = '${namePrefix}-reranker${nameSuffix}'
var hasRealRerankerImage = !empty(rerankerImage)
var defaultRerankerImage = 'mcr.microsoft.com/azuredocs/containerapps-helloworld:latest'
var effectiveRerankerImage = hasRealRerankerImage ? rerankerImage : defaultRerankerImage

var rerankerProbes = hasRealRerankerImage ? [
  {
    type: 'Startup'
    httpGet: { path: '/health', port: 8002 }
    initialDelaySeconds: 10
    periodSeconds: 10
    timeoutSeconds: 5
    failureThreshold: 30
  }
  {
    type: 'Liveness'
    httpGet: { path: '/health', port: 8002 }
    initialDelaySeconds: 30
    periodSeconds: 30
    timeoutSeconds: 5
    failureThreshold: 3
  }
] : []

// Reuses the embedder-token secret rather than minting a new KV secret —
// the search API and both sidecars share one bearer token.
var rerankerRealSecrets = [
  {
    name: 'embedder-token'
    keyVaultUrl: '${keyVault.properties.vaultUri}secrets/embedder-token'
    identity: 'system'
  }
]

var rerankerRealEnv = [
  {
    name: 'RERANKER_TOKEN'
    secretRef: 'embedder-token'
  }
  {
    name: 'RERANK_MODEL'
    value: rerankModel
  }
  {
    name: 'PYTORCH_CUDA_ALLOC_CONF'
    value: 'expandable_segments:True'
  }
]

resource rerankerApp 'Microsoft.App/containerApps@2024-03-01' = {
  name: rerankerAppName
  location: location
  tags: tags
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    managedEnvironmentId: containerAppsEnv.id
    workloadProfileName: enableWorkloadProfiles ? rerankerWorkloadProfileName : null
    configuration: {
      ingress: {
        external: true
        targetPort: hasRealRerankerImage ? 8002 : 80
        allowInsecure: false
        transport: 'http'
      }
      registries: hasRealRerankerImage ? [
        {
          server: acr.properties.loginServer
          identity: 'system'
        }
      ] : []
      secrets: hasRealRerankerImage ? rerankerRealSecrets : []
    }
    template: {
      containers: [
        {
          name: 'docforge-reranker'
          image: effectiveRerankerImage
          resources: {
            // GPU profile requires integer CPU equal to the full SKU vCPU count;
            // Consumption profile uses fractional CPU via json(). Branch on the
            // active workload profile name.
            cpu: (enableWorkloadProfiles && rerankerWorkloadProfileName == 'gpu-nc8as-t4') ? rerankerCpu : json('2.0')
            memory: (enableWorkloadProfiles && rerankerWorkloadProfileName == 'gpu-nc8as-t4') ? '${rerankerMemoryGi}Gi' : '4Gi'
          }
          env: hasRealRerankerImage ? rerankerRealEnv : []
          probes: rerankerProbes
        }
      ]
      scale: {
        minReplicas: rerankerMinReplicas
        maxReplicas: rerankerMaxReplicas
        rules: [
          {
            name: 'http-rule'
            http: {
              metadata: {
                concurrentRequests: '5'
              }
            }
          }
        ]
      }
    }
  }
}

// ─── Role assignments ───────────────────────────────────────────────────

var keyVaultSecretsUserRoleId = '4633458b-17de-408a-b874-0445c86b69e6'
var acrPullRoleId = '7f951dda-4ed3-4680-a7ca-43fe172d538d'

resource kvSecretsUser 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: keyVault
  name: guid(keyVault.id, containerApp.id, keyVaultSecretsUserRoleId)
  properties: {
    principalId: containerApp.identity.principalId
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', keyVaultSecretsUserRoleId)
    principalType: 'ServicePrincipal'
  }
}

resource acrPull 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: acr
  name: guid(acr.id, containerApp.id, acrPullRoleId)
  properties: {
    principalId: containerApp.identity.principalId
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', acrPullRoleId)
    principalType: 'ServicePrincipal'
  }
}

resource embedderKvSecretsUser 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: keyVault
  name: guid(keyVault.id, embedderApp.id, keyVaultSecretsUserRoleId)
  properties: {
    principalId: embedderApp.identity.principalId
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', keyVaultSecretsUserRoleId)
    principalType: 'ServicePrincipal'
  }
}

resource embedderAcrPull 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: acr
  name: guid(acr.id, embedderApp.id, acrPullRoleId)
  properties: {
    principalId: embedderApp.identity.principalId
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', acrPullRoleId)
    principalType: 'ServicePrincipal'
  }
}

resource rerankerKvSecretsUser 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: keyVault
  name: guid(keyVault.id, rerankerApp.id, keyVaultSecretsUserRoleId)
  properties: {
    principalId: rerankerApp.identity.principalId
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', keyVaultSecretsUserRoleId)
    principalType: 'ServicePrincipal'
  }
}

resource rerankerAcrPull 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: acr
  name: guid(acr.id, rerankerApp.id, acrPullRoleId)
  properties: {
    principalId: rerankerApp.identity.principalId
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', acrPullRoleId)
    principalType: 'ServicePrincipal'
  }
}

// ─── Outputs ────────────────────────────────────────────────────────────

output apiFqdn string = containerApp.properties.configuration.ingress.fqdn
output acrLoginServer string = acr.properties.loginServer
output acrName string = acr.name
output keyVaultName string = keyVault.name
output databaseHost string = postgres.properties.fullyQualifiedDomainName
output databaseName string = databaseName
output containerAppName string = containerApp.name
output embedderFqdn string = embedderApp.properties.configuration.ingress.fqdn
output embedderAppName string = embedderApp.name
output rerankerFqdn string = rerankerApp.properties.configuration.ingress.fqdn
output rerankerAppName string = rerankerApp.name
