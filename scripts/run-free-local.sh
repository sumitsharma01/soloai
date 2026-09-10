#!/usr/bin/env bash
# No cloud credentials, model calls or Azure deployment. Run on your own machine.
set -euo pipefail
cd "$(dirname "$0")/.."
unset AZURE_OPENAI_ENDPOINT AZURE_OPENAI_DEPLOYMENT
unset AZURE_FOUNDRY_PROJECT_ENDPOINT AZURE_FOUNDRY_AGENT_NAME AZURE_FOUNDRY_AGENT_VERSION AZURE_FOUNDRY_MODEL
export SOLOAI_ENV=development
export DATABASE_URL=sqlite:///./soloai-free.db
export PUBLIC_ORIGIN=http://127.0.0.1:8000
export SOLOAI_INIT_SCHEMA=true
export SOLOAI_METRICS_PORT=9464
exec python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --no-access-log --no-proxy-headers
