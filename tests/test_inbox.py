import asyncio
import base64
import json
import time
from email import message_from_bytes
import httpx
import pytest
from sqlalchemy import select, update
from fastapi import HTTPException
from tests.test_gmail import configured, mock_google
from tests.test_email_workflows import setup, enqueue
from app import gmail
from app.email_schema import jobs
from app.inbox_schema import tickets, deliveries, grants, settings
from app.inbox import guidance
from app.email_delivery import deliver, message_source


def ready(s, human=True):
    id=enqueue(s,content='What are your opening hours?')
    cipher=gmail.settings()[2];encrypted=gmail.seal(cipher,s.tenants[0],'refresh')
    with s.store.transaction(s.tenants[0]) as c:
        c.execute(gmail.connections.insert().values(tenant=s.tenants[0],email='owner@gmail.com',refresh_token=encrypted,history_id='1',next_sync=0,created=1))
        c.execute(grants.insert().values(tenant=s.tenants[0],token_digest=gmail.digest(encrypted)))
        c.execute(update(jobs).where(jobs.c.execution_id==id).values(draft='We open at 9am.',status='WAITING_FOR_REVIEW',needs_human=human))
        c.execute(update(tickets).where(tickets.c.execution_id==id).values(source=json.dumps(dict(recipient='customer@example.com',mailbox='owner@gmail.com',subject='Opening hours',message_id='<original@example.com>',thread_id='abc123',automated=False))))
    return id


def client_factory(handler):
    return lambda **kw: httpx.AsyncClient(transport=httpx.MockTransport(handler),**kw)


def test_labels_guidance_and_revision_are_tenant_scoped(configured):
    s=configured;id=ready(s)
    assert s.b.get('/api/inbox/emails/'+id).status_code==404
    r=s.a.get('/api/inbox').json();assert r['send_authorized'] and not r['rules']['automatic']
    body=dict(draft='A human-edited reply',labels=['query'],local_guidance='This customer asks about weekend hours.',revision=1)
    assert s.a.put('/api/inbox/emails/'+id,json=body).status_code==200
    assert s.a.put('/api/inbox/emails/'+id,json=body).status_code==409
    assert s.a.post('/api/inbox/instructions',json={'content':'Weekend opening starts at ten.','label_id':'query'}).status_code==200
    with s.engine.connect() as c:
        context=guidance(c,s.tenants[0],id)
        assert 'Weekend opening' in context and 'This customer' in context
        assert guidance(c,s.tenants[1],id)==''
    assert s.a.delete('/api/inbox/labels/query').status_code==200
    assert s.a.get('/api/inbox').json()['instructions'][0]['active'] is False
    assert s.a.get('/api/inbox/emails/'+id).json()['labels']==[]


def test_manual_send_threads_and_blocks_repeated_delivery(configured):
    s=configured;id=ready(s);sent=[]
    def handler(request):
        if request.url.path=='/token':return httpx.Response(200,json={'access_token':'a'})
        sent.append(json.loads(request.content));return httpx.Response(200,json={'id':'sent123'})
    result=asyncio.run(deliver(s.store,s.tenants[0],id,'reviewer',1,client_factory(handler)))
    assert result['sent']
    msg=message_from_bytes(base64.urlsafe_b64decode(sent[0]['raw']))
    assert msg['To']=='customer@example.com' and msg['In-Reply-To']=='<original@example.com>'
    assert sent[0]['threadId']=='abc123'
    with pytest.raises(HTTPException):asyncio.run(deliver(s.store,s.tenants[0],id,'reviewer',1,client_factory(handler)))
    assert len(sent)==1
    assert s.a.post('/api/executions/'+id+'/reject').status_code==409


def test_unknown_send_never_retries(configured):
    s=configured;id=ready(s)
    def handler(request):
        if request.url.path=='/token':return httpx.Response(200,json={'access_token':'a'})
        raise httpx.ReadTimeout('uncertain')
    assert asyncio.run(deliver(s.store,s.tenants[0],id,'reviewer',1,client_factory(handler)))['status']=='UNKNOWN'
    with pytest.raises(HTTPException):asyncio.run(deliver(s.store,s.tenants[0],id,'reviewer',1,client_factory(handler)))
    assert s.a.post('/api/inbox/emails/'+id+'/regenerate',json={'revision':1}).status_code==409


