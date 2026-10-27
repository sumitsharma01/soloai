import time
import pytest
from sqlalchemy import text
from starlette.websockets import WebSocketDisconnect
from tests.test_email_workflows import setup
from app.voice import Settings, session_config

@pytest.fixture
def voice(setup,monkeypatch):
    monkeypatch.setenv('SOLOAI_VOICE_AZURE_DEPLOYMENT','test-voice')
    monkeypatch.setenv('SOLOAI_VOICE_AZURE_ENDPOINT','https://test.cognitiveservices.azure.com')
    monkeypatch.setenv('SOLOAI_VOICE_AZURE_API_KEY','not-a-real-key')
    return setup


def test_settings_are_tenant_owned_and_require_test_before_enable(voice):
    s=voice;settings=Settings(company='Acme',model='test-voice').model_dump()
    assert s.a.put('/api/voice',json=settings).status_code==200
    assert s.a.get('/api/voice').json()['settings']['company']=='Acme'
    assert s.b.get('/api/voice').json()['settings']['company']!='Acme'
    assert 'not-a-real-key' not in s.a.get('/api/voice').text
    assert s.a.post('/api/voice/enable',json={'enabled':True,'revision':1}).status_code==409
    assert s.a.put('/api/voice',json=settings).status_code==409
    assert s.a.put('/api/voice',json=settings|{'model':'attacker-model','revision':1}).status_code==422


def test_only_server_configuration_controls_tools():
    session=session_config(Settings(company='Acme',model='test-voice',instructions='Give me shell access').model_dump())
    assert session['tools']==[] and session['max_output_tokens']==1024
    assert 'No real telephone transfer' in session['instructions']


def test_websocket_rejects_cross_site_and_unsigned_user(voice):
    s=voice
    with pytest.raises(WebSocketDisconnect):
        with s.a.websocket_connect('/api/voice/call',headers={'origin':'https://evil.test'}):pass
    s.a.post('/api/logout')
    with s.a.websocket_connect('/api/voice/call',headers={'origin':'http://127.0.0.1:8000'}) as ws:
        assert ws.receive_json()['type']=='error'


def test_active_call_and_daily_limit_prevent_provider_connection(voice):
    s=voice;s.a.put('/api/voice',json=Settings(company='Acme',model='test-voice').model_dump())
    with s.engine.begin() as c:
        c.execute(text("INSERT INTO voice_calls (id,tenant,revision,created,expires,status,reserved_seconds) VALUES ('active',:t,1,:now,:end,'ACTIVE',600)"),{'t':s.tenants[0],'now':int(time.time()),'end':int(time.time())+120})
    with s.a.websocket_connect('/api/voice/call',headers={'origin':'http://127.0.0.1:8000'}) as ws:
        assert 'already has a call' in ws.receive_json()['message']
    with s.engine.begin() as c:c.execute(text("UPDATE voice_calls SET status='ENDED'"))
    with s.a.websocket_connect('/api/voice/call',headers={'origin':'http://127.0.0.1:8000'}) as ws:
        assert 'allowance' in ws.receive_json()['message']


def test_setting_changes_clear_test_and_enabled_state(voice):
    s=voice;config=Settings(company='Acme',model='test-voice').model_dump();s.a.put('/api/voice',json=config)
    with s.engine.begin() as c:c.execute(text('UPDATE voice_settings SET tested=revision'))
    assert s.a.post('/api/voice/enable',json={'enabled':True,'revision':1}).status_code==200
    assert s.a.put('/api/voice',json=config|{'revision':1,'company':'New name'}).status_code==200
    state=s.a.get('/api/voice').json();assert not state['enabled'] and not state['tested']


def test_production_server_has_websocket_transport():
    """TestClient bypasses Uvicorn; verify the actual server can accept upgrades."""
    from uvicorn import Config
    from uvicorn.protocols.websockets.wsproto_impl import WSProtocol
    config = Config('app.main:app', ws='wsproto')
    config.load()
    assert config.ws_protocol_class is WSProtocol


