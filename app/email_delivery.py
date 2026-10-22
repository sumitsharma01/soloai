"""Send one reply once. Unknown Gmail outcomes require investigation, never replay."""
import base64
import hashlib
import json
import re
import time
from email.message import EmailMessage
from email.utils import getaddresses
import httpx
from fastapi import HTTPException
from sqlalchemy import select, update, text
from app.email_schema import jobs, tool_calls
from app.inbox_schema import tickets, settings, deliveries
from app.inbox import row_for, ensure_ticket, send_permission


def message_source(message, mailbox):
    """Only Gmail intake creates destinations. Public events cannot supply them."""
    headers={}
    for h in message.get('payload',{}).get('headers',[]):
        headers.setdefault(h['name'].lower(),[]).append(h['value'])
    addresses=getaddresses(headers.get('from',[]))
    recipient=addresses[0][1] if len(addresses)==1 else ''
    if not re.fullmatch(r'[^\s@<>\r\n]+@[^\s@<>\r\n]+\.[^\s@<>\r\n]+',recipient): return None
    subject=(headers.get('subject') or [''])[0]
    message_id=(headers.get('message-id') or [''])[0]
    thread_id=message.get('threadId','')
    if any('\r' in x or '\n' in x for x in (subject,message_id)) or len(subject)>500: return None
    if not re.fullmatch(r'<[^<>\s]{1,250}>',message_id) or not re.fullmatch(r'[a-f0-9]{1,80}',thread_id): return None
    automated=(any(x.lower()!='no' for x in headers.get('auto-submitted',[])) or
        bool(headers.get('list-id')) or any(x.lower() in ('bulk','list','junk') for x in headers.get('precedence',[])))
    if recipient.lower()==mailbox.lower(): automated=True
    return dict(recipient=recipient,subject=subject,message_id=message_id,thread_id=thread_id,
                mailbox=mailbox,automated=automated)


