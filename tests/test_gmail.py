import asyncio
import base64
import json
import time
from urllib.parse import urlparse, parse_qs
import httpx
import pytest
from cryptography.fernet import Fernet
from sqlalchemy import select, update
from tests.test_email_workflows import setup
from app import gmail
from app.email_tools import EmailFailure
from app.email_schema import jobs


@pytest.fixture
def configured(setup,tmp_path,monkeypatch):
    config=tmp_path/'client.json'; key=tmp_path/'token.key'
    config.write_text(json.dumps({'web':{'client_id':'fake-client','client_secret':'SECRET-CLIENT',
        'redirect_uris':['http://127.0.0.1:8300/api/integrations/gmail/callback']}}))
    key.write_bytes(Fernet.generate_key())
    monkeypatch.setenv('GMAIL_CLIENT_FILE',str(config))
    monkeypatch.setenv('GMAIL_TOKEN_KEY_FILE',str(key))
    monkeypatch.setenv('PUBLIC_ORIGIN','http://127.0.0.1:8300')
    return setup


def mock_google(monkeypatch,handle):
    original=httpx.AsyncClient
    monkeypatch.setattr(gmail.httpx,'AsyncClient',lambda **kwargs:original(transport=httpx.MockTransport(handle),**kwargs))


def start(s):
    r=s.a.post('/api/integrations/gmail/connect',json={'email':'testingsoloai@gmail.com'})
    assert r.status_code==200,r.text
    query=parse_qs(urlparse(r.json()['url']).query)
    assert query['scope']==[gmail.SCOPE]
    assert query['code_challenge_method']==['S256']
    assert 'SECRET-CLIENT' not in r.text
    return query['state'][0]


def test_oauth_binding_replay_and_encryption(configured,monkeypatch):
    s=configured;state=start(s)
    def handle(request):
        if request.url.path=='/token':return httpx.Response(200,json={'access_token':'ACCESS','refresh_token':'REFRESH-SECRET','scope':gmail.SCOPE})
        return httpx.Response(200,json={'emailAddress':'testingsoloai@gmail.com','historyId':'100'})
    mock_google(monkeypatch,handle)
    path='/api/integrations/gmail/callback?state='+state+'&code=CODE'
    assert s.b.get(path,follow_redirects=False).status_code==400
    assert s.a.get(path,follow_redirects=False).status_code==303
    assert s.a.get(path,follow_redirects=False).status_code==400
    with s.engine.connect() as c:
        row=c.execute(select(gmail.connections)).mappings().one()
    assert 'REFRESH-SECRET' not in row['refresh_token']
    cipher=gmail.settings()[2]
    assert gmail.unseal(cipher,s.tenants[0],row['refresh_token'])=='REFRESH-SECRET'
    with pytest.raises(EmailFailure):gmail.unseal(cipher,s.tenants[1],row['refresh_token'])
    assert s.b.get('/api/integrations/gmail').json()['connected'] is False
    assert 'REFRESH-SECRET' not in s.a.get('/api/integrations/gmail').text
    s.a.post('/api/integrations/gmail/disconnect')
    assert s.a.get('/api/integrations/gmail').json()['connected'] is False


def test_wrong_google_account_rejected(configured,monkeypatch):
    s=configured;state=start(s)
    def handle(request):
        if request.url.path=='/token':return httpx.Response(200,json={'access_token':'A','refresh_token':'R','scope':gmail.SCOPE})
        return httpx.Response(200,json={'emailAddress':'other@gmail.com','historyId':'100'})
    mock_google(monkeypatch,handle)
    r=s.a.get('/api/integrations/gmail/callback?state='+state+'&code=CODE')
    assert r.status_code==400 and r.json()['detail']=='gmail_wrong_account'


