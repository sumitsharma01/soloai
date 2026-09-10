# One database holds tenant-scoped configuration and operational metadata.
# Agent instances are rows, not database servers. Message bodies are not stored.
resource "azurerm_postgresql_flexible_server" "main" {
  name                          = "${var.name_prefix}-pg-${local.suffix}"
  resource_group_name           = data.azurerm_resource_group.existing.name
  location                      = local.location
  version                       = "16"
  administrator_login           = "soloadmin"
  administrator_password        = var.database_admin_password
  sku_name                      = var.database_sku
  storage_mb                    = 32768
  backup_retention_days         = 7
  geo_redundant_backup_enabled  = false
  delegated_subnet_id           = azurerm_subnet.database.id
  private_dns_zone_id           = azurerm_private_dns_zone.database.id
  public_network_access_enabled = false
  tags                          = local.tags

  # A private zone must already be linked before PostgreSQL validates networking.
  depends_on = [azurerm_private_dns_zone_virtual_network_link.database]

  lifecycle {
    prevent_destroy = true
  }
}

resource "azurerm_postgresql_flexible_server_database" "soloai" {
  name      = "soloai"
  server_id = azurerm_postgresql_flexible_server.main.id
  charset   = "UTF8"
  collation = "en_US.utf8"
  lifecycle {
    prevent_destroy = true
  }
}
