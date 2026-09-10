# Cloudflare Free edge. CLOUDFLARE_API_TOKEN authenticates the provider.
resource "cloudflare_zero_trust_tunnel_cloudflared" "main" {
  account_id = var.cloudflare_account_id
  name       = "${var.name_prefix}-soloai"
  config_src = "cloudflare"
}
data "cloudflare_zero_trust_tunnel_cloudflared_token" "main" {
  account_id = var.cloudflare_account_id
  tunnel_id  = cloudflare_zero_trust_tunnel_cloudflared.main.id
}
resource "cloudflare_zero_trust_tunnel_cloudflared_config" "main" {
  account_id = var.cloudflare_account_id
  tunnel_id  = cloudflare_zero_trust_tunnel_cloudflared.main.id
  config = {
    ingress = [
      { hostname = var.public_hostname, service = "http://localhost:8000" },
      { service = "http_status:404" }
    ]
  }
}
resource "cloudflare_dns_record" "app" {
  zone_id = var.cloudflare_zone_id
  name    = var.public_hostname
  content = "${cloudflare_zero_trust_tunnel_cloudflared.main.id}.cfargotunnel.com"
  type    = "CNAME"
  ttl     = 1
  proxied = true
}
# Zone-wide setting: review other applications before taking ownership.
resource "cloudflare_zone_setting" "https" {
  zone_id    = var.cloudflare_zone_id
  setting_id = "always_use_https"
  value      = "on"
}
# Import existing entrypoint rulesets before managing these phases here.
resource "cloudflare_ruleset" "no_cache" {
  zone_id = var.cloudflare_zone_id
  name    = "SoloAI private responses"
  kind    = "zone"
  phase   = "http_request_cache_settings"
  rules = [{
    action            = "set_cache_settings"
    expression        = "(http.host eq \"${var.public_hostname}\")"
    action_parameters = { cache = false }
    description       = "Never cache SoloAI responses"
    enabled           = true
  }]
}
# Free allows one rule with a 10-second period and mitigation timeout.
resource "cloudflare_ruleset" "rate_limit" {
  zone_id = var.cloudflare_zone_id
  name    = "SoloAI API rate limit"
  kind    = "zone"
  phase   = "http_ratelimit"
  rules = [{
    action     = "block"
    expression = "(starts_with(http.request.uri.path, \"/api/\"))"
    enabled    = true
    ratelimit = {
      characteristics     = ["cf.colo.id", "ip.src"]
      period              = 10
      requests_per_period = var.edge_requests_per_10_seconds
      mitigation_timeout  = 10
    }
  }]
}
# Free Managed Ruleset is deployed automatically by Cloudflare on Free zones.
# This stack does not subscribe to a paid plan or add paid managed rulesets.