def test_sync_deduplicates_and_advances_after_enqueue(configured,monkeypatch,capsys):
    s=configured;cipher=gmail.settings()[2]
    with s.engine.begin() as c:
        c.execute(gmail.connections.insert().values(tenant=s.tenants[0],email='testingsoloai@gmail.com',
            refresh_token=gmail.seal(cipher,s.tenants[0],'SECRET-TOKEN'),history_id='100',next_sync=0,created=int(time.time())))
    def handle(request):
        if request.url.path=='/token':return httpx.Response(200,json={'access_token':'SECRET-ACCESS'})
        if request.url.path.endswith('/history'):
            return httpx.Response(200,json={'historyId':'102','history':[{'messagesAdded':[{'message':{'id':'abc123'}}]}]})
        return httpx.Response(200,json={'labelIds':['INBOX'],'payload':{'mimeType':'text/plain',
            'headers':[{'name':'Subject','value':'Booking question'}],
            'body':{'data':base64.urlsafe_b64encode(b'SECRET BODY Can I change booking BK-2041?').decode()}}})
    mock_google(monkeypatch,handle)
    asyncio.run(gmail.sync_one(s.store))
    with s.engine.begin() as c:
        assert c.execute(select(gmail.connections.c.history_id)).scalar_one()=='102'
        c.execute(update(gmail.connections).values(next_sync=0))
    asyncio.run(gmail.sync_one(s.store))
    with s.engine.connect() as c:
        rows=c.execute(select(jobs).where(jobs.c.tenant==s.tenants[0])).mappings().all()
    assert len(rows)==1 and rows[0]['status']=='QUEUED'
    assert 'SECRET' not in capsys.readouterr().out


def test_expired_history_stops_without_importing_old_mail(configured,monkeypatch):
    s=configured;cipher=gmail.settings()[2]
    with s.engine.begin() as c:
        c.execute(gmail.connections.insert().values(tenant=s.tenants[0],email='testingsoloai@gmail.com',
            refresh_token=gmail.seal(cipher,s.tenants[0],'R'),history_id='1',next_sync=0,created=0))
    def handle(request):
        return httpx.Response(200,json={'access_token':'A'}) if request.url.path=='/token' else httpx.Response(404,json={})
    mock_google(monkeypatch,handle)
    asyncio.run(gmail.sync_one(s.store))
    with s.engine.connect() as c:
        assert c.execute(select(gmail.connections.c.error)).scalar_one()=='gmail_history_expired'
        assert not c.execute(select(jobs)).first()


def test_mime_does_not_fetch_attachments():
    message={'payload':{'parts':[
        {'filename':'secret.txt','mimeType':'text/plain','body':{'data':base64.urlsafe_b64encode(b'ATTACHMENT').decode()}},
        {'mimeType':'text/html','body':{'data':base64.urlsafe_b64encode(b'<script>SECRET</script><p>Hello</p>').decode()}}]}}
    result=gmail.message_text(message)
    assert 'Hello' in result and 'SECRET' not in result and 'ATTACHMENT' not in result


def test_account_picker_uses_google_verified_mailbox(configured, monkeypatch):
    s = configured
    result = s.a.post('/api/integrations/gmail/connect', json={})
    assert result.status_code == 200
    query = parse_qs(urlparse(result.json()['url']).query)
    assert 'login_hint' not in query
    assert 'select_account' in query['prompt'][0]
    assert query['code_challenge_method'] == ['S256']
    def handle(request):
        if request.url.path == '/token':
            return httpx.Response(200, json={'access_token':'A','refresh_token':'R','scope':gmail.SCOPE})
        return httpx.Response(200, json={'emailAddress':'selected@gmail.com','historyId':'100'})
    mock_google(monkeypatch, handle)
    callback = '/api/integrations/gmail/callback?state=' + query['state'][0] + '&code=CODE'
    assert s.b.get(callback, follow_redirects=False).status_code == 400
    assert s.a.get(callback, follow_redirects=False).status_code == 303
    assert s.a.get('/api/integrations/gmail').json()['email'] == 'selected@gmail.com'
    assert s.b.get('/api/integrations/gmail').json()['connected'] is False
    assert s.a.get(callback, follow_redirects=False).status_code == 400
