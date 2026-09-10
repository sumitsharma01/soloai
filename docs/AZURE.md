# Deploy the minimal private-edge architecture

The supported path is **Terraform** under `infra/terraform`. GitHub Actions supports opt-in reviewed-plan deployment from a private runner; see [CI/CD](CICD.md). No Azure deployment has been performed by this repository change.

## 1. Prepare the existing resources

- An environment resource group, an ACR with a versioned SoloAI image, and one shared Azure OpenAI account/model deployment in the same group.
- The model account must have public network access and local API-key authentication disabled. Coordinate this with its owner if other clients use it. They also need private connectivity and Entra ID authentication. Terraform checks these settings and creates the private endpoint/DNS; it does not change the account's other settings.
- An existing protected Azure Blob state container: Entra ID access, restricted network, versioning/soft delete, separate state key per environment. State and plan files contain secrets.
- A private runner with Azure CLI/Terraform, routing and DNS access to the new private services. The provisioning principal needs resource write/role-assignment rights, state Blob Data Contributor, and authority to create private connections to the shared account. The app gets only AcrPull, model inference and secret-read roles.
- Register `Microsoft.App`, `Microsoft.Network`, `Microsoft.KeyVault`, `Microsoft.Sql`, `Microsoft.ManagedIdentity`, `Microsoft.OperationalInsights`, `Microsoft.Insights`, `Microsoft.ContainerRegistry` and `Microsoft.CognitiveServices`.

Prepare an existing Cloudflare Free zone, public hostname and scoped API token using [Cloudflare setup](CLOUDFLARE.md). Azure compute, private endpoints and model usage remain billable.

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

## 3. Verify the tunnel and application

Terraform creates the tunnel, DNS record, HTTPS setting, cache bypass and API rate rule.
The cloudflared sidecar connects outbound and forwards to localhost:8000. The app has
no managed ingress. Use `terraform output -raw application_url` after DNS activation,
certificate issuance and the tunnel connector becoming healthy.

1. Confirm the Free Managed Ruleset is enabled in Cloudflare. Test HTTPS login and a synthetic agent request.
2. Confirm there is no public Container Apps ingress or alternate origin URL.
3. Resolve SQL, vault and model endpoints to private addresses from the app network.
4. Test rate blocking from one controlled IP and inspect Cloudflare security events.
5. Verify tenant isolation, token limits and emergency stop using two test workspaces.
6. Stop/restart a connector and check recovery. Test database and model failures.
7. Check logs, alerts and backup restore before accepting customer data.

The connector requires outbound connectivity to Cloudflare. At least one replica must
run continuously. There is no HTTP autoscaler in this tunnel layout; increase
`min_replicas` deliberately after measuring load. Multiple replicas share SQL state.
This single-region starter does not provide guaranteed HA or durable job recovery.

## Runtime database role

The default creates the staging schema using `soloadmin`. Before production, migrate the schema with a separate elevated identity, provision a DML-only runtime role, set sensitive `runtime_database_url`, and set `initialize_schema=false`. Update secrets through Terraform to avoid drift. RLS, verified identity/recovery and a trusted-proxy-aware login limiter remain application launch work.

The existing login limiter uses the immediate peer address. Behind ingress, unrelated users may share that address and be throttled together. WAF socket-IP rate limiting adds perimeter protection but does not correct that application behavior. Test concurrent logins before public signup.

## Upgrading the earlier layout

The former Azure Front Door Premium resources are removed from configuration.
An existing state will therefore plan their deletion. For a live deployment, stage
the tunnel and hostname first, verify them, switch traffic, then retire the old edge
in a separately reviewed change. Do not apply a destructive plan to live traffic.
Internal environment changes can replace Container Apps resources. Back up data and
review every replacement. This change does not deploy or delete Azure resources.

Remove `http_concurrency_target` and `edge_requests_per_minute` from old tfvars.
Use the new Cloudflare inputs in the example. Import and merge existing zone
rulesets before applying; Terraform must not overwrite unrelated rules.

Bicep remains a legacy PostgreSQL deployment with a separately configured Cloudflare
tunnel. Never run it against Terraform-owned resources. See [legacy notes](LEGACY_BICEP.md).
