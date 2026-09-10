# No public Key Vault fallback. Terraform must run from a private-network runner
# with DNS/routing to this endpoint for secret create/read/refresh operations.
resource "azurerm_key_vault" "main" {
  name                          = "${var.name_prefix}-kv-${local.suffix}"
  location                      = local.location
  resource_group_name           = data.azurerm_resource_group.existing.name
  tenant_id                     = data.azurerm_client_config.current.tenant_id
  sku_name                      = "standard"
  rbac_authorization_enabled    = true
  public_network_access_enabled = false
  purge_protection_enabled      = true
  soft_delete_retention_days    = 90
  tags                          = local.tags

  network_acls {
    default_action = "Deny"
    bypass         = "None"
  }

  lifecycle {
    prevent_destroy = true
  }
}

resource "azurerm_private_endpoint" "vault" {
  name                = "${var.name_prefix}-vault-private"
  location            = local.location
  resource_group_name = data.azurerm_resource_group.existing.name
  subnet_id           = azurerm_subnet.endpoints.id
  tags                = local.tags

  private_service_connection {
    name                           = "vault"
    private_connection_resource_id = azurerm_key_vault.main.id
    subresource_names              = ["vault"]
    is_manual_connection           = false
  }

  private_dns_zone_group {
    name                 = "default"
    private_dns_zone_ids = [azurerm_private_dns_zone.vault.id]
  }
}

resource "azurerm_key_vault_secret" "database_url" {
  name         = "database-url"
  value        = local.database_url
  key_vault_id = azurerm_key_vault.main.id
  content_type = "Azure SQL connection URL"
  tags         = local.tags

  depends_on = [
    azurerm_role_assignment.terraform_secret_writer,
    azurerm_private_endpoint.vault,
    azurerm_private_dns_zone_virtual_network_link.vault,
    azurerm_resource_group_template_deployment.database,
  ]
}
