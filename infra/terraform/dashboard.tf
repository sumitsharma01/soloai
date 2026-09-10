# A Workbook queries the existing log workspace. No Grafana server, collector,
# Application Insights component, or public metrics endpoint is required.
locals {
  workbook_queries = {
    infrastructure = { title = "Infrastructure metrics (last hour)", seconds = 3600 }
    platform       = { title = "HTTP throughput, errors and latency (last hour)", seconds = 3600 }
    agents         = { title = "Agent latency, tokens and allowance (last hour)", seconds = 3600 }
    slo            = { title = "99% execution success target — rolling 30 days", seconds = 2592000 }
  }
}
resource "azurerm_application_insights_workbook" "operations" {
  name                = uuidv5("url", "${data.azurerm_resource_group.existing.id}/soloai-operations")
  resource_group_name = data.azurerm_resource_group.existing.name
  location            = local.location
  display_name        = "SoloAI operations"
  source_id           = azurerm_log_analytics_workspace.main.id
  tags                = local.tags
  data_json = jsonencode({
    version = "Notebook/1.0"
    items = concat([{ type = 1, content = { json = "# SoloAI operations\nMetadata only. Empty data is not proof of health. SLO excludes user stops and rejected requests; crashes before final events need separate investigation. Infrastructure: open the Container App and PostgreSQL Metrics blades for CPU, memory, replicas, restarts and connections." }, name = "overview" }], [for key, item in local.workbook_queries : {
      type = 3
      name = key
      content = {
        version                 = "KqlItem/1.0"
        title                   = item.title
        query                   = templatefile("${path.module}/queries/${key}.kql", { app_name = local.app_name, app_id = azurerm_container_app.main.id, database_id = azurerm_postgresql_flexible_server.main.id })
        queryType               = 0
        resourceType            = "microsoft.operationalinsights/workspaces"
        crossComponentResources = [azurerm_log_analytics_workspace.main.id]
        timeContext             = { durationMs = item.seconds * 1000 }
        visualization           = "table"
      }
    }])
  })
}
output "operations_workbook_id" {
  description = "Open in Azure Monitor > Workbooks after deployment."
  value       = azurerm_application_insights_workbook.operations.id
}
