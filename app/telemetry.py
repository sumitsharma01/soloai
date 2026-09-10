"""Allowlisted operational events; never log request bodies or identities."""
import json
import time
import os

FIELDS = {'agent', 'status', 'latency_ms', 'provider_ms', 'tokens', 'usage_kind',
          'route', 'status_code', 'allowance_percent'}

def emit(event, **fields):
    safe = {key: value for key, value in fields.items() if key in FIELDS}
    if os.getenv('SOLOAI_METRICS_PORT'):
        from app.metrics import observe
        observe(event,safe)
    print(json.dumps({'schema': 1, 'event': event, **safe}), flush=True)

class RequestTelemetry:
    """ASGI wrapper measures complete responses, including rejected requests."""
    def __init__(self, app): self.app = app
    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http':
            return await self.app(scope, receive, send)
        start = time.monotonic()
        status = 500
        async def capture(message):
            nonlocal status
            if message['type'] == 'http.response.start': status = message['status']
            await send(message)
        try:
            await self.app(scope, receive, capture)
        finally:
            # Route templates only: raw paths and query strings may contain secrets.
            route = getattr(scope.get('route'), 'path', 'unmatched')
            if route not in ('/health','/live'):
                emit('http.request', route=route, status_code=status,
                     latency_ms=round((time.monotonic()-start)*1000))
