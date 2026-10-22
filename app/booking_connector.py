"""Restricted Supabase function client. URL and identity never come from the model."""
import json
import os
from pathlib import Path
import httpx
from cryptography.fernet import Fernet
from sqlalchemy import select
from app.email_tools import BookingResult,EmailFailure
from app.reliability_schema import connectors,identities
from app.gmail import seal,unseal


def cipher():
    path=os.getenv('SOLOAI_CONNECTOR_KEY_FILE') or os.getenv('GMAIL_TOKEN_KEY_FILE')
    try:return Fernet(Path(path).read_bytes().strip())
    except Exception:raise EmailFailure('connector_encryption_unavailable') from None


async def lookup(store,context,booking_id):
    import time
    tenant=context['tenant']
    with store.engine.connect() as c:
        connection=c.execute(select(connectors).where(connectors.c.tenant==tenant)).mappings().first()
        identity=c.execute(select(identities).where(identities.c.tenant==tenant,
            identities.c.execution_id==context['execution_id'],identities.c.expires>int(time.time()))).mappings().first()
    if not connection:return None
    # A reference or an email's From header is not proof of customer ownership.
    if not identity:return {'found':False,'booking_id':booking_id,'status':None,'change_allowed':None}
    try:
        async with httpx.AsyncClient(timeout=4,follow_redirects=False,trust_env=False) as client:
            async with client.stream('POST',connection['url'],headers={'Authorization':'Bearer '+unseal(cipher(),tenant,connection['secret'])},
                json={'booking_id':booking_id,'customer_id':identity['customer_id']}) as response:
                if response.status_code!=200:raise ValueError()
                body=b''
                async for chunk in response.aiter_bytes():
                    body+=chunk
                    if len(body)>4096:raise ValueError()
        result=json.loads(body)
        if result.pop('customer_id',None)!=identity['customer_id']:raise ValueError()
        parsed=BookingResult.model_validate(result)
        if parsed.booking_id!=booking_id or (parsed.status and len(parsed.status)>100):raise ValueError()
        if not parsed.found and (parsed.status is not None or parsed.change_allowed is not None):raise ValueError()
        # Recheck authorization after the network operation to fence disconnects.
        with store.engine.connect() as c:
            current=c.execute(select(connectors.c.revision).where(connectors.c.tenant==tenant)).scalar()
            verified=c.execute(select(identities.c.customer_id).where(identities.c.tenant==tenant,
                identities.c.execution_id==context['execution_id'],identities.c.expires>int(time.time()))).scalar()
        if current!=connection['revision'] or verified!=identity['customer_id']:raise ValueError()
        return parsed.model_dump()
    except Exception:raise EmailFailure('booking_connection_unavailable') from None
