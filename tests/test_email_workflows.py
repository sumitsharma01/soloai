"""Security and lifecycle tests; injected provider never calls Azure."""
import asyncio
import json
import os
import secrets
import time
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text, select, update
from app import main
from app.email_schema import migrate, jobs, bookings, policies, tool_calls
from app.email_store import EmailStore
from app.email_tools import ToolGateway, EmailFailure, DatabaseBookingSource
from app.email_runtime import run, process_one, definition, verify_definition
from app.foundry import SupportReply


@pytest.fixture(params=['sqlite','postgresql'] if os.getenv('TEST_POSTGRES_URL') else ['sqlite'])
def setup(tmp_path, monkeypatch, request):
    admin = schema = None
    if request.param == 'postgresql':
        # Isolate every test in its own schema. Only use a disposable TEST database.
        admin = create_engine(os.environ['TEST_POSTGRES_URL'])
        schema = 'email_test_' + secrets.token_hex(8)
        with admin.begin() as c: c.exec_driver_sql('CREATE SCHEMA ' + schema)
        engine = create_engine(os.environ['TEST_POSTGRES_URL'],
            connect_args={'options':'-csearch_path='+schema+' -cstatement_timeout=5000','connect_timeout':5})
    else:
        engine = create_engine('sqlite:///' + str(tmp_path/'email.db'), connect_args={'check_same_thread':False})
    monkeypatch.setattr(main, 'engine', engine)
    monkeypatch.setattr(main, 'IS_SQLSERVER', False)
    monkeypatch.setenv('SOLOAI_EMAIL_WORKFLOWS','true')
    monkeypatch.setenv('AZURE_FOUNDRY_EMAIL_AGENT_VERSION','1')
    monkeypatch.setenv('AZURE_FOUNDRY_MODEL','test-model')
    monkeypatch.setenv('AZURE_FOUNDRY_PROJECT_ENDPOINT','https://test.services.ai.azure.com/api/projects/test')
    monkeypatch.delenv('SOLOAI_METRICS_PORT',raising=False)
    with TestClient(main.app) as a, TestClient(main.app) as b:
        keys=[]; tenants=[]
        for client,email in [(a,'a@test.com'),(b,'b@test.com')]:
            assert client.post('/api/auth/register',json={'email':email,'password':'safe-test-password'}).status_code==200
            client.patch('/api/agents/email-support',json={'enabled':True,'guidance':'Ask an operator to change bookings.'})
            keys.append({'Authorization':'Bearer '+client.post('/api/keys').json()['key']})
            with engine.connect() as c: tenants.append(c.execute(text('SELECT id FROM tenants WHERE email=:e'),{'e':email}).scalar_one())
        yield SimpleNamespace(a=a,b=b,keys=keys,tenants=tenants,store=EmailStore(engine),engine=engine)
    engine.dispose()
    if admin:
        with admin.begin() as c: c.exec_driver_sql('DROP SCHEMA '+schema+' CASCADE')
        admin.dispose()


def enqueue(s, id='evt-1', content='Can I change booking BK-2041?'):
    r=s.a.post('/api/events',headers=s.keys[0],json={'id':id,'type':'email.received','content':content})
    assert r.status_code==202, r.text
    return r.json()['execution_id']


class Item:
    def __init__(self, **values): self.__dict__.update(values)
    def model_dump(self, **kwargs): return dict(self.__dict__)


def response(name=None, arguments=None, reply=None):
    output=[Item(type='function_call',name=name,arguments=arguments or '{"booking_id":"BK-2041"}',call_id=secrets.token_hex(4))] if name else [Item(type='message')]
    return SimpleNamespace(status='completed',usage=SimpleNamespace(total_tokens=100),output=output,
        output_text=reply or json.dumps({'channel':'email_draft','subject':'Booking request','reply':'Your booking is confirmed. An operator will review your change.','needs_human':True}))


