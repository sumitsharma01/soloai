# Deliberately output identifiers and URLs only, never credentials or tokens.
output "application_url" {
  description = "Cloudflare HTTPS URL for the dashboard and SDK, once DNS and tunnel are healthy."
  value       = local.public_origin
}

output "public_origin" {
  description = "Exact origin accepted by the application's browser mutation guard."
  value       = local.public_origin
}

output "virtual_network_id" {
  description = "VNet to route/peer the Terraform runner to, with private DNS resolution."
  value       = azurerm_virtual_network.main.id
}

output "database_fqdn" {
  description = "Private Azure SQL hostname for migration/restore operations."
  value       = azurerm_mssql_server.main.fully_qualified_domain_name
}

output "key_vault_id" {
  description = "Vault containing the versioned database connection secret."
  value       = azurerm_key_vault.main.id
}

output "application_identity_principal_id" {
  description = "Shared SoloAI infrastructure identity; distinct from application tenant IDs."
  value       = azurerm_user_assigned_identity.app.principal_id
}

output "monitor_workspace_id" {
  description = "Azure resource ID for Monitor queries and operational dashboards."
  value       = azurerm_log_analytics_workspace.main.id
}

output "container_environment_id" {
  description = "Private Azure environment hosting the app and outbound tunnel connector."
  value       = azurerm_container_app_environment.main.id
}

output "cloudflare_tunnel_id" {
  description = "Tunnel identifier for diagnostics; no connector token is output."
  value       = cloudflare_zero_trust_tunnel_cloudflared.main.id
}
