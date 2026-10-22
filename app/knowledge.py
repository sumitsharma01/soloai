"""Session-only policy management and restricted booking setup."""
import secrets,time
from fastapi import APIRouter,Depends,HTTPException
from pydantic import BaseModel,ConfigDict,Field
from sqlalchemy import select,delete,update
from app.email_schema import policies
from app.reliability_schema import connectors,identities
from app.inbox import row_for,ensure_not_sending
from app.booking_connector import cipher
from app.gmail import seal

class Input(BaseModel):model_config=ConfigDict(extra='forbid',strict=True)
class Policy(Input):
    title:str=Field(min_length=1,max_length=200,pattern=r'.*\S.*')
    content:str=Field(min_length=1,max_length=600,pattern=r'[\s\S]*\S[\s\S]*')
class Connection(Input):
    url:str=Field(pattern=r'^https://[a-z0-9]{20}\.supabase\.co/functions/v1/soloai-booking$',max_length=300)
    token:str=Field(min_length=32,max_length=256,pattern=r'^[A-Za-z0-9_-]+$')
class Identity(Input):
    customer_id:str=Field(min_length=1,max_length=100,pattern=r'^[A-Za-z0-9_-]+$')
    verified:bool

def router(get_store,tenant):
    routes=APIRouter(prefix='/api/support')
    @routes.get('/policies')
    def listing(t=Depends(tenant)):
        with get_store().engine.connect() as c:
            return {'policies':[dict(r) for r in c.execute(select(policies.c.id,policies.c.title,policies.c.content).where(policies.c.tenant==t).order_by(policies.c.id)).mappings()]}
    @routes.post('/policies')
    def add(body:Policy,t=Depends(tenant)):
        store=get_store()
        with store.transaction(t) as c:
            if len(c.execute(select(policies.c.id).where(policies.c.tenant==t).limit(50)).all())>=50:raise HTTPException(409,'Limit: 50 short policies')
            c.execute(policies.insert().values(tenant=t,id=secrets.token_hex(12),**body.model_dump()))
            store.audit(c,t,'policy.approved')
        return {'saved':True}
    @routes.delete('/policies/{id}')
    def remove(id:str,t=Depends(tenant)):
        store=get_store()
        with store.transaction(t) as c:
            c.execute(delete(policies).where(policies.c.tenant==t,policies.c.id==id));store.audit(c,t,'policy.removed')
        return {'saved':True}
    @routes.get('/booking')
    def status(t=Depends(tenant)):
        with get_store().engine.connect() as c:row=c.execute(select(connectors.c.url).where(connectors.c.tenant==t)).first()
        return {'configured':bool(row),'url':row[0] if row else None,'note':'Connectivity is verified on lookup. Customer verification is required.'}
    @routes.post('/booking')
    def connect(body:Connection,t=Depends(tenant)):
        store=get_store()
        try:encrypted=seal(cipher(),t,body.token)
        except Exception:raise HTTPException(503,'Connector encryption must be configured by your operator') from None
        with store.transaction(t) as c:
            c.execute(delete(connectors).where(connectors.c.tenant==t))
            c.execute(connectors.insert().values(tenant=t,url=body.url,secret=encrypted,revision=secrets.randbelow(2**30),created=int(time.time())))
            c.execute(delete(identities).where(identities.c.tenant==t))
            store.audit(c,t,'booking.connected_verification_reset')
        return {'configured':True}
    @routes.delete('/booking')
    def disconnect(t=Depends(tenant)):
        store=get_store()
        with store.transaction(t) as c:
            c.execute(delete(connectors).where(connectors.c.tenant==t));c.execute(delete(identities).where(identities.c.tenant==t));store.audit(c,t,'booking.disconnected')
        return {'configured':False}
    @routes.post('/emails/{execution}/verify-customer')
    def verify(execution:str,body:Identity,t=Depends(tenant)):
        if not body.verified:raise HTTPException(422,'Confirm independent customer verification first')
        store=get_store()
        with store.transaction(t) as c:
            row=row_for(c,t,execution);ensure_not_sending(c,t,execution)
            if row['status']=='RUNNING' or row['expires_at']<=int(time.time()):raise HTTPException(409,'Wait for processing or choose an unexpired email')
            c.execute(delete(identities).where(identities.c.tenant==t,identities.c.execution_id==execution))
            c.execute(identities.insert().values(tenant=t,execution_id=execution,customer_id=body.customer_id,expires=min(row['expires_at'],int(time.time())+3600)))
            store.audit(c,t,'customer.verified_by_operator.'+execution)
        return {'verified':True,'valid_for_seconds':3600,'next_step':'Regenerate the draft. Sending still requires review.'}
    return routes
