# SoloAI Terraform infrastructure

A readable alternative to `../main.bicep`, matching the current shared-service architecture. **Choose Terraform or Bicep for an environment; do not let both manage the same Azure resources.** The existing `azure-pipelines.yml` still deploys Bicep. Do not run that deployment against a Terraform-owned environment.

The files below form **one Terraform root module and one state per environment**. Terraform combines all `.tf` files; file order does not determine creation order. Resource references and explicit dependency edges do.

## File organization

| File | Responsibility |
|---|---|
| `versions.tf` | Terraform/provider constraints, remote backend, Azure provider |
| `variables.tf` | Documented inputs, safe defaults and input validation |
| `main.tf` | Existing resource lookups, deterministic names, common settings |
| `networking.tf` | VNet, segregated subnets and private DNS |
| `identity.tf` | Application managed identity and scoped role assignments |
| `database.tf` | Private PostgreSQL, database, backup retention, optional HA |
| `secrets.tf` | Private Key Vault, private endpoint, database URL secret |
| `application.tf` | Shared Container Apps environment/app, HTTPS, probes and scaling |
| `monitoring.tf` | Log Analytics, reserved Insights resource, failure alert and optional email |
| `outputs.tf` | Non-secret service identifiers and URLs |
| `tests/security.tftest.hcl` | Five mocked plan tests for security/defaults/invalid inputs |
| `.terraform.lock.hcl` | Exact selected provider release and checksums; commit this |

[Architecture diagrams and design decisions](../../docs/ARCHITECTURE.md) explain the workflow, tenant isolation, shared model, reliability and scaling limits.

## Scope and prerequisites

1. Terraform >=1.10 and <2, Azure CLI or configured federated OIDC, and a dedicated environment resource group.
2. An existing ACR and chat-compatible Azure OpenAI/Foundry deployment in that group. The ACR must use Registry RBAC permissions mode for `AcrPull`. Push an image from this repository before applying.
3. Registered providers: `Microsoft.App`, `Microsoft.OperationalInsights`, `Microsoft.Insights`, `Microsoft.Network`, `Microsoft.DBforPostgreSQL`, `Microsoft.KeyVault`, `Microsoft.ManagedIdentity`, `Microsoft.ContainerRegistry`, `Microsoft.CognitiveServices`. Provider auto-registration is disabled deliberately.
4. A provisioning principal with resource-group resource write and role-assignment rights. Terraform grants it Secrets Officer on the newly managed vault, and gives the app narrower read/inference/pull permissions. Do not grant these rights to founder accounts.
5. An existing Azure Blob state container, bootstrapped separately with Entra ID access, restricted network access, blob versioning/soft delete, and backups/recovery procedures. The deployment principal needs Storage Blob Data Contributor for state operations. Use a different state key per environment.
6. A runner with private routing and DNS access to Key Vault. Ordinary GitHub-hosted or Microsoft-hosted runners cannot reach the private endpoint. Validation is safe on hosted runners; a real apply/refresh needs private connectivity.

No model resource, model quota, customer app hosting, connector OAuth, WAF, Foundry private endpoint, or public-production identity service is created. Existing shared model network policy is preserved. Container Apps does not have zone redundancy enabled by this template.

## Validate without Azure access

```bash
terraform -chdir=infra/terraform fmt -check -recursive
terraform -chdir=infra/terraform init -backend=false -input=false
terraform -chdir=infra/terraform validate
terraform -chdir=infra/terraform test
```

The tests use a mock provider and do not create Azure resources. GitHub CI runs these checks. They verify configuration contracts, not Azure SKU availability, RBAC propagation, private routing, model compatibility or a successful deployment.

## Prepare an environment

From `infra/terraform`:

```bash
cp terraform.tfvars.example terraform.tfvars
cp backend.hcl.example backend.hcl
# Edit the placeholders for your environment.
```

Supply `TF_VAR_database_admin_password` through your CI secret store. For local interactive work, use Terraform's hidden sensitive-input prompt. Do not put a real password in shell command history, an example file, a checked-in tfvars file or a plan artifact shared publicly.

Authenticate with Azure CLI (`az login`) or your approved OIDC setup. Initialize remote state:

```bash
terraform init -reconfigure -backend-config=backend.hcl
terraform plan -out=soloai.tfplan
# Inspect the plan, then apply the exact reviewed plan:
terraform apply soloai.tfplan
```

