import os
os.environ.pop('AZURE_FOUNDRY_PROJECT_ENDPOINT', None)
import os, tempfile
os.environ['DATABASE_URL']='sqlite:///'+tempfile.mktemp(suffix='.db')
os.environ.pop('AZURE_OPENAI_ENDPOINT',None)
from fastapi.testclient import TestClient
from sqlalchemy import text
from app.main import app,engine

def create(c,email):
    r=c.post('/api/auth/register',json={'email':email,'password':'test-password-1234','name':'Test Workspace'})
    assert r.status_code==200

def test_tenant_boundaries_permissions_quota_and_stop():
    with TestClient(app) as a,TestClient(app) as b:
        create(a,'a@example.com');create(b,'b@example.com')
        assert a.patch('/api/agents/website-chat',json={'enabled':True,'guidance':'Policy Alpha'}).status_code==200
        assert b.get('/api/dashboard').json()['agents'][0]['enabled']==0
        key=a.post('/api/keys').json()['key'];headers={'Authorization':'Bearer '+key}
        r=b.post('/api/events',headers=headers,json={'type':'chat.message','content':'help'})
        assert r.status_code==200 and 'Policy Alpha' in r.json()['reply']
        assert b.get('/api/dashboard').json()['executions']==[]
        assert a.get('/api/dashboard').json()['executions'][0]['tokens']>0
        assert 'content' not in a.get('/api/dashboard').json()['executions'][0]
        assert b.post('/api/events',json={'type':'chat.message','content':'help'}).status_code==401
        assert a.post('/api/try',json={'type':'email.send','content':'send'}).status_code==400
        a.patch('/api/agents/email-support',json={'enabled':True})
        r=a.post('/api/try',json={'type':'email.received','content':'help'})
        assert r.status_code==200 and r.json()['draft'] is True
        a.post('/api/stop')
        assert a.post('/api/events',headers=headers,json={'type':'chat.message','content':'help'}).status_code==409
        a.patch('/api/agents/website-chat',json={'enabled':True})
        with engine.begin() as c:c.execute(text('UPDATE tenants SET used=budget WHERE email=\'a@example.com\''))
        assert a.post('/api/try',json={'type':'chat.message','content':'help'}).status_code==429
        a.post('/api/keys')
        assert a.post('/api/events',headers=headers,json={'type':'chat.message','content':'help'}).status_code==401
        assert a.post('/api/stop',headers={'Origin':'https://evil.example'}).status_code==403
        assert a.post('/api/logout').status_code==200
        assert a.get('/api/dashboard').status_code==401

def test_login_validation_and_no_secrets_in_dashboard():
    with TestClient(app) as c:
        create(c,'c@example.com')
        assert 'password' not in c.get('/api/dashboard').text
        c.post('/api/logout')
        assert c.post('/api/auth/login',json={'email':'c@example.com','password':'wrong-password'}).status_code==401
        assert c.post('/api/auth/login',json={'email':'c@example.com','password':'test-password-1234'}).status_code==200
        assert c.post('/api/try',json={'type':'chat.message','content':'x'*8001}).status_code==422
        assert c.post('/api/try',content='x'*24001).status_code==413

def test_concurrent_budget_admission():
    from concurrent.futures import ThreadPoolExecutor
    with TestClient(app) as c:
        create(c,'concurrent@example.com')
        c.patch('/api/agents/website-chat',json={'enabled':True})
        key=c.post('/api/keys').json()['key']
        with engine.begin() as conn:conn.execute(text("UPDATE tenants SET budget=2200 WHERE email='concurrent@example.com'"))
        def send(_):return c.post('/api/events',headers={'Authorization':'Bearer '+key},json={'type':'chat.message','content':'x'*400}).status_code
        with ThreadPoolExecutor(max_workers=4) as pool: statuses=list(pool.map(send,range(4)))
        assert 429 in statuses and 200 in statuses
        w=c.get('/api/dashboard').json()['workspace'];assert w['used']<=w['budget']

def test_production_rejects_missing_configuration():
    import subprocess,sys
    env=dict(os.environ,SOLOAI_ENV='production')
    result=subprocess.run([sys.executable,'-c','import app.main'],env=env,capture_output=True)
    assert result.returncode!=0
    assert b'Production requires PostgreSQL' in result.stderr

def test_live_adapter_tenant_context_and_inflight_stop(monkeypatch):
    import json
    import threading
    from concurrent.futures import ThreadPoolExecutor
    from app import foundry
    started,release=threading.Event(),threading.Event()
    def invoke(payload):
        assert json.loads(payload)['business_guidance']=='Tenant-only policy'
        started.set()
        assert release.wait(5)
        return foundry.SupportReply(channel='website_chat',subject='',reply='Suppressed reply',needs_human=False),123
    monkeypatch.setenv('AZURE_FOUNDRY_PROJECT_ENDPOINT','https://test.services.ai.azure.com/api/projects/test')
    monkeypatch.setattr(foundry,'invoke',invoke)
    with TestClient(app) as c:
        create(c,'stop-live@example.com')
        c.patch('/api/agents/website-chat',json={'enabled':True,'guidance':'Tenant-only policy'})
        with ThreadPoolExecutor() as pool:
            future=pool.submit(c.post,'/api/try',json={'type':'chat.message','content':'Hello'})
            assert started.wait(5)
            assert c.post('/api/stop').status_code==200
            release.set()
            response=future.result()
        assert response.status_code==503 and 'Suppressed reply' not in response.text
        dashboard=c.get('/api/dashboard').json()
        assert dashboard['workspace']['used']==123
        assert dashboard['executions'][0]['status']=='stopped'
