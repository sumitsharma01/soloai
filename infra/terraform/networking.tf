# Azure VNet is the equivalent of a VPC. Only the application HTTPS ingress is
# internet-facing. PostgreSQL and Key Vault are reached through private addresses.
resource "azurerm_virtual_network" "main" {
  name                = "${var.name_prefix}-vnet"
  location            = local.location
  resource_group_name = data.azurerm_resource_group.existing.name
  address_space       = [var.vnet_address_space]
  tags                = local.tags
}

resource "azurerm_subnet" "apps" {
  name                 = "apps"
  resource_group_name  = data.azurerm_resource_group.existing.name
  virtual_network_name = azurerm_virtual_network.main.name
  address_prefixes     = [local.apps_cidr]
  delegation {
    name = "container-apps"
    service_delegation {
      name    = "Microsoft.App/environments"
      actions = ["Microsoft.Network/virtualNetworks/subnets/join/action"]
    }
  }
}

resource "azurerm_subnet" "database" {
  name                 = "postgres"
  resource_group_name  = data.azurerm_resource_group.existing.name
  virtual_network_name = azurerm_virtual_network.main.name
  address_prefixes     = [local.database_cidr]
  delegation {
    name = "postgresql"
    service_delegation {
      name    = "Microsoft.DBforPostgreSQL/flexibleServers"
      actions = ["Microsoft.Network/virtualNetworks/subnets/join/action"]
    }
  }
}

resource "azurerm_subnet" "endpoints" {
  name                              = "private-endpoints"
  resource_group_name               = data.azurerm_resource_group.existing.name
  virtual_network_name              = azurerm_virtual_network.main.name
  address_prefixes                  = [local.endpoints_cidr]
  private_endpoint_network_policies = "Disabled"
}

# PostgreSQL VNet integration requires a linked private zone ending in
# postgres.database.azure.com. Key Vault uses its standard Private Link zone.
resource "azurerm_private_dns_zone" "database" {
  name                = "${var.name_prefix}.postgres.database.azure.com"
  resource_group_name = data.azurerm_resource_group.existing.name
  tags                = local.tags
}

resource "azurerm_private_dns_zone_virtual_network_link" "database" {
  name                  = "soloai-database"
  resource_group_name   = data.azurerm_resource_group.existing.name
  private_dns_zone_name = azurerm_private_dns_zone.database.name
  virtual_network_id    = azurerm_virtual_network.main.id
  registration_enabled  = false
  tags                  = local.tags
}

resource "azurerm_private_dns_zone" "vault" {
  name                = "privatelink.vaultcore.azure.net"
  resource_group_name = data.azurerm_resource_group.existing.name
  tags                = local.tags
}

resource "azurerm_private_dns_zone_virtual_network_link" "vault" {
  name                  = "soloai-vault"
  resource_group_name   = data.azurerm_resource_group.existing.name
  private_dns_zone_name = azurerm_private_dns_zone.vault.name
  virtual_network_id    = azurerm_virtual_network.main.id
  registration_enabled  = false
  tags                  = local.tags
}