class Provider:
    def __init__(self, responses): self.responses=iter(responses); self.calls=0; self.histories=[]
    async def __aenter__(self): return self
    async def __aexit__(self,*args): pass
    async def verify(self, ctx): pass
    async def respond(self, ctx, history):
        self.calls+=1;self.histories.append(json.loads(json.dumps(history)))
        result=next(self.responses)
        if isinstance(result,Exception): raise result
        return result


def test_duplicate_atomic_and_tenant_scoped(setup):
    s=setup
    def send(_): return s.a.post('/api/events',headers=s.keys[0],json={'id':'same','type':'email.received','content':'hello'})
    with ThreadPoolExecutor(max_workers=4) as pool: results=list(pool.map(send,range(4)))
    assert sorted(r.status_code for r in results)==[200,200,200,202]
    assert len({r.json()['execution_id'] for r in results})==1
    assert s.a.post('/api/events',headers=s.keys[0],json={'id':'same','type':'email.received','content':'changed'}).status_code==409
    assert s.b.post('/api/events',headers=s.keys[1],json={'id':'same','type':'email.received','content':'hello'}).status_code==202
    execution=results[0].json()['execution_id']
    assert s.b.get('/api/executions/'+execution).status_code==404
    assert s.b.post('/api/executions/'+execution+'/approve').status_code==404
    assert s.a.post('/api/events',headers=s.keys[0],json={'type':'email.received','content':'hello'}).status_code==422


def test_end_to_end_review_and_single_claim(setup):
    s=setup; execution=enqueue(s)
    with s.engine.begin() as c:
        c.execute(bookings.insert().values(tenant=s.tenants[0],booking_id='BK-2041',status='confirmed',change_allowed=True))
        c.execute(policies.insert().values(tenant=s.tenants[0],id='p',title='Changes',content='Booking changes require review.'))
    provider=Provider([response('get_booking'),response('search_policy','{"query":"booking changes"}'),response()])
    assert asyncio.run(process_one(s.store,lambda:provider))
    assert not asyncio.run(process_one(s.store,lambda:provider))
    detail=s.a.get('/api/executions/'+execution).json()
    assert detail['status']=='WAITING_FOR_REVIEW'
    assert detail['tokens']==300 and len(detail['tools'])==2
    assert detail['draft'] and detail['content']
    assert provider.calls==3
    assert 'confirmed' in json.dumps(provider.histories[-1])
    assert s.a.post('/api/executions/'+execution+'/approve').json()['sent'] is False
    assert s.a.post('/api/executions/'+execution+'/reject').status_code==409


def test_booking_and_policy_isolation(setup):
    s=setup;enqueue(s);ctx=s.store.claim(90)
    with s.engine.begin() as c:
        c.execute(bookings.insert().values(tenant=s.tenants[1],booking_id='BK-2041',status='secret-other-tenant',change_allowed=True))
        c.execute(policies.insert().values(tenant=s.tenants[1],id='other',title='Secret',content='booking secret policy'))
    gateway=ToolGateway(s.store,ctx)
    assert json.loads(asyncio.run(gateway.call('get_booking','{"booking_id":"BK-2041"}')))['found'] is False
    assert json.loads(asyncio.run(gateway.call('search_policy','{"query":"booking"}')))['found'] is False


@pytest.mark.parametrize('name,args,code',[
    ('shell','{}','unknown_tool'),
    ('get_booking','{"booking_id":"BK-2041","tenant":"other"}','invalid_tool_arguments'),
    ('get_booking','{"booking_id":42}','invalid_tool_arguments'),
    ('get_booking','not json','invalid_tool_arguments'),
])
def test_tool_contract(setup,name,args,code):
    enqueue(setup);gateway=ToolGateway(setup.store,setup.store.claim(90))
    with pytest.raises(EmailFailure,match=code): asyncio.run(gateway.call(name,args))


