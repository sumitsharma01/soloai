# Local Grafana demo

This optional single-process demo runs entirely on loopback. Azure Terraform still
uses the Azure Workbook; it does not deploy Grafana or Prometheus. Only live Foundry
calls incur Azure model usage. Do not use this anonymous local Grafana configuration
on a public server or forward its ports.

Install the application requirements, Prometheus and Grafana OSS from their official
release sites (demo verified with Prometheus 3.14.0 and Grafana 13.2.1 on Apple Silicon).
Check vendor checksums before running downloaded binaries. Keep binaries and runtime
data outside Git. No Docker is required.

From the repository root, use separate terminals:

1. Start the app with the environment settings in `docs/live-agent.md` and add
   `SOLOAI_METRICS_PORT=9464` to its environment. Use one Uvicorn worker.
2. Start Prometheus:

```bash
prometheus --config.file=monitoring/prometheus.yml \
  --storage.tsdb.path=/YOUR/PRIVATE/DATA/prometheus \
  --storage.tsdb.retention.time=2d --web.listen-address=127.0.0.1:9090
```

3. Start Grafana with these environment variables (absolute paths):

```bash
export GF_SERVER_HTTP_ADDR=127.0.0.1
export GF_SERVER_HTTP_PORT=3000
export GF_AUTH_ANONYMOUS_ENABLED=true
export GF_AUTH_ANONYMOUS_ORG_ROLE=Viewer
export GF_AUTH_DISABLE_LOGIN_FORM=true
export GF_SECURITY_ADMIN_PASSWORD="$(python3 -c 'import secrets; print(secrets.token_urlsafe(40))')"
export GF_ANALYTICS_REPORTING_ENABLED=false
export GF_PATHS_PROVISIONING="$PWD/monitoring/grafana/provisioning"
export SOLOAI_DASHBOARD_PATH="$PWD/monitoring/grafana/dashboards"
export GF_PATHS_DATA=/YOUR/PRIVATE/DATA/grafana
export GF_PATHS_LOGS=/YOUR/PRIVATE/DATA/grafana-logs
export GF_PATHS_PLUGINS=/YOUR/PRIVATE/DATA/grafana-plugins
grafana server --homepath /PATH/TO/GRAFANA
```

Open http://127.0.0.1:3000/d/soloai-live and generate a test message in SoloAI at
http://127.0.0.1:8000. Prometheus scrapes every 5 seconds. Rates require at least two
samples; sparse traffic and newly created series may leave percentile/rate panels
empty. Counters show only work since the app process started, not historical DB usage.
The error budget is an observed one-hour demonstration, not a production 30-day SLA.
It excludes user stops and simulated executions. Initial counter increments before
first scrape cannot be recovered by rate/increase queries.

Metrics contain route templates and agent package names, not tenant IDs, prompts,
responses or credentials. Allowance is the last observed workspace snapshot, not a
sum across users. Process memory is OS-dependent and may show no data on macOS.
This local dashboard does not show undeployed Azure infrastructure metrics.

Stop each process with Ctrl+C. Local metrics are optional and disabled when
`SOLOAI_METRICS_PORT` is unset. The public app port never serves `/metrics`.
Production multi-worker or multi-replica collection requires a separate design.
