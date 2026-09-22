# Queued Email Support

SoloAI can receive a support email from a customer's server, look up a booking or
policy, and prepare a draft for an operator. Approval records a decision. It never
sends an email or changes a booking.

This is an opt-in extension of the existing app. `/api/try` and Website Chat keep
their existing synchronous behavior. An optional [read-only Gmail connector](GMAIL.md)
can forward new inbox mail. Outlook sync is not included; customer servers can also
forward messages through the authenticated event API.

## Request flow

```mermaid
flowchart TD
    A[Customer server] -->|1. API key and email event with id| B[SoloAI API]
    B -->|2. Authenticate, validate, deduplicate| C[(PostgreSQL: execution and job)]
    B -->|3. Return 202 and execution_id| A
    C -->|4. Claim durable job| D[SoloAI worker]
    D -->|5. Enabled state, stop, token reservation| C
    D <-->|6. Pinned agent and bounded reasoning loop| E[Azure Foundry]
    D -->|7. Authorize and validate tool request| F[Tool gateway]
    F --> G[get_booking: tenant support snapshot]
    F --> H[search_policy: tenant policy excerpts]
    G --> D
    H --> D
    D -->|8. Validate and save draft| C
    I[Operator dashboard] <-->|9. View draft and tool metadata| C
    I -->|10. Approve or reject through SoloAI API| B
```

The dashboard accesses PostgreSQL through SoloAI's authenticated API, not directly.
One application image runs in two processes: API and worker. PostgreSQL is the only
queue. A transaction persists both the existing execution record and its email job.

## Enable locally

Run commands from the repository root in your existing virtual environment. Install
the updated requirements, including the asynchronous Azure transport:

```sh
pip install -r requirements.txt
export SOLOAI_ENV=development
export DATABASE_URL=sqlite:///./soloai.db
export SOLOAI_INIT_SCHEMA=true
export SOLOAI_EMAIL_WORKFLOWS=true
export SOLOAI_EMAIL_RETENTION_HOURS=168
export PUBLIC_ORIGIN=http://127.0.0.1:8000
export AZURE_FOUNDRY_PROJECT_ENDPOINT=https://soloai-v0-resource.services.ai.azure.com/api/projects/soloai-v0
export AZURE_FOUNDRY_MODEL=gpt-5.4
export AZURE_FOUNDRY_AGENT_NAME=soloai-support
export AZURE_FOUNDRY_AGENT_VERSION=1
python -m scripts.email_admin migrate
```

Setting `SOLOAI_EMAIL_WORKFLOWS=true` explicitly enables temporary email and draft
storage. Default retention is seven days, configurable between one hour and 30 days.
Do not put real customer content in a shared development database.

Create a separate email agent. The original `soloai-support` definition remains
tool-free so existing manual tests and Website Chat continue to work:

```sh
az login
# Inspect the instructions and exact tool schemas without Azure mutation:
python -m scripts.create_email_agent --model gpt-5.4
# Create or reuse a matching version after reviewing the definition:
python -m scripts.create_email_agent --model gpt-5.4 --apply
export AZURE_FOUNDRY_EMAIL_AGENT_NAME=soloai-email
# Use the version returned by the command, not an assumed "latest" version:
export AZURE_FOUNDRY_EMAIL_AGENT_VERSION=1
```

The creation command does not retry mutations. Following an uncertain failure,
inspect the Foundry project before repeating it. Creating the definition is separate
from proving live inference and network access. No new agent is silently deployed
by the API or worker.

Start the API:

```sh
SOLOAI_METRICS_PORT=9464 uvicorn app.main:app --host 127.0.0.1 --port 8000 --workers 1 --no-access-log --no-proxy-headers
```

In another terminal with the same exported environment:

```sh
SOLOAI_METRICS_PORT=9465 python -m app.email_worker
```

Create a workspace or sign in, enable Email Support, and create an application key.
For local synthetic data only, seed that existing workspace:

```sh
python -m scripts.email_admin seed-demo --workspace-email YOUR_LOCAL_WORKSPACE_EMAIL
```

