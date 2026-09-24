"""SoloAI: shared compute, tenant-scoped configuration, transient content."""
import hashlib, hmac, json, os, secrets, time
from pathlib import Path
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, HTTPException, Depends
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, ConfigDict
from sqlalchemy import create_engine, text as sql_text
from sqlalchemy.pool import NullPool
from sqlalchemy.exc import SQLAlchemyError
from app.sqlserver import statement
import httpx
from starlette.concurrency import run_in_threadpool
from app import foundry
from app.telemetry import emit, RequestTelemetry

PROD = os.getenv('SOLOAI_ENV') == 'production'
DATABASE = os.getenv('DATABASE_URL', 'sqlite:///./soloai.db')
if PROD and (not DATABASE.startswith(('postgresql','mssql+pyodbc')) or not (os.getenv('AZURE_OPENAI_ENDPOINT') or os.getenv('AZURE_FOUNDRY_PROJECT_ENDPOINT'))):
    raise RuntimeError('Production requires PostgreSQL or Azure SQL and Azure Foundry configuration')
IS_SQLSERVER=DATABASE.startswith('mssql')
if IS_SQLSERVER:
    import pyodbc
    pyodbc.pooling=False
def text(sql): return sql_text(statement(sql) if IS_SQLSERVER else sql)
engine = create_engine(DATABASE, pool_pre_ping=True, hide_parameters=True,
    **({'poolclass':NullPool} if IS_SQLSERVER else {}),
    **({'connect_args': {'check_same_thread': False}} if DATABASE.startswith('sqlite') else
       {'connect_args': {'connect_timeout':5, 'options':'-c statement_timeout=5000 -c lock_timeout=5000'}} if DATABASE.startswith('postgresql') else {}))
from app.packages import PACKAGES

def digest(s): return hashlib.sha256(s.encode()).hexdigest()
def email_enabled(): return os.getenv('SOLOAI_EMAIL_WORKFLOWS', 'false').lower() == 'true'
def password_hash(password, salt): return hashlib.pbkdf2_hmac('sha256', password.encode(), salt.encode(), 600000).hex()
def init_db():
    with engine.begin() as c:
        for sql in [
          'CREATE TABLE IF NOT EXISTS tenants (id TEXT PRIMARY KEY, email TEXT UNIQUE NOT NULL, salt TEXT NOT NULL, password TEXT NOT NULL, name TEXT NOT NULL, used INTEGER NOT NULL DEFAULT 0, budget INTEGER NOT NULL DEFAULT 10000, "window" BIGINT NOT NULL DEFAULT 0, requests INTEGER NOT NULL DEFAULT 0, stopped INTEGER NOT NULL DEFAULT 0)',
          'CREATE TABLE IF NOT EXISTS supabase_setups (tenant TEXT PRIMARY KEY REFERENCES tenants(id), configuration TEXT NOT NULL)',
          'CREATE TABLE IF NOT EXISTS sessions (token TEXT PRIMARY KEY, tenant TEXT NOT NULL REFERENCES tenants(id), expires BIGINT NOT NULL)',
          'CREATE TABLE IF NOT EXISTS api_keys (token TEXT PRIMARY KEY, tenant TEXT NOT NULL REFERENCES tenants(id))',
          'CREATE TABLE IF NOT EXISTS agents (tenant TEXT NOT NULL REFERENCES tenants(id), id TEXT NOT NULL, enabled INTEGER NOT NULL DEFAULT 0, guidance TEXT NOT NULL DEFAULT \'\', PRIMARY KEY (tenant,id))',
          'CREATE TABLE IF NOT EXISTS executions (id TEXT PRIMARY KEY, tenant TEXT NOT NULL REFERENCES tenants(id), agent TEXT NOT NULL, status TEXT NOT NULL, tokens INTEGER NOT NULL, latency INTEGER NOT NULL, created BIGINT NOT NULL)',
          'CREATE TABLE IF NOT EXISTS audit (id TEXT PRIMARY KEY, tenant TEXT NOT NULL REFERENCES tenants(id), action TEXT NOT NULL, created BIGINT NOT NULL)',
          'CREATE TABLE IF NOT EXISTS auth_limits (key TEXT PRIMARY KEY, count INTEGER NOT NULL)',
          'CREATE INDEX IF NOT EXISTS executions_tenant_created ON executions(tenant,created)',
          'CREATE INDEX IF NOT EXISTS audit_tenant_created ON audit(tenant,created)'
        ]: c.execute(text(sql))
