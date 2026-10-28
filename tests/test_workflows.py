import json
import pytest
from sqlalchemy import text
from tests.test_email_workflows import setup
from app import workflows

BASE={'name':'Request review','blocks':[{'kind':'trigger','label':'Start'},{'kind':'approval','label':'Review'},{'kind':'tool','label':'Create task'},{'kind':'handoff','label':'Staff action'}]}

def create(s,definition=BASE):
    r=s.a.post('/api/workflows',json=definition);assert r.status_code==200,r.text
    return r.json()['id']
def start(s,fid,key='test-key-001',test=True):
    r=s.a.post(f'/api/workflows/{fid}/runs',json={'key':key,'content':'Sample request','test':test});assert r.status_code==200,r.text
    return r.json()['id']
def run(s,rid):return s.a.get('/api/workflows/runs/'+rid).json()
def approve(s,rid):return s.a.post('/api/workflows/runs/'+rid+'/decision',json={'approved':True})

def test_test_publish_enable_and_duplicate_actions(setup):
    s=setup;fid=create(s)
    assert s.a.post(f'/api/workflows/{fid}/publish',json={'revision':1}).status_code==409
    rid=start(s,fid)
    assert run(s,rid)['status']=='WAITING_APPROVAL'
    assert approve(s,rid).status_code==200
    assert run(s,rid)['status']=='NEEDS_HUMAN'
    assert s.a.get('/api/workflows').json()['tasks']==[]
    approve(s,rid);assert run(s,rid)['status']=='COMPLETED'
    assert s.a.post(f'/api/workflows/{fid}/publish',json={'revision':1}).status_code==200
    assert s.a.post(f'/api/workflows/{fid}/enable',json={'version':1,'enabled':True}).status_code==200
    live=start(s,fid,'live-key-001',False);approve(s,live)
    assert len(s.a.get('/api/workflows').json()['tasks'])==1
    assert start(s,fid,'live-key-001',False)==live
    assert len(s.a.get('/api/workflows').json()['tasks'])==1
    approve(s,live)
    assert approve(s,live).status_code==409

def test_tenant_isolation_validation_and_stale_draft(setup):
    s=setup;fid=create(s);rid=start(s,fid)
    assert s.b.get('/api/workflows/runs/'+rid).status_code==404
    assert s.b.post('/api/workflows/runs/'+rid+'/decision',json={'approved':True}).status_code==404
    assert s.b.put('/api/workflows/'+fid,json=BASE|{'revision':1}).status_code==404
    assert s.a.put('/api/workflows/'+fid,json=BASE|{'revision':1}).status_code==200
    assert s.a.put('/api/workflows/'+fid,json=BASE|{'revision':1}).status_code==409
    approve(s,rid);approve(s,rid)
    assert s.a.post(f'/api/workflows/{fid}/publish',json={'revision':2}).status_code==409
    assert s.a.post('/api/workflows',json={'name':'bad','blocks':[{'kind':'trigger','label':'start'},{'kind':'tool','label':'bad','tool':'send_email'}]}).status_code==422

def test_condition_rejection_stop_and_model_failure(setup,monkeypatch):
    s=setup
    fid=create(s,{'name':'Condition','blocks':[{'kind':'trigger','label':'Start'},{'kind':'condition','label':'Match','instruction':'not present'},{'kind':'tool','label':'Do not run'}]})
    assert run(s,start(s,fid))['status']=='CONDITION_NOT_MET'
    async def fail(*args):raise TimeoutError()
    monkeypatch.setattr(workflows,'model_task',fail)
    fid=create(s,{'name':'AI','blocks':[{'kind':'trigger','label':'Start'},{'kind':'ai_task','label':'Summarize','instruction':'Summarize this.'}]})
    rid=start(s,fid)
    assert run(s,rid)['status']=='FAILED'
    assert run(s,rid)['steps'][-1]['status']=='UNKNOWN'
    fid=create(s);rid=start(s,fid)
    s.a.post('/api/stop')
    assert approve(s,rid).status_code==409

