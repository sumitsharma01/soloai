# Voice Receptionist

Voice Receptionist is a browser-call preview. Customers configure it in SoloAI; the operator connects one shared Azure realtime deployment. Each call loads only the signed-in workspace's settings and opens its own Azure conversation. LiveKit is not required for this version.

![Voice Receptionist setup in SoloAI](screenshots/voice-receptionist.png)

## Set up your receptionist

1. Open **My agents → Voice Receptionist · Preview** or select it in the Agent store.
2. Enter your business name, approved information, instructions and welcome message. Use `{Company}` in the greeting or instructions.
3. Explain how callers can contact a person when the receptionist cannot help.
4. Choose the model and voice. Only the deployment configured by the operator appears.
5. Save, then select **Start test call** and allow microphone access. End the call when you finish.
6. Reopen the page after a completed test and enable the setup when you are happy with it.

Enabling marks the tested configuration ready. It does not publish a phone service. Signed-in owners can run test calls while the setup is disabled. Editing settings clears the tested and enabled state. Calls already running retain their original instructions; disabling stops them.

Advanced settings contain language, maximum test length and whether callers can interrupt a reply. We do not ask customers for model keys, dispatch rules or infrastructure settings.

## What works today

The receptionist can greet callers, answer from supplied business information and explain how to contact the team. It can prepare callback requests for confirmation. In development mode it can also look up and propose changes to synthetic bookings. It has no tools for real transfers, reservations, orders or payments. The server explicitly tells it not to claim those actions. These instructions reduce misleading responses, but do not guarantee that every spoken answer is correct. Test your business scenarios before relying on the answers.

## Operator setup

Use an Azure realtime deployment. Keep the existing chat/email deployment separate. Set these environment variables on the SoloAI server, using a private file outside Git or your secret manager:

```bash
export SOLOAI_VOICE_AZURE_ENDPOINT=https://your-resource.cognitiveservices.azure.com
export SOLOAI_VOICE_AZURE_DEPLOYMENT=gpt-realtime-2.1-mini
# Load SOLOAI_VOICE_AZURE_API_KEY from your private environment file.
export SOLOAI_VOICE_DAILY_SECONDS=600
```

The endpoint is the resource root, without `/openai/v1/realtime` or a query string. The deployment name must match your Azure deployment. Restart SoloAI after changing environment variables. Never put the key in a browser form or commit it.

For local development, `SOLOAI_INIT_SCHEMA=true` creates the voice tables at startup. Existing installations with automatic schema creation disabled must run the application's `init_db()` using their normal deployment environment before enabling this feature. Back up the database first. The voice preview supports SQLite locally and PostgreSQL. It does not support SQL Server yet.

Set `PUBLIC_ORIGIN` to the exact browser origin, including the local port. Production needs HTTPS and a proxy that supports WebSocket upgrades and connections lasting at least the configured call duration. Browsers require a secure context for microphone access; localhost is permitted for local tests.

## Request flow

```mermaid
flowchart LR
    A[Customer browser] -->|1. Save business settings| B[SoloAI API]
    B -->|2. Store workspace configuration| C[(SQLite or PostgreSQL)]
    A <-->|3. Authenticated audio connection| B
    B -->|4. Check session and call allowance| C
    B <-->|5. Separate conversation per call| D[Shared Azure realtime model]
    B -->|6. Save status and reported token usage| C
```

Audio passes through SoloAI to Azure. The browser receives audio, not the Azure key. The server supplies instructions and accepts audio bytes only, so a caller cannot submit arbitrary session settings or tools through this endpoint. There are no database tools attached to the model.

## Conversation and actions

The receptionist introduces itself once at the start of a call. Later turns use the same Azure conversation, so follow-up questions can refer to details already discussed. Business instructions can describe tone and rules, but cannot create new capabilities. A warm conversational style should never imply that the assistant is a person.

### Actions available in the local demo

![Voice action controls](screenshots/voice-actions.png)

Under **Actions**, enable callback requests and, if needed, the synthetic booking demo. Save the settings before starting a new call.