@asynccontextmanager
async def lifespan(app):
    if os.getenv('SOLOAI_INIT_SCHEMA','true').lower()=='true': init_db()
    if email_enabled():
        if engine.dialect.name not in ('postgresql','sqlite') or (PROD and engine.dialect.name != 'postgresql'):
            raise RuntimeError('Production email workflows require PostgreSQL')
        if not PROD and os.getenv('SOLOAI_INIT_SCHEMA','true').lower() == 'true':
            from app.email_schema import migrate
            migrate(engine)
        from app.email_schema import versions
        with engine.connect() as c:
            if c.execute(versions.select().where(versions.c.version==1)).first() is None:
                raise RuntimeError('Run python -m scripts.email_admin migrate before enabling email workflows')
    metrics_server=None
    if os.getenv('SOLOAI_METRICS_PORT'):
        from app.metrics import start
        metrics_server,_=start(int(os.environ['SOLOAI_METRICS_PORT']))
    try:
        yield
    finally:
        if metrics_server:
            metrics_server.shutdown()
            metrics_server.server_close()
app = FastAPI(title='SoloAI', lifespan=lifespan, docs_url=None if PROD else '/docs', redoc_url=None)

@app.exception_handler(SQLAlchemyError)
async def database_failure(request, exc):
    # SQL exceptions can embed customer values. Never include exception text in
    # responses or let the server print the original traceback with bound parameters.
    emit('database.unavailable', status='failed')
    return JSONResponse({'detail':'Database temporarily unavailable'},503)
@app.middleware('http')
async def safeguards(request, call_next):
    if request.method in ('POST','PATCH','DELETE'):
        if request.headers.get('origin') and request.headers['origin'] != os.getenv('PUBLIC_ORIGIN', 'http://127.0.0.1:8000'):
            return JSONResponse({'detail':'Origin not allowed'},403)
        chunks=[]; total=0
        async for chunk in request.stream():
            total+=len(chunk)
            if total>24000: return JSONResponse({'detail':'Request too large'},413)
            chunks.append(chunk)
        request._body=b''.join(chunks)
    response = await call_next(request)
    response.headers.update({'X-Content-Type-Options':'nosniff','Referrer-Policy':'no-referrer','Content-Security-Policy':"default-src 'self'; style-src 'self'; script-src 'self'; frame-ancestors 'none'; base-uri 'none'",'Cache-Control':'no-store'})
    if PROD: response.headers['Strict-Transport-Security']='max-age=31536000; includeSubDomains'
    return response

def tenant(request: Request):
    token = request.cookies.get('session','')
    with engine.connect() as c:
        row = c.execute(text('SELECT tenant FROM sessions WHERE token=:token AND expires>:now'), {'token':digest(token),'now':int(time.time())}).first()
    if not row: raise HTTPException(401,'Please sign in')
    return row[0]
def api_tenant(request: Request):
    token = request.headers.get('authorization','').removeprefix('Bearer ')
    with engine.connect() as c: row = c.execute(text('SELECT tenant FROM api_keys WHERE token=:token'),{'token':digest(token)}).first()
    if not row: raise HTTPException(401,'Invalid application key')
    return row[0]
def audit(c,t,action): c.execute(text('INSERT INTO audit VALUES (:id,:t,:action,:now)'),{'id':secrets.token_hex(16),'t':t,'action':action,'now':int(time.time())})
class Credentials(BaseModel):
    email: str = Field(min_length=3,max_length=254,pattern=r'^[^\s@]+@[^\s@]+\.[^\s@]+$')
    password: str = Field(min_length=12,max_length=128)
    name: str = Field(default='My workspace',min_length=1,max_length=80)