def check(c,tenant,execution,actor,revision):
    row=row_for(c,tenant,execution);ticket=ensure_ticket(c,tenant,row)
    existing=c.execute(select(deliveries).where(deliveries.c.tenant==tenant,deliveries.c.execution_id==execution)).mappings().first()
    if existing and existing['status'] in ('SENT','DISPATCHING','UNKNOWN'):
        raise HTTPException(409,'Delivery already started. Do not resend; check delivery status.')
    if row['expires_at']<=int(time.time()) or not row['draft'] or row['status'] not in ('WAITING_FOR_REVIEW','APPROVED','FAILED'):
        raise HTTPException(409,'No current draft available to send')
    if ticket['revision']!=revision: raise HTTPException(409,'Draft changed. Reload before sending.')
    state=c.execute(text("SELECT a.enabled,t.stopped FROM tenants t JOIN agents a ON a.tenant=t.id WHERE t.id=:t AND a.id='email-support'"),{'t':tenant}).one()
    if not state.enabled or state.stopped!=row['epoch']: raise HTTPException(409,'Agent stopped. Regenerate after enabling it before sending.')
    source=json.loads(ticket['source']) if ticket['source'] else None
    provider=(source or {}).get('provider','gmail')
    if not send_permission(c,tenant,provider):raise HTTPException(409,'Authorize sending for this mailbox first')
    if provider=='outlook':
        from app.outlook import connections
    else:
        from app.gmail import connections
    connection=c.execute(select(connections).where(connections.c.tenant==tenant)).mappings().one()
    if not source or source['mailbox']!=connection['email']: raise HTTPException(409,'No matching mailbox reply destination. Older or forwarded events cannot be sent.')
    cfg=c.execute(select(settings).where(settings.c.tenant==tenant)).mappings().one()
    count=len(c.execute(select(deliveries.c.execution_id).where(deliveries.c.tenant==tenant,deliveries.c.created>=int(time.time())//86400*86400)).all())
    if count>=cfg['daily_limit']: raise HTTPException(409,'Daily send limit reached (UTC day)')
    if actor=='agent':
        # Existing review backlog never becomes automatic when a switch is enabled.
        risky=re.search(r'\b(refund|cancel\w*|booking|payment|password|account|order|invoice|credit|card)\b', (row['content'] or '')+' '+row['draft'],re.I)
        booking=c.execute(select(tool_calls.c.id).where(tool_calls.c.tenant==tenant,tool_calls.c.execution_id==execution,tool_calls.c.tool_name=='get_booking')).first()
        if (existing or not cfg['automatic'] or row['created_at']<=cfg['enabled_at'] or row['needs_human'] is not False
            or row['status']!='WAITING_FOR_REVIEW' or not set(json.loads(ticket['labels'])) & set(json.loads(cfg['allowed_labels']))
            or source['automated'] or risky or booking or ticket['revision']!=1):
            raise HTTPException(409,'Human review required')
    return row,ticket,source,dict(connection)


async def deliver(store,tenant,execution,actor,revision,client_factory=None):
    client_factory = client_factory or httpx.AsyncClient
    from app.gmail import settings as gmail_settings, unseal, digest
    with store.transaction(tenant) as c: row,ticket,source,connection=check(c,tenant,execution,actor,revision)
    outlook=source.get('provider')=='outlook'
    if not outlook:config,_,cipher=gmail_settings()
    # Token acquisition precedes the durable dispatch marker. No message is sent here.
    try:
        async with client_factory(timeout=15,follow_redirects=False) as client:
            if outlook:
                from app.outlook import access_token
                tokens=await access_token(connection,client)
                access=tokens['access_token']
            else:
                token=await client.post('https://oauth2.googleapis.com/token',data={'client_id':config['client_id'],
                    'client_secret':config['client_secret'],'grant_type':'refresh_token',
                    'refresh_token':unseal(cipher,tenant,connection['refresh_token'])})
                if token.status_code!=200: raise ValueError()
                access=token.json()['access_token']
    except Exception:
        raise HTTPException(503,'Mailbox authorization could not be refreshed. Reconnect if this persists.') from None
    now=int(time.time())
    with store.transaction(tenant) as c:
        row,ticket,source,current=check(c,tenant,execution,actor,revision)
        if digest(current['refresh_token'])!=digest(connection['refresh_token']): raise HTTPException(409,'Gmail connection changed. Reload and try again.')
        message=EmailMessage()
        message['From']=connection['email'];message['To']=source['recipient']
        message['Subject']=source['subject']
        message['In-Reply-To']=source['message_id'];message['References']=source['message_id']
        message['Message-ID']='<soloai-'+hashlib.sha256((tenant+execution).encode()).hexdigest()+'@soloai.local>'
        message['Auto-Submitted']='auto-replied';message.set_content(row['draft'])
        mime=base64.b64encode(message.as_bytes()).decode()
        payload={'raw':base64.urlsafe_b64encode(message.as_bytes()).decode(),'threadId':source['thread_id']}
        prior=c.execute(select(deliveries.c.status).where(deliveries.c.tenant==tenant,deliveries.c.execution_id==execution)).scalar()
        if prior:
            c.execute(update(deliveries).where(deliveries.c.tenant==tenant,deliveries.c.execution_id==execution).values(status='DISPATCHING',actor=actor,created=now,updated=now,error=None))
        else: c.execute(deliveries.insert().values(tenant=tenant,execution_id=execution,status='DISPATCHING',actor=actor,created=now,updated=now))
        store.audit(c,tenant,'email.send_started.'+actor+'.'+execution)
    # DISPATCHING is the point of no return. Pausing prevents later dispatches.
    status,error,provider_id='UNKNOWN','mailbox_send_outcome_unknown',None
    try:
        async with client_factory(timeout=20,follow_redirects=False) as client:
            if outlook:
                response=await client.post('https://graph.microsoft.com/v1.0/me/sendMail',
                    headers={'Authorization':'Bearer '+access,'Content-Type':'text/plain'},content=mime)
                if response.status_code==202:status,error='SENT',None
                elif response.status_code in (400,401,403,404,429):status,error='FAILED','outlook_send_rejected'
            else:
                response=await client.post('https://gmail.googleapis.com/gmail/v1/users/me/messages/send',
                    headers={'Authorization':'Bearer '+access},json=payload)
                if response.status_code==200:
                    provider_id=response.json().get('id')
                    if isinstance(provider_id,str) and re.fullmatch(r'[a-zA-Z0-9_-]{1,128}',provider_id): status,error='SENT',None
                    else: provider_id=None
                elif response.status_code in (400,401,403,404,429): status,error='FAILED','gmail_send_rejected'

    except Exception: pass  # No raw provider errors or message content in logs.
    with store.transaction(tenant) as c:
        c.execute(update(deliveries).where(deliveries.c.tenant==tenant,deliveries.c.execution_id==execution).values(status=status,error=error,provider_id=provider_id,updated=int(time.time())))
        if status=='SENT':
            c.execute(update(jobs).where(jobs.c.tenant==tenant,jobs.c.execution_id==execution).values(status='COMPLETED'))
            c.execute(text("UPDATE executions SET status='COMPLETED' WHERE tenant=:t AND id=:id"),{'t':tenant,'id':execution})
        store.audit(c,tenant,'email.delivery_'+status.lower()+'.'+actor+'.'+execution)
    from app.telemetry import emit
    emit('email.delivery',status=status)
    return {'status':status,'sent':status=='SENT'}


async def automatic_one(store):
    now=int(time.time())
    with store.transaction() as c:
        c.execute(update(deliveries).where(deliveries.c.status=='DISPATCHING',deliveries.c.updated<now-120).values(status='UNKNOWN',error='worker_interrupted',updated=now))
        candidates=c.execute(select(jobs.c.tenant,jobs.c.execution_id,tickets.c.revision).join(settings,settings.c.tenant==jobs.c.tenant)
            .join(tickets,(tickets.c.tenant==jobs.c.tenant)&(tickets.c.execution_id==jobs.c.execution_id))
            .where(settings.c.automatic==True,jobs.c.status=='WAITING_FOR_REVIEW',jobs.c.created_at>settings.c.enabled_at)
            .order_by(jobs.c.created_at.desc()).limit(100)).all()
    for tenant,execution,revision in candidates:
        try:
            await deliver(store,tenant,execution,'agent',revision)
            return True
        except HTTPException as exc:
            if exc.status_code==503:
                # Do not hammer a failing token endpoint on every worker tick.
                with store.transaction(tenant) as c:
                    c.execute(update(settings).where(settings.c.tenant==tenant).values(automatic=False,revision=settings.c.revision+1))
                    store.audit(c,tenant,'email.automatic_paused_authorization_failure')
                return False
            continue
    return False
