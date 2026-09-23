import json
from fastapi.testclient import TestClient
from app.main import app
from app.telemetry import emit


def test_allowlist_excludes_content_and_identity(capsys):
    emit('agent.execution', tokens=123, content='secret-body', tenant='secret-tenant', api_key='secret-key')
    event=json.loads(capsys.readouterr().out)
    assert event == {'schema':1,'event':'agent.execution','tokens':123}


def test_raw_url_and_query_never_logged(capsys):
    with TestClient(app) as client:
        client.get('/missing-secret-path?password=secret-password')
        client.get('/health')
    events=[json.loads(line) for line in capsys.readouterr().out.splitlines() if line.startswith('{')]
    assert len(events)==1
    assert events[0]['route']=='unmatched' and events[0]['status_code']==404
    assert 'secret' not in json.dumps(events)


def test_origin_rejection_is_measured(capsys):
    with TestClient(app) as client:
        assert client.post('/api/stop',headers={'Origin':'https://invalid.example'}).status_code==403
    events=[json.loads(line) for line in capsys.readouterr().out.splitlines() if line.startswith('{')]
    assert events[-1]['status_code']==403


from decimal import Decimal

def test_postgresql_numeric_telemetry_is_json_and_metric_compatible(monkeypatch, capsys):
    from app import metrics
    observed = []
    monkeypatch.setenv('SOLOAI_METRICS_PORT', '9470')
    monkeypatch.setattr(metrics, 'observe', lambda event, fields: observed.append(fields))
    emit('agent.execution', allowance_percent=Decimal('42.0400000000000000'),
         tokens=42, status='completed', customer_email='must-not-be-logged')
    payload = json.loads(capsys.readouterr().out)
    assert payload['allowance_percent'] == 42.04
    assert isinstance(observed[0]['allowance_percent'], float)
    assert payload['tokens'] == 42
    assert 'customer_email' not in payload
    assert 'customer_email' not in observed[0]