def test_ai_progress_and_published_definition_are_stable(setup,monkeypatch):
    s=setup
    async def answer(*args):return 'Summary',25
    monkeypatch.setattr(workflows,'model_task',answer)
    body={'name':'AI','blocks':[{'kind':'trigger','label':'Start'},{'kind':'ai_task','label':'Summarize','instruction':'Summarize this.'}]}
    fid=create(s,body);rid=start(s,fid)
    assert run(s,rid)['status']=='COMPLETED' and run(s,rid)['context']=='Summary'
    s.a.post(f'/api/workflows/{fid}/publish',json={'revision':1});s.a.post(f'/api/workflows/{fid}/enable',json={'version':1,'enabled':True})
    s.a.put('/api/workflows/'+fid,json=BASE|{'revision':1})
    rid=start(s,fid,'live-stable-1',False)
    assert run(s,rid)['version']==1 and run(s,rid)['status']=='COMPLETED'
    assert json.loads(run(s,rid)['definition'])['name']=='AI'


def test_retry_key_mismatch_and_expired_ai_claim_are_safe(setup):
    s=setup;fid=create(s);rid=start(s,fid)
    assert s.a.post(f'/api/workflows/{fid}/runs',json={'key':'test-key-001','content':'Different input','test':True}).status_code==409
    with s.engine.begin() as c:
        c.execute(text("UPDATE workflow_runs SET status='RUNNING',lease=0 WHERE id=:id"),{'id':rid})
        c.execute(text("UPDATE workflow_steps SET status='RUNNING' WHERE run=:id AND position=1"),{'id':rid})
    assert s.a.post('/api/workflows/runs/'+rid+'/resume',json={}).status_code==200
    assert run(s,rid)['status']=='FAILED'
    assert run(s,rid)['steps'][-1]['status']=='UNKNOWN'
    assert s.a.get('/api/workflows').json()['tasks']==[]


def test_budget_failure_does_not_call_provider(setup,monkeypatch):
    s=setup
    async def forbidden(*args):raise AssertionError('Provider must not be called')
    monkeypatch.setattr(workflows,'model_task',forbidden)
    fid=create(s,{'name':'AI','blocks':[{'kind':'trigger','label':'Start'},{'kind':'ai_task','label':'Summary','instruction':'Summarize'}]})
    with s.engine.begin() as c:c.execute(text('UPDATE tenants SET used=budget WHERE id=:t'),{'t':s.tenants[0]})
    response=s.a.post(f'/api/workflows/{fid}/runs',json={'key':'budget-test','content':'Example','test':True})
    assert response.status_code==429
    rows=s.a.get(f'/api/workflows/{fid}/runs').json()
    assert run(s,rows[0]['id'])['status']=='READY'


def test_archive_restore_and_policy_scope(setup):
    s=setup
    s.a.post('/api/support/policies',json={'title':'Returns','content':'Returns require staff approval.'})
    s.b.post('/api/support/policies',json={'title':'Private','content':'Other workspace secret policy.'})
    fid=create(s,{'name':'Policy agent','blocks':[{'kind':'trigger','label':'Start'},{'kind':'tool','label':'Policies','tool':'read_business_policies'}]})
    rid=start(s,fid)
    assert 'Returns require' in run(s,rid)['context']
    assert 'Other workspace' not in run(s,rid)['context']
    assert s.b.delete('/api/workflows/'+fid).status_code==404
    assert s.a.delete('/api/workflows/'+fid).status_code==200
    assert not s.a.get('/api/workflows').json()['flows']
    assert s.a.post(f'/api/workflows/{fid}/runs',json={'key':'archived-key','content':'Example'}).status_code==409
    assert len(s.a.get('/api/workflows/deleted').json())==1
    assert s.a.post(f'/api/workflows/{fid}/restore').status_code==200
    assert len(s.a.get('/api/workflows').json()['flows'])==1


