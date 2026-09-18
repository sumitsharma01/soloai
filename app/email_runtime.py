"""Bounded, stateless Foundry email loop. All tools execute in SoloAI."""
import asyncio
import json
import os
import time
from pathlib import Path
from pydantic import ValidationError
from app.foundry import SupportReply
from app.email_tools import TOOLS, ToolGateway, EmailFailure

INSTRUCTIONS = (Path(__file__).resolve().parents[1] / 'agents/soloai-email/instructions.md').read_text()
MAX_OUTPUT = 1024
MAX_SECONDS = 90


def configuration():
    result = {'agent_name': os.getenv('AZURE_FOUNDRY_EMAIL_AGENT_NAME', 'soloai-email'),
              'agent_version': os.getenv('AZURE_FOUNDRY_EMAIL_AGENT_VERSION', ''),
              'model': os.getenv('AZURE_FOUNDRY_MODEL', '')}
    if not os.getenv('AZURE_FOUNDRY_PROJECT_ENDPOINT') or not all(result.values()):
        raise EmailFailure('email_agent_not_configured')
    return result


def definition(model):
    return {'kind':'prompt', 'model':model, 'instructions':INSTRUCTIONS,
            'tools':[tool.definition() for tool in TOOLS.values()]}


def verify_definition(saved, model):
    expected = definition(model)
    if any(saved.get(key) != expected[key] for key in ('kind','model','instructions')):
        raise EmailFailure('agent_definition_mismatch')
    actual = saved.get('tools') or []
    if len(actual) != len(expected['tools']): raise EmailFailure('agent_definition_mismatch')
    # The SDK can add null optional properties. Every effective tool property must match.
    for tool in expected['tools']:
        candidates = [t for t in actual if t.get('name') == tool['name']]
        if len(candidates) != 1 or any(candidates[0].get(k) != v for k,v in tool.items()):
            raise EmailFailure('agent_definition_mismatch')
        if any(v is not None for k,v in candidates[0].items() if k not in tool):
            raise EmailFailure('agent_definition_mismatch')


class FoundryProvider:
    async def __aenter__(self):
        from azure.identity.aio import DefaultAzureCredential
        from azure.ai.projects.aio import AIProjectClient
        from contextlib import AsyncExitStack
        self.stack = AsyncExitStack()
        await self.stack.__aenter__()
        try:
            credential = await self.stack.enter_async_context(DefaultAzureCredential(exclude_interactive_browser_credential=True))
            self.project = await self.stack.enter_async_context(AIProjectClient(
                endpoint=os.environ['AZURE_FOUNDRY_PROJECT_ENDPOINT'], credential=credential, retry_total=0))
            self.client = await self.stack.enter_async_context(self.project.get_openai_client(max_retries=0, timeout=30))
            return self
        except BaseException:
            await self.stack.aclose()
            raise

    async def __aexit__(self, *args): return await self.stack.__aexit__(*args)

    async def verify(self, context):
        agent = await self.project.agents.get_version(context['agent_name'], context['agent_version'])
        verify_definition(agent.definition.as_dict(), context['model'])

    async def respond(self, context, history):
        return await self.client.responses.create(input=history, store=False,
            max_output_tokens=MAX_OUTPUT, parallel_tool_calls=False,
            include=['reasoning.encrypted_content'],
            extra_body={'agent_reference': {'type':'agent_reference',
                'name':context['agent_name'],'version':context['agent_version']}})


def provider_failure(exc):
    """Only bounded stable codes leave the runtime; no raw Azure response text."""
    from openai import APITimeoutError, APIConnectionError, APIStatusError
    from azure.core.exceptions import HttpResponseError, ServiceRequestError
    from sqlalchemy.exc import SQLAlchemyError
    if isinstance(exc, SQLAlchemyError): return EmailFailure('database_unavailable')
    if isinstance(exc, (TimeoutError, APITimeoutError)): return EmailFailure('foundry_timeout')
    if isinstance(exc, (APIConnectionError, ServiceRequestError)):
        return EmailFailure('foundry_unavailable')  # Outcome may be unknown; do not replay.
    if isinstance(exc, (APIStatusError, HttpResponseError)):
        status = getattr(exc, 'status_code', None)
        return EmailFailure('foundry_unavailable' if status in (429, 502, 503, 504) else 'foundry_rejected',
                            transient=status in (429, 503))
    return EmailFailure('invalid_foundry_response')


async def run(store, context, provider, gateway=None):
    gateway = gateway or ToolGateway(store, context)
    history = [{'role':'user', 'content':json.dumps({'channel':'email_draft',
        'business_guidance':context['guidance'], 'customer_message':context['content']})}]
    store.check_active(context)
    await provider.verify(context)
    for _ in range(4):  # At most three tool calls and one final model turn.
        store.check_active(context)
        # UTF-8 byte bound includes serialized history, tool definitions, instructions,
        # output and protocol overhead. Every model turn reserves independently.
        bound = len(json.dumps(history, ensure_ascii=False).encode()) + len(
            json.dumps(definition(context['model']), ensure_ascii=False).encode()) + MAX_OUTPUT + 512
        store.reserve(context, bound)
        start = time.monotonic()
        try:
            response = await provider.respond(context, history)
        except BaseException:
            store.provider_failed(context, round((time.monotonic()-start)*1000))
            raise
        store.settle(context, response.usage.total_tokens, round((time.monotonic()-start)*1000))
        store.check_active(context)
        if response.status != 'completed': raise EmailFailure('invalid_foundry_response')
        if any(item.type not in ('message','reasoning','function_call') for item in response.output):
            raise EmailFailure('invalid_foundry_response')
        calls = [item for item in response.output if item.type == 'function_call']
        if not calls:
            try: answer = SupportReply.model_validate_json(response.output_text)
            except (ValidationError, ValueError): raise EmailFailure('invalid_foundry_response') from None
            if answer.channel != 'email_draft': raise EmailFailure('invalid_foundry_response')
            if gateway.missing_information: answer.needs_human = True
            return answer
        if len(calls) + gateway.count > 3: raise EmailFailure('tool_limit')
        ids = [call.call_id for call in calls]
        if len(set(ids)) != len(ids): raise EmailFailure('invalid_foundry_response')
        # Responses history stays in this execution's memory. No server-side conversation
        # or previous_response_id is shared across jobs, tenants, or retry attempts.
        history.extend(item.model_dump(mode='json', exclude_none=True) for item in response.output)
        for call in calls:
            result = await gateway.call(call.name, call.arguments)
            history.append({'type':'function_call_output','call_id':call.call_id,'output':result})
    raise EmailFailure('tool_limit')


async def process_one(store, provider_factory=FoundryProvider):
    context = store.claim(MAX_SECONDS)
    if context is None: return False
    answer = failure = None
    try:
        if context['attempts'] > 1: store.admit_retry(context)
        async with asyncio.timeout(MAX_SECONDS):
            async with provider_factory() as provider:
                answer = await run(store, context, provider)
    except asyncio.CancelledError:
        store.finish(context, failure=EmailFailure('worker_interrupted'))
        raise
    except TimeoutError: failure = EmailFailure('execution_timeout')
    except EmailFailure as exc: failure = exc
    except Exception as exc: failure = provider_failure(exc)
    store.finish(context, answer=answer, failure=failure)
    return True
