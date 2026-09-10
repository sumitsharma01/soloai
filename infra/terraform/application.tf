# One shared application deployment serves every tenant. Scaling replicas changes
# service capacity; enabling an agent never changes this Terraform resource.
resource "azurerm_container_app_environment" "main" {
  name                           = "${var.name_prefix}-environment"
  location                       = local.location
  resource_group_name            = data.azurerm_resource_group.existing.name
  infrastructure_subnet_id       = azurerm_subnet.apps.id
  internal_load_balancer_enabled = true
  public_network_access          = "Disabled"
  logs_destination               = "log-analytics"
  log_analytics_workspace_id     = azurerm_log_analytics_workspace.main.id
  tags                           = local.tags

  workload_profile {
    name                  = "Consumption"
    workload_profile_type = "Consumption"
  }
}

resource "azurerm_container_app" "main" {
  name                         = local.app_name
  container_app_environment_id = azurerm_container_app_environment.main.id
  resource_group_name          = data.azurerm_resource_group.existing.name
  revision_mode                = "Single"
  workload_profile_name        = "Consumption"
  tags                         = local.tags

  identity {
    type         = "UserAssigned"
    identity_ids = [azurerm_user_assigned_identity.app.id]
  }

  registry {
    server   = data.azurerm_container_registry.shared.login_server
    identity = azurerm_user_assigned_identity.app.id
  }

  # A versioned reference is deliberate: a changed URL requires a reviewed apply.
  # No raw database password appears in the container's environment definition.
  secret {
    name                = "database-url"
    identity            = azurerm_user_assigned_identity.app.id
    key_vault_secret_id = azurerm_key_vault_secret.database_url.id
  }

  secret {
    name  = "tunnel-token"
    value = data.cloudflare_zero_trust_tunnel_cloudflared_token.main.token
  }

  template {
    min_replicas = var.min_replicas
    max_replicas = var.max_replicas

    # No app ingress or HTTP autoscaling. Set min_replicas for capacity.
    container {
      name   = "cloudflared"
      image  = var.cloudflared_image
      cpu    = 0.25
      memory = "0.5Gi"
      args   = ["tunnel", "--no-autoupdate", "run"]
      env {
        name        = "TUNNEL_TOKEN"
        secret_name = "tunnel-token"
      }
    }

    container {
      name   = "soloai"
      image  = var.container_image
      cpu    = 0.5
      memory = "1Gi"

      # Keep operator settings explicit. Tenant settings live in Azure SQL.
      env {
        name  = "SOLOAI_ENV"
        value = "production"
      }
      env {
        name  = "PUBLIC_ORIGIN"
        value = local.public_origin
      }
      env {
        name        = "DATABASE_URL"
        secret_name = "database-url"
      }
      env {
        name  = "SOLOAI_INIT_SCHEMA"
        value = tostring(var.initialize_schema)
      }
      env {
        name  = "AZURE_CLIENT_ID"
        value = azurerm_user_assigned_identity.app.client_id
      }
      env {
        name  = "AZURE_OPENAI_ENDPOINT"
        value = data.azurerm_cognitive_account.shared_model.endpoint
      }
      env {
        name  = "AZURE_OPENAI_DEPLOYMENT"
        value = var.model_deployment_name
      }

      # Readiness checks the process without waking a paused SQL database.
      # /health remains an on-demand database check for deployment verification.
      readiness_probe {
        transport               = "HTTP"
        port                    = 8000
        path                    = "/live"
        initial_delay           = 10
        interval_seconds        = 10
        failure_count_threshold = 3
      }
      liveness_probe {
        transport               = "TCP"
        port                    = 8000
        initial_delay           = 30
        interval_seconds        = 30
        failure_count_threshold = 3
      }
    }
  }

  depends_on = [
    cloudflare_zero_trust_tunnel_cloudflared_config.main,
    azurerm_role_assignment.registry_pull,
    azurerm_role_assignment.model_inference,
    azurerm_role_assignment.app_secret_reader,
    azurerm_private_endpoint.model,
    azurerm_private_endpoint.database,
    azurerm_private_dns_zone_virtual_network_link.model,
  ]
}