def test_ai_condition_fails_closed_and_preserves_input(setup,monkeypatch):
    s=setup
    body={'name':'Decision','blocks':[{'kind':'trigger','label':'Start'},{'kind':'condition','mode':'ai','label':'Eligible','instruction':'Is this a support request?'},{'kind':'approval','label':'Review'}]}
    fid=create(s,body)
    async def yes(*args):return 'CONTINUE',5
    monkeypatch.setattr(workflows,'model_task',yes)
    rid=start(s,fid);assert run(s,rid)['status']=='WAITING_APPROVAL'
    assert run(s,rid)['context']=='Sample request'
    async def uncertain(*args):return 'Probably yes',5
    monkeypatch.setattr(workflows,'model_task',uncertain)
    rid=start(s,fid,'uncertain-key');assert run(s,rid)['status']=='CONDITION_NOT_MET'


def test_booking_requires_verified_identity_and_uses_tenant_connector(setup,monkeypatch):
    import httpx
    from app import workflow_booking
    s=setup
    fid=create(s,{'name':'Booking','blocks':[{'kind':'trigger','label':'Start'},{'kind':'tool','tool':'get_booking','label':'Read booking'}]})
    payload={'key':'booking-run-1','content':'Check booking','test':True,'booking_id':'DEMO-1','customer_id':'C-1','identity_verified':True}
    assert s.a.post(f'/api/workflows/{fid}/runs',json=payload).status_code==409
    with s.engine.begin() as c:c.execute(text("INSERT INTO booking_connections (tenant,url,secret,revision,created) VALUES (:t,'https://example.supabase.co/functions/v1/soloai-booking','encrypted',1,0)"),{'t':s.tenants[0]})
    assert s.a.post(f'/api/workflows/{fid}/runs',json=payload|{'identity_verified':False}).status_code==422
    monkeypatch.setattr(workflow_booking,'cipher',lambda:None)
    monkeypatch.setattr(workflow_booking,'unseal',lambda *args:'test-only-token')
    original=httpx.AsyncClient
    def handler(request):
        assert json.loads(request.content)=={'booking_id':'DEMO-1','customer_id':'C-1'}
        return httpx.Response(200,json={'customer_id':'C-1','booking_id':'DEMO-1','found':True,'status':'confirmed','change_allowed':False})
    monkeypatch.setattr(workflow_booking.httpx,'AsyncClient',lambda **kwargs:original(transport=httpx.MockTransport(handler),**kwargs))
    response=s.a.post(f'/api/workflows/{fid}/runs',json=payload);assert response.status_code==200
    result=run(s,response.json()['id']);assert result['status']=='COMPLETED'
    assert 'confirmed' in result['context']
    assert s.b.get('/api/workflows/runs/'+result['id']).status_code==404
    def wrong_customer(request):
        return httpx.Response(200,json={'customer_id':'C-OTHER','booking_id':'DEMO-1','found':True,'status':'confirmed','change_allowed':False})
    monkeypatch.setattr(workflow_booking.httpx,'AsyncClient',lambda **kwargs:original(transport=httpx.MockTransport(wrong_customer),**kwargs))
    response=s.a.post(f'/api/workflows/{fid}/runs',json=payload|{'key':'booking-wrong-customer'})
    result=run(s,response.json()['id']);assert result['status']=='FAILED'
    assert 'C-OTHER' not in result['context']
    def revoked(request):
        with s.engine.begin() as c:c.execute(text('UPDATE booking_connections SET revision=revision+1 WHERE tenant=:t'),{'t':s.tenants[0]})
        return handler(request)
    monkeypatch.setattr(workflow_booking.httpx,'AsyncClient',lambda **kwargs:original(transport=httpx.MockTransport(revoked),**kwargs))
    response=s.a.post(f'/api/workflows/{fid}/runs',json=payload|{'key':'booking-revoked'})
    assert run(s,response.json()['id'])['status']=='FAILED'
