"""Direct Azure model access. Credentials remain on the server."""
import os
from types import SimpleNamespace
from openai import AsyncAzureOpenAI


def client():
    return AsyncAzureOpenAI(azure_endpoint=os.environ['AZURE_OPENAI_ENDPOINT'],
        api_key=os.environ['AZURE_OPENAI_API_KEY'],
        api_version=os.getenv('AZURE_OPENAI_API_VERSION','2025-01-01-preview'),
        max_retries=0, timeout=30)


class ToolCall:
    type = 'function_call'

    def __init__(self, call):
        self.call_id, self.name, self.arguments = call.id, call.function.name, call.function.arguments

    def model_dump(self, **kwargs):
        return dict(type=self.type, call_id=self.call_id, name=self.name, arguments=self.arguments)


def messages(history, instructions):
    result=[{'role':'system','content':instructions}]
    for item in history:
        if item.get('type')=='function_call':
            call={'id':item['call_id'],'type':'function','function':{'name':item['name'],'arguments':item['arguments']}}
            if result[-1].get('role')=='assistant' and 'tool_calls' in result[-1]:
                result[-1]['tool_calls'].append(call)
            else: result.append({'role':'assistant','content':None,'tool_calls':[call]})
        elif item.get('type')=='function_call_output':
            result.append({'role':'tool','tool_call_id':item['call_id'],'content':item['output']})
        else: result.append(item)
    return result


class DirectEmailProvider:
    async def __aenter__(self):
        self.client=client()
        await self.client.__aenter__()
        return self

    async def __aexit__(self,*args):
        return await self.client.__aexit__(*args)

    async def verify(self,context):
        from app.email_runtime import INSTRUCTIONS
        import hashlib
        from app.email_tools import EmailFailure
        if context['model']!=os.environ['AZURE_OPENAI_DEPLOYMENT'] or context['agent_version']!=hashlib.sha256(INSTRUCTIONS.encode()).hexdigest():
            raise EmailFailure('agent_definition_mismatch')

    async def respond(self,context,history):
        from app.email_runtime import INSTRUCTIONS, MAX_OUTPUT
        from app.email_tools import TOOLS
        tools=[]
        for tool in TOOLS.values():
            definition=tool.definition().copy()
            definition.pop('type',None)
            tools.append({'type':'function','function':definition})
        reply=await self.client.chat.completions.create(model=context['model'],
            messages=messages(history,INSTRUCTIONS),tools=tools,parallel_tool_calls=False,
            response_format={'type':'json_object'},max_tokens=MAX_OUTPUT,temperature=0)
        choice=reply.choices[0]
        return SimpleNamespace(status='completed' if choice.finish_reason in ('stop','tool_calls') else 'incomplete',
            usage=reply.usage,output=[ToolCall(call) for call in choice.message.tool_calls or []],
            output_text=choice.message.content or '')
