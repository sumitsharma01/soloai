# Gmail integration runbook

Owner: application operator, with the Google project owner for console changes.
Related guide: [Gmail setup](../GMAIL.md).

## 1. Authorization and Google configuration

| Symptom | Check | Recovery | Verify |
|---|---|---|---|
| Permission denied or `gmail_access_denied` | Is Gmail API enabled in the same project as the OAuth client? Is consent granted? A 403 alone does not identify the cause. | Enable Gmail API using the project owner account. Confirm read-only consent. Start a fresh connection. | Connected status, then a recent successful sync |
| Project missing or resource picker opens | Google Cloud may be using a different signed-in account | Switch to the account owning the project named in your client JSON. Do not enable an unrelated project. | Correct project selected and Gmail API shows enabled |
| Google blocks a testing app | Check Google Auth Platform, Audience, Test users | Add the exact mailbox as a test user. Keep the app in Testing during development. | That account reaches consent |
| `redirect_uri_mismatch` | Compare scheme, hostname, port and callback path | Register the exact PUBLIC_ORIGIN plus `/api/integrations/gmail/callback`. localhost and 127.0.0.1 differ. Update the local JSON if needed and restart both processes. | Consent returns to the intended local server |
| Invalid or expired Gmail connection request | Ten-minute state expired, binding cookie missing, different browser, or callback already consumed | Return to SoloAI and select Connect Gmail again in the same browser. Do not refresh or reuse the callback URL. | Fresh consent completes once |
| First callback fails, later refresh says invalid request | State is consumed before token exchange and profile lookup | Preserve the first safe error message. Fix that underlying failure and reconnect. Do not disable state checks. | Connected status |
| Sign in again before connecting Gmail | Original SoloAI session has expired | Sign in to SoloAI and start a new connection | Callback accepts the active session |
| `gmail_wrong_account` | Google account differs from the address entered in SoloAI | Select the matching Google account on a fresh attempt | Connected address matches |
| `gmail_readonly_consent_required` | Refresh token missing or returned scopes differ from the required scope | Start fresh consent and grant gmail.readonly. Do not add send/modify scopes to work around it. | Connection succeeds with read-only access |
| Mailbox already connected to another workspace | Mailbox uniqueness is enforced | Confirm ownership and disconnect from the original workspace before reconnecting | One intended workspace owns the connection |

Observed during local setup: the initial callback failed; subsequent refreshes showed a consumed-state error. Gmail API activation and selecting the correct Google project account were setup blockers. The generic callback error did not retain enough detail to prove the exact first provider error. A later connection succeeded.

## 2. Sync and queue processing

| Symptom | Recovery | Verify |
|---|---|---|
| Connected but no new messages | Confirm worker is running, Email Support enabled, last sync recent. Send a new message after connection. Existing inbox contents are not imported. Check INBOX placement, supported body and 8,000-character limit. | New entry in Email review after polling and processing |
| `gmail_reconnect_required` | Authorization may be revoked or expired. Disconnect and reconnect. Testing-mode refresh tokens for Gmail scopes generally expire after seven days. | Last sync advances |
| `gmail_history_expired` | Disconnect and reconnect to establish a new baseline. Record the unprocessed interval for manual handling. Reconnection does not backfill it. | New mail after reconnection appears |
| `gmail_rate_limited` or `gmail_unavailable` | Check provider availability and quotas. Allow scheduled retry; do not run a rapid reconnect loop. | Error clears and last sync advances |
| Token allowance exhausted or pending queue full | Review pending work and token budget. Do not delete jobs or reset usage just to bypass controls. | Intake resumes after capacity is legitimately available |
| Duplicate delivery | Stable event IDs should return the existing job. Inspect metadata before retrying. | One execution per tenant/message |
| Draft waiting for review | Normal behavior. Operator reviews accuracy and customer identity | Approve/reject records a decision; neither sends email |

## 3. Secrets, containment and recovery

If server configuration is unavailable, verify both processes can read the same client JSON and Fernet key file and that the callback is registered. Never print their contents. Keep files outside Git with restrictive permissions.

If the encryption key changes or is lost, restore it from secure backup. Do not overwrite encrypted tokens or silently generate a replacement. If recovery is impossible, the owner must reconnect each affected mailbox with an intentionally configured new key.

To stop intake, use Disconnect Gmail. This removes saved tokens and fences future intake, but queued content remains under retention. Revoke SoloAI in Google Account third-party access to remove Google's grant too. Use the agent stop control to halt further processing; already submitted Azure calls may still consume tokens.

## 4. Evidence and escalation

Collect only timestamp, safe error code, connected/last-sync status, worker health and execution status. Do not include the OAuth code, state, client secret, refresh token or message body. Escalate project permissions to the Google project owner; worker/model failures to the application operator. Close the incident only after a new synthetic email reaches review and no unexpected send occurs.

References: [Google Gmail setup](https://developers.google.com/workspace/gmail/api/quickstart/python), [OAuth token expiration](https://developers.google.com/identity/protocols/oauth2#expiration), [Gmail sync and history](https://developers.google.com/workspace/gmail/api/guides/sync).
