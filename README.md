> **SoloAI is the plug-and-play AI control plane for founders who can build software with AI but don't want to become AI infrastructure engineers.**

# SoloAI

**Current release: v0.2.0 · Preview** · [Release notes](CHANGELOG.md)

## One platform. Many agents.

SoloAI gives founders a place to connect their tools and put agents to work. The goal is fewer repetitive tasks, clear permissions and guardrails you can understand without learning how AI infrastructure works.

Your application stays where it is, whether that is Vercel, AWS or another host. SoloAI connects to the services an agent needs. You choose what it can access and review the results.

**Create an account → Connect a tool → Set your agent's guidance → Turn it on.**

We are starting with customer support. Website Chat answers questions using your guidance. Email Support prepares replies for review. We will add more agents as these workflows prove useful and reliable.

## Custom flows preview

Create a custom agent from six blocks: manual trigger, AI task, approved tool, condition, approval and human handoff. It appears in My agents with a connected block diagram and a recoverable delete option. Tools can read workspace policies, look up a verified customer booking through the connected Supabase service, or create an internal review task. Conditions can use a text match or an AI assessment of a business rule. Test a draft, publish its version, then enable it. Runs and decisions are saved so they can be inspected and resumed. External writes and automatic triggers are not connected yet. See the [workflow builder guide](docs/WORKFLOW-BUILDER.md).

## Voice Receptionist preview

Configure a receptionist and try a microphone conversation from SoloAI. Enter your business information, instructions and greeting, then choose the configured Azure model and a voice. No customer Azure account or LiveKit setup is required.

This preview supports browser conversations. It can prepare callback requests for confirmation and, in local development, demonstrate booking lookups and confirmed changes using synthetic records. It does not connect a telephone number, transfer calls or change real bookings. Azure audio usage is billed separately. See the [voice setup guide](docs/VOICE-RECEPTIONIST.md) for operator configuration and limits.

## Try it on your computer

Install Python 3.13 and Git, then run:

```bash
git clone https://github.com/sumitsharma01/soloai.git
cd soloai
bash scripts/run-free-local.sh
```

Already have the repository? Run the last command from its folder. The script creates a Python environment and installs dependencies on first use. An internet connection is needed to download them.

Open [SoloAI](http://127.0.0.1:8000), choose **Create a workspace**, and use your own email and password. This creates a local account, not a Gmail connection. Open **My agents**, add some business guidance, enable an agent and try a message.

This preview uses simulated replies and a local SQLite database. It does not deploy Azure, call a paid model, connect Gmail or start Grafana. Stop it with `Ctrl+C`. Your workspace stays on your computer for the next run.

If port 8000 is already in use:

```bash
SOLOAI_LOCAL_PORT=8001 bash scripts/run-free-local.sh
```

Then open [port 8001](http://127.0.0.1:8001). For more help, see [Getting started](docs/GETTING-STARTED.md).

## Connect your tools

Open **Integrations** in SoloAI. It is the starting point for connections and their status.

| Connection | Available today |
|---|---|
| Gmail | Sign in with Google once your SoloAI operator has configured Gmail. Read new inbox messages and prepare drafts. Optional send consent supports reviewed replies and explicitly enabled automatic replies. No deleting. |
| Booking information | Restricted Supabase lookup with customer verification. MCP and imported snapshots remain available for development. |
| Your application | Optional server API for custom events. Kept under the developer section. |
| Supabase | [Restricted booking connection](docs/SUPABASE.md). Requires an operator-configured Edge Function and a dedicated token. |
| Outlook | Pilot implementation with separate Microsoft consent. Automated tests pass; live mailbox verification is still pending. |

You do not need to give SoloAI access to your AWS or Vercel account just because your website runs there. Connect the mailbox or approved business data the agent needs instead.

For a managed SoloAI service, the operator sets up the Google application once and customers use **Connect with Google**. If you run SoloAI yourself, you are also its operator and must complete that setup. The local preview does not skip Google's requirements.

## Keep control

- Each workspace has its own agent settings, permissions and usage allowance.
- Booking access is read-only. Agents do not get unrestricted database credentials.
- Support Inbox lets you edit and send reviewed replies. Automatic sending is off by default and requires separate consent and rules.
- Stop controls and token limits bound agent activity.
- Manual test content is transient. The optional email review workflow stores emails and drafts temporarily, with a configurable retention period.

These controls reduce risk; they do not guarantee that an AI response is correct. See [security boundaries and limitations](SECURITY.md).

## Support Inbox

Review emails in a compact list, open a message to edit the reply, manage labels and save business instructions. Sending requires explicit Gmail authorization. See the [Support Inbox guide](docs/SUPPORT-INBOX.md) for setup, automation rules and recovery.

## Go beyond the preview

These guides are for the person running SoloAI. Customers of a configured instance should not need to follow infrastructure instructions.

| Task | Guide |
|---|---|
| Use the product locally | [Getting started](docs/GETTING-STARTED.md) |
| Connect a real model | [Direct Azure model](docs/AZURE-MODEL.md) or [registered Foundry agent](docs/IMPLEMENTATION.md#prepared-foundry-support-agent) |
| Receive Gmail and review drafts | [Gmail setup](docs/GMAIL.md) and [email worker](docs/EMAIL-WORKFLOWS.md) |
| Connect booking data | [MCP setup](docs/MCP.md) |
| Run Grafana and Prometheus | [Monitoring](docs/monitoring.md) |
| Understand Azure and Cloudflare | [Architecture](docs/ARCHITECTURE.md) |
| Deploy with Terraform and GitHub Actions | [CI/CD](docs/CICD.md) |
| Diagnose a known issue | [Runbooks](docs/runbooks/README.md) |
| Develop or operate SoloAI | [Implementation reference](docs/IMPLEMENTATION.md) |

## Product demo

[![SoloAI helps a busy lemonade shop](docs/media/soloai-lemonade.gif)](docs/media/soloai-lemonade.mp4)

The animation illustrates the product vision. The screenshots below show earlier local demo sessions; they are not evidence of an Azure deployment. The navigation has since been consolidated into Integrations.

| SoloAI | Grafana |
|---|---|
| ![SoloAI local dashboard](docs/screenshots/platform-live.png) | ![Grafana local dashboard](docs/screenshots/grafana-live.png) |

### Email pilot checks

See [Email pilot: review, recovery and evaluation](docs/EMAIL-PILOT.md) for inbox outcomes, failure recovery, lifecycle tests and the live Azure evaluation.