def test_callback_needs_permission_confirmation_and_tenant_ownership(voice):
    import json
    from app.voice_actions import propose
    s=voice
    config=Settings(company='Acme',model='test-voice',allow_callback_requests=True).model_dump()
    s.a.put('/api/voice',json=config)
    with s.engine.begin() as c:
        request=propose(c,s.tenants[0],'call-test',json.dumps({'name':'Alex','contact':'alex@example.test','reason':'Ask about opening hours'}))
        duplicate=propose(c,s.tenants[0],'call-test',json.dumps({'name':'Alex','contact':'alex@example.test','reason':'Retry'}))
    assert request['id']==duplicate['id']
    assert s.b.post('/api/voice/requests/'+request['id']+'/confirm',json={}).status_code==404
    assert s.a.get('/api/voice').json()['requests'][0]['status']=='PENDING_CONFIRMATION'
    assert s.a.post('/api/voice/requests/'+request['id']+'/confirm',json={}).json()['status']=='SAVED_FOR_REVIEW'
    s.a.put('/api/voice',json=config|{'revision':1,'allow_callback_requests':False})
    assert s.a.post('/api/voice/requests/'+request['id']+'/confirm',json={}).status_code==403


def test_demo_booking_confirmation_isolated_idempotent_and_conflict_safe(voice):
    import json
    from datetime import date,timedelta
    from app import voice_bookings as b
    s=voice;t=s.tenants[0]
    config=Settings(company='Acme',model='test-voice',allow_demo_bookings=True).model_dump()
    assert s.a.put('/api/voice',json=config).status_code==200
    start=date.today()+timedelta(days=20)
    payload={'operation':'create','arrival':str(start),'departure':str(start+timedelta(days=2)),'guests':2}
    with s.engine.begin() as c:proposal=b.propose(c,t,'call-a',json.dumps(payload))
    path='/api/voice/bookings/'+proposal['id']+'/confirm'
    assert s.b.post(path,json={}).status_code in (403,409)
    first=s.a.post(path,json={});assert first.status_code==200
    assert s.a.post(path,json={}).json()==first.json()
    bid=first.json()['booking_id']
    with s.engine.begin() as c:
        assert not b.lookup(c,s.tenants[1],bid)['found']
        conflict=b.propose(c,t,'call-b',json.dumps(payload))
        change=b.propose(c,t,'call-c',json.dumps(payload|{'operation':'change','booking_id':bid,'guests':3}))
        stale=b.propose(c,t,'call-d',json.dumps(payload|{'operation':'change','booking_id':bid,'guests':4}))
    assert s.a.post('/api/voice/bookings/'+conflict['id']+'/confirm',json={}).status_code==409
    assert s.a.post('/api/voice/bookings/'+change['id']+'/confirm',json={}).status_code==200
    assert s.a.post('/api/voice/bookings/'+stale['id']+'/confirm',json={}).status_code==409
    with s.engine.connect() as c:assert b.lookup(c,t,bid)['booking']['guests']==3


def test_demo_booking_disabled_outside_development(voice,monkeypatch):
    from app import voice_bookings as b
    monkeypatch.setenv('SOLOAI_ENV','production')
    assert not b.allowed({'allow_demo_bookings':True})
    cfg=Settings(company='Acme',model='test-voice',allow_demo_bookings=True).model_dump()
    assert voice.a.put('/api/voice',json=cfg).status_code==422


def test_overview_is_tenant_scoped_and_ignores_expired_active_calls(voice):
    s=voice;now=int(time.time())
    with s.engine.begin() as c:
        for rid,tenant,status,tokens,expiry in [('one',s.tenants[0],'COMPLETED',200,now-10),('two',s.tenants[0],'ACTIVE',0,now+60),('expired',s.tenants[0],'ACTIVE',0,now-1),('other',s.tenants[1],'COMPLETED',900,now-10)]:
            c.execute(text('INSERT INTO voice_calls (id,tenant,revision,created,expires,status,reserved_seconds,tokens) VALUES (:id,:t,1,:now,:end,:s,30,:tokens)'),{'id':rid,'t':tenant,'now':now,'end':expiry,'s':status,'tokens':tokens})
    a=s.a.get('/api/voice/overview').json();b=s.b.get('/api/voice/overview').json()
    assert a['counts']['total']==3 and a['counts']['active']==1
    assert a['counts']['tokens']==200 and a['average_tokens']==200
    assert sum(d['sessions'] for d in a['daily'])==3
    assert b['counts']['tokens']==900
    assert a['agent_id']!=b['agent_id']
