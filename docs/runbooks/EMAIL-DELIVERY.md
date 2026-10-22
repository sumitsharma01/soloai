# Email delivery recovery

## Sending is unavailable

Check **Automation rules** for Gmail send authorization. Read-only Gmail connections cannot send. The email also needs delivery metadata captured by the new Gmail intake. Older emails and generic API events are review-only. The agent must be enabled, the draft must be current and its retention deadline must not have passed.

## FAILED

Gmail returned a definite rejection, such as invalid authorization or a rate limit. The draft remains saved. Correct the cause and retry manually. A failed automatic send is not replayed by the automatic worker. Check the daily send limit as failed attempts count conservatively.

## UNKNOWN or a stuck DISPATCHING record

The request may have reached Gmail even though SoloAI did not receive a usable response. Do not resend from SoloAI. Check the connected mailbox's Sent folder for the recipient, subject and time. Gmail does not provide an exactly-once send transaction with our database.

The worker changes dispatches older than two minutes to UNKNOWN. If the API died during sending, restart the worker to run recovery. Both states block editing, regeneration and another dispatch. The deterministic Message-ID helps investigate a sent reply; it is not a Gmail idempotency guarantee.

There is deliberately no one-click retry for uncertain delivery. If investigation proves that nothing was sent, an operator can compose a new reply directly in Gmail. Record that resolution in the operational incident log. This release does not have an inbox reconciliation button.

## Automatic replies are not going out

Check that sending is authorized, automation is enabled, eligible labels are selected and the daily limit is not exhausted. The message must have arrived after the most recent rules save. Drafts requiring human help, sensitive requests, booking lookups, edited drafts and automated messages remain in review. Reconnecting Gmail or editing a label pauses automation. A token-refresh failure also pauses automatic sending to avoid repeated failing calls; reconnect or resolve the outage before explicitly enabling it again.

## Someone changed the draft while I was reviewing it

Close and reopen the email. Revision checks prevent a stale browser from overwriting a newer draft or sending an older version. Your unsaved edits are not automatically merged.

## Immediate stop

Use **Pause automatic sending** to stop new automatic dispatches. Use **Stop all agents** to block new manual and automatic sends too. Requests already dispatched may still finish. Never delete the delivery ledger to clear an error; doing so removes duplicate-send protection.
