# Get started with SoloAI

SoloAI keeps your agents and their connections in one workspace. Start with a local preview, then connect real services when you are ready.

## 1. Start the preview

Install Python 3.13. In the SoloAI repository folder, run:

```bash
bash scripts/run-free-local.sh
```

Open http://127.0.0.1:8000 and choose **Create a workspace**. Use a password of at least 12 characters. No shared demo password is needed. If you already created an account in this preview, sign in with those details.

The preview installs its dependencies in `.venv` and keeps its accounts in `soloai-free.db`. It deliberately ignores live model settings and does not start Gmail syncing or monitoring. This keeps the first run independent of your cloud setup.

## 2. Try an agent

Open **My agents**, choose Email Support, and add a short policy such as “Customers can change a booking up to 24 hours before arrival. Refer payment questions to support.” Save it, turn the agent on, and try a customer message.

Replies in this mode are simulated. Use this step to explore the controls, not to judge the quality of an AI model. Real replies need [Azure Foundry setup](IMPLEMENTATION.md#prepared-foundry-support-agent).

## 3. Connect Gmail on a configured instance

1. Open **Integrations** and click Gmail's **Connect with Google**.
2. Choose the Gmail account you want SoloAI to read.
3. Review Google's permission screen and sign in with the mailbox you intend to connect.
4. Return to SoloAI and check that the address is shown as connected.
5. Enable Email Support and send a new message to the connected inbox. With the email worker running, it should appear in **Email review** after syncing and processing.

Existing inbox messages are not imported. Sync runs roughly once a minute while the worker is running. SoloAI reads mail but does not send or delete it. Review the draft and verify any customer details before replying through your mailbox.

If the page says setup is needed, the person running SoloAI must complete the [Gmail setup guide](GMAIL.md) and [email worker setup](EMAIL-WORKFLOWS.md). A Google sign-in button cannot work until that installation has its own OAuth configuration. Never send your Google password to SoloAI.

## 4. Add booking information

The booking card shows the connection selected for your workspace. Today, your operator configures an approved read-only booking service or a local snapshot. There is no self-service Supabase connection yet. See the [booking setup guide](MCP.md) if you operate the installation.

## If something goes wrong

| Problem | What to do |
|---|---|
| Port 8000 is busy | Run `SOLOAI_LOCAL_PORT=8001 bash scripts/run-free-local.sh` and open port 8001. |
| Python is missing | Install Python 3.13 and reopen your terminal. |
| Package installation fails | Check your internet connection and Python version, then retry. Keep the final error for the operator if it fails again. |
| Sign-in fails | The preview uses a separate local database. Create a workspace if this is your first visit; credentials from another installation will not work here. |
| Replies are simulated | This is intentional in the free preview. Use the Foundry guide for a live installation. |
| Gmail says invalid or expired request | Start a new connection from Integrations. Do not reuse an old Google callback URL. See the [runbooks](runbooks/README.md). |
| No new email appears | Check the connected address, agent status and worker. Send a new email after connecting. Ask the operator to check the Gmail runbook. |

Stop the preview with `Ctrl+C`. Start it again with the same command. Do not delete the database to resolve a sign-in problem unless you intend to remove all preview workspaces.
