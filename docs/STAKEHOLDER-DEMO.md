# SoloAI stakeholder walkthrough

Open the platform at http://127.0.0.1:8000 and Grafana at
http://127.0.0.1:3000/d/soloai-live. Keep this computer awake and online.

## Five-minute walkthrough

1. **My agents:** show Website Chat and Email Support running in one workspace.
   Explain that enabling an agent changes configuration, not the customer's deployment.
2. **Website Chat:** open Manage agent and show its business guidance. Ask:
   “What can SoloAI automate for my business?” The live Foundry agent responds.
3. **Email Support:** ask “Please reset my account password and email confirmation.”
   The expected behavior is a review-only draft referring the action to human support.
   It has no tool that can reset an account or send an email. Model wording may vary.
4. **Activity:** show the actual execution, latency and token usage.
5. **Grafana:** show scrape health, request throughput, agent latency and reported tokens.
   Refresh after 5 seconds. Quiet charts are normal; these are real measurements,
   not generated traffic or a load-test claim. Newly created rate series need time.
6. **Control:** disable an agent, try a message and show the rejection. Turn it back on.
   Stop all agents is available, but it disables both and they must be re-enabled.

The workspace has a finite starter allowance. Large requests reserve their maximum
possible usage, so a request can be rejected before the displayed usage reaches 10,000.
Use short questions and avoid repeating live tests unnecessarily.

## What this demonstration actually runs

- Local FastAPI application and SQLite database, with tenant-scoped configuration.
- A real shared Azure Foundry support agent using gpt-5.4 and server-side Entra login.
- Local Prometheus and Grafana with loopback-only listeners.

Azure SQL, Cloudflare Tunnel, private networking and the Azure Workbook are described in
Terraform, not deployed locally. This demo does not validate their production behavior.
Live AI requires internet access and incurs model usage. Email inbox ingestion and
sending are not implemented. The model has no privileged tools or shared conversation.

The browser session is already signed in on the demo machine. Credentials are not
included in this document. If the session expires, sign in with your workspace account.
For restarting, see `docs/live-agent.md` and `monitoring/README.md`; add
`SOLOAI_METRICS_PORT=9464` to the app environment. Azure CLI must remain on PATH with
the same AZURE_CONFIG_DIR used to sign in. Do not expose these local ports publicly.
