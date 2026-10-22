# Support Inbox release notes

## Added

- Compact email list with sender, subject, labels, status and received time.
- Expandable detail panel, editable replies and email-specific guidance.
- Editable keyword labels and reusable business instructions.
- Separate Gmail send consent, reviewed sending and opt-in automatic replies.
- A durable delivery ledger, daily send limit and pause control.
- Database migrations through version 006, delivery metrics and recovery guidance.

## What stays unchanged

The agent creates drafts through a registered Foundry agent or a direct Azure model deployment. It does not receive a send tool or unrestricted database access. Supabase now supports a restricted booking function with customer verification. The older setup-request form does not grant access. MCP remains a development option for read-only booking lookups. Legacy approve/reject endpoints retain their original meaning: approval records a review decision and does not send.

## Before upgrading

Back up the database. Stop the API and email worker. Run `python -m scripts.email_admin migrate` with the target database configuration, then start both updated processes. PostgreSQL is required in production.

Gmail connections stay read-only until the owner approves the extra send scope. Automatic sending starts off. Older emails remain visible, but lack reply metadata and cannot be sent through the new delivery endpoint.

## Validation

Delivery tests use mocked Gmail responses. Browser checks use fictional customer messages. No real email was sent and no live send grant was approved during implementation. Check the pull request's CI result for the PostgreSQL run, dependency audit and container build.

See [Support Inbox](SUPPORT-INBOX.md) for daily use and [Email delivery recovery](runbooks/EMAIL-DELIVERY.md) for failures.

See [the email pilot report](EMAIL-PILOT.md) for the current test results and the known missing-price escalation issue.
