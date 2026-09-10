# Azure identity is shared by SoloAI replicas. It is NOT the tenant identity.
# Application auth/database scoping isolates tenants above this infrastructure.
resource "azurerm_user_assigned_identity" "app" {
  name                = "${var.name_prefix}-app"
  resource_group_name = data.azurerm_resource_group.existing.name
  location            = local.location
  tags                = local.tags
}

resource "azurerm_role_assignment" "registry_pull" {
  scope                = data.azurerm_container_registry.shared.id
  role_definition_name = "AcrPull"
  principal_id         = azurerm_user_assigned_identity.app.principal_id
  principal_type       = "ServicePrincipal"
}

resource "azurerm_role_assignment" "model_inference" {
  scope                = data.azurerm_cognitive_account.shared_model.id
  role_definition_name = "Cognitive Services OpenAI User"
  principal_id         = azurerm_user_assigned_identity.app.principal_id
  principal_type       = "ServicePrincipal"
}

resource "azurerm_role_assignment" "app_secret_reader" {
  scope                = azurerm_key_vault.main.id
  role_definition_name = "Key Vault Secrets User"
  principal_id         = azurerm_user_assigned_identity.app.principal_id
  principal_type       = "ServicePrincipal"
}

# The deployment principal needs data-plane rights to write/refresh the secret.
# This is intentionally distinct from the application's read-only vault role.
resource "azurerm_role_assignment" "terraform_secret_writer" {
  scope                = azurerm_key_vault.main.id
  role_definition_name = "Key Vault Secrets Officer"
  principal_id         = data.azurerm_client_config.current.object_id
}
