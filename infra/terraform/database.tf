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
  storage_mb                    = var.database_storage_mb
  zone                          = var.database_primary_zone
  backup_retention_days         = var.database_backup_days
  geo_redundant_backup_enabled  = false
  delegated_subnet_id           = azurerm_subnet.database.id
  private_dns_zone_id           = azurerm_private_dns_zone.database.id
  public_network_access_enabled = false
  tags                          = local.tags

  dynamic "high_availability" {
    for_each = var.database_ha_enabled ? [true] : []
    content {
      mode                      = "ZoneRedundant"
      standby_availability_zone = var.database_standby_zone
    }
  }

  # A private zone must already be linked before PostgreSQL validates networking.
  depends_on = [azurerm_private_dns_zone_virtual_network_link.database]

  lifecycle {
    prevent_destroy = true
    # Avoid undoing an Azure-managed zone switch after a successful HA failover.
    ignore_changes = [zone, high_availability[0].standby_availability_zone]
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