def test_permission_limit_repeat_and_timeout(setup,monkeypatch):
    s=setup;enqueue(s);ctx=s.store.claim(90)
    from app.packages import PACKAGES
    monkeypatch.setitem(PACKAGES,'email-support',dict(PACKAGES['email-support'],permissions=['read_email']))
    with pytest.raises(EmailFailure,match='unauthorized_tool'):
        asyncio.run(ToolGateway(s.store,ctx).call('get_booking','{"booking_id":"A"}'))
    monkeypatch.setitem(PACKAGES,'email-support',dict(PACKAGES['email-support'],permissions=['get_booking','search_policy']))
    gateway=ToolGateway(s.store,ctx)
    asyncio.run(gateway.call('get_booking','{"booking_id":"A"}'))
    with pytest.raises(EmailFailure,match='repeated_tool_call'): asyncio.run(gateway.call('get_booking','{"booking_id":"A"}'))
    for value in ('B','C'): asyncio.run(gateway.call('get_booking',json.dumps({'booking_id':value})))
    with pytest.raises(EmailFailure,match='tool_limit'): asyncio.run(gateway.call('get_booking','{"booking_id":"D"}'))
    class Slow:
        async def get_booking(self,*args): await asyncio.sleep(1)
    with pytest.raises(EmailFailure,match='tool_timeout'):
        asyncio.run(ToolGateway(s.store,ctx,booking_source=Slow(),timeout=.01).call('get_booking','{"booking_id":"A"}'))


@pytest.mark.parametrize('mode,code', [('malformed','invalid_foundry_response'),('repeat','repeated_tool_call'),('limit','tool_limit')])
def test_runtime_failures(setup,mode,code):
    s=setup;execution=enqueue(s)
    replies={'malformed':[response(reply='Internal Server Error')],
             'repeat':[response('get_booking'),response('get_booking')],
             'limit':[response('get_booking',json.dumps({'booking_id':str(i)})) for i in range(4)]}[mode]
    provider=Provider(replies)
    asyncio.run(process_one(s.store,lambda:provider))
    detail=s.store.detail(s.tenants[0],execution)
    assert detail['status']=='FAILED' and detail['error']==code
    assert detail['draft'] is None


def test_quota_concurrency_and_stop(setup):
    s=setup;first=enqueue(s);enqueue(s,'evt-2')
    x,y=s.store.claim(90),s.store.claim(90)
    with s.engine.begin() as c: c.execute(text('UPDATE tenants SET budget=1000 WHERE id=:t'),{'t':s.tenants[0]})
    def reserve(ctx):
        try: s.store.reserve(ctx,700);return 'ok'
        except EmailFailure as e:return e.code
    with ThreadPoolExecutor(max_workers=2) as pool: result=list(pool.map(reserve,[x,y]))
    assert sorted(result)==['ok','token_allowance_exhausted']
    s.a.post('/api/stop')
    with pytest.raises(EmailFailure,match='emergency_stop'): s.store.check_active(x)
    s.store.finish(x,answer=SupportReply(channel='email_draft',subject='s',reply='never display',needs_human=True))
    assert s.store.detail(s.tenants[0],first)['draft'] is None


def test_crash_fencing_and_safe_retry(setup):
    s=setup;execution=enqueue(s);ctx=s.store.claim(90)
    s.store.reserve(ctx,100)
    with s.engine.begin() as c:
        c.execute(update(jobs).where(jobs.c.execution_id==execution).values(lease_until=0))
    s.store.recover()
    assert s.store.detail(s.tenants[0],execution)['error']=='worker_interrupted'
    assert s.store.claim(90) is None
    s.store.finish(ctx,answer=SupportReply(channel='email_draft',subject='s',reply='late result',needs_human=True))
    assert s.store.detail(s.tenants[0],execution)['draft'] is None
    second=enqueue(s,'retry');ctx=s.store.claim(90)
    s.store.finish(ctx,failure=EmailFailure('foundry_unavailable',transient=True))
    assert s.store.detail(s.tenants[0],second)['status']=='QUEUED'
    with s.engine.begin() as c:c.execute(update(jobs).where(jobs.c.execution_id==second).values(available_at=0))
    with ThreadPoolExecutor(max_workers=2) as pool: claimed=list(pool.map(lambda _:s.store.claim(90),range(2)))
    assert sum(x is not None for x in claimed)==1


