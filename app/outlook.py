"""Delegated Outlook OAuth and bounded delta polling. No application-wide mailbox permissions."""
import asyncio,base64,hashlib,hmac,json,os,secrets,time,re
from pathlib import Path
from urllib.parse import urlencode,urlsplit,quote
import httpx
from cryptography.fernet import Fernet
from fastapi import APIRouter,Depends,HTTPException,Request
from fastapi.responses import JSONResponse,RedirectResponse
from sqlalchemy import Table,Column,String,Text,BigInteger,Boolean,select,update,delete,text
from sqlalchemy.exc import IntegrityError
from app.email_schema import metadata,versions
from app.email_store import EmailStore
from app.email_tools import EmailFailure
from app.gmail import digest,seal,unseal,PlainHTML
BASE='https://graph.microsoft.com/v1.0'
DELTA=BASE+'/me/mailFolders/inbox/messages/delta'
connections=Table('outlook_connections',metadata,
    Column('tenant',String(64),primary_key=True),Column('email',String(254),nullable=False,unique=True),
    Column('refresh_token',Text,nullable=False),Column('cursor',Text),Column('baseline',Boolean,nullable=False),
    Column('can_send',Boolean,nullable=False),Column('owner',String(64)),Column('next_sync',BigInteger,nullable=False),
    Column('last_sync',BigInteger),Column('error',String(64)),Column('created',BigInteger,nullable=False))
states=Table('outlook_oauth_states',metadata,
    Column('state',String(64),primary_key=True),Column('tenant',String(64),nullable=False),
    Column('session',String(64),nullable=False),Column('binding',String(64),nullable=False),
    Column('verifier',Text,nullable=False),Column('can_send',Boolean,nullable=False),Column('expires',BigInteger,nullable=False))

def migrate(c):
    if not c.execute(select(versions.c.version).where(versions.c.version==6)).first():
        connections.create(c);states.create(c);c.execute(versions.insert().values(version=6))

def settings():
    try:
        config=json.loads(Path(os.environ['OUTLOOK_CLIENT_FILE']).read_text())
        directory=config.get('directory','common')
        if directory not in ('common','organizations','consumers') and not re.fullmatch(r'[a-fA-F0-9-]{36}',directory):raise ValueError()
        callback=os.environ['PUBLIC_ORIGIN'].rstrip('/')+'/api/integrations/outlook/callback'
        if callback not in config['redirect_uris']:raise ValueError()
        cipher=Fernet(Path(os.environ['SOLOAI_CONNECTOR_KEY_FILE']).read_bytes().strip())
        return config,callback,cipher,'https://login.microsoftonline.com/'+directory+'/oauth2/v2.0'
    except Exception:raise HTTPException(503,'Outlook server configuration is unavailable') from None

def scopes(send=False):return 'offline_access User.Read Mail.Read'+(' Mail.Send' if send else '')

def validate_scopes(tokens,send):
    actual={x.removeprefix('https://graph.microsoft.com/') for x in tokens.get('scope','').split()}
    required={'User.Read','Mail.Read'}|({'Mail.Send'} if send else set())
    if not required<=actual or actual-required-{'openid','profile','email','offline_access'}:raise EmailFailure('outlook_consent_required')

async def graph(client,method,url,**kwargs):
    r=await client.request(method,url,**kwargs)
    if r.status_code!=200:raise EmailFailure({400:'outlook_reconnect_required',401:'outlook_reconnect_required',403:'outlook_access_denied',410:'outlook_cursor_expired',429:'outlook_rate_limited'}.get(r.status_code,'outlook_unavailable'))
    if len(r.content)>1024*1024:raise EmailFailure('outlook_response_too_large')
    return r.json()

def cursor_url(value):
    p=urlsplit(value)
    if p.scheme!='https' or p.netloc!='graph.microsoft.com' or not p.path.lower().startswith('/v1.0/me/mailfolders/') or not p.path.lower().endswith('/messages/delta') or p.fragment:raise EmailFailure('outlook_invalid_cursor')
    return value

async def access_token(row,client):
    config,_,cipher,authority=settings()
    result=await graph(client,'POST',authority+'/token',data={'client_id':config['client_id'],'client_secret':config['client_secret'],'grant_type':'refresh_token','refresh_token':unseal(cipher,row['tenant'],row['refresh_token']),'scope':scopes(row['can_send'])})
    return result

