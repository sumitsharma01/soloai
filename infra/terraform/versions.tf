# One state per environment. Provider versions are constrained here and the exact
# selected versions/checksums are committed in .terraform.lock.hcl.
terraform {
  required_version = ">= 1.10.0, < 2.0.0"

  required_providers {
    cloudflare = {
      source  = "cloudflare/cloudflare"
      version = "~> 5.17"
    }
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 4.0"
    }
  }

  # Bootstrap this Storage Account/container separately. Never place state in Git.
  # Values come from a local backend.hcl file; authentication uses Entra ID/OIDC.
  backend "azurerm" {}
}

provider "azurerm" {
  subscription_id                 = var.subscription_id
  resource_provider_registrations = "none"
  features {}
}

provider "cloudflare" {}
