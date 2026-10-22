"""Support inbox. Session-only management; delivery permissions are checked in code."""
import os
from typing import Literal
import json
import re
import secrets
import time
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select, update, delete, text
from app.email_schema import jobs, tool_calls
from app.inbox_schema import labels, settings, tickets, instructions, deliveries, grants

DEFAULT_LABELS = [('refund','Refund','refund,reimburse'), ('new-order','New order','new order,purchase'),
    ('cancellation','Cancellation','cancel'), ('query','Query','question,when,how,where,?'),
    ('miscellaneous','Miscellaneous','')]


def bootstrap(c, tenant):
    if c.execute(select(settings.c.tenant).where(settings.c.tenant==tenant)).first(): return
    c.execute(settings.insert().values(tenant=tenant, automatic=False, allowed_labels='[]', daily_limit=20,revision=1,enabled_at=0))
    for id, name, keywords in DEFAULT_LABELS:
        c.execute(labels.insert().values(tenant=tenant,id=id,name=name,keywords=keywords,colour={'refund':'amber','new-order':'green','cancellation':'red','query':'blue'}.get(id,'slate')))


def create_ticket(c, tenant, execution, content, source=None):
    bootstrap(c, tenant)
    matched = [r.id for r in c.execute(select(labels).where(labels.c.tenant==tenant))
               if any(k.strip().lower() in content.lower() for k in r.keywords.split(',') if k.strip())]
    if not matched and c.execute(select(labels.c.id).where(labels.c.tenant==tenant,labels.c.id=='miscellaneous')).first():
        matched=['miscellaneous']
    c.execute(tickets.insert().values(tenant=tenant,execution_id=execution,labels=json.dumps(matched),
        revision=1,local_guidance='',source=json.dumps(source) if source else None))


def ensure_ticket(c, tenant, row):
    if not c.execute(select(tickets.c.execution_id).where(tickets.c.tenant==tenant,tickets.c.execution_id==row['execution_id'])).first():
        create_ticket(c,tenant,row['execution_id'],row['content'] or '')
    return c.execute(select(tickets).where(tickets.c.tenant==tenant,tickets.c.execution_id==row['execution_id'])).mappings().one()


def guidance(c, tenant, execution):
    ticket=c.execute(select(tickets).where(tickets.c.tenant==tenant,tickets.c.execution_id==execution)).mappings().first()
    if not ticket: return ''
    chosen=json.loads(ticket['labels'])
    rules=c.execute(select(instructions).where(instructions.c.tenant==tenant,instructions.c.active==True).order_by(instructions.c.created)).mappings().all()
    content=[r['content'] for r in rules if r['label_id'] is None or r['label_id'] in chosen]
    if ticket['local_guidance']: content.append(ticket['local_guidance'])
    return '\nApproved business guidance (not tool permissions):\n'+'\n'.join(content) if content else ''


def ensure_not_sending(c, tenant, execution):
    delivery=c.execute(select(deliveries.c.status).where(deliveries.c.tenant==tenant,deliveries.c.execution_id==execution)).scalar()
    if delivery in ('DISPATCHING','SENT','UNKNOWN'):
        raise HTTPException(409,'Delivery already started. Check delivery status before taking further action.')


def row_for(c, tenant, execution):
    row=c.execute(select(jobs).where(jobs.c.tenant==tenant,jobs.c.execution_id==execution)).mappings().first()
    if not row: raise HTTPException(404,'Email not found')
    return row


def send_permission(c, tenant):
    from app.gmail import connections, digest
    connection=c.execute(select(connections).where(connections.c.tenant==tenant)).mappings().first()
    granted=c.execute(select(grants.c.token_digest).where(grants.c.tenant==tenant)).scalar()
    return bool(connection and granted and granted==digest(connection['refresh_token']))


class Input(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True)
class LabelInput(Input):
    name: str=Field(min_length=1,max_length=60,pattern=r'.*\S.*')
    keywords: str=Field(default='',max_length=500)
    colour: Literal['slate','blue','green','amber','red','purple','teal','pink']='slate'
class AssistInput(Input):
    content: str=Field(min_length=1,max_length=1000,pattern=r'[\s\S]*\S[\s\S]*')
class RulesInput(Input):
    automatic: bool
    allowed_labels: list[str]=Field(max_length=30)
    daily_limit: int=Field(ge=1,le=200)
    revision: int
