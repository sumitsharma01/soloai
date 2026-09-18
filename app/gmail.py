"""Read-only Gmail OAuth and incremental intake. No sending, labels, or mailbox writes."""
import asyncio
import base64
import hashlib
import hmac
import json
import os
import secrets
import time
from pathlib import Path
from urllib.parse import urlencode
from html.parser import HTMLParser
import httpx
from cryptography.fernet import Fernet
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import Table, Column, String, Text, BigInteger, select, update, delete
from sqlalchemy.exc import IntegrityError
from app.email_schema import metadata, versions
from app.email_store import EmailStore
from app.email_tools import EmailFailure

SCOPE = 'https://www.googleapis.com/auth/gmail.readonly'
BASE = 'https://gmail.googleapis.com/gmail/v1/users/me'
connections = Table('gmail_connections', metadata,
    Column('tenant', String(64), primary_key=True),
    Column('email', String(254), nullable=False, unique=True),
    Column('refresh_token', Text, nullable=False),
    Column('history_id', String(64), nullable=False),
    Column('page_token', Text), Column('owner', String(64)),
    Column('next_sync', BigInteger, nullable=False), Column('last_sync', BigInteger),
    Column('error', String(64)), Column('created', BigInteger, nullable=False))
states = Table('gmail_oauth_states', metadata,
    Column('state', String(64), primary_key=True), Column('tenant', String(64), nullable=False),
    Column('session', String(64), nullable=False), Column('binding', String(64), nullable=False),
    Column('verifier', Text, nullable=False), Column('email', String(254), nullable=False),
    Column('expires', BigInteger, nullable=False))


def migrate(c):
    if not c.execute(select(versions.c.version).where(versions.c.version==2)).first():
        for table in (connections, states): table.create(c)
        c.execute(versions.insert().values(version=2))


def digest(value): return hashlib.sha256(value.encode()).hexdigest()


def settings():
    try:
        data = json.loads(Path(os.environ['GMAIL_CLIENT_FILE']).read_text())['web']
        callback = os.environ['PUBLIC_ORIGIN'].rstrip('/') + '/api/integrations/gmail/callback'
        if callback not in data['redirect_uris']: raise ValueError()
        cipher = Fernet(Path(os.environ['GMAIL_TOKEN_KEY_FILE']).read_bytes().strip())
        return data, callback, cipher
    except (KeyError, ValueError, OSError):
        raise HTTPException(503, 'Gmail server configuration is unavailable') from None


def seal(cipher, tenant, token):
    return cipher.encrypt(json.dumps({'tenant':tenant,'token':token}).encode()).decode()


def unseal(cipher, tenant, encrypted):
    data = json.loads(cipher.decrypt(encrypted.encode()))
    if data['tenant'] != tenant: raise EmailFailure('gmail_tenant_mismatch')
    return data['token']


async def google_json(client, method, url, **kwargs):
    response = await client.request(method, url, **kwargs)
    if response.status_code != 200:
        code = {400:'gmail_reconnect_required',401:'gmail_reconnect_required',403:'gmail_access_denied',
                404:'gmail_history_expired',429:'gmail_rate_limited'}.get(response.status_code,'gmail_unavailable')
        raise EmailFailure(code)
    return response.json()


class ConnectInput(BaseModel):
    model_config = ConfigDict(extra='forbid',strict=True)
    email: str = Field(max_length=254,pattern=r'^[^\s@]+@gmail\.com$')


