# Contract tests use a MOCK provider: no Azure login, state backend or resources.
# They verify explicit infrastructure settings, not actual Azure service behavior.
mock_provider "azurerm" {}

override_data {
  target = data.azurerm_client_config.current
  values = {
    tenant_id       = "11111111-1111-1111-1111-111111111111"
    object_id       = "22222222-2222-2222-2222-222222222222"
    subscription_id = "00000000-0000-0000-0000-000000000000"
  }
}

override_data {
  target = data.azurerm_resource_group.existing
  values = {
    name     = "rg-soloai-test"
    location = "westeurope"
    id       = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-soloai-test"
  }
}

override_data {
  target = data.azurerm_container_registry.shared
  values = {
    name         = "soloaitest"
    login_server = "soloaitest.azurecr.io"
    id           = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-soloai-test/providers/Microsoft.ContainerRegistry/registries/soloaitest"
  }
}

override_data {
  target = data.azurerm_cognitive_account.shared_model
  values = {
    name     = "soloai-model"
    endpoint = "https://soloai-model.openai.azure.com/"
    id       = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-soloai-test/providers/Microsoft.CognitiveServices/accounts/soloai-model"
  }
}

variables {
  subscription_id         = "00000000-0000-0000-0000-000000000000"
  resource_group_name     = "rg-soloai-test"
  registry_name           = "soloaitest"
  model_resource_name     = "soloai-model"
  model_deployment_name   = "chat-test"
  container_image         = "soloaitest.azurecr.io/soloai:test-build"
  database_admin_password = "Synthetic-Test-Password-123!"
}

run "private_data_and_bounded_compute" {
  command = plan

  assert {
    condition     = !azurerm_postgresql_flexible_server.main.public_network_access_enabled && !azurerm_key_vault.main.public_network_access_enabled
    error_message = "Database and vault must not allow public network access."
  }
  assert {
    condition     = azurerm_key_vault.main.purge_protection_enabled && azurerm_key_vault.main.rbac_authorization_enabled
    error_message = "Vault RBAC and purge protection must remain enabled."
  }
  assert {
    condition     = !azurerm_container_app.main.ingress[0].allow_insecure_connections
    error_message = "Customer-facing ingress must require HTTPS."
  }
  assert {
    condition     = azurerm_container_app.main.template[0].min_replicas == 1 && azurerm_container_app.main.template[0].max_replicas == 3
    error_message = "Default staging compute must stay bounded at 1–3 replicas."
  }
  assert {
    condition     = azurerm_role_assignment.model_inference.role_definition_name == "Cognitive Services OpenAI User" && azurerm_role_assignment.app_secret_reader.role_definition_name == "Key Vault Secrets User"
    error_message = "Application identity must only receive inference and secret-read roles."
  }
  assert {
    condition     = length(azurerm_monitor_action_group.operations) == 0
    error_message = "No notification recipient should be invented by default."
  }
}

run "optional_ha_profile" {
  command = plan
  variables {
    database_sku        = "GP_Standard_D2s_v3"
    database_ha_enabled = true
    min_replicas        = 2
    max_replicas        = 6
    alert_email         = "operations@example.com"
  }
  assert {
    condition     = azurerm_postgresql_flexible_server.main.high_availability[0].mode == "ZoneRedundant" && azurerm_container_app.main.template[0].min_replicas == 2
    error_message = "HA profile must enable DB zone redundancy and at least two app replicas."
  }
  assert {
    condition     = length(azurerm_monitor_action_group.operations) == 1
    error_message = "An explicit operations email must create an action group."
  }
}

run "reject_ha_on_burstable" {
  command = plan
  variables {
    database_ha_enabled = true
  }
  expect_failures = [var.database_ha_enabled]
}

run "reject_inverted_scaling_limits" {
  command = plan
  variables {
    min_replicas = 4
    max_replicas = 2
  }
  expect_failures = [var.min_replicas]
}

run "reject_unencrypted_origin" {
  command = plan
  variables {
    public_origin = "http://example.com"
  }
  expect_failures = [var.public_origin]
}