class InstructionInput(Input):
    content: str=Field(min_length=1,max_length=1000,pattern=r'[\s\S]*\S[\s\S]*')
    label_id: str | None=None
    active: bool=True
    revision: int=0
class DraftInput(Input):
    draft: str=Field(min_length=1,max_length=12000,pattern=r'[\s\S]*\S[\s\S]*')
    labels: list[str]=Field(max_length=30)
    local_guidance: str=Field(default='',max_length=1000)
    revision: int
class RevisionInput(Input):
    revision: int


def valid_labels(c,t,ids):
    valid=set(c.execute(select(labels.c.id).where(labels.c.tenant==t)).scalars())
    if not set(ids)<=valid: raise HTTPException(422,'Choose existing labels')


def router(get_store, tenant):
    routes=APIRouter(prefix='/api/inbox')

    @routes.post('/instructions/assist')
    def assist(body:AssistInput,t=Depends(tenant)):
        from app import instruction_assist
        if not os.getenv('AZURE_FOUNDRY_PROJECT_ENDPOINT') or not os.getenv('AZURE_FOUNDRY_MODEL'):
            raise HTTPException(503,'AI assistance needs the Azure Foundry connection. Your notes are unchanged.')
        store=get_store();now=int(time.time());reserve=instruction_assist.reservation(body.content)
        with store.transaction(t) as c:
            c.execute(text('UPDATE tenants SET "window"=:w,requests=0 WHERE id=:t AND "window"<>:w'),{'w':now//60,'t':t})
            if not c.execute(text('UPDATE tenants SET used=used+:r,requests=requests+1 WHERE id=:t AND used+:r<=budget AND requests<20'),{'r':reserve,'t':t}).rowcount:
                raise HTTPException(429,'Usage allowance or request limit reached')
        used=reserve;status='failed'
        try:
            suggestion,used=instruction_assist.rewrite(body.content)
            status='completed'
        except Exception:
            # A failed provider call may still have consumed tokens. Keep its reservation.
            raise HTTPException(503,'Could not prepare a suggestion. Your notes are unchanged. Try again later.') from None
        finally:
            with store.transaction(t) as c:
                c.execute(text('UPDATE tenants SET used=used+:delta WHERE id=:t'),{'delta':used-reserve,'t':t})
                store.audit(c,t,'inbox.instruction_assist.'+status)
        return {'suggestion':suggestion,'tokens':used}

    @routes.get('')
    def listing(t=Depends(tenant)):
        store=get_store()
        with store.transaction(t) as c:
            bootstrap(c,t)
            rows=c.execute(select(jobs).where(jobs.c.tenant==t).order_by(jobs.c.created_at.desc()).limit(100)).mappings().all()
            result=[]
            for row in rows:
                ticket=ensure_ticket(c,t,row)
                expired=row['expires_at']<=int(time.time())
                source=json.loads(ticket['source']) if ticket['source'] and not expired else {}
                delivery=c.execute(select(deliveries).where(deliveries.c.tenant==t,deliveries.c.execution_id==row['execution_id'])).mappings().first()
                result.append(dict(id=row['execution_id'],subject='Content expired' if expired else source.get('subject') or row['subject'] or 'Support email',
                    sender=source.get('recipient','Forwarded event'),status=row['status'],needs_human=row['needs_human'],
                    created=row['created_at'],labels=json.loads(ticket['labels']),delivery=dict(delivery) if delivery else None))
            cfg=dict(c.execute(select(settings).where(settings.c.tenant==t)).mappings().one())
            cfg['allowed_labels']=json.loads(cfg['allowed_labels']);cfg.pop('tenant')
            return dict(emails=result,labels=[dict(r) for r in c.execute(select(labels.c.id,labels.c.name,labels.c.keywords,labels.c.colour).where(labels.c.tenant==t)).mappings()],
                rules=cfg,send_authorized=send_permission(c,t),instructions=[dict(r) for r in c.execute(select(instructions.c.id,instructions.c.content,instructions.c.label_id,instructions.c.active,instructions.c.revision).where(instructions.c.tenant==t).order_by(instructions.c.created)).mappings()])

    @routes.get('/emails/{execution}')
    def detail(execution:str,t=Depends(tenant)):
        store=get_store()
        result=store.detail(t,execution)
        with store.transaction(t) as c:
            row=row_for(c,t,execution); ticket=ensure_ticket(c,t,row)
            expired=row['expires_at']<=int(time.time())
            source=json.loads(ticket['source']) if ticket['source'] and not expired else {}
            delivery=c.execute(select(deliveries).where(deliveries.c.tenant==t,deliveries.c.execution_id==execution)).mappings().first()
            return result | dict(labels=json.loads(ticket['labels']),revision=ticket['revision'],local_guidance='' if expired else ticket['local_guidance'],
                recipient=source.get('recipient'),original_subject=source.get('subject'),send_authorized=send_permission(c,t),delivery=dict(delivery) if delivery else None)

    @routes.put('/emails/{execution}')
    def edit(execution:str,body:DraftInput,t=Depends(tenant)):
        store=get_store()
        with store.transaction(t) as c:
            row=row_for(c,t,execution);ticket=ensure_ticket(c,t,row)
            ensure_not_sending(c,t,execution)
            if row['status'] not in ('WAITING_FOR_REVIEW','APPROVED','FAILED') or row['expires_at']<=int(time.time()):
                raise HTTPException(409,'Email cannot be edited in its current state')
            if ticket['revision']!=body.revision: raise HTTPException(409,'This email changed. Close and reopen it before editing.')
            valid_labels(c,t,body.labels)
            c.execute(update(tickets).where(tickets.c.tenant==t,tickets.c.execution_id==execution).values(
                labels=json.dumps(body.labels),local_guidance=body.local_guidance,revision=body.revision+1))
            c.execute(update(jobs).where(jobs.c.tenant==t,jobs.c.execution_id==execution).values(draft=body.draft,needs_human=True))
            store.audit(c,t,'inbox.draft_saved.'+execution)
        return {'revision':body.revision+1}

    @routes.post('/emails/{execution}/regenerate')
    def regenerate(execution:str,body:RevisionInput,t=Depends(tenant)):
        store=get_store()
        with store.transaction(t) as c:
            row=row_for(c,t,execution);ticket=ensure_ticket(c,t,row);ensure_not_sending(c,t,execution)
            if row['status'] not in ('WAITING_FOR_REVIEW','APPROVED','FAILED') or row['expires_at']<=int(time.time()) or ticket['revision']!=body.revision:
                raise HTTPException(409,'Email changed or is unavailable for regeneration')
            enabled=c.execute(text("SELECT enabled FROM agents WHERE tenant=:t AND id='email-support'"),{'t':t}).scalar()
            if not enabled: raise HTTPException(409,'Enable Email Support first')
            store.admit(c,t,int(time.time()))
            epoch=c.execute(text('SELECT stopped FROM tenants WHERE id=:t'),{'t':t}).scalar_one()
            c.execute(update(jobs).where(jobs.c.tenant==t,jobs.c.execution_id==execution).values(status='QUEUED',epoch=epoch,
                available_at=int(time.time()),error=None,attempts=0,owner=None,lease_until=None,completed_at=None,draft=None,needs_human=None,
                uncertain_tokens=row['uncertain_tokens']+row['reserved_tokens'],reserved_tokens=0))
            c.execute(update(tickets).where(tickets.c.tenant==t,tickets.c.execution_id==execution).values(revision=body.revision+1))
            c.execute(text("UPDATE executions SET status='QUEUED' WHERE tenant=:t AND id=:id"),{'t':t,'id':execution})
            store.audit(c,t,'inbox.regenerated.'+execution)
        return {'status':'QUEUED'}

    @routes.put('/rules')
    def rules(body:RulesInput,t=Depends(tenant)):
        store=get_store()
        with store.transaction(t) as c:
            bootstrap(c,t);valid_labels(c,t,body.allowed_labels)
            old=c.execute(select(settings).where(settings.c.tenant==t)).mappings().one()
            if old['revision']!=body.revision: raise HTTPException(409,'Rules changed. Refresh before saving.')
            if body.automatic and (not body.allowed_labels or not send_permission(c,t)):
                raise HTTPException(409,'Authorize Gmail sending and choose at least one label first')
            c.execute(update(settings).where(settings.c.tenant==t).values(automatic=body.automatic,allowed_labels=json.dumps(body.allowed_labels),
                daily_limit=body.daily_limit,revision=body.revision+1,enabled_at=int(time.time())))
            store.audit(c,t,'inbox.automatic_enabled' if body.automatic else 'inbox.automatic_paused')
        return {'saved':True}

    @routes.post('/labels')
    def add_label(body:LabelInput,t=Depends(tenant)):
        store=get_store()
        with store.transaction(t) as c:
            bootstrap(c,t)
            if len(c.execute(select(labels.c.id).where(labels.c.tenant==t)).all())>=30: raise HTTPException(409,'Limit: 30 labels')
            c.execute(labels.insert().values(tenant=t,id=secrets.token_hex(12),**body.model_dump()))
            store.audit(c,t,'inbox.label_created')
        return {'saved':True}

    @routes.put('/labels/{id}')
    def edit_label(id:str,body:LabelInput,t=Depends(tenant)):
        store=get_store()
        with store.transaction(t) as c:
            if not c.execute(update(labels).where(labels.c.tenant==t,labels.c.id==id).values(**body.model_dump())).rowcount: raise HTTPException(404,'Label not found')
            c.execute(update(settings).where(settings.c.tenant==t).values(automatic=False,revision=settings.c.revision+1))
            store.audit(c,t,'inbox.label_updated_automation_paused')
        return {'saved':True}

    @routes.delete('/labels/{id}')
    def remove_label(id:str,t=Depends(tenant)):
        store=get_store()
        with store.transaction(t) as c:
            if not c.execute(delete(labels).where(labels.c.tenant==t,labels.c.id==id)).rowcount: raise HTTPException(404,'Label not found')
            cfg=c.execute(select(settings).where(settings.c.tenant==t)).mappings().one()
            c.execute(update(settings).where(settings.c.tenant==t).values(automatic=False,allowed_labels=json.dumps([x for x in json.loads(cfg['allowed_labels']) if x!=id]),revision=cfg['revision']+1))
            c.execute(update(instructions).where(instructions.c.tenant==t,instructions.c.label_id==id).values(active=False,revision=instructions.c.revision+1))
            for r in c.execute(select(tickets).where(tickets.c.tenant==t)).mappings().all():
                c.execute(update(tickets).where(tickets.c.tenant==t,tickets.c.execution_id==r['execution_id']).values(labels=json.dumps([x for x in json.loads(r['labels']) if x!=id]),revision=r['revision']+1))
            store.audit(c,t,'inbox.label_removed_automation_paused')
        return {'saved':True}

    @routes.post('/instructions')
    def add_instruction(body:InstructionInput,t=Depends(tenant)):
        store=get_store()
        with store.transaction(t) as c:
            bootstrap(c,t)
            if body.label_id: valid_labels(c,t,[body.label_id])
            if len(c.execute(select(instructions.c.id).where(instructions.c.tenant==t)).all())>=20: raise HTTPException(409,'Limit: 20 instructions; edit or delete an existing one')
            c.execute(instructions.insert().values(tenant=t,id=secrets.token_hex(12),content=body.content,label_id=body.label_id,active=body.active,revision=1,created=int(time.time())))
            store.audit(c,t,'inbox.instruction_created')
        return {'saved':True}

    @routes.put('/instructions/{id}')
    def edit_instruction(id:str,body:InstructionInput,t=Depends(tenant)):
        store=get_store()
        with store.transaction(t) as c:
            if body.label_id: valid_labels(c,t,[body.label_id])
            changed=c.execute(update(instructions).where(instructions.c.tenant==t,instructions.c.id==id,instructions.c.revision==body.revision).values(content=body.content,label_id=body.label_id,active=body.active,revision=body.revision+1)).rowcount
            if not changed: raise HTTPException(409,'Instruction changed or no longer exists')
            store.audit(c,t,'inbox.instruction_updated.'+id)
        return {'saved':True}

    @routes.delete('/instructions/{id}')
    def remove_instruction(id:str,t=Depends(tenant)):
        store=get_store()
        with store.transaction(t) as c:
            c.execute(delete(instructions).where(instructions.c.tenant==t,instructions.c.id==id))
            store.audit(c,t,'inbox.instruction_deleted.'+id)
        return {'saved':True}

    @routes.post('/emails/{execution}/send')
    async def send(execution:str,body:RevisionInput,t=Depends(tenant)):
        from app.email_delivery import deliver
        return await deliver(get_store(),t,execution,'reviewer',body.revision)
    return routes