def router(get_engine,tenant,enabled):
    routes=APIRouter(prefix='/api/integrations/outlook')
    from app.gmail import ConnectInput
    @routes.get('')
    def status(t=Depends(tenant)):
        if not enabled():return {'available':False,'connected':False}
        try:settings();available=True
        except HTTPException:available=False
        with get_engine().connect() as c:row=c.execute(select(connections.c.email,connections.c.last_sync,connections.c.error,connections.c.can_send,connections.c.baseline).where(connections.c.tenant==t)).mappings().first()
        return {'available':available,'connected':bool(row),**(dict(row) if row else {})}
    @routes.post('/connect')
    def connect(body:ConnectInput,request:Request,t=Depends(tenant)):
        if not enabled():raise HTTPException(409,'Enable email workflows first')
        config,callback,cipher,authority=settings();state,binding,verifier=(secrets.token_urlsafe(32) for _ in range(3))
        store=EmailStore(get_engine())
        with store.transaction(t) as c:
            c.execute(delete(states).where(states.c.tenant==t));c.execute(states.insert().values(state=digest(state),tenant=t,session=digest(request.cookies.get('session','')),binding=digest(binding),verifier=seal(cipher,t,verifier),can_send=body.allow_send,expires=int(time.time())+600))
        challenge=base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip('=')
        result=JSONResponse({'url':authority+'/authorize?'+urlencode({'client_id':config['client_id'],'redirect_uri':callback,'response_type':'code','response_mode':'query','scope':scopes(body.allow_send),'state':state,'code_challenge':challenge,'code_challenge_method':'S256','prompt':'select_account'})})
        result.set_cookie('outlook_oauth',binding,httponly=True,secure=callback.startswith('https:'),samesite='lax',max_age=600,path='/api/integrations/outlook');return result
    @routes.get('/callback')
    async def callback(request:Request):
        if not enabled():raise HTTPException(409,'Email workflows disabled')
        config,redirect,cipher,authority=settings();store=EmailStore(get_engine());state=digest(request.query_params.get('state',''))
        with store.transaction() as c:
            row=c.execute(select(states).where(states.c.state==state,states.c.expires>int(time.time()))).mappings().first()
            if not row or not hmac.compare_digest(row['binding'],digest(request.cookies.get('outlook_oauth',''))):raise HTTPException(400,'Invalid or expired Outlook connection request')
            if not c.execute(text('SELECT token FROM sessions WHERE token=:s AND tenant=:t AND expires>:n'),{'s':row['session'],'t':row['tenant'],'n':int(time.time())}).first():raise HTTPException(401,'Sign in again before connecting Outlook')
            if not c.execute(delete(states).where(states.c.state==state)).rowcount:raise HTTPException(400,'Connection request already used')
        if request.query_params.get('error'):return RedirectResponse('/?outlook=cancelled',303)
        if not request.query_params.get('code'):raise HTTPException(400,'Missing authorization code')
        try:
            async with httpx.AsyncClient(timeout=15,follow_redirects=False) as client:
                tokens=await graph(client,'POST',authority+'/token',data={'client_id':config['client_id'],'client_secret':config['client_secret'],'code':request.query_params['code'],'grant_type':'authorization_code','redirect_uri':redirect,'code_verifier':unseal(cipher,row['tenant'],row['verifier']),'scope':scopes(row['can_send'])})
                validate_scopes(tokens,row['can_send'])
                profile=await graph(client,'GET',BASE+'/me?$select=mail,userPrincipalName',headers={'Authorization':'Bearer '+tokens['access_token']})
            mailbox=(profile.get('mail') or profile.get('userPrincipalName') or '').lower()
            if not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+',mailbox):raise ValueError()
            with store.transaction(row['tenant']) as c:
                old=c.execute(select(connections).where(connections.c.tenant==row['tenant'])).mappings().first()
                same=old and old['email']==mailbox
                c.execute(delete(connections).where(connections.c.tenant==row['tenant']))
                c.execute(connections.insert().values(tenant=row['tenant'],email=mailbox,refresh_token=seal(cipher,row['tenant'],tokens['refresh_token']),cursor=old['cursor'] if same else None,baseline=old['baseline'] if same else True,can_send=row['can_send'],next_sync=int(time.time()),created=int(time.time())))
                from app.inbox_schema import settings as rules
                c.execute(update(rules).where(rules.c.tenant==row['tenant']).values(automatic=False,revision=rules.c.revision+1));store.audit(c,row['tenant'],'outlook.connected')
        except IntegrityError:raise HTTPException(409,'Mailbox already belongs to another workspace') from None
        except Exception:raise HTTPException(503,'Outlook connection failed. Check consent and try again.') from None
        result=RedirectResponse('/?outlook=connected',303);result.delete_cookie('outlook_oauth',path='/api/integrations/outlook');return result
    @routes.post('/reset-sync')
    def reset_sync(t=Depends(tenant)):
        store=EmailStore(get_engine())
        with store.transaction(t) as c:
            changed=c.execute(update(connections).where(connections.c.tenant==t,connections.c.error=='outlook_cursor_expired').values(cursor=None,baseline=True,owner=None,error=None,next_sync=int(time.time()))).rowcount
            if not changed:raise HTTPException(409,'Only an expired cursor can be reset')
            from app.inbox_schema import settings as rules
            c.execute(update(rules).where(rules.c.tenant==t).values(automatic=False,revision=rules.c.revision+1));store.audit(c,t,'outlook.baseline_reset_gap_acknowledged')
        return {'reset':True,'note':'A new baseline skips existing inbox messages. Review the missed period manually.'}
    @routes.post('/disconnect')
    def disconnect(t=Depends(tenant)):
        store=EmailStore(get_engine())
        with store.transaction(t) as c:
            c.execute(delete(connections).where(connections.c.tenant==t));c.execute(delete(states).where(states.c.tenant==t))
            from app.inbox_schema import settings as rules
            c.execute(update(rules).where(rules.c.tenant==t).values(automatic=False,revision=rules.c.revision+1));store.audit(c,t,'outlook.disconnected')
        return {'connected':False}
    return routes

