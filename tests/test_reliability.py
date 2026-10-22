"""Failure contracts, isolation and recovery. No real mail or external data is used."""
import asyncio,json,time
from types import SimpleNamespace
import httpx
import pytest
from sqlalchemy import select,update,text
from tests.test_gmail import configured,mock_google
from tests.test_email_workflows import setup,enqueue
from tests.test_inbox import ready
from app import gmail,outlook,booking_connector,operations
from app.email_tools import EmailFailure,ToolGateway
from app.email_schema import jobs
from app.reliability_schema import alerts,connectors,identities
from app.inbox_schema import deliveries


def test_policies_are_bounded_approved_and_tenant_scoped(setup):
    s=setup
    assert s.a.post('/api/support/policies',json={'title':'Returns','content':'Returns require review within 30 days.'}).status_code==200
    data=s.a.get('/api/support/policies').json()['policies'];assert len(data)==1
    assert not s.b.get('/api/support/policies').json()['policies']
    s.b.delete('/api/support/policies/'+data[0]['id'])
    assert s.a.get('/api/support/policies').json()['policies']==data
    assert s.a.post('/api/support/policies',json={'title':'Too much','content':'x'*601}).status_code==422
    s.a.delete('/api/support/policies/'+data[0]['id']);assert not s.a.get('/api/support/policies').json()['policies']


def connection(s):
    assert s.a.post('/api/support/booking',json={'url':'https://abcdefghijklmnopqrst.supabase.co/functions/v1/soloai-booking','token':'secret_'+'a'*40}).status_code==200


def verify(s,id):
    assert s.a.post('/api/support/emails/'+id+'/verify-customer',json={'customer_id':'customer-alex','verified':True}).status_code==200


def test_booking_verification_and_cross_customer_rejection(configured,monkeypatch):
    s=configured;id=enqueue(s);connection(s)
    ctx={'tenant':s.tenants[0],'execution_id':id}
    assert asyncio.run(booking_connector.lookup(s.store,ctx,'BK-1001'))['found'] is False
    assert s.b.post('/api/support/emails/'+id+'/verify-customer',json={'customer_id':'customer-alex','verified':True}).status_code==404
    verify(s,id)
    original=httpx.AsyncClient
    def handler(request):
        assert json.loads(request.content)=={'booking_id':'BK-1001','customer_id':'customer-alex'}
        return httpx.Response(200,json={'customer_id':'customer-alex','booking_id':'BK-1001','found':True,'status':'confirmed','change_allowed':True})
    monkeypatch.setattr(booking_connector.httpx,'AsyncClient',lambda **kw:original(transport=httpx.MockTransport(handler),**kw))
    assert asyncio.run(booking_connector.lookup(s.store,ctx,'BK-1001'))['status']=='confirmed'
    def wrong(request):return httpx.Response(200,json={'customer_id':'customer-sam','booking_id':'BK-1001','found':True,'status':'private','change_allowed':True})
    monkeypatch.setattr(booking_connector.httpx,'AsyncClient',lambda **kw:original(transport=httpx.MockTransport(wrong),**kw))
    with pytest.raises(EmailFailure):asyncio.run(booking_connector.lookup(s.store,ctx,'BK-1001'))
    assert 'secret_' not in s.a.get('/api/support/booking').text
    assert not s.b.get('/api/support/booking').json()['configured']
    s.a.delete('/api/support/booking')
    with s.engine.connect() as c:assert not c.execute(select(identities)).first()


@pytest.mark.parametrize('url',['http://127.0.0.1/functions/v1/soloai-booking','https://evil.test/x','https://abcdefghijklmnopqrst.supabase.co@evil.test/functions/v1/soloai-booking'])
def test_booking_ssrf_urls_rejected(configured,url):
    assert configured.a.post('/api/support/booking',json={'url':url,'token':'a'*40}).status_code==422


def test_booking_disconnect_fences_inflight_result(configured,monkeypatch):
    s=configured;id=enqueue(s);connection(s);verify(s,id)
    original=httpx.AsyncClient
    def handler(request):
        s.a.delete('/api/support/booking')
        return httpx.Response(200,json={'customer_id':'customer-alex','booking_id':'BK-1001','found':True,'status':'confirmed','change_allowed':True})
    monkeypatch.setattr(booking_connector.httpx,'AsyncClient',lambda **kw:original(transport=httpx.MockTransport(handler),**kw))
    with pytest.raises(EmailFailure):asyncio.run(booking_connector.lookup(s.store,{'tenant':s.tenants[0],'execution_id':id},'BK-1001'))


