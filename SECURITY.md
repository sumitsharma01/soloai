# Security and data handling

This is a tested MVP foundation, not a completed public-production security program. Do not publish vulnerability details or secrets in a public issue; contact the repository owner privately.

Implemented: hashed opaque application/session keys; PBKDF2-SHA256 passwords with per-account salts; HttpOnly/SameSite cookies (Secure in production); same-origin mutation checks; request-size bounds; parameterized queries; tenant-scoped access; server-owned operations; shared database rate/usage counters; metadata-only executions; key rotation; emergency stop; CSP and security headers; managed model identity; private database and Key Vault infrastructure declarations.

Content policy: manual tests and synchronous responses remain transient. Enabling `SOLOAI_EMAIL_WORKFLOWS=true` opts into temporary database storage of forwarded emails, guidance snapshots and drafts for operator review. Default retention is seven days; API expiry and worker/CLI cleanup apply. Deduplication tombstones and operational metadata remain. See [email retention and deployment](docs/EMAIL-WORKFLOWS.md). No email content or tool inputs/results enter application logs or metrics. Business guidance must not contain credentials. Model-provider retention and database backups have separate policies.

Operational metadata: account email, password hash, tenant configuration, key/session hashes, usage totals, execution status/time/token count/latency and configuration audit events. Cleanup is a documented daily operator job, not an already-running scheduler. Account deletion/export and backup expiry handling are not implemented.

Known limitations: one owner per workspace; no verified email, password recovery, MFA or invitation workflow; no RLS; runtime database bootstrap privilege must be reduced; Gmail OAuth is optional and read-only, with encrypted tenant-bound refresh tokens; Outlook is not implemented; legacy Bicep requires separate Cloudflare configuration and model private networking; the current Terraform target adds private AI access and Cloudflare Free controls but has not been deployed/penetration-tested; no remote cancellation of already-started inference; no per-end-user quotas on the customer's side. Durable execution is available only in the opt-in PostgreSQL email profile. The customer server must authenticate and rate-limit its users. A server API key must never be exposed in a public chat widget. Signup token grants are not abuse-resistant until verified identity and edge admission controls are added.

OAuth must be used when adding external inbox access. Never ask for customer mail passwords. Email drafts must stay drafts until the user explicitly approves a future send capability and the backend enforces it independently of model text.

The opt-in email worker adds durable execution, lease recovery and two read-only tools.
It requires PostgreSQL in production, strict schemas and a separately pinned Foundry
email agent. Approval uses the owner's session and never sends mail. Booking lookup
is scoped to the tenant; a booking number or sender address is not customer identity
verification. Human review must resolve disclosure and identity questions. The model
has no database credentials, HTTP tool, SQL tool, shell, or permission to send email.
An interrupted inference is failed visibly rather than replayed; unknown token costs
remain reserved. Existing identity lifecycle, backup, runtime-role and deployment
limitations still apply. This change is not a security certification.

Optional MCP booking access is operator-configured per tenant. The fixed read-only
get_booking tool uses a distinct tenant credential, approved URL, bounded transport,
validated output and the existing tool gateway. No arbitrary remote tool discovery
or model-supplied endpoint is supported. The remote server must enforce tenant
permissions; MCP alone does not establish isolation or stop prompt injection.
Production requires HTTPS, protected secret mounts and egress restrictions. See
[the MCP security boundaries](docs/MCP.md) and [MCP runbook](docs/runbooks/MCP.md).
