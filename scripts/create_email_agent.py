"""Preview a separate pinned email agent. --apply explicitly creates/reuses a version."""
import argparse
import json
import os
from app.email_runtime import definition, verify_definition
from scripts.create_foundry_agent import validate_endpoint


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--model',default=os.getenv('AZURE_FOUNDRY_MODEL'))
    p.add_argument('--name',default='soloai-email')
    p.add_argument('--apply',action='store_true')
    args = p.parse_args()
    if not args.model: raise SystemExit('--model is required')
    body = definition(args.model)
    if not args.apply:
        print(json.dumps({'name':args.name,'definition':body},indent=2)); return
    from azure.ai.projects import AIProjectClient
    from azure.ai.projects.models import PromptAgentDefinition, FunctionTool
    from azure.identity import DefaultAzureCredential
    from azure.core.exceptions import ResourceNotFoundError
    from app.email_tools import EmailFailure
    with DefaultAzureCredential(exclude_interactive_browser_credential=True) as cred:
        with AIProjectClient(endpoint=validate_endpoint(os.getenv('AZURE_FOUNDRY_PROJECT_ENDPOINT')),
                             credential=cred,retry_total=0) as project:
            try:
                for saved in project.agents.list_versions(agent_name=args.name):
                    try: verify_definition(saved.definition.as_dict(),args.model)
                    except EmailFailure: continue
                    print(json.dumps({'name':args.name,'version':saved.version,'status':'existing'})); return
            except ResourceNotFoundError: pass
            tools = [FunctionTool(**{k:v for k,v in tool.items() if k!='type'}) for tool in body['tools']]
            result = project.agents.create_version(agent_name=args.name,
                definition=PromptAgentDefinition(model=args.model,instructions=body['instructions'],tools=tools))
            saved = project.agents.get_version(args.name,result.version)
            verify_definition(saved.definition.as_dict(),args.model)
            print(json.dumps({'name':args.name,'version':saved.version,'status':'created'}))


if __name__ == '__main__': main()
