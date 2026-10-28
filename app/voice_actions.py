"""Voice requests require an explicit browser confirmation before they are saved."""
import json
import secrets
import time
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text

class CallbackRequest(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    name: str = Field(min_length=1, max_length=100)
    contact: str = Field(min_length=3, max_length=200)
    reason: str = Field(min_length=1, max_length=600)

CALLBACK_TOOL = {
    'type': 'function', 'name': 'request_callback',
    'description': 'Prepare a callback request for the caller to review and confirm in SoloAI. This does not save or send it. Collect name, contact and reason first.',
    'parameters': CallbackRequest.model_json_schema(),
}

def initialize(c):
    c.execute(text('CREATE TABLE IF NOT EXISTS voice_requests (id TEXT PRIMARY KEY, tenant TEXT NOT NULL REFERENCES tenants(id), call_id TEXT NOT NULL, payload TEXT NOT NULL, status TEXT NOT NULL, created BIGINT NOT NULL, expires BIGINT NOT NULL)'))
    c.execute(text('CREATE INDEX IF NOT EXISTS voice_requests_tenant ON voice_requests(tenant,created)'))

def propose(c, tenant, call_id, arguments):
    body = CallbackRequest.model_validate_json(arguments)
    # One proposal per call keeps retries from creating duplicate callback requests.
    existing = c.execute(text('SELECT id,status FROM voice_requests WHERE tenant=:t AND call_id=:call'), {'t':tenant,'call':call_id}).mappings().first()
    if existing:
        return dict(existing)
    now = int(time.time())
    request_id = secrets.token_hex(16)
    c.execute(text("INSERT INTO voice_requests (id,tenant,call_id,payload,status,created,expires) VALUES (:id,:t,:call,:payload,'PENDING_CONFIRMATION',:now,:expiry)"),
              {'id':request_id,'t':tenant,'call':call_id,'payload':body.model_dump_json(),'now':now,'expiry':now+86400})
    return {'id':request_id,'status':'PENDING_CONFIRMATION'}

STATUS_TOOL={'type':'function','name':'check_action_status','description':'Check whether the user confirmed a proposed callback or synthetic booking in SoloAI. Only report success if status is SAVED_FOR_REVIEW or CONFIRMED.', 'parameters':{'type':'object','properties':{'id':{'type':'string','maxLength':64}},'required':['id'],'additionalProperties':False}}

def status(c,t,rid):
    row=c.execute(text('SELECT status FROM voice_requests WHERE tenant=:t AND id=:id AND expires>:now'),{'t':t,'id':rid,'now':int(time.time())}).mappings().first()
    if row:return dict(row)
    row=c.execute(text('SELECT status,result_id FROM voice_booking_proposals WHERE tenant=:t AND id=:id'),{'t':t,'id':rid}).mappings().first()
    return dict(row) if row else {'status':'NOT_FOUND'}
