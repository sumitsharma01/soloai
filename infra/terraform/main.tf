# This root composes one small environment. Splitting by responsibility provides
# clear navigation without a module per resource or multiple dependent states.
# Shared ACR and Foundry resources are referenced, never recreated for a tenant.
data "azurerm_client_config" "current" {}

data "azurerm_resource_group" "existing" {
  name = var.resource_group_name
}

data "azurerm_container_registry" "shared" {
  name                = var.registry_name
  resource_group_name = data.azurerm_resource_group.existing.name
}

data "azurerm_cognitive_account" "shared_model" {
  name                = var.model_resource_name
  resource_group_name = data.azurerm_resource_group.existing.name
}

locals {
  location = data.azurerm_resource_group.existing.location
  # Stable across applies, different across environments. Not a secret.
  suffix   = substr(sha256("${var.subscription_id}/${var.resource_group_name}/${var.name_prefix}"), 0, 8)
  app_name = "${var.name_prefix}-app"
  tags = merge(var.tags, {
    application = "SoloAI"
    managed_by  = "Terraform"
  })

  # Subnets are derived, so they remain within the chosen VNet and do not overlap.
  apps_cidr      = cidrsubnet(var.vnet_address_space, 7, 0) # first /23
  database_cidr  = cidrsubnet(var.vnet_address_space, 8, 2) # following /24
  endpoints_cidr = cidrsubnet(var.vnet_address_space, 8, 3) # following /24

  # The environment's default domain exists before the app: no self-reference
  # cycle or two-pass deployment is needed for the origin/CSRF configuration.
  public_origin = coalesce(var.public_origin, "https://${local.app_name}.${azurerm_container_app_environment.main.default_domain}")

  # For staging only. Replace with a migrated runtime role for production.
  # urlencode protects delimiters in generated passwords; secrets stay in state.
  database_url = var.runtime_database_url != null ? var.runtime_database_url : "postgresql+psycopg://soloadmin:${urlencode(var.database_admin_password)}@${azurerm_postgresql_flexible_server.main.fqdn}:5432/soloai?sslmode=require"
}
