# Azure SQL with the free allowance

We use one Azure SQL database for workspace accounts, sessions, agent settings and
usage records. Tenants share the database, with their records separated by tenant ID.
Customer messages and replies are not stored in it.

The database requests the free offer at creation. It has a 32 GB size limit, local
backup redundancy, and stops when its monthly free allowance runs out. There is no
fallback to a paid database if Azure rejects the offer. Check subscription eligibility
and regional restrictions before deployment.

Microsoft currently includes 100,000 vCore seconds, 32 GB data and 32 GB backup storage
per month. See [the offer and its limits](https://learn.microsoft.com/en-us/azure/azure-sql/database/free-offer).
The database becomes unavailable when the allowance is exhausted and resumes after
the monthly reset. This is suitable for a small trial, not an uptime commitment.

> **Note:** Cloudflare Free replaces the paid Azure edge. The SQL private endpoint,
> application hosting, monitoring and model usage also have separate pricing. Changing
> the database does not make the complete Azure deployment free.

## Terraform layout

`database.tf` creates the SQL logical server, database and private endpoint. The pinned
AzureRM provider does not expose free-offer fields, so the database is created through
an incremental ARM template with `useFreeLimit=true` and
`freeLimitExhaustionBehavior=AutoPause`. The logical server is private and requires TLS
1.2 or later. No public firewall exceptions are added.

The template deployment manages the database as a nested ARM resource. It does not
provide the same per-property Terraform drift reporting as a native database resource.
Do not enable paid overages in the portal. Review the free-limit settings after apply.
The offer limits point-in-time recovery to seven days and uses local backup storage.

`networking.tf` supplies the `privatelink.database.windows.net` zone. `secrets.tf` stores
the connection URL in Key Vault. Container Apps receives a secret reference. The server
administrator is a bootstrap account for staging; provision a restricted runtime user
before public use and pass its connection URL through `runtime_database_url`.

## Application changes

The container includes Microsoft ODBC Driver 18 and pyodbc. Use this URL shape, with
credentials URL-encoded and kept in Key Vault:

```text
mssql+pyodbc://USER:PASSWORD@SERVER.database.windows.net:1433/soloai?driver=ODBC+Driver+18+for+SQL+Server&Encrypt=yes&TrustServerCertificate=no
```

The app translates its small set of database-specific statements for SQL Server,
including table setup, pagination and the concurrent sign-in limiter. Indexed IDs use
bounded strings; business guidance supports Unicode. SQL Server connection pooling is
disabled to let idle serverless databases pause. Container readiness probes use `/live`, which
does not query SQL. `/health` remains an on-demand database check.

Resume delays or monthly exhaustion may cause database requests to fail. The app does
not bypass authentication or token checks when SQL is unavailable. No automatic paid
retry or upgrade is enabled. Avoid constant database health polling and open SQL tools,
which can prevent idle pause and consume the allowance.

## Existing deployments

This change is intended for a new deployment. It is not a PostgreSQL-to-SQL data
migration. If an earlier Terraform state contains PostgreSQL resources, stop before
apply. Back up the database, preserve the old resources in a separate state or root,
and review a data migration and cutover plan. Removing resource blocks can schedule
deletion even if the old configuration once had `prevent_destroy`. Do not approve a
plan deleting an existing database merely to try this offer.

## Verification

Local application regression tests and SQL translation tests cover the code changes.
Mocked Terraform tests check free-limit, auto-pause and private-access settings. These
are not a live SQL Server integration test. Before deployment, build the new container,
validate login, agent settings, concurrent quota reservations and emergency stop against
a staging Azure SQL database, and check its free-offer banner and pause settings.
No Azure resources were created by this repository update.
