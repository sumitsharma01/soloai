# Local demo runbook

## Startup and login

- **Address already in use:** identify the owner with `lsof -nP -iTCP:8300 -sTCP:LISTEN` and repeat for metrics ports. Stop only the known old demo process. API and worker need different metrics ports. If ports change, update PUBLIC_ORIGIN, Google redirect registration and Prometheus targets together.
- **Email/password incorrect:** use the workspace created in the currently configured database. Switching DATABASE_URL changes the accounts visible to the app. Do not reset or delete the database to fix a login.
- **Missing tables:** run `python -m scripts.email_admin migrate` against the intended database with a migration role. API and worker must share the database and feature settings.

## Foundry and worker

- **Jobs remain queued:** check worker process, enabled state, budget and database connectivity. A running API alone does not process the queue.
- **Foundry authentication failure:** verify the credential identity, project endpoint and project role. For local Azure CLI credentials, sign in with `az login` using the same environment as the worker. Do not paste bearer tokens into logs.
- **Agent definition mismatch:** verify the configured email agent version matches the approved tools, model and instructions. Review `scripts.create_email_agent` before publishing a new version. Do not bypass definition checks.
- **worker_interrupted or uncertain inference:** inspect the execution before resubmitting. Retrying blindly can duplicate model cost. Follow [email execution controls](../EMAIL-WORKFLOWS.md).
- **Unexpected token / Internal Server Error:** inspect the original backend safe error and HTTP status. It is not proof of a model connection. Never expose a traceback or provider secret in the UI.

## Grafana and Prometheus

If panels show no data, verify Prometheus targets are up and the API and worker metrics ports match the scrape configuration. Confirm Grafana's Prometheus datasource, dashboard time range and that a synthetic execution occurred within it. Low traffic can produce empty percentile panels. Process counters reset after restarts; SQL execution history remains the durable record.

Recovery check: sign in, confirm Gmail last sync, submit a new synthetic email, verify a draft in Email review, and confirm relevant metrics appear. A dashboard screenshot is not a production availability or SLO guarantee.
