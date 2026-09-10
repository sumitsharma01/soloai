from app.metrics import observe, TOKENS, HTTP

def test_metrics_are_bounded_and_account_sources_separate():
    labels=('email-support','reported')
    before=TOKENS.labels(*labels)._value.get()
    observe('agent.execution',{'agent':'email-support','status':'completed','usage_kind':'reported','tokens':7,'latency_ms':1000,'allowance_percent':2})
    assert TOKENS.labels(*labels)._value.get()==before+7
    observe('http.request',{'route':'/api/agents/{agent}','status_code':409,'latency_ms':20})
    assert HTTP.labels('/api/agents/{agent}','409')._value.get()>=1
