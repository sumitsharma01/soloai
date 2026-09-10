# SoloAI Support — one shared Foundry prompt agent

**Status: definition and creation utility prepared; not yet created in Azure.**

One agent supports website support answers and email drafts. It has **zero tools**, so it cannot send mail, query a database, read an inbox, or issue refunds. It uses the supplied business guidance, marks uncertainty for human handling, and returns a small JSON response. Instructions improve behavior; they do not prove correctness or replace tenant authorization.

## Create in your Foundry project

An existing Foundry project, a compatible deployed text model, an authenticated identity allowed to create/read agents, and private network access where required are prerequisites. A model endpoint alone is not a project endpoint. The current Terraform provisions model access, not the complete Foundry Agent Service project/network configuration.

From the repository root:

```bash
python3 -m venv .venv-foundry
source .venv-foundry/bin/activate
pip install -r agents/soloai-support/requirements.txt

# Local preview; no Azure call:
python scripts/create_foundry_agent.py --model YOUR_DEPLOYMENT_NAME

# Set your actual project and deployed model (these values are not secrets):
export AZURE_AI_PROJECT_ENDPOINT='https://YOUR_RESOURCE.services.ai.azure.com/api/projects/YOUR_PROJECT'
export AZURE_AI_MODEL_DEPLOYMENT_NAME='YOUR_DEPLOYMENT_NAME'
az login
python scripts/create_foundry_agent.py --apply
```

The script creates `soloai-support`, reads back its definition, and prints its ID/version. An identical existing version is reused. An existing differently configured agent is left alone unless you explicitly pass `--new-version`. Run serially; after a timeout inspect the project before retrying, because a version might have been created even if the response was lost. No publish/permission-grant operation is performed by this utility.

## What to test

Open the agent in Foundry and submit the synthetic inputs in [examples.json](examples.json). Review policy accuracy, uncertainty, draft-only behavior and attempted instruction overrides. Do not use customer data during initial testing. Model calls may incur charges.

Each call must contain a single tenant's business guidance and customer message. Do not reuse conversation IDs or stored context across tenants. The intended initial flow is stateless. Review Foundry's own retention settings separately; prompt instructions cannot enforce provider retention.

## SoloAI integration boundary

Creating this agent does **not** automatically attach it to the current dashboard. The runtime still calls a model directly. A follow-up integration must invoke a pinned agent version, validate the returned JSON, preserve tenant isolation, and enforce usage/stop rules around each invocation. It must not assume that the current model-only token reservation covers every possible agent execution.

The expected result is:

```json
{"channel":"email_draft","subject":"Your return request","reply":"...","needs_human":true}
```

Keys are output conventions, not an Azure structured-output guarantee; the future runtime adapter must validate them. Do not send an email based only on model output. Keep provider credentials out of the browser and do not grant agent-creation rights to the ordinary SaaS runtime identity.

[Microsoft prompt-agent quickstart](https://learn.microsoft.com/en-us/azure/foundry/agents/quickstarts/prompt-agent)
