"""Read-only workflow adapter. Identity is operator-verified, never model-selected."""
import json
import time
import httpx
from sqlalchemy import text
from app.booking_connector import cipher
from app.gmail import unseal
from app.email_tools import BookingResult

async def read_booking(engine, tenant, run):
    def current():
        with engine.connect() as c:
            row=c.execute(text('SELECT b.url,b.secret,b.revision,v.booking_id,v.customer_id,v.expires FROM booking_connections b JOIN workflow_booking_context v ON b.tenant=v.tenant AND b.revision=v.revision WHERE b.tenant=:t AND v.run=:r AND v.expires>:now'),{'t':tenant,'r':run,'now':int(time.time())}).mappings().first()
            if not row:raise ValueError('Booking authorization expired or connector changed')
            return dict(row)
    connection=current()
    async with httpx.AsyncClient(timeout=4,follow_redirects=False,trust_env=False) as client:
        async with client.stream('POST',connection['url'],headers={'Authorization':'Bearer '+unseal(cipher(),tenant,connection['secret'])},json={'booking_id':connection['booking_id'],'customer_id':connection['customer_id']}) as response:
            if response.status_code!=200:raise ValueError('Booking service unavailable')
            body=b''
            async for chunk in response.aiter_bytes():
                body+=chunk
                if len(body)>4096:raise ValueError('Oversized booking response')
    result=json.loads(body)
    if result.pop('customer_id',None)!=connection['customer_id']:raise ValueError('Customer mismatch')
    parsed=BookingResult.model_validate(result)
    if parsed.booking_id!=connection['booking_id'] or (parsed.status and len(parsed.status)>100):raise ValueError('Invalid booking response')
    if not parsed.found and (parsed.status is not None or parsed.change_allowed is not None):raise ValueError('Invalid missing booking')
    if current()!=connection:raise ValueError('Booking authorization changed')
    return parsed.model_dump()
