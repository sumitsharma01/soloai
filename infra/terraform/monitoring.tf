# 5. BASIC OPERATIONS
# One log workspace and one failure alert. No unused tracing service or extra collector.
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
