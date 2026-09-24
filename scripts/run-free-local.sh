#!/usr/bin/env bash
# An isolated local preview. This deliberately ignores cloud credentials.
set -euo pipefail
cd "$(dirname "$0")/.."
PYTHON="${SOLOAI_PYTHON:-python3}"
command -v "$PYTHON" >/dev/null || { echo 'Install Python 3.13 first, then run this command again.'; exit 1; }
if [[ ! -x .venv/bin/python ]]; then "$PYTHON" -m venv .venv; fi
# Pip reuses installed packages on later starts.
.venv/bin/python -m pip install -q -r requirements.txt
unset AZURE_OPENAI_ENDPOINT AZURE_OPENAI_DEPLOYMENT
unset AZURE_FOUNDRY_PROJECT_ENDPOINT AZURE_FOUNDRY_AGENT_NAME AZURE_FOUNDRY_AGENT_VERSION AZURE_FOUNDRY_MODEL
unset SOLOAI_METRICS_PORT SOLOAI_MCP_CONFIG_FILE GMAIL_CLIENT_FILE GMAIL_TOKEN_KEY_FILE
if [[ -n "${SOLOAI_LOCAL_METRICS_PORT:-}" ]]; then
  export SOLOAI_METRICS_PORT="$SOLOAI_LOCAL_METRICS_PORT"
fi
export SOLOAI_EMAIL_WORKFLOWS=false
export SOLOAI_ENV=development
export DATABASE_URL=sqlite:///./soloai-free.db
export PUBLIC_ORIGIN=http://127.0.0.1:${SOLOAI_LOCAL_PORT:-8000}
export SOLOAI_INIT_SCHEMA=true
.venv/bin/python - <<'PY'
import os, socket, sys
port = int(os.environ.get('SOLOAI_LOCAL_PORT', '8000'))
try:
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', port))
except OSError:
    sys.exit(f'Port {port} is busy. Try: SOLOAI_LOCAL_PORT=8001 bash scripts/run-free-local.sh')
PY
printf '\nOpen %s and choose Create a workspace.\nSimulated replies only. Gmail, Azure and monitoring are not started.\nStop with Ctrl+C.\n\n' "$PUBLIC_ORIGIN"
exec .venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port "${SOLOAI_LOCAL_PORT:-8000}" --no-access-log --no-proxy-headers
