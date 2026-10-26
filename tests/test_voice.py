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
    assert 'No telephone transfer' in session['instructions']


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
