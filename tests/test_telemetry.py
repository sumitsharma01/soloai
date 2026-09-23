import json
from decimal import Decimal

from app.telemetry import emit


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
