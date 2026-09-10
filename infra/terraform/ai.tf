# 4. SHARED AI BACKEND
# Reuse one Azure OpenAI account/deployment. No per-user Azure AI resources.
# Its owner must disable public/key-based access first; this root deliberately
# does not take ownership of an existing shared account or change other clients.
data "azurerm_cognitive_account" "shared_model" {
  name                = var.model_resource_name
  resource_group_name = data.azurerm_resource_group.existing.name

  lifecycle {
    postcondition {
      condition     = self.kind == "OpenAI" && !self.public_network_access_enabled && !self.local_auth_enabled
      error_message = "The shared account must be kind OpenAI, with public access and local key authentication disabled. Coordinate with its owner before deploying."
    }
  }
}

resource "azurerm_private_dns_zone" "model" {
  name                = "privatelink.openai.azure.com"
  resource_group_name = data.azurerm_resource_group.existing.name
  tags                = local.tags
}

resource "azurerm_private_dns_zone_virtual_network_link" "model" {
  name                  = "soloai-model"
  resource_group_name   = data.azurerm_resource_group.existing.name
  private_dns_zone_name = azurerm_private_dns_zone.model.name
  virtual_network_id    = azurerm_virtual_network.main.id
  registration_enabled  = false
  tags                  = local.tags
}

resource "azurerm_private_endpoint" "model" {
  name                = "${var.name_prefix}-model-private"
  location            = local.location
  resource_group_name = data.azurerm_resource_group.existing.name
  subnet_id           = azurerm_subnet.endpoints.id
  tags                = local.tags
  private_service_connection {
    name                           = "model"
    private_connection_resource_id = data.azurerm_cognitive_account.shared_model.id
    subresource_names              = ["account"]
    is_manual_connection           = false
  }
  private_dns_zone_group {
    name                 = "default"
    private_dns_zone_ids = [azurerm_private_dns_zone.model.id]
  }
}