def test_automatic_send_is_opt_in_and_skips_backlog(configured):
    s=configured;id=ready(s,False)
    with pytest.raises(HTTPException):asyncio.run(deliver(s.store,s.tenants[0],id,'agent',1))
    rules=s.a.get('/api/inbox').json()['rules']
    assert s.a.put('/api/inbox/rules',json={k:rules[k] for k in ('automatic','allowed_labels','daily_limit','revision')} | {'automatic':True,'allowed_labels':['query']}).status_code==200
    with pytest.raises(HTTPException):asyncio.run(deliver(s.store,s.tenants[0],id,'agent',1))
    with s.engine.begin() as c:c.execute(update(settings).where(settings.c.tenant==s.tenants[0]).values(enabled_at=int(time.time())-10))
    def handler(request):return httpx.Response(200,json={'access_token':'a'} if request.url.path=='/token' else {'id':'auto123'})
    assert asyncio.run(deliver(s.store,s.tenants[0],id,'agent',1,client_factory(handler)))['sent']


def test_pause_during_refresh_blocks_dispatch(configured):
    s=configured;id=ready(s,False)
    with s.engine.begin() as c:c.execute(update(settings).where(settings.c.tenant==s.tenants[0]).values(automatic=True,allowed_labels='["query"]',enabled_at=1))
    def handler(request):
        assert request.url.path=='/token'
        with s.engine.begin() as c:c.execute(update(settings).where(settings.c.tenant==s.tenants[0]).values(automatic=False))
        return httpx.Response(200,json={'access_token':'a'})
    with pytest.raises(HTTPException):asyncio.run(deliver(s.store,s.tenants[0],id,'agent',1,client_factory(handler)))
    with s.engine.connect() as c:assert not c.execute(select(deliveries)).first()


def test_source_rejects_ambiguous_addresses_and_header_injection():
    msg={'threadId':'abc','payload':{'headers':[{'name':'From','value':'a@example.com, b@example.com'}]}}
    assert message_source(msg,'owner@gmail.com') is None
    msg['payload']['headers']=[{'name':'From','value':'a@example.com'},{'name':'Message-ID','value':'<abc@example.com>'},{'name':'Subject','value':'x\r\nBcc: victim@example.com'}]
    assert message_source(msg,'owner@gmail.com') is None


def test_send_consent_is_explicit_and_revoked_on_disconnect(configured,monkeypatch):
    from urllib.parse import urlparse,parse_qs
    s=configured
    r=s.a.post('/api/integrations/gmail/connect',json={'allow_send':True})
    query=parse_qs(urlparse(r.json()['url']).query)
    assert set(query['scope'][0].split())=={gmail.SCOPE,gmail.SEND_SCOPE}
    def handler(request):
        if request.url.path=='/token':return httpx.Response(200,json={'access_token':'A','refresh_token':'R','scope':gmail.SCOPE+' '+gmail.SEND_SCOPE})
        return httpx.Response(200,json={'emailAddress':'owner@gmail.com','historyId':'1'})
    mock_google(monkeypatch,handler)
    assert s.a.get('/api/integrations/gmail/callback?state='+query['state'][0]+'&code=C',follow_redirects=False).status_code==303
    assert s.a.get('/api/inbox').json()['send_authorized']
    s.a.post('/api/integrations/gmail/disconnect')
    assert not s.a.get('/api/inbox').json()['send_authorized']