The seed adds booking `BK-2041` and one change policy. It refuses production and
non-SQLite databases. The booking adapter reads an imported support snapshot; it is
not a live vendor integration. Replace `DatabaseBookingSource` with an implementation
of `BookingSource` when connecting a real system, keeping trusted tenant context,
short timeouts and minimal returned fields. Policy data lives in `support_policies`.
Production data imports are operator-controlled, not model tools or public endpoints.

Forward an event from your server using the existing SDK:

```javascript
const result = await solo.emit('email.received', {
  id: 'mailbox-42-message-123', // stable across delivery retries
  content: 'Can I change booking BK-2041?'
});
// result: { execution_id, status: 'QUEUED', duplicate: false }
```

The body must contain only `id`, `type`, and `content`. Never pass a tenant ID.
Do not include credentials, attachments or full unrelated email threads. Sign in to
**Email review**, refresh the list, open the execution and approve or reject the
draft. Refresh explicitly to see background status changes.

## API contract

| Endpoint | Authorization | Result |
|---|---|---|
| `POST /api/events` | Application key | Email event requires an ID when workflows are enabled; returns 202 |
| `GET /api/executions/{id}` | Same-tenant application key or operator session | Message, draft, status, safe error code, tokens, timings and tool metadata |
| `GET /api/email/executions` | Operator session | Latest 50 email jobs for the workspace |
| `POST /api/executions/{id}/approve` | Operator session | WAITING_FOR_REVIEW to APPROVED; `sent:false` |
| `POST /api/executions/{id}/reject` | Operator session | WAITING_FOR_REVIEW to REJECTED; `sent:false` |

A duplicate `(tenant, event_id)` returns 200 with the existing execution ID and
status. Reusing that ID with different content returns 409. The database unique
constraint and tenant-row transaction enforce concurrent idempotency. Application
keys cannot approve or reject. Wrong-tenant execution IDs return 404.

States are QUEUED, RUNNING, WAITING_FOR_REVIEW, APPROVED, REJECTED and FAILED.
COMPLETED is reserved for future non-review completion; approval does not imply mail
delivery. Invalid transitions return 409. Stop or disable prevents approval of a
stopped agent's draft, and emergency-stop epochs invalidate old work even after the
agent is enabled again.

## Execution controls and failures

- Every new event and retry is admitted under the existing 20-per-minute tenant limit. There can
  be at most 100 queued, running or unreviewed emails per tenant.
- The 10,000 lifetime token allowance remains. Each model turn reserves a conservative
  UTF-8 input bound, reviewed instructions/tool schemas, output ceiling and overhead
  before calling Azure. Actual usage is settled transactionally. Large emails or long
  histories can be rejected even when a smaller request fits the remaining allowance.
- At most three tool calls, no repeated identical calls, four model turns, 1,024
  output tokens per turn, five seconds per tool, and 90 seconds overall.
- Tenant IDs never come from tool arguments. Unknown tools, unauthorized tools,
  malformed arguments/results and invalid Foundry JSON terminate safely.
- The worker verifies model, instructions and exact approved tool schemas against
  the saved agent name/version before inference. `store=false` and execution-local
  history are used on every turn. No shared conversation or previous-response ID.
- Missing booking/policy returns `found:false`. The runtime forces `needs_human:true`
  when any lookup misses; it still requires a valid model draft before review.
- Foundry 429/503 failures before any successful model response can retry at most
  twice, after two and four seconds. Unknown network outcomes, timeouts, validation,
  permission, quota and tool failures are not automatically replayed. A failed
  attempt's uncertain token reservation stays charged to the allowance.
- Worker leases expire after the 90-second limit plus 30 seconds of margin. The next
  worker poll marks abandoned RUNNING jobs FAILED with `worker_interrupted`; it
  never republishes a late result or automatically repeats uncertain inference.
- A worker database outage uses bounded polling backoff. Recovery reconciles expired
  leases after the database returns. PostgreSQL connect/statement/lock timeouts bound
  individual database operations. Read-only tool queries run outside the event loop.
