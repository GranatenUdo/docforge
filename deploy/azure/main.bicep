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

@description('HuggingFace token for gated-model access (EmbeddingGemma-300M).')
@secure()
param hfToken string

@description('Confluence API token for page crawling.')
@secure()
param confluenceApiToken string

@description('Tags applied to every created resource. Useful for cost allocation or org policies that require specific tags.')
param tags object = {}

// ─── Derived names ──────────────────────────────────────────────────────

var keyVaultName = '${namePrefix}-kv'
var postgresServerName = '${namePrefix}-pg'
var logAnalyticsName = '${namePrefix}-law'
var containerAppsEnvName = '${namePrefix}-env'
var containerAppName = '${namePrefix}-search-api'

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
    name: 'Basic'
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

resource containerAppsEnv 'Microsoft.App/managedEnvironments@2024-03-01' = {
  name: containerAppsEnvName
  location: location
  tags: tags
  properties: {
    appLogsConfiguration: {
      destination: 'log-analytics'
      logAnalyticsConfiguration: {
        customerId: logAnalytics.properties.customerId
        sharedKey: logAnalytics.listKeys().primarySharedKey
      }
    }
  }
}

// ─── Container App ──────────────────────────────────────────────────────

var defaultImage = 'mcr.microsoft.com/azuredocs/containerapps-helloworld:latest'
var effectiveImage = empty(containerImage) ? defaultImage : containerImage

var databaseUrl = 'postgresql://${postgresAdminUser}:${postgresAdminPassword}@${postgres.properties.fullyQualifiedDomainName}:5432/${databaseName}?sslmode=require'

resource secretDatabaseUrl 'Microsoft.KeyVault/vaults/secrets@2024-04-01-preview' = {
  parent: keyVault
  name: 'database-url'
  properties: {
    value: databaseUrl
  }
}

resource containerApp 'Microsoft.App/containerApps@2024-03-01' = {
  name: containerAppName
  location: location
  tags: tags
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    managedEnvironmentId: containerAppsEnv.id
    configuration: {
      ingress: {
        external: true
        targetPort: 8000
        allowInsecure: false
        transport: 'http'
      }
      registries: [
        {
          server: acr.properties.loginServer
          identity: 'system'
        }
      ]
      secrets: [
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
      ]
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
          env: [
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
          ]
          probes: [
            {
              // Startup probe: runs first; allows up to 10 min for the
              // FastAPI lifespan to finish loading the 1.2GB embedding
              // model before Container Apps considers the revision ready.
              // (Container Apps caps initialDelaySeconds at 60, so the
              // long startup is expressed via periodSeconds * failureThreshold.)
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
          ]
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

// ─── Outputs ────────────────────────────────────────────────────────────

output apiFqdn string = containerApp.properties.configuration.ingress.fqdn
output acrLoginServer string = acr.properties.loginServer
output acrName string = acr.name
output keyVaultName string = keyVault.name
output databaseHost string = postgres.properties.fullyQualifiedDomainName
output databaseName string = databaseName
output containerAppName string = containerApp.name
