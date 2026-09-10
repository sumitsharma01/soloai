# 5. BASIC OPERATIONS
# One log workspace, a Workbook, and bounded alerts. No extra collector.
resource "azurerm_log_analytics_workspace" "main" {
  name                = "${var.name_prefix}-logs"
  location            = local.location
  resource_group_name = data.azurerm_resource_group.existing.name
  sku                 = "PerGB2018"
  retention_in_days   = 30
  tags                = local.tags
}

resource "azurerm_monitor_action_group" "operations" {
  count               = var.alert_email == null ? 0 : 1
  name                = "${var.name_prefix}-operations"
  resource_group_name = data.azurerm_resource_group.existing.name
  short_name          = "SoloAI"
  tags                = local.tags

  email_receiver {
    name                    = "operations"
    email_address           = var.alert_email
    use_common_alert_schema = true
  }
}

resource "azurerm_monitor_scheduled_query_rules_alert_v2" "failures" {
  name                 = "${var.name_prefix}-execution-failures"
  resource_group_name  = data.azurerm_resource_group.existing.name
  location             = local.location
  scopes               = [azurerm_log_analytics_workspace.main.id]
  display_name         = "SoloAI execution failures"
  description          = "More than five failed agent executions in five minutes. No message bodies are inspected."
  severity             = 2
  enabled              = true
  evaluation_frequency = "PT5M"
  window_duration      = "PT5M"
  # The table may not exist until the first replica emits a console event.
  skip_query_validation = true
  tags                  = local.tags

  criteria {
    query                   = <<-KQL
      ContainerAppConsoleLogs_CL
      | where ContainerAppName_s == '${local.app_name}'
      | where Log_s contains 'agent.execution'
      | extend execution = parse_json(Log_s)
      | where tostring(execution.status) == 'failed'
    KQL
    time_aggregation_method = "Count"
    operator                = "GreaterThan"
    threshold               = 5
    failing_periods {
      minimum_failing_periods_to_trigger_alert = 1
      number_of_evaluation_periods             = 1
    }
  }

  dynamic "action" {
    for_each = var.alert_email == null ? [] : [true]
    content {
      action_groups = [azurerm_monitor_action_group.operations[0].id]
    }
  }
}

# Export platform metrics into the same workspace for the infrastructure panel.
resource "azurerm_monitor_diagnostic_setting" "infrastructure" {
  for_each = {
    app      = azurerm_container_app.main.id
    database = azurerm_postgresql_flexible_server.main.id
  }
  name                       = "soloai-platform-metrics"
  target_resource_id         = each.value
  log_analytics_workspace_id = azurerm_log_analytics_workspace.main.id
  enabled_metric {
    category = "AllMetrics"
  }
}

# Low-volume traffic should not page on a single slow request. These defaults
# are starting thresholds; tune them using observed production behavior.
resource "azurerm_monitor_scheduled_query_rules_alert_v2" "platform" {
  for_each = {
    http_errors = {
      event       = "http.request"
      aggregate   = "Requests=count(), Bad=countif(toint(e.status_code)>=500)"
      filter      = "Requests >= 20 and Bad*1.0/Requests > 0.05"
      description = "More than 5% HTTP server errors with at least 20 requests in 5 minutes."
    }
    slow_agents = {
      event       = "agent.execution"
      aggregate   = "Requests=count(), P95=percentile(todouble(e.latency_ms),95)"
      filter      = "Requests >= 20 and P95 > 30000"
      description = "Agent P95 exceeds 30 seconds with at least 20 executions in 5 minutes."
    }
  }
  name                  = "${var.name_prefix}-${each.key}"
  resource_group_name   = data.azurerm_resource_group.existing.name
  location              = local.location
  scopes                = [azurerm_log_analytics_workspace.main.id]
  description           = each.value.description
  severity              = 2
  evaluation_frequency  = "PT5M"
  window_duration       = "PT5M"
  skip_query_validation = true
  tags                  = local.tags
  criteria {
    query                   = <<-KQL
      ContainerAppConsoleLogs_CL
      | where ContainerAppName_s == '${local.app_name}'
      | extend e=parse_json(Log_s)
      | where e.event == '${each.value.event}'
      | summarize ${each.value.aggregate}
      | where ${each.value.filter}
    KQL
    time_aggregation_method = "Count"
    operator                = "GreaterThan"
    threshold               = 0
    failing_periods {
      minimum_failing_periods_to_trigger_alert = 1
      number_of_evaluation_periods             = 1
    }
  }
  dynamic "action" {
    for_each = var.alert_email == null ? [] : [true]
    content {
      action_groups = [azurerm_monitor_action_group.operations[0].id]
    }
  }
}
