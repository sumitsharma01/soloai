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

  ingress {
    # External to this app, but private to the environment/Private Link.
    external_enabled           = true
    allow_insecure_connections = false
    target_port                = 8000
    transport                  = "auto"
    traffic_weight {
      latest_revision = true
      percentage      = 100
    }
  }

  template {
    min_replicas = var.min_replicas
    max_replicas = var.max_replicas

    http_scale_rule {
      name                = "http"
      concurrent_requests = tostring(var.http_concurrency_target)
    }

    container {
      name   = "soloai"
      image  = var.container_image
      cpu    = 0.5
      memory = "1Gi"

      # Keep operator settings explicit. Tenant settings live in PostgreSQL.
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

      # Readiness checks the DB; a DB outage removes traffic without endlessly
      # restarting containers. TCP liveness checks only that the process listens.
      readiness_probe {
        transport               = "HTTP"
        port                    = 8000
        path                    = "/health"
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
    azurerm_role_assignment.registry_pull,
    azurerm_role_assignment.model_inference,
    azurerm_role_assignment.app_secret_reader,
    azurerm_private_endpoint.model,
    azurerm_private_dns_zone_virtual_network_link.model,
  ]
}
