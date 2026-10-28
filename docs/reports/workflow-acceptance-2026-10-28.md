# Workflow acceptance test

Tested on 28 October 2026 against the running local SoloAI API and its configured Azure chat model. All customer requests were synthetic. No customer email was sent and no external booking, order or refund was changed.

## Verdict

The builder performs the actions currently described in the preview. It can run a bounded sequence, ask Azure to transform text, stop on a condition, wait for approval, create an internal task and pause for a human. Nine live acceptance checks passed. Six automated workflow tests also passed.

This is a working manual workflow preview, not yet an autonomous refund handler or a production workflow service. This acceptance run used the authenticated API. The earlier implementation check covered the browser editor; this report does not claim a new browser interaction test.

## Automation created

**Acceptance: refund review 167fb1** is saved in the local demo workspace. It was published as version 1, exercised live, and disabled after verification. Its run history and the resulting internal task remain available for inspection.

Manual trigger → condition containing “refund” → Azure summary → staff approval → internal review task → human handoff.

The AI instruction asked for two sentences, preservation of order references, no claim that a refund was approved or processed, and no obedience to instructions embedded in customer text.

Input:

> Please refund order DEMO-43. The item arrived damaged. No refund has been approved.

Actual Azure output:

> The customer requests a refund for order DEMO-43 due to the item arriving damaged. They mention that no refund has been approved yet.

The completed live run is `c9f9cedab4ef11bfb6d980dc8bca33f3`. It created internal task `f8cce2709943c9b6bcf16e79041d867c`, titled **Refund review task**, with that summary. The order reference and approval uncertainty were preserved in this example.

## Live results

| Check | Observed result |
|---|---|
| Publish before testing | Rejected with HTTP 409. |
| Request without “refund” | Stopped at CONDITION_NOT_MET, before AI or task creation. |
| Test the six-block flow | Completed after two decisions; no internal task was created. |
| Run published version | Paused at WAITING_APPROVAL; task count unchanged. |
| Approve the request | Created one internal task and paused at NEEDS_HUMAN. |
| Repeat the same start request and key | Returned the same run; task count stayed unchanged. |
| Complete handoff, then repeat decision | Run completed; extra decision rejected with HTTP 409. |
| Reject another refund request | Run became REJECTED; no additional task. |
| Disable, then start live | Rejected with HTTP 409. |

The six automated tests additionally exercise tenant isolation, stale draft updates, unsupported tools, immutable published definitions, token-budget exhaustion, model failure, expired claims and workspace stop behavior. Model responses in those automated tests are stubbed; the acceptance flow above used the configured Azure connection.

## Findings and limits

1. **The approved action is narrow.** The tool creates a SoloAI task. It does not look up an order, determine refund eligibility, issue money or contact the customer. Those actions need explicit connectors and authorization before they can be offered.
2. **Conditions match text, not intent.** “I do not want a refund” still contains “refund.” The condition must not be used to authorize a financial action. Structured classification and deterministic business rules would be needed for that use case.
3. **Human handoff is a persisted pause.** Completing it records an operator decision. It neither notifies a staff member externally nor verifies that a refund was processed elsewhere.
4. **Recovery is manual.** There is no background recovery worker. An uncertain AI outcome fails safely rather than retrying automatically. This run did not include a process restart, concurrent load or an actual provider outage.
5. **One correct summary is not an AI quality evaluation.** This example preserved the request accurately. It does not establish robustness against prompt injection, unusual language or ambiguous customer requests.
6. **Preview data persists.** Inputs, outputs and internal tasks have no automatic expiry. Use synthetic data until retention and deletion controls are implemented.

The next useful increment is one real, read-only order lookup connector, followed by a separately approved action. Keep that work distinct from adding automatic triggers and background recovery, so each new capability has a clear acceptance test.
