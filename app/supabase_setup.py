"""Collect a tenant's booking access requirements. No credentials or remote calls."""
import json
from typing import Annotated
from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field

Identifier = Annotated[str, Field(pattern=r'^[a-zA-Z_][a-zA-Z0-9_]{0,62}$')]

class SetupInput(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    project_url: str = Field(pattern=r'^https://[a-z0-9-]+\.supabase\.co$', max_length=200)
    table_name: Identifier
    reference_column: Identifier
    customer_column: Identifier
    allowed_fields: list[Identifier] = Field(min_length=1, max_length=20)
    ownership_rule: str = Field(min_length=10, max_length=1000)
    verification_rule: str = Field(min_length=10, max_length=1000)


def router(engine, tenant, text, audit):
    routes = APIRouter(prefix='/api/integrations/supabase')

    @routes.get('')
    def status(t=Depends(tenant)):
        with engine.connect() as c:
            row = c.execute(text('SELECT configuration FROM supabase_setups WHERE tenant=:t'), {'t':t}).first()
        return {'status':'setup_requested' if row else 'not_configured', 'connected':False,
                'configuration':json.loads(row[0]) if row else None}

    @routes.post('/setup')
    def save(body:SetupInput, t=Depends(tenant)):
        with engine.begin() as c:
            # Serialize saves within the workspace before replacing its request.
            c.execute(text('UPDATE tenants SET name=name WHERE id=:t'), {'t':t})
            c.execute(text('DELETE FROM supabase_setups WHERE tenant=:t'), {'t':t})
            c.execute(text('INSERT INTO supabase_setups (tenant,configuration) VALUES (:t,:config)'),
                      {'t':t,'config':json.dumps(body.model_dump())})
            audit(c,t,'supabase.setup_requested')
        return {'status':'setup_requested','connected':False,
                'message':'Setup request saved. Authorization and the restricted booking endpoint still need operator setup. No database access has been granted.'}

    return routes