async def sync_one(store):
    if not os.getenv('OUTLOOK_CLIENT_FILE'):return
    now=int(time.time());owner=secrets.token_hex(16)
    with store.engine.connect() as c:
        row=c.execute(select(connections).where(connections.c.next_sync<=now,(connections.c.error.is_(None)|connections.c.error.not_in(['outlook_reconnect_required','outlook_access_denied','outlook_cursor_expired']))).order_by(connections.c.next_sync).limit(1)).mappings().first()
    if not row:return
    with store.transaction(row['tenant']) as c:
        if not c.execute(text("SELECT enabled FROM agents WHERE tenant=:t AND id='email-support'"),{'t':row['tenant']}).scalar():
            c.execute(update(connections).where(connections.c.tenant==row['tenant']).values(next_sync=now+60,error='email_agent_disabled'));return
        if not c.execute(update(connections).where(connections.c.tenant==row['tenant'],connections.c.next_sync<=now).values(owner=owner,next_sync=now+120)).rowcount:return
    fence=(connections.c.tenant==row['tenant'],connections.c.owner==owner)
    try:
        async with asyncio.timeout(50):
            async with httpx.AsyncClient(timeout=12,follow_redirects=False) as client:
                tokens=await access_token(row,client)
                headers={'Authorization':'Bearer '+tokens['access_token'],'Prefer':'IdType="ImmutableId", outlook.body-content-type="text", odata.maxpagesize=10'}
                page=await graph(client,'GET',cursor_url(row['cursor']) if row['cursor'] else DELTA+'?changeType=created&$select=id',headers=headers)
                if not row['baseline']:
                    from app.main import IncomingEvent
                    from app.email_runtime import configuration
                    from app.email_delivery import message_source
                    for item in page.get('value',[]):
                        if '@removed' in item:continue
                        message_id=item.get('id','')
                        if not isinstance(message_id,str) or not 1<=len(message_id)<=512:raise EmailFailure('outlook_invalid_message')
                        message=await graph(client,'GET',BASE+'/me/messages/'+quote(message_id,safe='')+'?$select=from,subject,body,internetMessageHeaders,internetMessageId,isDraft',headers=headers)
                        if message.get('isDraft'):continue
                        content=message.get('body',{}).get('content','')
                        if message.get('body',{}).get('contentType','').lower()=='html':
                            parser=PlainHTML();parser.feed(content);content=' '.join(parser.parts)
                        sender=message.get('from',{}).get('emailAddress',{}).get('address','')
                        content='From: '+sender+'\nSubject: '+message.get('subject','')+'\n\n'+content
                        if not content.strip() or len(content)>8000:
                            with store.transaction(row['tenant']) as c:store.audit(c,row['tenant'],'outlook.unsupported_body')
                            continue
                        source=message_source({'threadId':digest(message_id),'payload':{'headers':message.get('internetMessageHeaders',[]) or [{'name':'From','value':sender},{'name':'Subject','value':message.get('subject','')},{'name':'Message-ID','value':message.get('internetMessageId','')}]}},row['email'])
                        if source:source['provider']='outlook'
                        event=IncomingEvent(id='outlook:'+digest(row['email']+':'+message_id),type='email.received',content=content)
                        retention=max(1,min(int(os.getenv('SOLOAI_EMAIL_RETENTION_HOURS','168')),720))*3600
                        store.enqueue(row['tenant'],event,configuration(),retention,mailbox_owner=owner,mailbox_provider='outlook',source=source)
                cursor=page.get('@odata.nextLink') or page.get('@odata.deltaLink')
                if not cursor:raise EmailFailure('outlook_invalid_cursor')
                values={'cursor':cursor_url(cursor),'baseline':row['baseline'] and bool(page.get('@odata.nextLink')),'next_sync':int(time.time())+(1 if page.get('@odata.nextLink') else 60),'last_sync':int(time.time()),'owner':None,'error':None}
                if tokens.get('refresh_token'):values['refresh_token']=seal(settings()[2],row['tenant'],tokens['refresh_token'])
                with store.transaction(row['tenant']) as c:c.execute(update(connections).where(*fence).values(**values))
    except Exception as exc:
        code=exc.code if isinstance(exc,EmailFailure) else 'outlook_sync_unavailable'
        with store.transaction(row['tenant']) as c:
            c.execute(update(connections).where(*fence).values(error=code,owner=None,next_sync=int(time.time())+300));store.audit(c,row['tenant'],'outlook.sync_failed.'+code)
