# Connect a Gmail inbox

Gmail intake is read-only. SoloAI reads new inbox messages, forwards them to the
existing email queue, and produces drafts for operator review. It does not create
Gmail drafts, send mail, change labels, or delete messages. Forwarded content is
processed by the configured Azure Foundry agent and follows email-review retention.

1. Enable Gmail API in your Google Cloud project.
2. Configure the OAuth consent screen in testing mode and add your Gmail account
   as a test user. Request only `https://www.googleapis.com/auth/gmail.readonly`.
3. Create a **Web application** client. Register
   `http://127.0.0.1:8300/api/integrations/gmail/callback` for this local demo.
4. Keep the downloaded JSON outside the repository. Configure `GMAIL_CLIENT_FILE`.
5. Generate an encryption key once with
   `python -m scripts.gmail_key /absolute/private/path/gmail-token.key`, then set
   `GMAIL_TOKEN_KEY_FILE` to that file for both API and worker. Do not replace the
   key while encrypted connections exist. Use your secret manager in production.
6. Run `python -m scripts.email_admin migrate` to apply additive migration 002.
   Restart the API and email worker with the same configuration.
7. Sign in to SoloAI, open **Connect Gmail**, enter your Gmail address, and complete
   Google's consent flow. Google sign-in and consent are performed by the account owner.

The baseline history cursor is captured at connection time. Existing mail is not
imported. Send a new support message from a different account and check **Email
review** after approximately one minute. The worker handles one page per sync and
may take longer under load. Messages must be in INBOX, not Sent, Draft, Spam or Trash.
Attachments are not fetched. Unsupported bodies and messages longer than the current
8,000-character event limit are skipped with an audit event, rather than silently
truncating customer information.

Refresh tokens are encrypted with a server-held Fernet key and bound to their tenant
inside the encrypted payload. Access tokens live only in process memory. OAuth uses
PKCE, a one-time state, a short-lived browser-binding cookie, and validation of the
original SoloAI session. The Google mailbox must match the address entered before
connecting. A mailbox can belong to only one workspace. Secrets, codes, message
content and token responses are not logged. Keep HTTP access logs disabled for the
OAuth callback, including at any reverse proxy, since its query contains a code.

Message IDs produce stable tenant-scoped event IDs. The history cursor advances only
after a page has been enqueued successfully. Quota/rate-limit failures preserve the
cursor, and retries deduplicate existing jobs. A polling lease fences concurrent
workers. Disconnect invalidates the lease and removes saved tokens; it prevents new
intake but does not remove already queued drafts. To also revoke Google's grant,
remove SoloAI under your Google Account's third-party access settings.

If Google expires the history cursor, sync pauses with `gmail_history_expired`.
Disconnect and reconnect establishes a new baseline; it does not silently import an
old inbox. Revoked/expired authorization requires reconnection. Google testing-mode
authorizations can expire; a public launch also needs the applicable Google scope
verification and data-policy review. This local integration is not evidence of that
verification having been completed.

See Google's [web OAuth documentation](https://developers.google.com/identity/protocols/oauth2/web-server)
and [Gmail synchronization guide](https://developers.google.com/workspace/gmail/api/guides/sync).
