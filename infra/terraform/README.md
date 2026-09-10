# SoloAI: minimal secure Azure infrastructure

```text
Internet
  → Cloudflare Free + Tunnel (inspect, rate-limit, block)
  → outbound Tunnel → cloudflared sidecar → localhost app (no managed ingress)
  → private Azure SQL / private Key Vault / private shared Azure OpenAI
```

**One environment, one Terraform state, one shared application.** Enabling a customer's agent changes a database row, not infrastructure. These files are one root module; Terraform handles dependency order.

## Read the code in this order

| File | Simple purpose |
|---|---|
| `main.tf`, `variables.tf`, `versions.tf` | Existing resources, inputs, naming and provider/state setup |
| `edge.tf` | Cloudflare tunnel, proxied DNS, HTTPS, cache bypass and one free API rate rule |
| `networking.tf` | VNet, separate app/database/endpoint subnets, private DNS |
| `application.tf` | One application with 1-3 replicas and health checks |
| `database.tf` | One small private Azure SQL server; 32 GB free allowance and stop-at-limit behavior |
| `ai.tf` | Private connection to the existing shared OpenAI model account |
| `identity.tf`, `secrets.tf` | Managed identity, scoped roles and private Key Vault |
| `monitoring.tf` | One log workspace and one failure alert; optional email recipient |
| `outputs.tf` | Cloudflare URL and diagnostic resource IDs; no secret outputs |

No AKS, API Management, Redis, queue, dedicated worker, Application Insights, second region or per-customer Azure resources. ACR and the shared model are existing resources. Cloudflare Free removes the paid Azure edge. Always-running app compute and private endpoints remain billable.

## Start here

1. Read the [architecture diagram](../../docs/ARCHITECTURE.md).
2. Copy `terraform.tfvars.example` to `terraform.tfvars` and fill the existing resource names.
3. Copy `backend.hcl.example` to `backend.hcl` for an existing protected Azure Blob state container.
4. Follow the [deployment runbook](../../docs/AZURE.md) from a runner with private network/DNS access.
5. Follow [Cloudflare setup](../../docs/CLOUDFLARE.md), verify tunnel health, HTTPS, Free Managed Ruleset and blocked direct-origin access.

The existing AI account must be `OpenAI` kind, with **public network access disabled** and **local key authentication disabled**. Terraform checks this; it does not silently reconfigure a shared account that may have other clients. SoloAI uses managed identity for inference. The current adapter targets Azure OpenAI in Foundry, not arbitrary Foundry account types.

## Validate locally without Azure credentials

```bash
terraform -chdir=infra/terraform fmt -check -recursive
terraform -chdir=infra/terraform init -backend=false -input=false -lockfile=readonly
terraform -chdir=infra/terraform validate
terraform -chdir=infra/terraform test
```

Mocked plan tests check private data access, absent app ingress, tunnel routing, free rate control, HTTPS/no caching, model network/auth requirements and invalid limits. GitHub Actions also supports opt-in reviewed deployment. These checks do not prove live Azure deployment or model connectivity.

## Only a few starting choices

- `edge_requests_per_10_seconds`: default 50 per IP per Cloudflare location. WAF counters are approximate; users behind one NAT share an IP. Tune with legitimate traffic.
- `min_replicas` / `max_replicas`: defaults 1 / 3, shared by all tenants. There is no HTTP scale rule; raise the minimum for more running replicas.
- Database size is fixed to the free-offer configuration. It pauses at the monthly limit.
- `alert_email`: optional operations destination; otherwise the alert remains portal-visible.
- `runtime_database_url` and `initialize_schema`: production uses a migrated least-privilege role with startup schema creation disabled. The default admin URL is for isolated staging only.

The backend, tfvars, saved plans and state must remain private. `sensitive=true` redacts output; it does **not** remove secrets from state. The committed lockfile includes Linux/macOS provider checksums.

**Upgrading the previous template:** see [migration notes](../../docs/AZURE.md#upgrading-the-earlier-layout). Internal Container Apps networking can require replacement. The old Bicep template/pipeline are legacy references and must not manage this environment.

Monitoring queries are segregated in `queries/`, Workbook configuration in
`dashboard.tf`, and collection/alerts in `monitoring.tf`. See the
[operations guide](../../docs/monitoring.md) for SLO definitions and deployment checks.
