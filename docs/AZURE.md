# Deploy the minimal private-edge architecture

The supported path is **Terraform** under `infra/terraform`. Both CI pipelines validate only; applying infrastructure is an explicit operation from a private runner. No Azure deployment has been performed by this repository change.

## 1. Prepare the existing resources

- An environment resource group, an ACR with a versioned SoloAI image, and one shared Azure OpenAI account/model deployment in the same group.
- The model account must have public network access and local API-key authentication disabled. Coordinate this with its owner if other clients use it. They also need private connectivity and Entra ID authentication. Terraform checks these settings and creates the private endpoint/DNS; it does not change the account's other settings.
- An existing protected Azure Blob state container: Entra ID access, restricted network, versioning/soft delete, separate state key per environment. State and plan files contain secrets.
- A private runner with Azure CLI/Terraform, routing and DNS access to the new private services. The provisioning principal needs resource write/role-assignment rights, state Blob Data Contributor, and authority to create private connections to the shared account. The app gets only AcrPull, model inference and secret-read roles.
- Register `Microsoft.Cdn`, `Microsoft.App`, `Microsoft.Network`, `Microsoft.KeyVault`, `Microsoft.Sql`, `Microsoft.ManagedIdentity`, `Microsoft.OperationalInsights`, `Microsoft.Insights`, `Microsoft.ContainerRegistry` and `Microsoft.CognitiveServices`.

Use a region supporting Front Door Private Link for Container Apps. Front Door Premium is required; it adds a baseline charge even with little traffic. There are also private-endpoint and service charges. Review those before applying.

## 2. Configure and review

From `infra/terraform`, copy the two `.example` files to `terraform.tfvars` and `backend.hcl`, and replace their placeholders. Authenticate through Azure CLI or your approved OIDC setup. Provide `TF_VAR_database_admin_password` through a secret store or Terraform's sensitive prompt, never a committed file or shell command history.

```bash
terraform init -reconfigure -backend-config=backend.hcl
terraform plan -out=soloai.tfplan
# Review the exact changes, then apply that reviewed plan.
terraform apply soloai.tfplan
```

Do not share the saved plan publicly. `prevent_destroy` protects the database/vault from planned removal but is not a backup or security boundary.

### First private-network bootstrap

Key Vault has no public fallback. A hosted CI runner cannot read/write its secret. If the runner's network cannot yet reach the new VNet, bootstrap only the vault/network dependency graph in the same state:

```bash
terraform plan \
  -target=azurerm_private_endpoint.vault \
  -target=azurerm_private_dns_zone_virtual_network_link.vault \
  -out=network-bootstrap.tfplan
terraform apply network-bootstrap.tfplan
```

Arrange runner VNet peering/routing and private DNS forwarding or zone links, then run an **untargeted** plan/apply from that runner. Peering alone does not solve DNS. Runner compute/connectivity is a platform prerequisite, not another application service. Do not put runner VMs in the delegated app/database subnets. Do not enable public access to get past a failed apply.

New Azure role assignments can take time to propagate. Check identity and DNS/routing before retrying a normal apply; do not broaden permissions as a workaround.

## 3. Activate the Front Door private origin

Azure Front Door creates a managed private-connection request on the Container Apps environment. In the portal, open the environment → Networking → Private endpoint connections. Verify its origin/profile and the request description **`SoloAI <name_prefix> Front Door origin`**, then approve the matching request. Do not approve unrelated connections. This approval is intentionally not an automatic approve-all script.

Until approval and Azure propagation complete, Front Door may return an origin error. Keep public origin access disabled. The application URL and SDK base URL are both `terraform output -raw application_url`. The generated Front Door hostname is the initial public hostname; custom domains/certificates can be added later.

`external_enabled=true` on the individual app means the environment ingress can route to it; **the environment itself is internal and has public access disabled**. The Front Door origin uses `managedEnvironments` Private Link. Front Door owns that managed connection; the VNet endpoint subnet holds the separate Key Vault and AI endpoints.

## 4. Verify before real customers

1. Open the Front Door HTTPS URL; check registration/login and a synthetic chat/email draft.
2. From the public internet, direct access to the Container Apps hostname must fail. Direct model access must also fail.
3. From the private network, resolve the model and vault names to private IPs. Test model inference using the app identity.
4. Inspect the WAF association: Prevention mode, managed rules, rate-limit rule and all paths `/*`. Tune against legitimate messages; free-text prompts can match generic WAF rules. Avoid broad exclusions or disabling inspection.
5. Use a controlled rate test from one IP and check WAF metrics/block responses. Its distributed counter is approximate; do not expect an exact global cutoff.
6. Verify tenant A cannot see B's config/history and that SQL token limits still block expensive work independently of WAF.
7. Test private-link approval, DB outage/readiness, key rotation, emergency stop and backup restore. Configure `alert_email` if someone should receive failure notifications.

This is a one-region, one-database starter. No zone-redundant HA, automatic model retry, durable job recovery or multi-region failover is included. Application minimum replicas alone do not establish an SLA.

## Runtime database role

The default creates the staging schema using `soloadmin`. Before production, migrate the schema with a separate elevated identity, provision a DML-only runtime role, set sensitive `runtime_database_url`, and set `initialize_schema=false`. Update secrets through Terraform to avoid drift. RLS, verified identity/recovery and a trusted-proxy-aware login limiter remain application launch work.

The existing login limiter uses the immediate peer address. Behind ingress, unrelated users may share that address and be throttled together. WAF socket-IP rate limiting adds perimeter protection but does not correct that application behavior. Test concurrent logins before public signup.

## Upgrading the earlier layout

- `internal_load_balancer_enabled` changes can **replace the Container Apps environment and app**. Review the plan and schedule downtime or use a separately named environment. Do not apply blindly to live traffic.
- Application Insights is removed because no application instrumentation used it. Terraform will plan its removal if it was deployed; export any externally added telemetry first.
- Old `public_origin`, database HA/zone/storage/retention input switches were removed. Remove those keys from your tfvars. The first version fixes storage at 32 GiB and retention at seven days; explicitly preserve larger settings in code before planning an upgrade of a larger database.
- Keep an existing HA configuration if one is already running; do not remove it inadvertently when adopting this minimal starter. Review any SKU/HA/zone change separately.
- The original `infra/main.bicep`, `infra/legacy/azure-pipelines-bicep.yml` and [old deployment guide](LEGACY_BICEP.md) are legacy only. They do not provide the new private-edge design. Do not run them against Terraform-owned resources. Import/migration requires a complete resource inventory and reviewed plan; matching names does not transfer ownership.

## Official references

- [Private Front Door origin for Container Apps](https://learn.microsoft.com/en-us/azure/container-apps/front-door-custom-virtual-network-private-link)
- [Front Door WAF rate-limit behavior](https://learn.microsoft.com/en-us/azure/web-application-firewall/afds/waf-front-door-rate-limit)
- [AzureRM origin Private Link](https://registry.terraform.io/providers/hashicorp/azurerm/latest/docs/resources/cdn_frontdoor_origin)
