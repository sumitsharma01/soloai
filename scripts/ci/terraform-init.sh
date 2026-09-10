#!/usr/bin/env bash
# Run from infra/terraform. Environment values come from GitHub settings, not PR text.
set -euo pipefail
: "${TF_STATE_ACCOUNT:?Set TF_STATE_ACCOUNT}"
: "${TF_STATE_CONTAINER:?Set TF_STATE_CONTAINER}"
: "${TF_STATE_KEY:?Set TF_STATE_KEY}"
: "${TF_CONFIG_JSON:?Set TF_CONFIG_JSON to reviewed non-secret Terraform inputs}"
if [[ -z ${TF_VAR_runtime_database_url:-} ]]; then unset TF_VAR_runtime_database_url; fi
printf '%s' "$TF_CONFIG_JSON" > ci.auto.tfvars.json
terraform init -input=false -lockfile=readonly \
  -backend-config="storage_account_name=$TF_STATE_ACCOUNT" \
  -backend-config="container_name=$TF_STATE_CONTAINER" \
  -backend-config="key=$TF_STATE_KEY" \
  -backend-config=use_azuread_auth=true -backend-config=use_oidc=true