def test_gmail_history_reset_explicit_and_pauses_sending(configured,monkeypatch):
    s=configured;ready(s)
    with s.engine.begin() as c:c.execute(update(gmail.connections).values(error='gmail_history_expired',history_id='old'))
    def handle(request):
        return httpx.Response(200,json={'access_token':'token'}) if request.url.path=='/token' else httpx.Response(200,json={'emailAddress':'owner@gmail.com','historyId':'new'})
    mock_google(monkeypatch,handle)
    assert s.b.post('/api/integrations/gmail/reset-sync').status_code==409
    assert s.a.post('/api/integrations/gmail/reset-sync').status_code==200
    assert s.a.post('/api/integrations/gmail/reset-sync').status_code==409
    with s.engine.connect() as c:assert c.execute(select(gmail.connections.c.history_id)).scalar_one()=='new'


def test_alerts_are_metadata_only_deduplicated_and_resolved(configured,monkeypatch):
    s=configured;id=ready(s)
    operations.collect(s.store);operations.collect(s.store)
    with s.engine.connect() as c:
        assert len(c.execute(select(alerts).where(alerts.c.kind=='review_needed')).all())==1
    assert not s.b.get('/api/support/health').json()['issues']
    original=httpx.AsyncClient;payloads=[]
    monkeypatch.setattr(operations,'destination',lambda tenant:{'url':'https://alerts.example.test','format':'webhook'})
    def handler(request):payloads.append(json.loads(request.content));return httpx.Response(200)
    monkeypatch.setattr(operations.httpx,'AsyncClient',lambda **kw:original(transport=httpx.MockTransport(handler),**kw))
    asyncio.run(operations.notify_one(s.store))
    assert payloads and 'customer@example.com' not in json.dumps(payloads) and '9am' not in json.dumps(payloads)
    with s.engine.begin() as c:
        c.execute(update(jobs).where(jobs.c.execution_id==id).values(status='COMPLETED'))
        c.execute(update(alerts).values(status='PENDING',available=0))
    before=len(payloads);asyncio.run(operations.notify_one(s.store));assert len(payloads)==before


def test_notification_failures_are_bounded(configured,monkeypatch):
    s=configured;ready(s);operations.collect(s.store)
    monkeypatch.setattr(operations,'destination',lambda tenant:(_ for _ in ()).throw(ValueError('secret')))
    for _ in range(3):
        with s.engine.begin() as c:c.execute(update(alerts).values(available=0))
        asyncio.run(operations.notify_one(s.store))
    with s.engine.connect() as c:
        row=c.execute(select(alerts).where(alerts.c.kind=='review_needed')).mappings().one()
        assert row['attempts']==3 and row['status']=='FAILED'


def test_outlook_cursor_cannot_redirect_credentials():
    assert outlook.cursor_url(outlook.DELTA+'?$deltatoken=abc').startswith(outlook.BASE)
    for url in ('https://evil.test/v1.0/me/mailFolders/inbox/messages/delta','https://graph.microsoft.com@evil.test/v1.0/me/mailFolders/inbox/messages/delta','http://graph.microsoft.com/v1.0/me/mailFolders/inbox/messages/delta'):
        with pytest.raises(EmailFailure):outlook.cursor_url(url)
    with pytest.raises(EmailFailure):outlook.validate_scopes({'scope':'User.Read Mail.Read Mail.ReadWrite'},False)


@pytest.fixture
def outlook_config(configured,tmp_path,monkeypatch):
    p=tmp_path/'outlook.json';p.write_text(json.dumps({'client_id':'id','client_secret':'SECRET','redirect_uris':['http://127.0.0.1:8300/api/integrations/outlook/callback']}))
    monkeypatch.setenv('OUTLOOK_CLIENT_FILE',str(p));monkeypatch.setenv('SOLOAI_CONNECTOR_KEY_FILE',str(tmp_path/'token.key'))
    return configured


def test_outlook_oauth_binding_and_replay(outlook_config,monkeypatch):
    from urllib.parse import urlsplit,parse_qs
    s=outlook_config;r=s.a.post('/api/integrations/outlook/connect',json={});assert r.status_code==200
    state=parse_qs(urlsplit(r.json()['url']).query)['state'][0]
    def handler(request):
        if request.url.path.endswith('/token'):return httpx.Response(200,json={'scope':'User.Read Mail.Read','access_token':'A','refresh_token':'SECRET-REFRESH'})
        return httpx.Response(200,json={'mail':'test@outlook.com'})
    mock_google(monkeypatch,handler)
    path='/api/integrations/outlook/callback?state='+state+'&code=fake'
    assert s.b.get(path,follow_redirects=False).status_code==400
    assert s.a.get(path,follow_redirects=False).status_code==303
    assert s.a.get(path,follow_redirects=False).status_code==400
    with s.engine.connect() as c:
        row=c.execute(select(outlook.connections)).mappings().one();assert row['baseline'] and not row['can_send'] and 'SECRET-REFRESH' not in row['refresh_token']
    assert 'SECRET' not in s.a.get('/api/integrations/outlook').text
    assert not s.b.get('/api/integrations/outlook').json()['connected']


