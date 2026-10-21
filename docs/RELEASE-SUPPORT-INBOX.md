# Support Inbox release notes

## Added

- Compact email list with sender, subject, labels, status and received time.
- Expandable detail panel, editable replies and email-specific guidance.
- Editable keyword labels and reusable business instructions.
- Separate Gmail send consent, reviewed sending and opt-in automatic replies.
- A durable delivery ledger, daily send limit and pause control.
- Migration 003, delivery metrics and a recovery runbook.

## What stays unchanged

The agent creates a draft through the existing Foundry integration. It does not receive a send tool or unrestricted database access. Supabase remains a setup-request form, and the booking MCP integration remains read-only. Legacy approve/reject endpoints retain their original meaning: approval records a review decision and does not send.

## Before upgrading

Back up the database. Stop the API and email worker. Run `python -m scripts.email_admin migrate` with the target database configuration, then start both updated processes. PostgreSQL is required in production.

Gmail connections stay read-only until the owner approves the extra send scope. Automatic sending starts off. Older emails remain visible, but lack reply metadata and cannot be sent through the new delivery endpoint.

## Validation

Delivery tests use mocked Gmail responses. Browser checks use fictional customer messages. No real email was sent and no live send grant was approved during implementation. Check the pull request's CI result for the PostgreSQL run, dependency audit and container build.

See [Support Inbox](SUPPORT-INBOX.md) for daily use and [Email delivery recovery](runbooks/EMAIL-DELIVERY.md) for failures.