def auth_limit(request):
    # Shared database limiter; never trust client-supplied forwarding headers.
    key = str(int(time.time())//3600)+':'+digest(request.client.host if request.client else 'unknown')
    with engine.begin() as c:
        c.execute(text('INSERT INTO auth_limits (key,count) VALUES (:key,0) ON CONFLICT (key) DO NOTHING'),{'key':key})
        updated=c.execute(text('UPDATE auth_limits SET count=count+1 WHERE key=:key AND count<30'),{'key':key}).rowcount
    if not updated: raise HTTPException(429,'Too many sign-in attempts; try again later')
@app.post('/api/auth/{action}')
def authenticate(action: str, body: Credentials, request: Request):
    auth_limit(request)
    email=body.email.lower().strip()
    with engine.begin() as c:
        row=c.execute(text('SELECT * FROM tenants WHERE email=:email'),{'email':email}).mappings().first()
        if action=='register':
            if row: raise HTTPException(409,'Account unavailable; try signing in')
            t,salt=secrets.token_hex(16),secrets.token_hex(16)
            c.execute(text('INSERT INTO tenants (id,email,salt,password,name) VALUES (:id,:email,:salt,:password,:name)'),{'id':t,'email':email,'salt':salt,'password':password_hash(body.password,salt),'name':body.name})
            for a in PACKAGES: c.execute(text('INSERT INTO agents (tenant,id) VALUES (:t,:a)'),{'t':t,'a':a})
            audit(c,t,'workspace.created')
        elif action=='login':
            valid=hmac.compare_digest(password_hash(body.password,row['salt'] if row else 'missing'), row['password'] if row else '0'*64)
            if not row or not valid: raise HTTPException(401,'Email or password is incorrect')
            t=row['id']
        else: raise HTTPException(404)
        token=secrets.token_urlsafe(32)
        c.execute(text('INSERT INTO sessions VALUES (:token,:tenant,:expires)'),{'token':digest(token),'tenant':t,'expires':int(time.time())+86400})
    response=JSONResponse({'ok':True})
    response.set_cookie('session',token,httponly=True,secure=PROD,samesite='strict',max_age=86400)
    return response
@app.post('/api/logout')
def logout(request: Request,t=Depends(tenant)):
    with engine.begin() as c: c.execute(text('DELETE FROM sessions WHERE token=:token AND tenant=:t'),{'token':digest(request.cookies.get('session','')),'t':t})
    r=JSONResponse({'ok':True});r.delete_cookie('session');return r
@app.get('/api/dashboard')
def dashboard(t=Depends(tenant)):
    with engine.connect() as c:
        workspace=dict(c.execute(text('SELECT name,used,budget,stopped FROM tenants WHERE id=:t'),{'t':t}).mappings().one())
        agents=[dict(r)|PACKAGES[r['id']] for r in c.execute(text('SELECT id,enabled,guidance FROM agents WHERE tenant=:t ORDER BY id DESC'),{'t':t}).mappings()]
        runs=[dict(r) for r in c.execute(text('SELECT id,agent,status,tokens,latency,created FROM executions WHERE tenant=:t ORDER BY created DESC LIMIT 30'),{'t':t}).mappings()]
        logs=[dict(r) for r in c.execute(text('SELECT action,created FROM audit WHERE tenant=:t ORDER BY created DESC LIMIT 20'),{'t':t}).mappings()]
    return {'workspace':workspace,'agents':agents,'executions':runs,'audit':logs,'email_workflows':email_enabled(),'estimated_cost_usd':round(workspace['used']*float(os.getenv('ESTIMATED_USD_PER_MILLION_TOKENS','0'))/1000000,6) if os.getenv('ESTIMATED_USD_PER_MILLION_TOKENS') else None,'mode':'Live Foundry agent • '+os.getenv('AZURE_FOUNDRY_AGENT_NAME','') if os.getenv('AZURE_FOUNDRY_PROJECT_ENDPOINT') else 'Azure Foundry' if os.getenv('AZURE_OPENAI_ENDPOINT') else 'Local demo • simulated replies'}
class Config(BaseModel):
    enabled: bool
    guidance: str = Field(default='',max_length=4000)
@app.patch('/api/agents/{agent}')
def configure(agent: str,b:Config,t=Depends(tenant)):
    if agent not in PACKAGES: raise HTTPException(404)
    with engine.begin() as c:
        c.execute(text('UPDATE agents SET enabled=:enabled,guidance=:guidance WHERE tenant=:t AND id=:a'),{'enabled':int(b.enabled),'guidance':b.guidance,'t':t,'a':agent})
        audit(c,t,f'{agent}.{"enabled" if b.enabled else "disabled"}')
    return {'ok':True}
@app.post('/api/keys')
def key(t=Depends(tenant)):
    token='solo_'+secrets.token_urlsafe(32)
    with engine.begin() as c:
        c.execute(text('DELETE FROM api_keys WHERE tenant=:t'),{'t':t})
        c.execute(text('INSERT INTO api_keys VALUES (:token,:t)'),{'token':digest(token),'t':t});audit(c,t,'application.key.rotated')
    return {'key':token}
@app.post('/api/stop')
def stop(t=Depends(tenant)):
    with engine.begin() as c:
        c.execute(text('UPDATE agents SET enabled=0 WHERE tenant=:t'),{'t':t})
        c.execute(text('UPDATE tenants SET stopped=stopped+1 WHERE id=:t'),{'t':t});audit(c,t,'agents.emergency_stop')
    return {'ok':True}
class Event(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    type: str
    content: str = Field(min_length=1,max_length=8000)

class IncomingEvent(Event):
    id: str | None = Field(default=None, min_length=1, max_length=128, pattern=r'^[A-Za-z0-9_.:-]+$')

def email_store():
    if not email_enabled(): raise HTTPException(409, 'Email workflows are not enabled')
    from app.email_store import EmailStore
    return EmailStore(engine)
async def execute(b,t):
    a=next((key for key,p in PACKAGES.items() if p['trigger']==b.type),None)
    if not a: raise HTTPException(400,'Unsupported event')
    start=time.monotonic();now=int(time.time());run=secrets.token_hex(16)
    with engine.begin() as c:
        cfg=c.execute(text('SELECT * FROM agents WHERE tenant=:t AND id=:a'),{'t':t,'a':a}).mappings().one()
        if not cfg['enabled']: raise HTTPException(409,'This agent is disabled')
        epoch=c.execute(text('SELECT stopped FROM tenants WHERE id=:t'),{'t':t}).scalar_one()
        # UTF-8 bytes upper-bound text tokens; add message overhead and output ceiling.
        payload=foundry.envelope(a,cfg['guidance'],b.content)
        reserve=(len((payload+foundry.INSTRUCTIONS).encode())+foundry.MAX_OUTPUT+512 if os.getenv('AZURE_FOUNDRY_PROJECT_ENDPOINT') else len((b.content+cfg['guidance']+PACKAGES[a]['instructions']).encode())+1024+256)
        c.execute(text('UPDATE tenants SET "window"=:w,requests=0 WHERE id=:t AND "window"<>:w'),{'w':now//60,'t':t})
        ok=c.execute(text('UPDATE tenants SET used=used+:r, requests=requests+1 WHERE id=:t AND used+:r<=budget AND requests<20'),{'r':reserve,'t':t}).rowcount
        if not ok: raise HTTPException(429,'Usage allowance or request limit reached')
        c.execute(text('INSERT INTO executions VALUES (:id,:t,:a,\'running\',:r,0,:now)'),{'id':run,'t':t,'a':a,'r':reserve,'now':now})
    status='completed';used=reserve;reply='';needs_human=False
    provider_start=time.monotonic();provider_ms=0;usage_kind='reserved'
    try:
        endpoint=os.getenv('AZURE_OPENAI_ENDPOINT')
        if os.getenv('AZURE_FOUNDRY_PROJECT_ENDPOINT'):
            answer,used=await run_in_threadpool(foundry.invoke,payload)
            reply=('Subject: '+answer.subject+'\n\n' if answer.subject else '')+answer.reply
            needs_human=answer.needs_human
        elif endpoint:
            from azure.identity.aio import DefaultAzureCredential
            async with DefaultAzureCredential() as cred: token=(await cred.get_token('https://cognitiveservices.azure.com/.default')).token
            async with httpx.AsyncClient(timeout=45) as client:
                response=await client.post(endpoint.rstrip('/')+'/openai/v1/chat/completions',headers={'Authorization':'Bearer '+token},json={'model':os.environ['AZURE_OPENAI_DEPLOYMENT'],'messages':[{'role':'system','content':PACKAGES[a]['instructions']+'\nBusiness guidance:\n'+cfg['guidance']},{'role':'user','content':b.content}],'max_completion_tokens':1024})
                response.raise_for_status();result=response.json()
            reply=result['choices'][0]['message']['content'];used=result.get('usage',{}).get('total_tokens',reserve)
        else:
            reply=('Subject: Your support request\n\n' if a=='email-support' else '')+'Thanks for reaching out! '+(cfg['guidance'] or 'Please contact our team for help with this request.')+'\n\n[Local demo: this is a simulated response.]'
            used=min(reserve, len(reply.encode())+len(b.content.encode()))
        provider_ms=round((time.monotonic()-provider_start)*1000)
        usage_kind='reported' if (endpoint or os.getenv('AZURE_FOUNDRY_PROJECT_ENDPOINT')) else 'simulated'
        with engine.connect() as c:
            live=c.execute(text('SELECT enabled FROM agents WHERE tenant=:t AND id=:a'),{'t':t,'a':a}).scalar_one()
            current=c.execute(text('SELECT stopped FROM tenants WHERE id=:t'),{'t':t}).scalar_one()
        if not live or current!=epoch: status='stopped';reply=''
    except Exception:
        provider_ms=round((time.monotonic()-provider_start)*1000)
        status='failed' # No prompts, provider errors or response content enter logs.
    finally:
        with engine.begin() as c:
            c.execute(text('UPDATE tenants SET used=used+:adjustment WHERE id=:t'),{'adjustment':used-reserve,'t':t})
            c.execute(text('UPDATE executions SET status=:s,tokens=:u,latency=:ms WHERE id=:id AND tenant=:t'),{'s':status,'u':used,'ms':int((time.monotonic()-start)*1000),'id':run,'t':t})
            allowance=c.execute(text('SELECT used*100.0/budget FROM tenants WHERE id=:t'),{'t':t}).scalar_one()
        emit('agent.execution',agent_version=os.getenv('AZURE_FOUNDRY_AGENT_VERSION','direct-model'),model=os.getenv('AZURE_FOUNDRY_MODEL',os.getenv('AZURE_OPENAI_DEPLOYMENT','simulated')),instructions_sha256=digest(foundry.INSTRUCTIONS if os.getenv('AZURE_FOUNDRY_PROJECT_ENDPOINT') else PACKAGES[a]['instructions']),needs_human=needs_human if status=='completed' else None,status=status,agent=a,latency_ms=round((time.monotonic()-start)*1000),provider_ms=provider_ms,tokens=used,usage_kind=usage_kind,allowance_percent=round(allowance,2))
    if status!='completed': raise HTTPException(503,'Execution '+status)
    return {'id':run,'agent':a,'reply':reply,'draft':a=='email-support','tokens':used,'needs_human':needs_human}
@app.post('/api/events')
async def event(b:IncomingEvent,t=Depends(api_tenant)):
    if b.type == 'email.received' and b.id is not None and not email_enabled():
        raise HTTPException(409, 'Email workflows are not enabled')
    if b.type == 'email.received' and email_enabled():
        if b.id is None: raise HTTPException(422, 'Email event id is required')
        from app.email_runtime import configuration
        from app.email_tools import EmailFailure
        try:
            retention = max(3600, min(int(os.getenv('SOLOAI_EMAIL_RETENTION_HOURS','168')),720)*3600)
            result = email_store().enqueue(t, b, configuration(), retention)
        except EmailFailure as exc:
            raise HTTPException(429 if exc.code in ('token_allowance_exhausted','rate_limit_exceeded') else 503, exc.code) from None
        return JSONResponse(result, status_code=200 if result['duplicate'] else 202,
                            headers={'Location':'/api/executions/' + result['execution_id']})
    return await execute(b,t)

def execution_reader(request: Request):
    # A customer server can poll using the same key as ingestion. Review requires
    # the operator's session and is never authorized by an application API key.
    return api_tenant(request) if request.headers.get('authorization') else tenant(request)

@app.get('/api/executions/{execution_id}')
def email_execution(execution_id: str, t=Depends(execution_reader)):
    return email_store().detail(t, execution_id)

@app.get('/api/email/executions')
def email_executions(t=Depends(tenant)):
    from app.email_schema import jobs
    from sqlalchemy import select
    email_store()
    with engine.connect() as c:
        rows = c.execute(select(jobs.c.execution_id,jobs.c.status,jobs.c.created_at,jobs.c.error)
            .where(jobs.c.tenant==t).order_by(jobs.c.created_at.desc()).limit(50)).mappings().all()
    return {'executions':[dict(row) for row in rows]}

@app.post('/api/executions/{execution_id}/approve')
def approve_email(execution_id: str,t=Depends(tenant)):
    return email_store().review(t,execution_id,'APPROVED')

@app.post('/api/executions/{execution_id}/reject')
def reject_email(execution_id: str,t=Depends(tenant)):
    return email_store().review(t,execution_id,'REJECTED')
@app.post('/api/try')
async def trial(b:Event,t=Depends(tenant)): return await execute(b,t)
@app.get('/live')
def live(): return {'status':'alive'}

@app.get('/health')
def health():
    with engine.connect() as c:c.execute(text('SELECT 1'))
    return {'status':'ok'}
app.mount('/static',StaticFiles(directory=Path(__file__).parent/'static'),name='static')
@app.get('/')
def index():return FileResponse(Path(__file__).parent/'static/index.html')

# Outermost user middleware includes origin and body-size rejections.
app.add_middleware(RequestTelemetry)

from app.gmail import router as gmail_router
app.include_router(gmail_router(lambda: engine, tenant, email_enabled))

@app.get('/api/evaluations')
def evaluations(t=Depends(tenant)):
    # Shared synthetic package evaluation only, never another tenant's executions.
    path=Path(__file__).resolve().parents[1]/'evals/latest.json'
    if not path.exists(): return {'available':False}
    report=json.loads(path.read_text())
    report['available']=True
    report['matches_current_agent']=(report.get('instructions_sha256')==digest(foundry.INSTRUCTIONS) and report.get('model')==os.getenv('AZURE_FOUNDRY_MODEL') and report.get('version')==os.getenv('AZURE_FOUNDRY_AGENT_VERSION') and report.get('agent')==os.getenv('AZURE_FOUNDRY_AGENT_NAME'))
    return report

@app.get('/api/integrations/booking')
def booking_integration(t=Depends(tenant)):
    from app.mcp_booking import connection
    from app.email_tools import EmailFailure
    try:
        configured = connection(t) is not None
        return {'mode': 'MCP booking' if configured else 'Local support snapshot',
                'configured': configured, 'read_only': True,
                'note': 'Configuration status only. A booking lookup verifies connectivity.'}
    except EmailFailure:
        return {'mode': 'Configuration error', 'configured': False, 'read_only': True,
                'note': 'Ask the operator to check the MCP configuration. Lookups fail closed.'}

from app.supabase_setup import router as supabase_router
app.include_router(supabase_router(engine, tenant, text, audit))
