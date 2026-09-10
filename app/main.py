"""SoloAI: shared compute, tenant-scoped configuration, transient content."""
import hashlib, hmac, json, os, secrets, time
from pathlib import Path
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, HTTPException, Depends
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlalchemy import create_engine, text
import httpx
from starlette.concurrency import run_in_threadpool
from app import foundry
from app.telemetry import emit, RequestTelemetry

PROD = os.getenv('SOLOAI_ENV') == 'production'
DATABASE = os.getenv('DATABASE_URL', 'sqlite:///./soloai.db')
if PROD and (not DATABASE.startswith('postgresql') or not (os.getenv('AZURE_OPENAI_ENDPOINT') or os.getenv('AZURE_FOUNDRY_PROJECT_ENDPOINT'))):
    raise RuntimeError('Production requires PostgreSQL and Azure Foundry configuration')
engine = create_engine(DATABASE, pool_pre_ping=True, **({'connect_args': {'check_same_thread': False}} if DATABASE.startswith('sqlite') else {}))
from app.packages import PACKAGES

def digest(s): return hashlib.sha256(s.encode()).hexdigest()
def password_hash(password, salt): return hashlib.pbkdf2_hmac('sha256', password.encode(), salt.encode(), 600000).hex()
def init_db():
    with engine.begin() as c:
        for sql in [
          'CREATE TABLE IF NOT EXISTS tenants (id TEXT PRIMARY KEY, email TEXT UNIQUE NOT NULL, salt TEXT NOT NULL, password TEXT NOT NULL, name TEXT NOT NULL, used INTEGER NOT NULL DEFAULT 0, budget INTEGER NOT NULL DEFAULT 10000, "window" BIGINT NOT NULL DEFAULT 0, requests INTEGER NOT NULL DEFAULT 0, stopped INTEGER NOT NULL DEFAULT 0)',
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
    yield
app = FastAPI(title='SoloAI', lifespan=lifespan, docs_url=None if PROD else '/docs', redoc_url=None)
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
    return {'workspace':workspace,'agents':agents,'executions':runs,'audit':logs,'estimated_cost_usd':round(workspace['used']*float(os.getenv('ESTIMATED_USD_PER_MILLION_TOKENS','0'))/1000000,6) if os.getenv('ESTIMATED_USD_PER_MILLION_TOKENS') else None,'mode':'Live Foundry agent • '+os.getenv('AZURE_FOUNDRY_AGENT_NAME','') if os.getenv('AZURE_FOUNDRY_PROJECT_ENDPOINT') else 'Azure Foundry' if os.getenv('AZURE_OPENAI_ENDPOINT') else 'Local demo • simulated replies'}
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
    type: str
    content: str = Field(min_length=1,max_length=8000)
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
        emit('agent.execution',status=status,agent=a,latency_ms=round((time.monotonic()-start)*1000),provider_ms=provider_ms,tokens=used,usage_kind=usage_kind,allowance_percent=round(allowance,2))
    if status!='completed': raise HTTPException(503,'Execution '+status)
    return {'id':run,'agent':a,'reply':reply,'draft':a=='email-support','tokens':used,'needs_human':needs_human}
@app.post('/api/events')
async def event(b:Event,t=Depends(api_tenant)): return await execute(b,t)
@app.post('/api/try')
async def trial(b:Event,t=Depends(tenant)): return await execute(b,t)
@app.get('/health')
def health():
    with engine.connect() as c:c.execute(text('SELECT 1'))
    return {'status':'ok'}
app.mount('/static',StaticFiles(directory=Path(__file__).parent/'static'),name='static')
@app.get('/')
def index():return FileResponse(Path(__file__).parent/'static/index.html')

# Outermost user middleware includes origin and body-size rejections.
app.add_middleware(RequestTelemetry)
