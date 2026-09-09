# Security and data handling

This is a tested MVP foundation, not a completed public-production security program. Do not publish vulnerability details or secrets in a public issue; contact the repository owner privately.

Implemented: hashed opaque application/session keys; PBKDF2-SHA256 passwords with per-account salts; HttpOnly/SameSite cookies (Secure in production); same-origin mutation checks; request-size bounds; parameterized queries; tenant-scoped access; server-owned operations; shared database rate/usage counters; metadata-only executions; key rotation; emergency stop; CSP and security headers; managed model identity; private database and Key Vault infrastructure declarations.

Content policy: incoming messages and model outputs live only in process memory during the request. They are not written to SQL or application logs. Tenant business guidance is intentionally persisted as configuration; it must not contain credentials or sensitive customer records. Browser memory displays the reply until navigation. Model-provider retention and abuse monitoring are separate policies and must be reviewed with Azure. Operational backups inherit the database's retention policy.

Operational metadata: account email, password hash, tenant configuration, key/session hashes, usage totals, execution status/time/token count/latency and configuration audit events. Cleanup is a documented daily operator job, not an already-running scheduler. Account deletion/export and backup expiry handling are not implemented.

Known limitations: one owner per workspace; no verified email, password recovery, MFA or invitation workflow; no RLS; runtime database bootstrap privilege must be reduced; no live inbox OAuth; no model-private-endpoint provisioning; no DDoS/WAF configuration; no durable worker/cancellation of already-started model inference; no per-end-user quotas on the customer's side. The customer server must authenticate and rate-limit its users. A server API key must never be exposed in a public chat widget. Signup token grants are not abuse-resistant until verified identity and edge admission controls are added.

OAuth must be used when adding external inbox access. Never ask for customer mail passwords. Email drafts must stay drafts until the user explicitly approves a future send capability and the backend enforces it independently of model text.