The default origin derives from the Container Apps environment domain, avoiding an app/origin dependency cycle. If you use a custom origin, DNS, certificate and domain binding remain separate operator steps. Default naming differs from the Bicep prefix; this is not an automatic migration/import mechanism.

### First-deployment private runner bootstrap

The runner must be able to resolve/reach the new vault endpoint before Terraform manages the secret. For an established network, prearrange peering/routing and DNS forwarding through your platform environment. If this is a brand-new VNet, perform one explicit bootstrap from the same root/state:

```bash
terraform plan \
  -target=azurerm_private_endpoint.vault \
  -target=azurerm_private_dns_zone_virtual_network_link.vault \
  -out=network-bootstrap.tfplan
terraform apply network-bootstrap.tfplan
```

This creates the vault/network/private endpoint dependency graph without the database secret or app. Then arrange a private runner and connectivity (for example, a peered runner VNet with linked private DNS or an appropriate resolver). Peering alone does not link DNS. Do not place runner VMs inside the delegated app/database subnets. Runner compute, peering and DNS forwarding are platform prerequisites, not provisioned here. Resume with an **untargeted full plan/apply from that runner**. Targeting is a one-time bootstrap exception, not routine deployment practice. Never enable public vault access to bypass this requirement.

New role assignments can take time to propagate. A correctly scoped dependency does not guarantee immediate Azure RBAC propagation. If secret or image access is temporarily denied, check identity/network permissions, wait for propagation, and rerun a normal plan/apply. Do not broaden access as a workaround.

## Database privileges and production transition

The default bootstraps an isolated staging database with the `soloadmin` credential and `initialize_schema=true`, matching the existing Bicep MVP. It is **not a least-privilege runtime role**.

Before production, run schema migrations using an elevated migration identity from the private network, create a dedicated runtime role with only required table DML permissions, and supply its TLS URL as sensitive `runtime_database_url`. Set `initialize_schema=false`. Terraform then updates the versioned Key Vault secret reference and app configuration. Use Terraform for subsequent secret changes; out-of-band edits will otherwise drift or be reverted. Adding RLS and verified identity/recovery are separate application milestones.

Both passwords/connection URLs can be present in **Terraform state and saved plans** despite `sensitive=true`. Sensitivity only redacts normal console output; it does not encrypt state fields. Restrict backend and artifact access, use encryption/recovery controls, and never publish plans. `.gitignore` excludes state, tfvars, backend credentials and plans, but cannot protect files already committed.

## Reliability and scaling profiles

| Setting | Staging default | Optional stronger profile |
|---|---|---|
| Application replicas | min 1 / max 3 | min 2 / max based on load tests |
| PostgreSQL SKU | `B_Standard_B1ms` | Supported GP or MO SKU |
| Database HA | Off | `database_ha_enabled=true`, distinct supported zones |
| Backup retention | 7 days | Up to 35 days |
| Model | Existing shared deployment | Increase shared quota or plan dedicated enterprise deployment |
| Alerts | Portal-visible | Set `alert_email` for an operations action group |

HA increases cost and is subject to regional capacity. It does not make the whole application multi-region or automatically zone-redundant. Changing a replica count does not change token allowances, model quota or database capacity. The application enforces tenant usage in SQL. Review [reliability and failure behavior](../../docs/ARCHITECTURE.md#4-reliability-what-is-and-is-not-guaranteed).

Database and vault resources have `prevent_destroy`; Key Vault also has purge protection. Review replacement plans carefully, export/restore-test data, and handle teardown as a deliberate maintenance operation. These lifecycle settings are not a data backup.

## Existing Bicep environments

Never apply this root expecting it to adopt Bicep resources by name. For an existing deployment, inventory every resource and ID, align names/settings and import them into Terraform state with reviewed import blocks or `terraform import`. Confirm the first plan has no unintended creation, replacement or deletion. Transfer ownership only after review, and disable the Bicep deployment for that environment. Alternatively, create a separate staging environment with a different resource group/state and migrate application data through a tested plan.

## Official references

- [AzureRM Container App resource](https://registry.terraform.io/providers/hashicorp/azurerm/latest/docs/resources/container_app)
- [AzureRM PostgreSQL Flexible Server](https://registry.terraform.io/providers/hashicorp/azurerm/latest/docs/resources/postgresql_flexible_server)
- [Azure Blob Terraform backend](https://developer.hashicorp.com/terraform/language/backend/azurerm)
- [Terraform test provider mocking](https://developer.hashicorp.com/terraform/language/tests/mocking)
