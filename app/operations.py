"""Content-free, tenant-visible health plus a bounded notification outbox."""
import asyncio,hashlib,json,os,secrets,time,re,smtplib
from email.message import EmailMessage
from pathlib import Path
from urllib.parse import urlsplit
import httpx
from fastapi import APIRouter,Depends
from sqlalchemy import select,update,delete,func,text
from app.email_schema import jobs
from app.inbox_schema import deliveries
from app.gmail import connections
from app.reliability_schema import alerts


def issues(c,tenant=None):
    now=int(time.time());result=[]
    query=select(jobs.c.tenant,jobs.c.execution_id,jobs.c.status,jobs.c.created_at,jobs.c.available_at).where(jobs.c.status.in_(['QUEUED','RUNNING','FAILED','WAITING_FOR_REVIEW']),jobs.c.expires_at>now)
    if tenant:query=query.where(jobs.c.tenant==tenant)
    for row in c.execute(query.order_by(jobs.c.created_at).limit(1000)).mappings():
        kind=('processing_failed' if row['status']=='FAILED' else 'review_needed' if row['status']=='WAITING_FOR_REVIEW' else 'queue_delayed' if row['status']=='QUEUED' and row['available_at']<now-300 else None)
        if kind:result.append({'tenant':row['tenant'],'kind':kind,'subject_id':row['execution_id']})
    from app.outlook import connections as outlook_connections
    for provider,table in (('gmail',connections),('outlook',outlook_connections)):
        query=select(table.c.tenant,table.c.error,table.c.last_sync,table.c.created)
        if tenant:query=query.where(table.c.tenant==tenant)
        for row in c.execute(query).mappings():
            kind='mailbox_disconnected' if row['error'] else 'mailbox_sync_delayed' if (row['last_sync'] or row['created'])<now-600 else None
            if kind:result.append({'tenant':row['tenant'],'kind':kind,'subject_id':provider})
    query=select(deliveries.c.tenant,deliveries.c.execution_id).where(deliveries.c.status.in_(['FAILED','UNKNOWN']))
    if tenant:query=query.where(deliveries.c.tenant==tenant)
    for row in c.execute(query.limit(1000)):result.append({'tenant':row.tenant,'kind':'delivery_needs_attention','subject_id':row.execution_id})
    return result


def collect(store):
    now=int(time.time())
    with store.transaction() as c:
        if store.engine.dialect.name=='postgresql' and not c.execute(text('SELECT pg_try_advisory_xact_lock(72651002)')).scalar():return
        # Enumerate tenants, then bound each tenant's active set. One busy workspace
        # must not hide alerts belonging to later workspaces.
        tenants=c.execute(text('SELECT id FROM tenants ORDER BY id')).scalars().all()
        current=[]
        for tenant in tenants:current.extend(issues(c,tenant))
        active_ids={hashlib.sha256(json.dumps(i,sort_keys=True).encode()).hexdigest() for i in current}
        for old in c.execute(select(alerts.c.id,alerts.c.status).where(alerts.c.status.in_(['PENDING','DELIVERED','UNCONFIGURED','FAILED']))).all():
            if old.id not in active_ids:c.execute(update(alerts).where(alerts.c.id==old.id).values(status='RESOLVED'))
        c.execute(update(alerts).where(alerts.c.status=='UNCONFIGURED',alerts.c.available<=now).values(status='PENDING',attempts=0))
        for issue in current:
            id=hashlib.sha256(json.dumps(issue,sort_keys=True).encode()).hexdigest()
            existing=c.execute(select(alerts.c.status).where(alerts.c.id==id)).scalar()
            if existing=='RESOLVED':c.execute(update(alerts).where(alerts.c.id==id).values(status='PENDING',attempts=0,available=now))
            if existing is None:
                c.execute(alerts.insert().values(id=id,**issue,status='PENDING',attempts=0,available=now,created=now))
        # Keep idempotency records for 30 days, no email bodies or subjects.
        c.execute(delete(alerts).where(alerts.c.created<now-30*86400))
    from app.metrics import QUEUE_DEPTH,QUEUE_AGE,REVIEW_AGE,MAILBOX_ERRORS,OPS_HEARTBEAT
    with store.engine.connect() as c:
        for state in ('QUEUED','RUNNING','WAITING_FOR_REVIEW','FAILED'):
            QUEUE_DEPTH.labels(state).set(c.execute(select(func.count()).select_from(jobs).where(jobs.c.status==state,jobs.c.expires_at>now)).scalar_one())
        for metric,state in ((QUEUE_AGE,'QUEUED'),(REVIEW_AGE,'WAITING_FOR_REVIEW')):
            oldest=c.execute(select(func.min(jobs.c.created_at)).where(jobs.c.status==state,jobs.c.expires_at>now)).scalar()
            metric.set(max(0,now-oldest) if oldest else 0)
        from app.outlook import connections as outlook_connections
        MAILBOX_ERRORS.set(sum(c.execute(select(func.count()).select_from(table).where(table.c.error.is_not(None))).scalar_one() for table in (connections,outlook_connections)))
    OPS_HEARTBEAT.set(now)