@pytest.mark.parametrize('reason',['no-grant','stopped','expired','human','sensitive','daily-limit'])
def test_dispatch_guards(configured,reason):
    s=configured;id=ready(s,False)
    with s.store.transaction(s.tenants[0]) as c:
        c.execute(update(settings).where(settings.c.tenant==s.tenants[0]).values(automatic=True,allowed_labels='["query"]',enabled_at=1))
        if reason=='no-grant':
            from sqlalchemy import delete
            c.execute(delete(grants))
        elif reason=='stopped':
            from sqlalchemy import text
            c.execute(text('UPDATE tenants SET stopped=stopped+1 WHERE id=:t'),{'t':s.tenants[0]})
        elif reason=='expired':c.execute(update(jobs).where(jobs.c.execution_id==id).values(expires_at=1))
        elif reason=='human':c.execute(update(jobs).where(jobs.c.execution_id==id).values(needs_human=True))
        elif reason=='sensitive':c.execute(update(jobs).where(jobs.c.execution_id==id).values(content='What is my refund status?'))
        elif reason=='daily-limit':
            c.execute(update(settings).where(settings.c.tenant==s.tenants[0]).values(daily_limit=1))
            c.execute(deliveries.insert().values(tenant=s.tenants[0],execution_id=id,status='FAILED',actor='reviewer',created=int(time.time()),updated=int(time.time())))
    with pytest.raises(HTTPException):asyncio.run(deliver(s.store,s.tenants[0],id,'agent' if reason in ('human','sensitive') else 'reviewer',1))


def test_retention_clears_address_and_local_guidance(configured):
    s=configured;id=ready(s)
    with s.engine.begin() as c:
        c.execute(update(jobs).where(jobs.c.execution_id==id).values(expires_at=1))
        c.execute(update(tickets).where(tickets.c.execution_id==id).values(local_guidance='private context'))
    s.store.purge()
    with s.engine.connect() as c:
        row=c.execute(select(tickets).where(tickets.c.execution_id==id)).mappings().one()
        assert row['source'] is None and row['local_guidance']==''
    assert s.a.get('/api/inbox/emails/'+id).json()['content'] is None


def test_changed_connection_during_token_refresh_is_blocked(configured):
    s=configured;id=ready(s)
    def handler(request):
        assert request.url.path=='/token'
        s.a.post('/api/integrations/gmail/disconnect')
        return httpx.Response(200,json={'access_token':'a'})
    with pytest.raises(HTTPException):asyncio.run(deliver(s.store,s.tenants[0],id,'reviewer',1,client_factory(handler)))


def test_permission_upgrade_preserves_intake_cursor(configured,monkeypatch):
    from urllib.parse import urlparse,parse_qs
    s=configured;ready(s)
    with s.engine.begin() as c:c.execute(update(gmail.connections).values(history_id='42',page_token='next'))
    response=s.a.post('/api/integrations/gmail/connect',json={'allow_send':True})
    state=parse_qs(urlparse(response.json()['url']).query)['state'][0]
    def handler(request):
        if request.url.path=='/token':return httpx.Response(200,json={'access_token':'A','refresh_token':'R','scope':gmail.SCOPE+' '+gmail.SEND_SCOPE})
        return httpx.Response(200,json={'emailAddress':'owner@gmail.com','historyId':'99'})
    mock_google(monkeypatch,handler)
    assert s.a.get('/api/integrations/gmail/callback?state='+state+'&code=C',follow_redirects=False).status_code==303
    with s.engine.connect() as c:
        row=c.execute(select(gmail.connections)).mappings().one()
        assert row['history_id']=='42' and row['page_token']=='next'


def test_concurrent_send_has_one_dispatch(configured):
    s=configured;id=ready(s);dispatches=[]
    async def handler(request):
        if request.url.path=='/token':
            await asyncio.sleep(0.01)
            return httpx.Response(200,json={'access_token':'a'})
        dispatches.append(1)
        await asyncio.sleep(0.01)
        return httpx.Response(200,json={'id':'sent123'})
    async def both():
        return await asyncio.gather(*(deliver(s.store,s.tenants[0],id,'reviewer',1,client_factory(handler)) for _ in range(2)),return_exceptions=True)
    results=asyncio.run(both())
    assert len(dispatches)==1
    assert sum(isinstance(x,HTTPException) for x in results)==1


def test_regeneration_carries_guidance_without_reusing_delivery(configured):
    s=configured;id=ready(s)
    body={'draft':'Existing draft','labels':['query'],'local_guidance':'Reception is closed this Sunday.','revision':1}
    assert s.a.put('/api/inbox/emails/'+id,json=body).status_code==200
    assert s.a.post('/api/inbox/emails/'+id+'/regenerate',json={'revision':2}).status_code==200
    context=s.store.claim(90)
    assert 'Reception is closed this Sunday.' in context['guidance']
    assert context['draft'] is None