def router(get_engine, tenant_dependency, enabled):
    routes = APIRouter(prefix='/api/integrations/gmail')

    @routes.get('')
    def status(t=Depends(tenant_dependency)):
        engine = get_engine()
        if not enabled(): return {'available':False,'connected':False}
        try: settings(); available=True
        except HTTPException: available=False
        with engine.connect() as c:
            row = c.execute(select(connections.c.email,connections.c.last_sync,connections.c.error)
                            .where(connections.c.tenant==t)).mappings().first()
        return {'available':available,'connected':row is not None,**(dict(row) if row else {})}

    @routes.post('/connect')
    def connect(body:ConnectInput, request:Request, t=Depends(tenant_dependency)):
        store = EmailStore(get_engine())
        if not enabled(): raise HTTPException(409,'Enable email workflows first')
        config, callback, cipher = settings()
        state,binding,verifier = (secrets.token_urlsafe(32) for _ in range(3))
        with store.transaction(t) as c:
            c.execute(delete(states).where(states.c.tenant==t))
            c.execute(states.insert().values(state=digest(state),tenant=t,
                session=digest(request.cookies.get('session','')),binding=digest(binding),
                verifier=seal(cipher,t,verifier),email=body.email.lower(),expires=int(time.time())+600))
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip('=')
        url = 'https://accounts.google.com/o/oauth2/v2/auth?' + urlencode({
            'client_id':config['client_id'],'redirect_uri':callback,'response_type':'code',
            'scope':SCOPE,'state':state,'access_type':'offline','prompt':'consent',
            'login_hint':body.email.lower(),'code_challenge':challenge,'code_challenge_method':'S256'})
        from fastapi.responses import JSONResponse
        result = JSONResponse({'url':url})
        # Separate short-lived binding survives Google's top-level callback without
        # weakening the application's Strict session cookie.
        result.set_cookie('gmail_oauth',binding,httponly=True,secure=callback.startswith('https:'),
                          samesite='lax',max_age=600,path='/api/integrations/gmail')
        return result

    @routes.get('/callback')
    async def callback(request:Request):
        store = EmailStore(get_engine())
        if not enabled(): raise HTTPException(409,'Email workflows are disabled')
        config, redirect, cipher = settings()
        state = request.query_params.get('state','')
        from sqlalchemy import text
        with store.transaction() as c:
            row = c.execute(select(states).where(states.c.state==digest(state),states.c.expires>int(time.time()))).mappings().first()
            if not row or not hmac.compare_digest(row['binding'],digest(request.cookies.get('gmail_oauth',''))):
                raise HTTPException(400,'Invalid or expired Gmail connection request')
            if not c.execute(text('SELECT token FROM sessions WHERE token=:s AND tenant=:t AND expires>:n'),
                {'s':row['session'],'t':row['tenant'],'n':int(time.time())}).first():
                raise HTTPException(401,'Sign in again before connecting Gmail')
            consumed = c.execute(delete(states).where(states.c.state==digest(state))).rowcount
            if not consumed: raise HTTPException(400,'Gmail connection request already used')
        if request.query_params.get('error'):
            return RedirectResponse('/?gmail=cancelled',status_code=303)
        code=request.query_params.get('code')
        if not code: raise HTTPException(400,'Google did not return an authorization code')
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                tokens = await google_json(client,'POST','https://oauth2.googleapis.com/token',data={
                    'client_id':config['client_id'],'client_secret':config['client_secret'],
                    'code':code,'grant_type':'authorization_code','redirect_uri':redirect,
                    'code_verifier':unseal(cipher,row['tenant'],row['verifier'])})
                if set(tokens.get('scope','').split()) != {SCOPE} or not tokens.get('refresh_token'):
                    raise EmailFailure('gmail_readonly_consent_required')
                profile=await google_json(client,'GET',BASE+'/profile',
                    headers={'Authorization':'Bearer '+tokens['access_token']})
                if profile['emailAddress'].lower()!=row['email']:
                    raise EmailFailure('gmail_wrong_account')
            # Baseline starts now. Old inbox contents are never imported automatically.
            with store.transaction(row['tenant']) as c:
                c.execute(delete(connections).where(connections.c.tenant==row['tenant']))
                c.execute(connections.insert().values(tenant=row['tenant'],email=row['email'],
                    refresh_token=seal(cipher,row['tenant'],tokens['refresh_token']),
                    history_id=profile['historyId'],next_sync=int(time.time())+60,created=int(time.time())))
                store.audit(c,row['tenant'],'gmail.connected')
        except EmailFailure as exc: raise HTTPException(400,exc.code) from None
        except IntegrityError: raise HTTPException(409,'This mailbox is already connected to another workspace') from None
        except Exception: raise HTTPException(503,'Gmail connection failed; try connecting again') from None
        result=RedirectResponse('/?gmail=connected',status_code=303)
        result.delete_cookie('gmail_oauth',path='/api/integrations/gmail')
        return result

    @routes.post('/disconnect')
    def disconnect(t=Depends(tenant_dependency)):
        store = EmailStore(get_engine())
        with store.transaction(t) as c:
            c.execute(delete(connections).where(connections.c.tenant==t))
            c.execute(delete(states).where(states.c.tenant==t))
            store.audit(c,t,'gmail.disconnected')
        return {'connected':False}
    return routes


class PlainHTML(HTMLParser):
    def __init__(self): super().__init__(); self.parts=[]; self.hidden=0
    def handle_starttag(self,tag,attrs):
        if tag in ('script','style'): self.hidden+=1
    def handle_endtag(self,tag):
        if tag in ('script','style'): self.hidden=max(0,self.hidden-1)
    def handle_data(self,data):
        if not self.hidden: self.parts.append(data)