def test_outlook_baseline_skips_backlog_and_then_enqueues(outlook_config,monkeypatch):
    s=outlook_config;cipher=outlook.settings()[2]
    with s.engine.begin() as c:c.execute(outlook.connections.insert().values(tenant=s.tenants[0],email='test@outlook.com',refresh_token=gmail.seal(cipher,s.tenants[0],'refresh'),baseline=True,can_send=False,next_sync=0,created=int(time.time())))
    def handler(request):
        if request.url.path.endswith('/token'):return httpx.Response(200,json={'access_token':'A','refresh_token':'rotated'})
        if request.url.path.endswith('/delta'):return httpx.Response(200,json={'value':[{'id':'one'}],'@odata.deltaLink':outlook.DELTA+'?$deltatoken=next'})
        return httpx.Response(200,json={'from':{'emailAddress':{'address':'a@example.com'}},'subject':'Opening hours','body':{'contentType':'text','content':'When do you open?'},'internetMessageId':'<one@example.com>'})
    mock_google(monkeypatch,handler)
    asyncio.run(outlook.sync_one(s.store))
    with s.engine.begin() as c:
        assert not c.execute(select(jobs)).first()
        c.execute(update(outlook.connections).values(next_sync=0))
    asyncio.run(outlook.sync_one(s.store))
    with s.engine.begin() as c:
        assert len(c.execute(select(jobs)).all())==1
        c.execute(update(outlook.connections).values(next_sync=0))
    asyncio.run(outlook.sync_one(s.store))
    with s.engine.connect() as c:assert len(c.execute(select(jobs)).all())==1


def test_sqlite_backup_restore_and_overwrite_protection(tmp_path):
    import sqlite3
    from scripts.database_backup import backup,restore
    source=tmp_path/'source.db';copy=tmp_path/'backup.db';target=tmp_path/'restored.db'
    with sqlite3.connect(source) as c:c.execute('CREATE TABLE fixture (id INTEGER)');c.execute('INSERT INTO fixture VALUES (42)')
    url='sqlite:///'+str(source);backup(url,copy)
    with pytest.raises(FileExistsError):backup(url,copy)
    with pytest.raises(ValueError):restore(url,url,copy)
    restore(url,'sqlite:///'+str(target),copy)
    with sqlite3.connect(target) as c:assert c.execute('SELECT id FROM fixture').fetchone()==(42,)
    with pytest.raises(ValueError):restore(url,'sqlite:///'+str(target),copy)


def test_busy_workspace_does_not_block_another_workspace(setup):
    s=setup;enqueue(s,'first');enqueue(s,'second');first=s.store.claim(90)
    assert first and first['tenant']==s.tenants[0]
    assert s.store.claim(90) is None
    r=s.b.post('/api/events',headers=s.keys[1],json={'id':'other','type':'email.received','content':'Opening hours?'})
    assert r.status_code==202
    second=s.store.claim(90);assert second['tenant']==s.tenants[1]


def test_outlook_send_is_fenced_and_accepted_is_not_recipient_delivery(outlook_config):
    from app.email_delivery import deliver
    from app.inbox_schema import tickets
    s=outlook_config;id=ready(s);cipher=outlook.settings()[2]
    with s.engine.begin() as c:
        c.execute(outlook.connections.insert().values(tenant=s.tenants[0],email='test@outlook.com',refresh_token=gmail.seal(cipher,s.tenants[0],'refresh'),baseline=False,can_send=True,next_sync=0,created=0))
        source=json.loads(c.execute(select(tickets.c.source).where(tickets.c.execution_id==id)).scalar_one());source.update(provider='outlook',mailbox='test@outlook.com')
        c.execute(update(tickets).where(tickets.c.execution_id==id).values(source=json.dumps(source)))
    calls=[]
    def handler(request):
        calls.append(request.url.path)
        if request.url.path.endswith('/token'):return httpx.Response(200,json={'access_token':'A'})
        assert request.url.path=='/v1.0/me/sendMail'
        import base64
        mime=base64.b64decode(request.content).decode();assert 'To: customer@example.com' in mime and 'In-Reply-To: <original@example.com>' in mime
        return httpx.Response(202)
    factory=lambda **kw:httpx.AsyncClient(transport=httpx.MockTransport(handler),**kw)
    assert asyncio.run(deliver(s.store,s.tenants[0],id,'reviewer',1,client_factory=factory))['sent']
    from fastapi import HTTPException
    with pytest.raises(HTTPException):asyncio.run(deliver(s.store,s.tenants[0],id,'reviewer',1,client_factory=factory))
    assert calls.count('/v1.0/me/sendMail')==1


def test_notification_email_contains_no_customer_content(configured,monkeypatch):
    s=configured;ready(s);operations.collect(s.store);sent=[]
    monkeypatch.setattr(operations,'destination',lambda tenant:{'format':'email','host':'smtp.example.test','from':'soloai@example.test','to':'operator@example.test'})
    monkeypatch.setattr(operations,'send_notification_email',lambda target,payload:sent.append(payload))
    asyncio.run(operations.notify_one(s.store))
    assert len(sent)==1 and set(sent[0])=={'event_id','event','message'}