def destination(tenant):
    path=os.getenv('SOLOAI_NOTIFICATION_CONFIG_FILE')
    if not path:return None
    data=json.loads(Path(path).read_text());entry=data.get('tenants',{}).get(tenant)
    if not entry:return None
    if entry.get('format')=='email':
        if entry.get('host') not in data.get('allowed_smtp_hosts',[]) or entry.get('to') not in data.get('allowed_recipients',[]):raise ValueError('Unapproved mail destination')
        if any(not re.fullmatch(r'[^\s@<>]+@[^\s@<>]+\.[^\s@<>]+',entry.get(k,'')) for k in ('from','to')):raise ValueError('Invalid email address')
        return entry
    url=entry['url'];parsed=urlsplit(url)
    if parsed.scheme!='https' or parsed.username or parsed.password or parsed.fragment or url not in data['allowed_urls']:raise ValueError('Unapproved destination')
    if entry.get('format','webhook') not in ('webhook','slack'):raise ValueError('Unsupported destination format')
    return entry


def send_notification_email(target,payload):
    message=EmailMessage();message['From']=target['from'];message['To']=target['to']
    message['Subject']='SoloAI: '+payload['event'].replace('_',' ')
    message['Message-ID']='<'+payload['event_id']+'@soloai.notification>'
    message.set_content(payload['message']+'\nEvent ID: '+payload['event_id'])
    with smtplib.SMTP_SSL(target['host'],int(target.get('port',465)),timeout=10) as smtp:
        if target.get('username'):smtp.login(target['username'],target['password'])
        smtp.send_message(message)


async def notify_one(store):
    now=int(time.time());owner=secrets.token_hex(16)
    with store.transaction() as c:
        # Alert receivers must deduplicate the stable event_id; retries can duplicate notifications.
        c.execute(update(alerts).where(alerts.c.status=='SENDING',alerts.c.available<=now).values(status='PENDING'))
        row=c.execute(select(alerts).where(alerts.c.status=='PENDING',alerts.c.available<=now,alerts.c.attempts<3).order_by(alerts.c.available).limit(1)).mappings().first()
        if not row:return False
        claimed=c.execute(update(alerts).where(alerts.c.id==row['id'],alerts.c.status=='PENDING').values(status='SENDING',owner=owner,available=now+60,attempts=alerts.c.attempts+1)).rowcount
    if not claimed:return False
    status='FAILED';delay=60*2**row['attempts']
    try:
        with store.engine.connect() as c:
            active=any(i['kind']==row['kind'] and i['subject_id']==row['subject_id'] for i in issues(c,row['tenant']))
        target=destination(row['tenant']) if active else None
        if not active:status='RESOLVED'
        elif not target:status='UNCONFIGURED';delay=300
        else:
            payload={'event_id':row['id'],'event':row['kind'],'message':'SoloAI needs your attention. Open Support Inbox to review.'}
            if target.get('format')=='email':
                await asyncio.to_thread(send_notification_email,target,payload)
                status='DELIVERED'
            elif target.get('format')=='slack':payload={'text':payload['message']+' Event: '+row['kind']+' ('+row['id'][:12]+')'}
            if target.get('format')!='email':
                async with httpx.AsyncClient(timeout=10,follow_redirects=False,trust_env=False) as client:
                    r=await client.post(target['url'],json=payload,headers={'Idempotency-Key':row['id']})
                status='DELIVERED' if 200<=r.status_code<300 else 'PENDING'
    except Exception:status='PENDING'
    if status=='PENDING' and row['attempts']>=2:status='FAILED'
    with store.transaction(row['tenant']) as c:
        c.execute(update(alerts).where(alerts.c.id==row['id'],alerts.c.owner==owner).values(status=status,available=now+delay,owner=None))
    return True


def router(get_store,tenant):
    routes=APIRouter(prefix='/api/support')
    @routes.get('/health')
    def health(t=Depends(tenant)):
        with get_store().engine.connect() as c:
            active=[{k:v for k,v in item.items() if k!='tenant'} for item in issues(c,t)]
            outbox=c.execute(select(alerts.c.status,func.count()).where(alerts.c.tenant==t).group_by(alerts.c.status)).all()
        return {'issues':active,'notifications':dict(outbox),'note':'Metadata only. A healthy API does not prove the worker is running.'}
    return routes
