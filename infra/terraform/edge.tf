# 1. INTERNET ENTRY POINT
# Premium is required for a private origin. WAF blocks suspicious/excess traffic
# before it reaches SoloAI. Do not expose the Container Apps origin publicly.
resource "azurerm_cdn_frontdoor_profile" "main" {
  name                = "${var.name_prefix}-frontdoor"
  resource_group_name = data.azurerm_resource_group.existing.name
  sku_name            = "Premium_AzureFrontDoor"
  tags                = local.tags
}

resource "azurerm_cdn_frontdoor_endpoint" "main" {
  name                     = "${var.name_prefix}-${local.suffix}"
  cdn_frontdoor_profile_id = azurerm_cdn_frontdoor_profile.main.id
  tags                     = local.tags
}

resource "azurerm_cdn_frontdoor_firewall_policy" "main" {
  name                = "${replace(var.name_prefix, "-", "")}waf"
  resource_group_name = data.azurerm_resource_group.existing.name
  sku_name            = azurerm_cdn_frontdoor_profile.main.sku_name
  enabled             = true
  mode                = "Prevention"
  tags                = local.tags

  managed_rule {
    type    = "Microsoft_DefaultRuleSet"
    version = "2.1"
    action  = "Block"
  }

  # Per socket IP, including IPv6. Distributed edge counters are approximate;
  # SQL-based per-tenant token/request limits still enforce application budgets.
  custom_rule {
    name                           = "LimitRequestsPerIP"
    enabled                        = true
    priority                       = 10
    type                           = "RateLimitRule"
    action                         = "Block"
    rate_limit_duration_in_minutes = 1
    rate_limit_threshold           = var.edge_requests_per_minute
    match_condition {
      match_variable = "SocketAddr"
      operator       = "IPMatch"
      match_values   = ["0.0.0.0/0", "::/0"]
    }
  }
}

# A WAF definition alone protects nothing: associate it with the public endpoint.
resource "azurerm_cdn_frontdoor_security_policy" "main" {
  name                     = "${var.name_prefix}-waf-binding"
  cdn_frontdoor_profile_id = azurerm_cdn_frontdoor_profile.main.id
  security_policies {
    firewall {
      cdn_frontdoor_firewall_policy_id = azurerm_cdn_frontdoor_firewall_policy.main.id
      association {
        patterns_to_match = ["/*"]
        domain {
          cdn_frontdoor_domain_id = azurerm_cdn_frontdoor_endpoint.main.id
        }
      }
    }
  }
}

resource "azurerm_cdn_frontdoor_origin_group" "main" {
  name                     = "soloai"
  cdn_frontdoor_profile_id = azurerm_cdn_frontdoor_profile.main.id
  session_affinity_enabled = false # Sessions are stored in PostgreSQL, not a replica.
  load_balancing {}
  health_probe {
    protocol            = "Https"
    path                = "/health"
    request_type        = "GET"
    interval_in_seconds = 60
  }
}

resource "azurerm_cdn_frontdoor_origin" "main" {
  name                           = "soloai-private"
  cdn_frontdoor_origin_group_id  = azurerm_cdn_frontdoor_origin_group.main.id
  enabled                        = true
  host_name                      = azurerm_container_app.main.ingress[0].fqdn
  origin_host_header             = azurerm_container_app.main.ingress[0].fqdn
  certificate_name_check_enabled = true
  http_port                      = 80
  https_port                     = 443

  # Front Door creates its managed connection request. Approve that exact
  # request on the Container Apps environment before public traffic can work.
  private_link {
    private_link_target_id = azurerm_container_app_environment.main.id
    target_type            = "managedEnvironments"
    location               = local.location
    request_message        = "SoloAI ${var.name_prefix} Front Door origin"
  }
}

resource "azurerm_cdn_frontdoor_route" "main" {
  name                          = "soloai"
  cdn_frontdoor_endpoint_id     = azurerm_cdn_frontdoor_endpoint.main.id
  cdn_frontdoor_origin_group_id = azurerm_cdn_frontdoor_origin_group.main.id
  cdn_frontdoor_origin_ids      = [azurerm_cdn_frontdoor_origin.main.id]
  patterns_to_match             = ["/*"]
  supported_protocols           = ["Http", "Https"]
  forwarding_protocol           = "HttpsOnly"
  https_redirect_enabled        = true
  link_to_default_domain        = true

  # No cache block: authenticated pages/API responses must not be CDN-cached.
  # Install the WAF binding before adding a route that can serve the application.
  depends_on = [azurerm_cdn_frontdoor_security_policy.main]
}
