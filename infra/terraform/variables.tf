# Inputs are grouped in the same order as the infrastructure files. Secrets have
# no defaults: supply them from your secret store using TF_VAR_* environment vars.

# ---- Deployment identity and existing shared resources ----
variable "subscription_id" {
  description = "Azure subscription containing the existing resource group."
  type        = string
}

variable "resource_group_name" {
  description = "Existing resource group for this environment; Terraform does not own/delete it."
  type        = string
}

variable "name_prefix" {
  description = "Short lowercase environment prefix. A deterministic suffix makes global names unique."
  type        = string
  default     = "soloai-dev"
  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{2,11}$", var.name_prefix))
    error_message = "Use 3–12 lowercase letters, numbers or hyphens, starting with a letter."
  }
}

variable "tags" {
  description = "Additional ownership, environment and cost-allocation tags."
  type        = map(string)
  default     = {}
}

variable "registry_name" {
  description = "Existing ACR in this resource group, using Registry RBAC permissions mode."
  type        = string
}

variable "model_resource_name" {
  description = "Existing shared Azure OpenAI account in this resource group. Not a per-tenant resource."
  type        = string
}

variable "model_deployment_name" {
  description = "Existing Foundry deployment supporting OpenAI v1 chat completions and max_completion_tokens."
  type        = string
}

# ---- Private network ----
variable "vnet_address_space" {
  description = "Non-overlapping /16 IPv4 range. Peered runner networks must not overlap it."
  type        = string
  default     = "10.40.0.0/16"
  validation {
    condition     = can(cidrnetmask(var.vnet_address_space)) && endswith(var.vnet_address_space, "/16")
    error_message = "Provide a valid IPv4 /16 network, for example 10.40.0.0/16."
  }
}

# ---- Database: one small server, 32 GiB, seven-day backups ----
variable "database_admin_password" {
  description = "Bootstrap PostgreSQL administrator password. Sensitive, but still present in Terraform state."
  type        = string
  sensitive   = true
  validation {
    condition     = length(var.database_admin_password) >= 16 && length(var.database_admin_password) <= 128 && can(regex("^[^[:space:]]+$", var.database_admin_password))
    error_message = "Use a strong generated password between 16 and 128 characters without whitespace."
  }
}

variable "database_sku" {
  description = "Flexible Server size. Start small; raise this after measuring database load."
  type        = string
  default     = "B_Standard_B1ms"
}

variable "runtime_database_url" {
  description = "Optional URL for a pre-provisioned least-privilege DB role. Null uses the bootstrap administrator for staging only."
  type        = string
  sensitive   = true
  default     = null
  validation {
    condition     = var.runtime_database_url == null ? true : startswith(var.runtime_database_url, "postgresql+psycopg://") && can(regex("sslmode=(require|verify-ca|verify-full)", var.runtime_database_url))
    error_message = "Use a postgresql+psycopg:// URL with an explicit TLS sslmode."
  }
}

variable "initialize_schema" {
  description = "Run startup CREATE TABLE statements. Disable after a separate migration and runtime-role setup."
  type        = bool
  default     = true
}

# ---- Application and scaling ----
variable "container_image" {
  description = "Already-pushed image in the supplied ACR, pinned by build tag or digest. Never use latest."
  type        = string
  validation {
    condition     = startswith(var.container_image, "${var.registry_name}.azurecr.io/") && !endswith(var.container_image, ":latest") && can(regex("(:[^/]+|@sha256:[a-f0-9]{64})$", var.container_image))
    error_message = "Use an immutable build tag or digest from the configured ACR; latest is not accepted."
  }
}

variable "min_replicas" {
  description = "Minimum running application replicas. Two reduces exposure to a single replica failure."
  type        = number
  default     = 1
  validation {
    condition     = var.min_replicas >= 1 && var.min_replicas <= var.max_replicas && floor(var.min_replicas) == var.min_replicas
    error_message = "min_replicas must be an integer >= 1 and <= max_replicas."
  }
}

variable "max_replicas" {
  description = "Application replica ceiling. Increasing this does not increase database or Foundry quota."
  type        = number
  default     = 3
  validation {
    condition     = var.max_replicas >= 1 && var.max_replicas <= 20 && floor(var.max_replicas) == var.max_replicas
    error_message = "Choose an integer replica ceiling between 1 and 20, then load-test database/model capacity."
  }
}

variable "http_concurrency_target" {
  description = "HTTP scaling target per replica; it is not a hard request/admission limit."
  type        = number
  default     = 20
  validation {
    condition     = var.http_concurrency_target >= 1 && floor(var.http_concurrency_target) == var.http_concurrency_target
    error_message = "Use a positive integer concurrency target."
  }
}

# ---- Monitoring ----
variable "alert_email" {
  description = "Optional operations email for Azure Monitor alerts. Null creates portal-visible alerts only."
  type        = string
  default     = null
  validation {
    condition     = var.alert_email == null ? true : can(regex("^[^@ ]+@[^@ ]+\\.[^@ ]+$", var.alert_email))
    error_message = "Supply a valid operations email or null."
  }
}

# ---- Edge protection ----
variable "edge_requests_per_minute" {
  description = "Approximate WAF threshold per socket IP per minute; not a per-tenant token budget."
  type        = number
  default     = 300
  validation {
    condition     = var.edge_requests_per_minute >= 1 && floor(var.edge_requests_per_minute) == var.edge_requests_per_minute
    error_message = "Use a positive integer edge rate threshold."
  }
}
