# Connect an Azure model

Email Support can use an Azure model deployment directly. SoloAI supplies the instructions, runs the allowed tools and checks the response. You do not need to create a separate Foundry agent for this option.

Store these settings in a private environment file outside the repository, then load them into both the API and worker processes:

```dotenv
AZURE_OPENAI_ENDPOINT=https://YOUR_RESOURCE.cognitiveservices.azure.com
AZURE_OPENAI_DEPLOYMENT=YOUR_DEPLOYMENT
AZURE_OPENAI_API_VERSION=2025-01-01-preview
AZURE_OPENAI_API_KEY=YOUR_RESOURCE_KEY
```

The endpoint is the resource address, without `/openai/deployments/...`. Keep `AZURE_FOUNDRY_PROJECT_ENDPOINT` unset: a registered Foundry project takes precedence when it is set.

The direct email connection currently uses a resource API key. Keep the key on the server, restrict access to the file and never commit it. The tested deployment is `gpt-4.1-mini`; another model must support the tool and JSON response settings used by this adapter.

After changing the settings, restart the API and worker. Run the [email evaluation](EMAIL-PILOT.md) to check the connection and response behavior. A successful authentication check alone does not verify the agent's decisions.

If you already use a registered Foundry agent, keep that configuration and use its Azure identity setup instead. When the checked-in agent instructions change, publish and configure the matching version before processing new emails.
