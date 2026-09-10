"""Create one versioned SoloAI Support prompt agent; default is a local preview.

No inference, tool grants, tenant data, or changes to the existing SaaS runtime.
Run creation serially. After an uncertain network failure, inspect Foundry before
retrying: Azure version creation is not an exactly-once operation.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
from urllib.parse import urlparse

AGENT_NAME = 'soloai-support'
INSTRUCTIONS = Path(__file__).resolve().parents[1] / 'agents/soloai-support/instructions.md'


def definition(model):
    if not model or not model.strip():
        raise ValueError('Set AZURE_AI_MODEL_DEPLOYMENT_NAME to an existing deployment name.')
    return {'kind': 'prompt', 'model': model, 'instructions': INSTRUCTIONS.read_text(), 'tools': []}


def fingerprint(body):
    return hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()


def validate_endpoint(endpoint):
    parsed = urlparse(endpoint or '')
    if (parsed.scheme != 'https' or not parsed.hostname
            or not parsed.hostname.endswith('.services.ai.azure.com')
            or parsed.username or parsed.password or parsed.query or parsed.fragment
            or not parsed.path.startswith('/api/projects/')
            or not parsed.path.removeprefix('/api/projects/').strip('/')
            or parsed.port not in (None, 443)):
        raise ValueError('Use the Azure public-cloud Foundry HTTPS project endpoint, not a model endpoint or API key.')
    return endpoint.rstrip('/')


def same_definition(saved, expected):
    return (all(saved.get(k) == expected[k] for k in ('kind', 'model', 'instructions'))
            and (saved.get('tools') or []) == expected['tools'])


def ensure_agent(project, body, allow_new_version=False):
    from azure.core.exceptions import ResourceNotFoundError
    from azure.ai.projects.models import PromptAgentDefinition

    expected = fingerprint(body)
    try:
        project.agents.get(agent_name=AGENT_NAME)
    except ResourceNotFoundError:
        exists = False
    else:
        exists = True
        # Reuse matching immutable configuration rather than creating duplicates.
        for version in project.agents.list_versions(agent_name=AGENT_NAME):
            if (version.metadata or {}).get('soloai_definition_sha256') == expected:
                if same_definition(version.definition.as_dict(), body):
                    return {'status': 'existing', 'name': version.name, 'version': version.version, 'id': version.id}
        if not allow_new_version:
            raise ValueError('soloai-support already exists with different settings. Review it before using --new-version.')

    agent = project.agents.create_version(
        agent_name=AGENT_NAME,
        definition=PromptAgentDefinition(model=body['model'], instructions=body['instructions'], tools=[]),
        description='SoloAI website replies and review-only email drafts. No tools or external actions.',
        metadata={'soloai_definition_sha256': expected},
    )
    saved = project.agents.get_version(agent_name=AGENT_NAME, agent_version=agent.version)
    saved_body = saved.definition.as_dict()
    if not same_definition(saved_body, body):
        raise RuntimeError('Read-back differs from the requested definition. Inspect the agent before using it.')
    return {'status': 'new-version' if exists else 'created', 'name': saved.name, 'version': saved.version, 'id': saved.id}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--model', default=os.getenv('AZURE_AI_MODEL_DEPLOYMENT_NAME'))
    parser.add_argument('--apply', action='store_true', help='Create the agent in the configured Foundry project.')
    parser.add_argument('--new-version', action='store_true', help='Allow a reviewed configuration update if the named agent exists.')
    args = parser.parse_args()
    body = definition(args.model)
    if not args.apply:
        print(json.dumps({'name': AGENT_NAME, 'definition': body}, indent=2))
        return
    endpoint = validate_endpoint(os.getenv('AZURE_AI_PROJECT_ENDPOINT'))
    from azure.identity import DefaultAzureCredential
    from azure.ai.projects import AIProjectClient
    # No browser login popups or automatic mutation retries.
    with DefaultAzureCredential(exclude_interactive_browser_credential=True) as credential:
        with AIProjectClient(endpoint=endpoint, credential=credential, retry_total=0) as project:
            print(json.dumps(ensure_agent(project, body, args.new_version)))


if __name__ == '__main__':
    try:
        main()
    except (ValueError, RuntimeError) as exc:
        raise SystemExit(str(exc)) from None
