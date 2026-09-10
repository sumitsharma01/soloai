"""Stateless, version-pinned Foundry support adapter. No customer tools or memory."""
import json
import os
from pathlib import Path
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field

INSTRUCTIONS = (Path(__file__).resolve().parents[1] / 'agents/soloai-support/instructions.md').read_text()
MAX_OUTPUT = 2048

class SupportReply(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    channel: Literal['website_chat', 'email_draft']
    subject: str = Field(max_length=300)
    reply: str = Field(min_length=1, max_length=12000)
    needs_human: bool


def envelope(agent, guidance, content):
    return json.dumps({'channel': 'email_draft' if agent == 'email-support' else 'website_chat',
                       'business_guidance': guidance, 'customer_message': content})


def invoke(payload):
    # Called in a worker thread so other requests, including Stop, remain responsive.
    from azure.ai.projects import AIProjectClient
    from azure.identity import DefaultAzureCredential
    name = os.environ['AZURE_FOUNDRY_AGENT_NAME']
    version = os.environ['AZURE_FOUNDRY_AGENT_VERSION']
    with DefaultAzureCredential(exclude_interactive_browser_credential=True) as credential:
        with AIProjectClient(endpoint=os.environ['AZURE_FOUNDRY_PROJECT_ENDPOINT'],
                             credential=credential, retry_total=0) as project:
            definition = project.agents.get_version(name, version).definition.as_dict()
            # Fail closed if an operator configured tools or changed the reviewed package.
            if (definition.get('kind') != 'prompt' or definition.get('tools') or
                    definition.get('instructions') != INSTRUCTIONS or
                    definition.get('model') != os.environ['AZURE_FOUNDRY_MODEL']):
                raise ValueError('Unapproved agent definition')
            with project.get_openai_client(max_retries=0, timeout=60) as client:
                response = client.responses.create(
                    input=payload, store=False, max_output_tokens=MAX_OUTPUT,
                    extra_body={'agent_reference': {'type': 'agent_reference',
                                                    'name': name, 'version': version}})
    if response.status != 'completed' or any(item.type not in ('message', 'reasoning') for item in response.output):
        raise ValueError('Incomplete or unexpected agent output')
    result = SupportReply.model_validate_json(response.output_text)
    if result.channel != json.loads(payload)['channel'] or (result.channel == 'website_chat' and result.subject):
        raise ValueError('Agent channel mismatch')
    tokens = response.usage.total_tokens
    if type(tokens) is not int or tokens < 0:
        raise ValueError('Missing usage')
    return result, tokens