def message_text(message):
    payload=message.get('payload',{})
    headers={h['name'].lower():h['value'] for h in payload.get('headers',[]) if h['name'].lower() in ('from','subject')}
    plain,html=[],[]
    def visit(part,depth=0):
        if depth>12 or part.get('filename'): return
        data=part.get('body',{}).get('data','')
        if data and len(data)<100000 and part.get('mimeType') in ('text/plain','text/html'):
            decoded=base64.urlsafe_b64decode(data+'='*(-len(data)%4)).decode('utf-8',errors='replace')
            (plain if part['mimeType']=='text/plain' else html).append(decoded)
        for child in part.get('parts',[])[:30]: visit(child,depth+1)
    visit(payload)
    body='\n'.join(plain)
    if not body and html:
        parser=PlainHTML();parser.feed('\n'.join(html));body=' '.join(parser.parts)
    if not body.strip(): raise EmailFailure('gmail_no_supported_body')
    result=f"From: {headers.get('from','Unknown')}\nSubject: {headers.get('subject','')}\n\n{body}"
    if len(result)>8000: raise EmailFailure('gmail_message_too_large')
    return result


async def sync_one(store):
    if not os.getenv('GMAIL_CLIENT_FILE'): return
    now=int(time.time())
    with store.engine.connect() as c:
        row=c.execute(select(connections).where(connections.c.next_sync<=now,
            connections.c.error.not_in(['gmail_history_expired','gmail_reconnect_required','gmail_access_denied']) |
            connections.c.error.is_(None)).order_by(connections.c.next_sync).limit(1)).mappings().first()
    if not row: return
    owner=secrets.token_hex(16)
    with store.transaction(row['tenant']) as c:
        from sqlalchemy import text
        active=c.execute(text("SELECT enabled FROM agents WHERE tenant=:t AND id='email-support'"),
                         {'t':row['tenant']}).scalar_one()
        if not active:
            c.execute(update(connections).where(connections.c.tenant==row['tenant'])
                .values(next_sync=now+60,error='email_agent_disabled'))
            return
        claimed=c.execute(update(connections).where(connections.c.tenant==row['tenant'],
            connections.c.next_sync<=now).values(owner=owner,next_sync=now+120)).rowcount
    if not claimed: return
    fence=(connections.c.tenant==row['tenant'],connections.c.owner==owner)
    try:
        async with asyncio.timeout(50):
            config,_,cipher=settings()
            async with httpx.AsyncClient(timeout=12) as client:
                tokens=await google_json(client,'POST','https://oauth2.googleapis.com/token',data={
                    'client_id':config['client_id'],'client_secret':config['client_secret'],
                    'grant_type':'refresh_token','refresh_token':unseal(cipher,row['tenant'],row['refresh_token'])})
                headers={'Authorization':'Bearer '+tokens['access_token']}
                params={'startHistoryId':row['history_id'],'historyTypes':'messageAdded','maxResults':10}
                if row['page_token']: params['pageToken']=row['page_token']
                history=await google_json(client,'GET',BASE+'/history',headers=headers,params=params)
                ids=list(dict.fromkeys(m['message']['id'] for h in history.get('history',[])
                    for m in h.get('messagesAdded',[])))
                from app.main import IncomingEvent
                from app.email_runtime import configuration
                for message_id in ids:
                    if not isinstance(message_id,str) or not all(ch in '0123456789abcdef' for ch in message_id):
                        raise EmailFailure('gmail_invalid_message')
                    try:
                        message=await google_json(client,'GET',BASE+'/messages/'+message_id,
                                                 headers=headers,params={'format':'full'})
                    except EmailFailure as exc:
                        if exc.code != 'gmail_history_expired': raise
                        with store.transaction(row['tenant']) as c: store.audit(c,row['tenant'],'gmail.message_removed')
                        continue
                    labels=set(message.get('labelIds',[]))
                    if 'INBOX' not in labels or labels & {'SENT','DRAFT','SPAM','TRASH'}: continue
                    try: content=message_text(message)
                    except EmailFailure as exc:
                        with store.transaction(row['tenant']) as c: store.audit(c,row['tenant'],exc.code)
                        continue
                    event=IncomingEvent(id='gmail:'+digest(row['email'])[:24]+':'+message_id,
                                        type='email.received',content=content)
                    retention=max(1,min(int(os.getenv('SOLOAI_EMAIL_RETENTION_HOURS','168')),720))*3600
                    store.enqueue(row['tenant'],event,configuration(),retention,mailbox_owner=owner)
                with store.transaction(row['tenant']) as c:
                    changes={'next_sync':int(time.time())+60,'last_sync':int(time.time()),'error':None,'owner':None}
                    if history.get('nextPageToken'): changes['page_token']=history['nextPageToken']
                    else: changes.update(history_id=history['historyId'],page_token=None)
                    c.execute(update(connections).where(*fence).values(**changes))
    except Exception as exc:
        error=exc.code if isinstance(exc,EmailFailure) else 'gmail_sync_unavailable'
        if isinstance(exc,HTTPException) and exc.status_code==409: error='email_agent_disabled'
        with store.transaction(row['tenant']) as c:
            c.execute(update(connections).where(*fence).values(error=error,owner=None,next_sync=int(time.time())+60))
            store.audit(c,row['tenant'],'gmail.sync_failed.'+error)
