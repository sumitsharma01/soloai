# Shared Azure SQL database. The free allowance stops at its monthly limit.
# The private endpoint is billed separately from the database offer.
resource "azurerm_mssql_server" "main" {
  name                          = "${var.name_prefix}-sql-${local.suffix}"
  resource_group_name           = data.azurerm_resource_group.existing.name
  location                      = local.location
  version                       = "12.0"
  administrator_login           = "soloadmin"
  administrator_login_password  = var.database_admin_password
  minimum_tls_version           = "1.2"
  public_network_access_enabled = false
  tags                          = local.tags
  lifecycle { prevent_destroy = true }
}
# The pinned AzureRM provider does not expose free-limit properties. Create the
# database with these flags in the initial request, never as a paid fallback.
resource "azurerm_resource_group_template_deployment" "database" {
  name                = "${var.name_prefix}-free-sql"
  resource_group_name = data.azurerm_resource_group.existing.name
  deployment_mode     = "Incremental"
  template_content = jsonencode({
    "$schema"      = "https://schema.management.azure.com/schemas/2019-04-01/deploymentTemplate.json#"
    contentVersion = "1.0.0.0"
    resources = [{
      type       = "Microsoft.Sql/servers/databases"
      apiVersion = "2023-08-01"
      name       = "${azurerm_mssql_server.main.name}/soloai"
      location   = local.location
      sku        = { name = "GP_S_Gen5_2", tier = "GeneralPurpose", family = "Gen5", capacity = 2 }
      properties = {
        useFreeLimit                     = true
        freeLimitExhaustionBehavior      = "AutoPause"
        minCapacity                      = 0.5
        autoPauseDelay                   = 60
        maxSizeBytes                     = 34359738368
        requestedBackupStorageRedundancy = "Local"
      }
    }]
  })
  lifecycle { prevent_destroy = true }
}
locals {
  sql_database_id = "${azurerm_mssql_server.main.id}/databases/soloai"
}
resource "azurerm_private_endpoint" "database" {
  name                = "${var.name_prefix}-sql-private"
  location            = local.location
  resource_group_name = data.azurerm_resource_group.existing.name
  subnet_id           = azurerm_subnet.endpoints.id
  private_service_connection {
    name                           = "sql"
    private_connection_resource_id = azurerm_mssql_server.main.id
    subresource_names              = ["sqlServer"]
    is_manual_connection           = false
  }
  private_dns_zone_group {
    name                 = "sql"
    private_dns_zone_ids = [azurerm_private_dns_zone.database.id]
  }
  tags = local.tags
}
