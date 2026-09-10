# SoloAI: minimal secure Azure infrastructure

```text
Internet
  → Front Door Premium + WAF (inspect, rate-limit, block)
  → Private Link → Container Apps (no public access)
  → private PostgreSQL / private Key Vault / private shared Azure OpenAI
```

**One environment, one Terraform state, one shared application.** Enabling a customer's agent changes a database row, not infrastructure. These files are one root module; Terraform handles dependency order.

## Read the code in this order

| File | Simple purpose |
|---|---|
| `main.tf`, `variables.tf`, `versions.tf` | Existing resources, inputs, naming and provider/state setup |
| `edge.tf` | Public Front Door URL, WAF rules, HTTPS route and private origin |
| `networking.tf` | VNet, separate app/database/endpoint subnets, private DNS |
| `application.tf` | One application with 1–3 replicas and health checks |
| `database.tf` | One small private PostgreSQL server; 32 GiB and seven-day backups |
| `ai.tf` | Private connection to the existing shared OpenAI model account |
| `identity.tf`, `secrets.tf` | Managed identity, scoped roles and private Key Vault |
| `monitoring.tf` | One log workspace and one failure alert; optional email recipient |
| `outputs.tf` | Front Door URL and diagnostic resource IDs; no secret outputs |

No AKS, API Management, Redis, queue, dedicated worker, Application Insights, second region or per-customer Azure resources. ACR and the shared model are existing resources. Front Door **Premium** and private endpoints have charges; this is the smallest service set for the requested private-origin design, not a claim of the cheapest Azure deployment.

## Start here

1. Read the [architecture diagram](../../docs/ARCHITECTURE.md).
2. Copy `terraform.tfvars.example` to `terraform.tfvars` and fill the existing resource names.
3. Copy `backend.hcl.example` to `backend.hcl` for an existing protected Azure Blob state container.
4. Follow the [deployment runbook](../../docs/AZURE.md) from a runner with private network/DNS access.
5. Approve the exact Front Door private-connection request on the Container Apps environment, then verify the public URL and blocked direct-origin access.

The existing AI account must be `OpenAI` kind, with **public network access disabled** and **local key authentication disabled**. Terraform checks this; it does not silently reconfigure a shared account that may have other clients. SoloAI uses managed identity for inference. The current adapter targets Azure OpenAI in Foundry, not arbitrary Foundry account types.

## Validate locally without Azure credentials

```bash
terraform -chdir=infra/terraform fmt -check -recursive
terraform -chdir=infra/terraform init -backend=false -input=false -lockfile=readonly
terraform -chdir=infra/terraform validate
terraform -chdir=infra/terraform test
```

Seven mocked plan tests check private data access, private ingress, WAF binding/rate control, HTTPS/no caching, model network/auth requirements and invalid limits. GitHub and Azure Pipelines run validation only. These checks do not prove live Azure deployment or model connectivity.

## Only a few starting choices

- `edge_requests_per_minute`: default 300 per socket IP. WAF counters are approximate; users behind one NAT share an IP. Tune with legitimate traffic.
- `min_replicas` / `max_replicas`: defaults 1 / 3, shared by all tenants.
- `database_sku`: small starter size. No HA or regional failover in this first version.
- `alert_email`: optional operations destination; otherwise the alert remains portal-visible.
- `runtime_database_url` and `initialize_schema`: production uses a migrated least-privilege role with startup schema creation disabled. The default admin URL is for isolated staging only.

The backend, tfvars, saved plans and state must remain private. `sensitive=true` redacts output; it does **not** remove secrets from state. The committed lockfile includes Linux/macOS provider checksums.

**Upgrading the previous template:** see [migration notes](../../docs/AZURE.md#upgrading-the-earlier-layout). Internal Container Apps networking can require replacement. The old Bicep template/pipeline are legacy references and must not manage this environment.
