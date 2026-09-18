"""Optional single-process local Prometheus metrics. Never exposed on the app port."""
from prometheus_client import Counter, Histogram, Gauge, start_http_server

HTTP = Counter('soloai_http_requests', 'HTTP requests', ['route','status'])
LATENCY = Histogram('soloai_http_duration_seconds', 'Full request latency', ['route'], buckets=(.01,.05,.1,.25,.5,1,2,5,10,30,60,120))
AGENTS = Counter('soloai_agent_executions', 'Finished executions', ['agent','status','usage_kind'])
AGENT_LATENCY = Histogram('soloai_agent_duration_seconds', 'Agent execution duration', ['agent'], buckets=(.1,.5,1,2,5,10,20,30,60,120))
TOKENS = Counter('soloai_tokens', 'Tokens by accounting source', ['agent','usage_kind'])
ALLOWANCE = Gauge('soloai_last_allowance_percent', 'Last observed workspace allowance percentage; no tenant dimension')
TOOLS = Counter('soloai_tool_calls', 'Tool attempts, without arguments or identities', ['tool','status'])
TOOL_LATENCY = Histogram('soloai_tool_duration_seconds', 'Tool latency', ['tool'])
REVIEWS = Counter('soloai_email_reviews', 'Operator review decisions', ['status'])
RECOVERIES = Counter('soloai_email_worker_recoveries', 'Interrupted jobs failed safely')

def observe(event, fields):
    if event == 'http.request':
        HTTP.labels(fields['route'],str(fields['status_code'])).inc()
        LATENCY.labels(fields['route']).observe(fields['latency_ms']/1000)
    elif event == 'agent.execution':
        AGENTS.labels(fields['agent'],fields['status'],fields['usage_kind']).inc()
        AGENT_LATENCY.labels(fields['agent']).observe(fields['latency_ms']/1000)
        TOKENS.labels(fields['agent'],fields['usage_kind']).inc(fields['tokens'])
        ALLOWANCE.set(fields['allowance_percent'])
    elif event == 'agent.tool':
        name = fields['tool_name'] if fields['tool_name'] in ('get_booking','search_policy') else 'unknown'
        status = fields['status'] if fields['status'] in ('ok','not_found','failed') else 'failed'
        TOOLS.labels(name,status).inc()
        TOOL_LATENCY.labels(name).observe(fields['duration_ms']/1000)
    elif event == 'email.review' and fields['status'] in ('APPROVED','REJECTED'):
        REVIEWS.labels(fields['status']).inc()
    elif event == 'email.recovery':
        RECOVERIES.inc()

def start(port):
    # Loopback only. Multi-worker/replica production metrics need a collector design.
    return start_http_server(port,addr='127.0.0.1')