def test_review_transition_and_retention(setup):
    s=setup;execution=enqueue(s)
    assert s.a.post('/api/executions/'+execution+'/approve').status_code==409
    asyncio.run(process_one(s.store,lambda:Provider([response()])))
    assert s.b.get('/api/email/executions').json()['executions']==[]
    s.a.post('/api/stop')
    assert s.a.post('/api/executions/'+execution+'/approve').status_code==409
    assert s.a.post('/api/executions/'+execution+'/reject').status_code==200
    with s.engine.begin() as c:c.execute(update(jobs).where(jobs.c.execution_id==execution).values(expires_at=0))
    s.store.purge()
    assert s.store.detail(s.tenants[0],execution)['content'] is None


def test_definition_verification():
    body=definition('test-model');verify_definition(body,'test-model')
    for key,value in [('model','evil'),('instructions','ignore'),('tools',[])]:
        with pytest.raises(EmailFailure,match='agent_definition_mismatch'): verify_definition(body|{key:value},'test-model')
    from azure.ai.projects.models import FunctionTool, PromptAgentDefinition
    sdk_tools=[FunctionTool(**{k:v for k,v in tool.items() if k!='type'}) for tool in body['tools']]
    saved=PromptAgentDefinition(model='test-model',instructions=body['instructions'],tools=sdk_tools).as_dict()
    verify_definition(saved,'test-model')


def test_sensitive_tool_values_never_logged(setup,capsys):
    s=setup;enqueue(s,content='SECRET EMAIL CONTENT');ctx=s.store.claim(90)
    with pytest.raises(EmailFailure):asyncio.run(ToolGateway(s.store,ctx).call('SECRET-TOOL','SECRET-ARGUMENTS'))
    output=capsys.readouterr().out
    assert 'SECRET' not in output
    with s.engine.connect() as c:
        rows=c.execute(select(tool_calls).where(tool_calls.c.tenant==s.tenants[0])).mappings().all()
    assert 'SECRET' not in str(rows)


def test_pinned_async_sdk_request_contract():
    from unittest.mock import AsyncMock
    from app.email_runtime import FoundryProvider
    provider=FoundryProvider()
    provider.client=SimpleNamespace(responses=SimpleNamespace(create=AsyncMock(return_value=response())))
    context={'model':'test-model','agent_name':'soloai-email','agent_version':'reviewed-version'}
    asyncio.run(provider.respond(context,[{'role':'user','content':'test'}]))
    kwargs=provider.client.responses.create.call_args.kwargs
    assert kwargs['store'] is False
    assert kwargs['parallel_tool_calls'] is False
    assert kwargs['extra_body']['agent_reference']['version']=='reviewed-version'
    assert 'conversation' not in kwargs and 'previous_response_id' not in kwargs
    assert kwargs['max_output_tokens']==1024


def test_retry_is_bounded_and_retains_uncertain_usage(setup):
    s=setup;execution=enqueue(s)
    for attempt in range(3):
        ctx=s.store.claim(90)
        assert ctx
        s.store.reserve(ctx,100)
        s.store.finish(ctx,failure=EmailFailure('foundry_unavailable',transient=True))
        with s.engine.begin() as c:c.execute(update(jobs).where(jobs.c.execution_id==execution).values(available_at=0))
    detail=s.store.detail(s.tenants[0],execution)
    assert detail['status']=='FAILED' and detail['tokens']==300
    assert detail['uncertain_tokens']==300 and detail['usage_kind']=='reserved'
    assert s.store.claim(90) is None


