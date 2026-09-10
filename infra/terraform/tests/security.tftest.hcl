# Contract tests use a MOCK provider: no Azure login, state backend or resources.
# They verify explicit infrastructure settings, not actual Azure service behavior.
mock_provider "azurerm" {}
mock_provider "cloudflare" {}

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
    kind                          = "OpenAI"
    public_network_access_enabled = false
    local_auth_enabled            = false
    name                          = "soloai-model"
    endpoint                      = "https://soloai-model.openai.azure.com/"
    id                            = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-soloai-test/providers/Microsoft.CognitiveServices/accounts/soloai-model"
  }
}

variables {
  cloudflare_account_id   = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
  cloudflare_zone_id      = "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
  public_hostname         = "soloai.example.com"
  cloudflared_image       = "cloudflare/cloudflared:2026.3.0"
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
    condition     = !azurerm_mssql_server.main.public_network_access_enabled && !azurerm_key_vault.main.public_network_access_enabled
    error_message = "Database and vault must not allow public network access."
  }
  assert {
    condition     = azurerm_key_vault.main.purge_protection_enabled && azurerm_key_vault.main.rbac_authorization_enabled
    error_message = "Vault RBAC and purge protection must remain enabled."
  }
  assert {
    condition     = length(azurerm_container_app.main.ingress) == 0
    error_message = "The Azure app must have no direct ingress."
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

run "private_edge_with_waf" {
  command = plan
  assert {
    condition     = azurerm_container_app_environment.main.public_network_access == "Disabled" && azurerm_container_app_environment.main.internal_load_balancer_enabled
    error_message = "The app origin must not be publicly reachable around the WAF."
  }
  assert {
    condition     = cloudflare_zero_trust_tunnel_cloudflared_config.main.config.ingress[0].service == "http://localhost:8000" && cloudflare_zero_trust_tunnel_cloudflared_config.main.config.ingress[1].service == "http_status:404"
    error_message = "Only the configured hostname may route to the local app."
  }
  assert {
    condition     = cloudflare_dns_record.app.proxied && cloudflare_zone_setting.https.value == "on"
    error_message = "The public hostname must use Cloudflare and HTTPS."
  }
  assert {
    condition     = cloudflare_ruleset.rate_limit.rules[0].action == "block" && cloudflare_ruleset.rate_limit.rules[0].ratelimit.period == 10 && cloudflare_ruleset.rate_limit.rules[0].ratelimit.requests_per_period == 50
    error_message = "Default edge rate control must block excessive requests."
  }
  assert {
    condition     = cloudflare_ruleset.no_cache.rules[0].action_parameters.cache == false
    error_message = "Authenticated content must not be cached."
  }
  assert {
    condition     = azurerm_container_app.main.template[0].container[0].name == "cloudflared" && length(azurerm_container_app.main.template[0].http_scale_rule) == 0
    error_message = "The app needs a tunnel connector and must not rely on ingress HTTP scaling."
  }
  assert {
    condition     = azurerm_private_dns_zone.model.name == "privatelink.openai.azure.com" && contains(azurerm_private_endpoint.model.private_service_connection[0].subresource_names, "account")
    error_message = "Inference needs the model private endpoint and matching DNS."
  }
}

run "scale_and_alert_without_extra_services" {
  command = plan
  variables {
    min_replicas = 2
    max_replicas = 6
    alert_email  = "operations@example.com"
  }
  assert {
    condition     = azurerm_container_app.main.template[0].min_replicas == 2 && length(azurerm_monitor_action_group.operations) == 1
    error_message = "Replica settings and an explicit alert recipient must remain configurable."
  }
}

run "reject_inverted_scaling_limits" {
  command = plan
  variables {
    min_replicas = 4
    max_replicas = 2
  }
  expect_failures = [var.min_replicas]
}

run "reject_invalid_edge_limit" {
  command = plan
  variables {
    edge_requests_per_10_seconds = 0
  }
  expect_failures = [var.edge_requests_per_10_seconds]
}

run "reject_public_model" {
  command = plan
  override_data {
    target = data.azurerm_cognitive_account.shared_model
    values = {
      name                          = "soloai-model"
      kind                          = "OpenAI"
      endpoint                      = "https://soloai-model.openai.azure.com/"
      id                            = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-soloai-test/providers/Microsoft.CognitiveServices/accounts/soloai-model"
      public_network_access_enabled = true
      local_auth_enabled            = false
    }
  }
  expect_failures = [data.azurerm_cognitive_account.shared_model]
}

run "reject_key_authenticated_model" {
  command = plan
  override_data {
    target = data.azurerm_cognitive_account.shared_model
    values = {
      name                          = "soloai-model"
      kind                          = "OpenAI"
      endpoint                      = "https://soloai-model.openai.azure.com/"
      id                            = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-soloai-test/providers/Microsoft.CognitiveServices/accounts/soloai-model"
      public_network_access_enabled = false
      local_auth_enabled            = true
    }
  }
  expect_failures = [data.azurerm_cognitive_account.shared_model]
}

run "sql_free_allowance_stops_at_limit" {
  command = plan
  assert {
    condition     = jsondecode(azurerm_resource_group_template_deployment.database.template_content).resources[0].properties.useFreeLimit == true && jsondecode(azurerm_resource_group_template_deployment.database.template_content).resources[0].properties.freeLimitExhaustionBehavior == "AutoPause"
    error_message = "The database must request the free offer and stop at the monthly limit."
  }
  assert {
    condition     = azurerm_mssql_server.main.minimum_tls_version == "1.2" && !azurerm_mssql_server.main.public_network_access_enabled
    error_message = "SQL must require TLS and private access."
  }
}