- **Callback request:** give a name, contact method and reason. The agent prepares a request; click **Confirm callback request** to save it for staff review. No email is sent and no callback is scheduled. These fields expire after twenty-four hours. Expired records are removed on the next voice-page visit, so physical deletion can occur later.
- **Booking lookup:** ask for a booking reference shown in the Synthetic bookings panel. The server restricts the lookup to your workspace's demo customer. A spoken name or reference is not identity verification.
- **Create or change a booking:** give exact future dates and a guest count. Review the proposal in SoloAI, then click **Confirm demo booking**. This writes only to the separate synthetic booking tables. The agent can check the proposal status when you tell it you confirmed.

Start by creating a synthetic booking, then use its reference for lookup and change tests. Each workspace has one demo accommodation, with up to eight guests and stays of one to thirty nights. Confirmed stays cannot overlap. Proposals expire after fifteen minutes; duplicate confirmations return the existing result. A change is rejected if someone has changed the booking since the proposal was created.

The signed-in workspace session acts as the verified demo customer. This is a demonstration identity boundary, not a production caller verification flow. Real bookings still need a write-capable connector and a customer authentication mechanism. The demo tools are unavailable outside `SOLOAI_ENV=development` and never call the existing Supabase or MCP connector.

The server rechecks permissions before preparing an action and before confirming it. Each call allows at most eight tool calls. The model cannot directly confirm a write. Booking demo records remain in the local database; do not put real customer data in them.

## Receptionist scope guardrail

The server adds a receptionist-only policy after the saved business instructions. The assistant should decline unrelated coding, trivia and general advice, including requests framed as roleplay or “ignore your rules”. For mixed questions it should answer only the supported business part. If business information is missing, it should say so and offer your configured contact route.

This is a model instruction guardrail, not a deterministic content filter. Audio is streamed as the model produces it; SoloAI does not independently classify each utterance before playback. Do not treat successful test cases as a guarantee against prompt injection. Tool permissions, workspace checks and confirmation requirements are enforced separately by the server.

To repeat the live behavior checks, load the private Azure voice environment and run:

```bash
python scripts/eval_voice_scope.py
```

This uses paid Azure audio inference. It sends only synthetic questions and prints generated transcripts for review. Check that coding and prompt-disclosure requests are declined, the closing-hours question is answered, and no refund policy is invented. It does not exercise microphone recognition or acoustic attacks.

## Limits and privacy

- One active call per workspace, with a maximum length of three minutes.
- Ten minutes reserved per workspace per UTC day by default. The full selected duration counts when a call starts, including failed or short calls.
- The server checks session expiry, logout and stop controls during a call.
- Configuration changes use revision checks to prevent overwriting newer settings.
- SoloAI stores settings and operational call metadata, including reported token totals. It does not persist call audio or transcripts. Callback details and synthetic booking records are stored separately when you enable those actions. Azure processes the audio under your Azure service terms.
- Voice has its own duration allowance. It is not deducted from the existing email/chat token budget. The allowance limits usage, but is not a currency spending cap.

This is a pilot, not a production telephone service. The audio relay adds a server hop and holds a connection per call. Before a wider rollout, measure concurrent calls, reconnect behavior, audio quality, provider throttling and regional latency. LiveKit or a direct WebRTC design can be evaluated when those requirements are known.

## Troubleshooting

| Problem | Check |
|---|---|
| Voice is not connected | Confirm all three Azure variables are present on the running server. Restart after changes. |
| Browser says Could not connect; server logs Unsupported upgrade request | Reinstall `requirements.txt` and restart SoloAI. Browser calls require the pinned `wsproto` dependency. In-process API tests do not verify the network upgrade. |
| Call fails immediately | Check the deployment name, Azure access and exact `PUBLIC_ORIGIN`. Never paste keys into logs. |
| Microphone blocked | Allow microphone access for SoloAI in browser settings. Use localhost or HTTPS. |
| No Enable button after testing | End the call and reopen the voice page. A completed model response is required for the saved revision. |
| Workspace already has a call | End the other call. A stale reservation expires after its maximum duration plus fifteen seconds. |
| Daily allowance reached | Wait until the next UTC day or ask the operator to review the allowance. |

## Verification

Automated tests cover workspace isolation, configuration revisions, model selection, enabling checks, origin checks, concurrent-call reservations and daily limits. A live smoke test against the configured Azure deployment returned audio through the SoloAI endpoint. Physical microphone quality and telephone handling are separate checks; telephone handling is not implemented.

API reference: [Azure realtime audio over WebSockets](https://learn.microsoft.com/en-us/azure/foundry/openai/how-to/realtime-audio-websockets).
