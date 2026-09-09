targetScope = 'resourceGroup'
param location string = resourceGroup().location
@minLength(3)
@maxLength(16)
param prefix string = 'soloai'
param image string
param registryName string
param modelResourceName string
param modelDeployment string
@secure()
param databasePassword string
param publicOrigin string
var suffix = uniqueString(resourceGroup().id)
resource identity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: '${prefix}-app'
  location: location
}
resource vnet 'Microsoft.Network/virtualNetworks@2024-05-01' = {
  name: '${prefix}-vnet'
  location: location
  properties: {
    addressSpace: { addressPrefixes: ['10.40.0.0/16'] }
    subnets: [
      { name: 'apps', properties: { addressPrefix: '10.40.0.0/23', delegations: [{ name: 'apps', properties: { serviceName: 'Microsoft.App/environments' } }] } }
      { name: 'postgres', properties: { addressPrefix: '10.40.2.0/24', delegations: [{ name: 'postgres', properties: { serviceName: 'Microsoft.DBforPostgreSQL/flexibleServers' } }] } }
      { name: 'private-endpoints', properties: { addressPrefix: '10.40.3.0/24', privateEndpointNetworkPolicies: 'Disabled' } }
    ]
  }
}
resource dns 'Microsoft.Network/privateDnsZones@2020-06-01' = {
  name: '${prefix}.postgres.database.azure.com'
  location: 'global'
}
resource link 'Microsoft.Network/privateDnsZones/virtualNetworkLinks@2020-06-01' = {
  parent: dns
  name: 'app-network'
  location: 'global'
  properties: { registrationEnabled: false, virtualNetwork: { id: vnet.id } }
}
resource db 'Microsoft.DBforPostgreSQL/flexibleServers@2024-08-01' = {
  name: '${prefix}-pg-${suffix}'
  location: location
  sku: { name: 'Standard_B1ms', tier: 'Burstable' }
  properties: {
    version: '16'
    administratorLogin: 'soloadmin'
    administratorLoginPassword: databasePassword
    storage: { storageSizeGB: 32 }
    backup: { backupRetentionDays: 7, geoRedundantBackup: 'Disabled' }
    network: { delegatedSubnetResourceId: '${vnet.id}/subnets/postgres', privateDnsZoneArmResourceId: dns.id, publicNetworkAccess: 'Disabled' }
  }
  dependsOn: [link]
}
resource database 'Microsoft.DBforPostgreSQL/flexibleServers/databases@2024-08-01' = {
  parent: db
  name: 'soloai'
  properties: { charset: 'UTF8', collation: 'en_US.utf8' }
}
resource vault 'Microsoft.KeyVault/vaults@2023-07-01' = {
  name: '${prefix}-kv-${suffix}'
  location: location
  properties: {
    tenantId: tenant().tenantId
    sku: { family: 'A', name: 'standard' }
    enableRbacAuthorization: true
    enableSoftDelete: true
    enablePurgeProtection: true
    publicNetworkAccess: 'Disabled'
    networkAcls: { defaultAction: 'Deny', bypass: 'AzureServices' }
  }
}
resource vaultDns 'Microsoft.Network/privateDnsZones@2020-06-01' = {
  name: 'privatelink.vaultcore.azure.net'
  location: 'global'
}
resource vaultLink 'Microsoft.Network/privateDnsZones/virtualNetworkLinks@2020-06-01' = {
  parent: vaultDns
  name: 'app-network'
  location: 'global'
  properties: { registrationEnabled: false, virtualNetwork: { id: vnet.id } }
}
resource endpoint 'Microsoft.Network/privateEndpoints@2024-05-01' = {
  name: '${prefix}-vault-private'
  location: location
  properties: {
    subnet: { id: '${vnet.id}/subnets/private-endpoints' }
    privateLinkServiceConnections: [{ name: 'vault', properties: { privateLinkServiceId: vault.id, groupIds: ['vault'] } }]
  }
}
resource group 'Microsoft.Network/privateEndpoints/privateDnsZoneGroups@2024-05-01' = {
  parent: endpoint
  name: 'default'
  properties: { privateDnsZoneConfigs: [{ name: 'vault', properties: { privateDnsZoneId: vaultDns.id } }] }
}
resource secret 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = {
  parent: vault
  name: 'database-url'
  properties: { value: 'postgresql+psycopg://soloadmin:${uriComponent(databasePassword)}@${db.properties.fullyQualifiedDomainName}:5432/soloai?sslmode=require' }
}
resource vaultRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(vault.id, identity.id, 'secrets-user')
  scope: vault
  properties: { principalId: identity.properties.principalId, principalType: 'ServicePrincipal', roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions','4633458b-17de-408a-b874-0445c86b69e6') }
}
resource registry 'Microsoft.ContainerRegistry/registries@2023-07-01' existing = { name: registryName }
resource pull 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(registry.id,identity.id,'pull')
  scope: registry
  properties: { principalId: identity.properties.principalId, principalType: 'ServicePrincipal', roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions','7f951dda-4ed3-4680-a7ca-43fe172d538d') }
}
resource model 'Microsoft.CognitiveServices/accounts@2024-10-01' existing = { name: modelResourceName }
resource modelRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(model.id,identity.id,'inference')
  scope: model
  properties: { principalId: identity.properties.principalId, principalType: 'ServicePrincipal', roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions','5e0bd9bd-7b93-4f28-af87-19fc36ad61bd') }
}
resource logs 'Microsoft.OperationalInsights/workspaces@2023-09-01' = {
  name: '${prefix}-logs'
  location: location
  properties: { sku: { name: 'PerGB2018' }, retentionInDays: 30 }
}
resource insights 'Microsoft.Insights/components@2020-02-02' = {
  name: '${prefix}-insights'
  location: location
  kind: 'web'
  properties: { Application_Type: 'web', WorkspaceResourceId: logs.id }
}
resource environment 'Microsoft.App/managedEnvironments@2024-03-01' = {
  name: '${prefix}-environment'
  location: location
  properties: {
    vnetConfiguration: { infrastructureSubnetId: '${vnet.id}/subnets/apps', internal: false }
    workloadProfiles: [{ name: 'Consumption', workloadProfileType: 'Consumption' }]
    appLogsConfiguration: { destination: 'log-analytics', logAnalyticsConfiguration: { customerId: logs.properties.customerId, sharedKey: logs.listKeys().primarySharedKey } }
  }
}
resource app 'Microsoft.App/containerApps@2024-03-01' = {
  name: '${prefix}-app'
  location: location
  identity: { type: 'UserAssigned', userAssignedIdentities: { '${identity.id}': {} } }
  properties: {
    managedEnvironmentId: environment.id
    configuration: {
      activeRevisionsMode: 'Single'
      ingress: { external: true, targetPort: 8000, allowInsecure: false, transport: 'auto' }
      registries: [{ server: registry.properties.loginServer, identity: identity.id }]
      secrets: [{ name: 'database-url', keyVaultUrl: secret.properties.secretUri, identity: identity.id }]
    }
    template: {
      containers: [{
        name: 'soloai'
        image: image
        resources: { cpu: json('0.5'), memory: '1Gi' }
        env: [
          { name: 'SOLOAI_ENV', value: 'production' }
          { name: 'PUBLIC_ORIGIN', value: publicOrigin }
          { name: 'DATABASE_URL', secretRef: 'database-url' }
          { name: 'AZURE_CLIENT_ID', value: identity.properties.clientId }
          { name: 'AZURE_OPENAI_ENDPOINT', value: model.properties.endpoint }
          { name: 'AZURE_OPENAI_DEPLOYMENT', value: modelDeployment }
        ]
        probes: [{ type: 'Readiness', httpGet: { path: '/health', port: 8000 }, initialDelaySeconds: 10, periodSeconds: 10 }]
      }]
      scale: { minReplicas: 1, maxReplicas: 3, rules: [{ name: 'http', http: { metadata: { concurrentRequests: '20' } } }] }
    }
  }
  dependsOn: [vaultRole,pull,modelRole,database,group,vaultLink]
}
resource failures 'Microsoft.Insights/scheduledQueryRules@2023-12-01' = {
  name: '${prefix}-execution-failures'
  location: location
  properties: {
    displayName: 'SoloAI agent failures'
    severity: 2
    enabled: true
    evaluationFrequency: 'PT5M'
    windowSize: 'PT5M'
    scopes: [logs.id]
    criteria: { allOf: [{ query: 'ContainerAppConsoleLogs_CL | where Log_s contains "agent.execution" | where Log_s contains "failed"', timeAggregation: 'Count', operator: 'GreaterThan', threshold: 5, failingPeriods: { numberOfEvaluationPeriods: 1, minFailingPeriodsToAlert: 1 } }] }
  }
}
output url string = 'https://${app.properties.configuration.ingress.fqdn}'
output logWorkspace string = logs.name
