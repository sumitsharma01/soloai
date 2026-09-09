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
