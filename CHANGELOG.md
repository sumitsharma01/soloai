# Release notes

## v0.2.0 · 28 October 2026

This release brings custom agents into My agents and adds browser voice conversations, clearer agent navigation and operational overviews. It is still a preview. The limits below are part of the release, not optional setup steps.

### Custom agents

- Build a flow from a manual trigger, AI tasks, approved tools, conditions, approvals and human handoffs.
- See the flow as connected blocks and select a block to edit its settings.
- Test, publish and enable separately. Draft changes do not alter a published run.
- Use workspace business policies and the business name as context. Read a booking through the existing restricted Supabase connector after independently verifying the customer.
- Let an AI condition assess a business rule. An unclear response stops the flow. AI decisions do not grant permissions.
- Create internal review tasks after the configured steps and approvals.
- Delete a custom agent from Options and restore it from Deleted agents. Deletion disables it and stops active runs; history is retained.

Runs have persisted step status, tenant isolation, token limits and duplicate-action protection. Recovery is manual, and uncertain provider outcomes are not automatically replayed. There are no schedules, email triggers, external writes, arbitrary branching or drag-and-drop connections yet. Policy and booking reads are real during tests; task writes are simulated.

### Voice and email

- Configure and test the Azure realtime receptionist inside SoloAI using a browser microphone.
- Keep introductions at the start of a conversation and apply receptionist-scope instructions.
- Confirm callback requests and demonstrate booking actions with synthetic local records.
- View email and voice operational overviews from collapsible agent navigation.

Telephone numbers, real call transfers and real voice booking changes are not connected. Scope controls reduce unwanted behavior but are not a guarantee against every prompt-injection attempt.

### Validation

The complete release test suite passed: 124 tests. Two dependency deprecation warnings remain in the test client.

The earlier workflow acceptance run used the live Azure chat model and passed nine checks, including approval pauses and duplicate-request handling. Supabase workflow adapter tests use mocked responses, including wrong-customer and changed-connector cases. A live Supabase workflow lookup has not yet been verified. See the [acceptance report](docs/reports/workflow-acceptance-2026-10-28.md).

### Updating an existing installation

Back up the application database, update the code, and run the normal schema initialization step before serving traffic. The workflow and archive tables are additive. Local installations can use `SOLOAI_INIT_SCHEMA=true`; production operators should run their controlled `init_db()` step. The workflow preview supports PostgreSQL and local SQLite, not SQL Server.

No new Azure infrastructure is required. AI tasks need the existing direct Azure chat configuration. Voice uses its separate realtime configuration. Existing connector credentials stay outside Git.

Run inputs, outputs and internal tasks have no automatic retention expiry yet. Recoverable deletion is not data erasure. Use synthetic workflow data until a retention process is in place.

Read the [workflow guide](docs/WORKFLOW-BUILDER.md) and [voice guide](docs/VOICE-RECEPTIONIST.md) before enabling these previews.