- Stop blocks further tool/model steps and suppresses the final draft. An already
  submitted Azure request can still consume tokens. No claim is made that Azure
  inference is cancelled remotely.

Errors are stable codes, including `foundry_timeout`, `execution_timeout`,
`foundry_unavailable`, `agent_definition_mismatch`, `invalid_foundry_response`,
`unknown_tool`, `unauthorized_tool`, `invalid_tool_arguments`, `tool_timeout`,
`tool_unavailable`, `tool_limit`, `repeated_tool_call`, `token_allowance_exhausted`,
`rate_limit_exceeded`, `emergency_stop`, `content_expired` and `worker_interrupted`.
Raw provider exceptions, arguments and customer content are never logged.

## Retention and access

Queued execution needs durable content. `email_jobs` therefore temporarily holds the
email, guidance snapshot and draft. Content is visible only to the owning tenant.
The API hides expired content immediately. Worker cleanup clears expired content;
run `python -m scripts.email_admin purge` independently if workers are stopped.
Expired queued/review jobs become FAILED. Metadata and event ID/hash tombstones remain
so old delivery retries do not restart processing. Removing tombstones deliberately
ends that idempotency window. Database backups have their own retention.

Review content is database plaintext protected by access controls and database/disk
encryption at rest. Use PostgreSQL TLS, restricted networking and a runtime role
without DDL privileges. No claim is made of application-level envelope encryption.
Prompts do not enforce authorization. The application supplies tenant context and
checks permissions on every call. Booking reference possession does not verify the
customer's identity; the operator must verify disclosure before using the draft.

## Deployment boundary

Production email workflows require PostgreSQL. The current Terraform defaults to
Azure SQL and a direct-model endpoint. **Do not enable this feature on that stack
without supplying PostgreSQL and the Foundry Agent Service project connection.**
No Terraform resources or live databases are replaced by this change. A future
infrastructure change must explicitly migrate existing tenant/configuration data.

Use the existing application image for API and worker, with separate commands.
Keep at least one worker running; no queue autoscaler is configured. A worker handles
one email at a time. Additional workers can safely claim separate jobs, subject to
the shared database and model quotas. There is no per-tenant container/model.

Run `python -m scripts.email_admin migrate` once with a deployment database role
before rollout, then set `SOLOAI_INIT_SCHEMA=false` for runtime processes. Migration
001 adds tables and a version marker; it does not drop or rebuild existing tables.
Rollback disables the feature and stops its workers while leaving data intact.
Run PostgreSQL privately with TLS certificate verification and encryption/backups,
and grant the worker's managed identity only the required Foundry read/invoke access.
Existing Foundry project private connectivity still needs deployment verification.

## Observability and verification

Scrape API port 9464 and worker port 9465 separately. Existing agent/token/latency
metrics remain compatible with Grafana. The email dashboard adds tool counts,
tool p95 latency, operator decisions and interrupted job recovery. Counters are
process-local and reset on restart. Multi-replica deployments must scrape every
worker independently; execution history in SQL remains the durable record.

No execution IDs, tenant IDs, email addresses, message bodies or tool arguments
are Prometheus labels. Database review/audit records contain execution references.
Failed provider calls can have uncertain usage; the API reports it separately and
does not pretend it is measured token consumption.

```sh
pytest -q
# Against a disposable PostgreSQL test database, never your production database:
TEST_POSTGRES_URL=postgresql+psycopg://USER:PASSWORD@127.0.0.1:5432/soloai_test pytest -q tests/test_email_workflows.py
```

CI provisions PostgreSQL 16 and runs the same boundary tests against both databases.
Tests inject a provider and do not call Azure. A live acceptance run must additionally
verify the deployed agent definition, credential permissions, tool loop, token usage
and review UI against synthetic data. Automated tests alone do not establish live
Azure connectivity or production readiness.

## Optional external booking source

Use the [curated MCP booking adapter](MCP.md) to replace local snapshot lookup for selected workspaces. It preserves the existing get_booking contract and tool limits. Configuration failure stops the lookup rather than falling back.