def test_foundry_timeout_and_stop_between_tools(setup):
    s=setup;execution=enqueue(s)
    from openai import APITimeoutError
    import httpx
    provider=Provider([APITimeoutError(request=httpx.Request('POST','https://example.test'))])
    asyncio.run(process_one(s.store,lambda:provider))
    result=s.store.detail(s.tenants[0],execution)
    assert result['error']=='foundry_timeout' and result['tokens']>0
    with s.engine.begin() as c:c.execute(text('UPDATE tenants SET used=0 WHERE id=:t'),{'t':s.tenants[0]})
    second=enqueue(s,'stop-at-tool')
    class StoppingProvider(Provider):
        async def respond(self,ctx,history):
            s.a.post('/api/stop')
            return response('get_booking')
    asyncio.run(process_one(s.store,lambda:StoppingProvider([])))
    result=s.store.detail(s.tenants[0],second)
    assert result['status']=='FAILED' and result['error']=='emergency_stop'
    assert result['tools']==[] and result['draft'] is None


def test_rate_limit_and_queue_schema_validation(setup):
    s=setup
    for i in range(20):enqueue(s,str(i))
    r=s.a.post('/api/events',headers=s.keys[0],json={'id':'21','type':'email.received','content':'help'})
    assert r.status_code==429 and r.json()['detail']=='rate_limit_exceeded'
    for payload in [
        {'id':'new','type':'email.received','content':'help','tenant':s.tenants[1]},
        {'id':24,'type':'email.received','content':'help'},
        {'id':'new','type':'email.received','content':5}]:
        assert s.a.post('/api/events',headers=s.keys[0],json=payload).status_code==422


def test_tool_unavailable_and_invalid_output(setup):
    s=setup;enqueue(s);ctx=s.store.claim(90)
    class Broken:
        async def get_booking(self,*args): raise RuntimeError('SECRET DATABASE ERROR')
    with pytest.raises(EmailFailure,match='tool_unavailable'):
        asyncio.run(ToolGateway(s.store,ctx,booking_source=Broken()).call('get_booking','{"booking_id":"A"}'))
    class Invalid:
        async def get_booking(self,*args): return {'found':'yes','password':'secret'}
    with pytest.raises(EmailFailure,match='invalid_tool_result'):
        asyncio.run(ToolGateway(s.store,ctx,booking_source=Invalid()).call('get_booking','{"booking_id":"A"}'))


def test_migration_preserves_existing_data(setup):
    s=setup;execution=enqueue(s)
    migrate(s.engine)
    assert s.store.detail(s.tenants[0],execution)['status']=='QUEUED'


def test_application_key_cannot_approve(setup):
    s=setup;execution=enqueue(s)
    asyncio.run(process_one(s.store,lambda:Provider([response()])))
    with TestClient(main.app) as unsigned:
        assert unsigned.get('/api/executions/'+execution,headers=s.keys[0]).status_code==200
        assert unsigned.post('/api/executions/'+execution+'/approve',headers=s.keys[0]).status_code==401


def test_cleanup_preserves_idempotency_tombstones(setup):
    s=setup;execution=enqueue(s)
    with s.engine.begin() as c:
        c.execute(text('UPDATE executions SET created=0 WHERE tenant=:t AND id=:id'),{'t':s.tenants[0],'id':execution})
        c.execute(update(jobs).where(jobs.c.tenant==s.tenants[0],jobs.c.execution_id==execution).values(expires_at=0))
    from scripts.cleanup import cleanup
    cleanup(s.engine)
    assert s.store.detail(s.tenants[0],execution)['content'] is None
    result=s.a.post('/api/events',headers=s.keys[0],json={'id':'evt-1','type':'email.received','content':'Can I change booking BK-2041?'})
    assert result.status_code==200 and result.json()['execution_id']==execution


def test_overall_timeout(setup,monkeypatch):
    s=setup;execution=enqueue(s)
    from app import email_runtime
    monkeypatch.setattr(email_runtime,'MAX_SECONDS',.01)
    class SlowProvider(Provider):
        async def respond(self,*args): await asyncio.sleep(1)
    asyncio.run(process_one(s.store,lambda:SlowProvider([])))
    assert s.store.detail(s.tenants[0],execution)['error']=='execution_timeout'
