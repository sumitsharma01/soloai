"""Local demo only. Never uses the customer's real booking connector."""
import json
import os
import secrets
import time
from datetime import date
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import text

class BookingProposal(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True)
    operation: str=Field(pattern='^(create|change)$')
    booking_id: str=Field(default='',max_length=80)
    arrival: str=Field(pattern=r'^\d{4}-\d{2}-\d{2}$')
    departure: str=Field(pattern=r'^\d{4}-\d{2}-\d{2}$')
    guests: int=Field(ge=1,le=8)

    @model_validator(mode='after')
    def dates(self):
        start,end=date.fromisoformat(self.arrival),date.fromisoformat(self.departure)
        if start<date.today() or not 0<(end-start).days<=30:raise ValueError('Choose future dates for a stay of one to thirty nights.')
        if self.operation=='change' and not self.booking_id:raise ValueError('Booking reference required.')
        if self.operation=='create' and self.booking_id:raise ValueError('New bookings must not supply a reference.')
        return self

TOOLS=[{'type':'function','name':'lookup_demo_booking','description':'Read a synthetic booking owned by the demo customer verified through this signed-in session. Never reads real bookings.',
        'parameters':{'type':'object','properties':{'booking_id':{'type':'string','maxLength':80}},'required':['booking_id'],'additionalProperties':False}},
       {'type':'function','name':'propose_demo_booking','description':'Propose creating or changing a synthetic booking. Ask for exact dates and number of guests first. Nothing is booked until the person clicks Confirm in SoloAI.',
        'parameters':BookingProposal.model_json_schema()}]

def allowed(config):
    return os.getenv('SOLOAI_ENV')=='development' and config.get('allow_demo_bookings',False)

def initialize(c):
    c.execute(text('CREATE TABLE IF NOT EXISTS voice_demo_bookings (id TEXT PRIMARY KEY, tenant TEXT NOT NULL REFERENCES tenants(id), customer TEXT NOT NULL, arrival TEXT NOT NULL, departure TEXT NOT NULL, guests INTEGER NOT NULL, revision INTEGER NOT NULL)'))
    c.execute(text('CREATE TABLE IF NOT EXISTS voice_booking_proposals (id TEXT PRIMARY KEY, tenant TEXT NOT NULL REFERENCES tenants(id), call_id TEXT NOT NULL, payload TEXT NOT NULL, booking_revision INTEGER NOT NULL, status TEXT NOT NULL, created BIGINT NOT NULL, result_id TEXT)'))

def lookup(c,t,booking_id):
    row=c.execute(text('SELECT id,arrival,departure,guests,revision FROM voice_demo_bookings WHERE tenant=:t AND customer=:customer AND id=:id'),{'t':t,'customer':t+':demo','id':booking_id}).mappings().first()
    return {'demo':True,'found':bool(row),'booking':dict(row) if row else None}

def propose(c,t,call_id,args):
    body=BookingProposal.model_validate_json(args)
    revision=0
    if body.operation=='change':
        booking=lookup(c,t,body.booking_id)['booking']
        if not booking:raise ValueError('No matching booking for this demo customer.')
        revision=booking['revision']
    payload=body.model_dump_json()
    existing=c.execute(text("SELECT id FROM voice_booking_proposals WHERE tenant=:t AND call_id=:call AND payload=:p AND status='PENDING_CONFIRMATION'"),{'t':t,'call':call_id,'p':payload}).first()
    if existing:return {'demo':True,'status':'PENDING_CONFIRMATION','id':existing.id}
    rid=secrets.token_hex(16)
    c.execute(text("INSERT INTO voice_booking_proposals (id,tenant,call_id,payload,booking_revision,status,created) VALUES (:id,:t,:call,:p,:r,'PENDING_CONFIRMATION',:now)"),{'id':rid,'t':t,'call':call_id,'p':payload,'r':revision,'now':int(time.time())})
    return {'demo':True,'status':'PENDING_CONFIRMATION','id':rid}

def confirm(c,t,rid):
    row=c.execute(text('SELECT * FROM voice_booking_proposals WHERE tenant=:t AND id=:id'),{'t':t,'id':rid}).mappings().first()
    if not row:raise ValueError('Proposal not found.')
    if row['status']=='CONFIRMED':return {'demo':True,'status':'CONFIRMED','booking_id':row['result_id']}
    if row['created']<int(time.time())-900:raise ValueError('Proposal expired. Ask for a new proposal.')
    body=BookingProposal.model_validate_json(row['payload'])
    if body.operation=='change':
        booking=lookup(c,t,body.booking_id)['booking']
        if not booking or booking['revision']!=row['booking_revision']:raise ValueError('Booking changed. Ask for a new proposal.')
    # Demo inventory: one accommodation per workspace, no overlapping stays.
    conflict=c.execute(text('SELECT id FROM voice_demo_bookings WHERE tenant=:t AND id!=:id AND arrival<:end AND departure>:start'),{'t':t,'id':body.booking_id,'start':body.arrival,'end':body.departure}).first()
    if conflict:raise ValueError('Those dates are unavailable in the demo inventory.')
    bid=body.booking_id or 'DEMO-'+secrets.token_hex(4).upper()
    args={'id':bid,'t':t,'customer':t+':demo','start':body.arrival,'end':body.departure,'guests':body.guests}
    if body.operation=='create':c.execute(text('INSERT INTO voice_demo_bookings (id,tenant,customer,arrival,departure,guests,revision) VALUES (:id,:t,:customer,:start,:end,:guests,1)'),args)
    else:c.execute(text('UPDATE voice_demo_bookings SET arrival=:start,departure=:end,guests=:guests,revision=revision+1 WHERE id=:id AND tenant=:t AND customer=:customer'),args)
    c.execute(text("UPDATE voice_booking_proposals SET status='CONFIRMED',result_id=:bid WHERE tenant=:t AND id=:id"),{'bid':bid,'t':t,'id':rid})
    return {'demo':True,'status':'CONFIRMED','booking_id':bid}
