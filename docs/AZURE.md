# Azure deployment

This template has been syntax-checked locally. It has **not** been deployed into a subscription. Provisioning availability, RBAC propagation, model compatibility and private networking still need staging verification.

## Prerequisites

Use one resource group containing an existing Azure Container Registry (RBAC permissions mode) and an Azure OpenAI resource with a compatible text-chat deployment in Foundry. The model must support the OpenAI v1 chat-completions route and `max_completion_tokens`. The template references this resource rather than creating a model or allocating model quota.

Create an Azure DevOps workload-identity service connection named `soloai-azure-oidc`, scoped to this resource group. It needs infrastructure write and role-assignment rights for initial provisioning. Restrict pipeline use and separate provisioning from routine image deployment after bootstrap. No subscription credential belongs in GitHub.

Import this GitHub repository into Azure Pipelines using `azure-pipelines.yml`. Create the `soloai-production` environment with an approval check. Create a variable group of the same name with:

| Variable | Value |
|---|---|
| `resourceGroup` | Existing resource group |
| `acrName` | Existing registry name |
| `modelResource` | Existing Azure OpenAI account in that group |
| `modelDeployment` | Chat-compatible deployment name, not model family |
| `databasePassword` | Strong random password; mark secret |
| `publicOrigin` | Exact HTTPS dashboard origin, without trailing slash |

Normal pushes run validation only. Manually run with `deploy=true` after configuring these values. The pipeline builds an immutable build-number image in ACR and deploys Bicep. It passes the password through a private temporary parameter file rather than command-line interpolation. Hosted agents are ephemeral; if using a persistent agent, delete that temporary file after deployment.

For the initial default Azure domain, you may use a deliberately nonmatching HTTPS origin on first deployment. Read the returned `url`, set `publicOrigin` to that exact origin and redeploy before using the browser. Requests from other origins are rejected. A custom domain also needs DNS/certificate binding, not included here.

## Resources

- VNet with separate delegated Container Apps and PostgreSQL subnets.
- Public HTTPS Container App ingress; the SaaS frontend must be reachable by customers. VNet integration does **not** make that ingress private.
- Private PostgreSQL Flexible Server, seven-day backups and TLS connection.
- Private Key Vault endpoint/DNS, RBAC and purge protection; application database URL is a Key Vault reference.
- User-assigned managed identity for registry pulls, Key Vault reads and Azure OpenAI inference.
- Log Analytics with 30-day retention and a failure-rate scheduled-query alert. Add an action group to deliver notifications; without one the alert is visible only in Azure Monitor.
- Application Insights resource reserved for later metadata-only tracing; SDK auto-instrumentation is intentionally not enabled, to avoid inadvertent content/header collection.

The existing model resource remains on its existing networking configuration. The template does not silently change a shared model's public access or add its private endpoint. For private model access, configure the resource endpoint and matching private DNS in the VNet before launch. Outbound traffic is not filtered by an Azure Firewall in this minimal template. Add WAF/Front Door and edge abuse protection before open public signup.

## Database role limitation

The initial template bootstraps with the PostgreSQL administrator credential. This is suitable for isolated staging, **not the final least-privilege runtime role**. Before production, create the schema with a migration identity, create a separate `soloai_runtime` role with only SELECT/INSERT/UPDATE/DELETE on SoloAI tables, disable startup schema creation (`SOLOAI_INIT_SCHEMA=false`), and replace the Key Vault database URL with that role. Rotate the bootstrap credential. Do this from a machine/job with VNet access; do not open PostgreSQL to the internet to run migrations.

## Verification and operations

1. Confirm HTTPS `/health` and readiness succeed.
2. Verify a second tenant cannot see the first tenant's settings or executions.
3. Grant the app identity model access, then test chat and email drafts using test content; verify provider tokens reconcile.
4. Confirm quotas and disabling work across two replicas, and that emergency stop suppresses a delayed response.
5. Confirm PostgreSQL and Key Vault cannot be accessed from a public network.
6. Run `python -m scripts.cleanup` daily from a job with private database access for 30-day execution/audit cleanup and expired-session removal. Scheduling that job is an operator setup step.
7. Exercise backup restore and record recovery time before accepting live customers.

Example Monitor query (no message content):

```kusto
ContainerAppConsoleLogs_CL
| where Log_s contains 'agent.execution'
| extend event = parse_json(Log_s)
| summarize runs=count(), failures=countif(tostring(event.status)=='failed'), p95_ms=percentile(todouble(event.latency_ms),95) by bin(TimeGenerated, 5m)
```

Configure `ESTIMATED_USD_PER_MILLION_TOKENS` only after checking the selected model's price. The dashboard multiplies total tokens by this operator-provided blended rate. It is an approximation, not a bill; actual input/output prices, cached tokens and infrastructure charges differ. No prices or charges are fabricated in the demo.

Official references used for the design:
- [Azure OpenAI managed identity](https://learn.microsoft.com/en-us/azure/ai-services/openai/how-to/managed-identity)
- [PostgreSQL private networking](https://learn.microsoft.com/en-us/azure/postgresql/network/concepts-networking-private)
- [Container Apps private endpoints](https://learn.microsoft.com/en-us/azure/container-apps/how-to-use-private-endpoint)
