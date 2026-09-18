# Operations runbooks

Start with the symptom, confirm the cause, apply the smallest fix, then verify recovery.
Never attach OAuth callback URLs, cookies, tokens, customer messages or database dumps to an issue.

| Area | Runbook | Owner |
|---|---|---|
| Gmail authorization and inbox sync | [Gmail](GMAIL.md) | Application operator and Google project owner |
| API, worker, Foundry and monitoring | [Local demo](LOCAL-DEMO.md) | Application operator |

For incidents record the time, environment, safe error code, affected component, action taken and recovery check. Treat a connected mailbox, a healthy sync, and a successful model execution as three separate checks.
