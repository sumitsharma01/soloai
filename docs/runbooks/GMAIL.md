# Gmail connector runbook

This runbook covers the optional, read-only Gmail intake used by the Email Support agent. It is kept separate from the general platform runbooks so an inbox incident cannot change the core agent or tenant controls.

## Normal setup

1. In the Google Cloud project that owns the OAuth client, enable **Gmail API**.
2. Configure the OAuth consent screen in testing mode and add the mailbox as a test user.
3. Create a Web application OAuth client with the exact callback shown in [GMAIL.md](../GMAIL.md).
4. Keep the downloaded client JSON outside Git. Set `GMAIL_CLIENT_FILE` and create `GMAIL_TOKEN_KEY_FILE` with `python -m scripts.gmail_key <path>`.
5. Run the additive migration, restart the API and worker, then use **Connect Gmail** in SoloAI.
6. Confirm the status shows the expected mailbox. Send a new message from another account and check Email review after the next polling cycle.

## Triage by symptom

| Symptom | Check | Recovery |
|---|---|---|
| Google says the app is not verified | OAuth consent screen | Continue only for an account listed as a test user. Production use needs Google's verification. |
| Permission denied or `gmail_access_denied` | Gmail API is enabled and the account is a test user | Enable Gmail API in the OAuth project, add the exact mailbox as a test user, then reconnect. |
| Invalid or expired connection request | Callback was refreshed, opened in another browser, or took over ten minutes | Return to SoloAI and start a new connection. OAuth states are one-time and browser-bound by design. |
| Wrong Google account | Account differs from the address entered in SoloAI | Sign out or choose the entered account, then reconnect. |
| `gmail_reconnect_required` | Consent was revoked or the refresh token expired | Remove SoloAI from Google third-party access if needed, then connect again. |
| `gmail_history_expired` | Gmail's incremental history cursor is no longer valid | Disconnect and reconnect. SoloAI creates a new baseline and does not import old mail. |
| Connected but no new job | Message is not in Inbox, agent is disabled, or worker is stopped | Confirm Email Support is enabled, start the worker, and check the worker logs and Email review dashboard. |
| Message skipped | Attachment-only, unsupported body, or over 8,000 characters | Send a plain-text message or handle it manually. Skips are recorded as audit metadata. |

## Safety and ownership

Only `gmail.readonly` is requested. Refresh tokens are encrypted and tenant-bound; access tokens remain in memory. A mailbox can belong to one workspace. Disconnect stops new intake and removes the saved token, while already queued drafts remain available for review. SoloAI never sends, deletes, labels, or modifies Gmail messages.

Do not paste OAuth JSON, refresh tokens, authorization codes, message bodies, or customer data into logs or issue trackers. OAuth callback access logs must be disabled because the query contains a temporary code. Rotate the encryption key only after all existing connections have been disconnected or migrated.

## Useful checks

```bash
python -m scripts.email_admin migrate
curl -s http://127.0.0.1:8300/health
curl -s http://127.0.0.1:8300/api/integrations/gmail
```

The status endpoint returns availability and mailbox state only. It never returns credentials.
