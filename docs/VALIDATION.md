# Validation record

Validated locally on 9 September 2026 with Python 3.13.6.

- `pytest -q`: **4 passed**. Two upstream test-client deprecation warnings; no failing tests.
- JavaScript syntax check: passed.
- Bicep CLI compilation: passed with no reported errors.
- `pip-audit -r requirements.txt`: no known vulnerabilities found at validation time.
- Local `/health`: HTTP 200.
- Browser: sign-in, dashboard rendering, email draft request/response and screenshot capture passed using synthetic data.

Not performed: Azure deployment/what-if, live Foundry inference, Docker build (Docker unavailable), PostgreSQL concurrency/role testing, load testing, failover, backup restoration, OAuth integration or an independent security assessment. SQLite concurrency tests do not substitute for staging tests against PostgreSQL.

The screenshots are actual local renders with simulated responses, not generated mockups or production telemetry. CI is configured to run dependency scanning, tests, infrastructure compilation and container building when pushed. CI results must be checked after publication.

## Terraform addition — 10 September 2026

- Terraform 1.15.8, AzureRM 4.81.0: initialization and validation passed.
- `terraform fmt -check -recursive`: passed.
- `terraform test`: five mocked plan tests passed, covering private data access, HTTPS, bounded replicas, scoped application roles, optional HA/alerts, and rejection of incompatible HA, replica limits and HTTP origins.
- Provider version/checksums are locked; GitHub CI includes the same credential-free checks.
- Architecture documentation maps current code behavior, shared model/tenant boundaries, reliability limits and future connector work.

No real Azure plan/apply, network reachability test or failover exercise was performed. Mocked tests do not establish live deployment success.
