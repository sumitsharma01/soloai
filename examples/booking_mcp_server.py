"""Loopback demo MCP server. Tokens select tenants; arguments cannot select them."""
import hmac
import json
import os
from contextvars import ContextVar
from pathlib import Path
from mcp.server.fastmcp import FastMCP
from app.email_tools import BookingInput

identity = ContextVar('booking_identity', default=None)
mcp = FastMCP('SoloAI booking demo', stateless_http=True, json_response=True)

@mcp.tool()
def get_booking(booking_id: str) -> dict:
    """Read a minimal booking record. No write operations."""
    BookingInput(booking_id=booking_id)
    entry = identity.get()
    if entry is None: raise ValueError('Unauthorized')
    row = entry['bookings'].get(booking_id)
    return {'found': row is not None, 'booking_id': booking_id,
            'status': row['status'] if row else None,
            'change_allowed': row['change_allowed'] if row else None}

class TenantAuth:
    def __init__(self, app): self.app = app
    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http': return await self.app(scope, receive, send)
        raw = dict(scope['headers']).get(b'authorization', b'').decode('ascii', errors='ignore')
        config = json.loads(Path(os.environ['BOOKING_MCP_SERVER_FILE']).read_text())
        entry = next((e for e in config['tenants'].values()
                      if len(e['token']) >= 32 and hmac.compare_digest(raw, 'Bearer '+e['token'])), None)
        if entry is None:
            await send({'type':'http.response.start', 'status':401, 'headers':[]})
            return await send({'type':'http.response.body','body':b'Unauthorized'})
        binding = identity.set(entry)
        try: await self.app(scope, receive, send)
        finally: identity.reset(binding)

app = TenantAuth(mcp.streamable_http_app())
