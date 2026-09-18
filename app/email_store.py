"""PostgreSQL is both queue and source of truth. Transactions fence workers and reviews."""
import hashlib
import json
import secrets
import time
from contextlib import contextmanager
from sqlalchemy import select, update, text
from fastapi import HTTPException
from app.email_schema import jobs, tool_calls
from app.email_tools import EmailFailure
from app.telemetry import emit

TERMINAL = {'APPROVED', 'REJECTED', 'FAILED', 'COMPLETED'}


class EmailStore:
    def __init__(self, engine): self.engine = engine

    @contextmanager
    def transaction(self, tenant=None):
        with self.engine.connect() as c:
            # SQLite is only a local development adapter. PostgreSQL serializes
            # each tenant using its existing row; no distributed lock service.
            if self.engine.dialect.name == 'sqlite': c.exec_driver_sql('BEGIN IMMEDIATE')
            try:
                if tenant:
                    sql = 'SELECT id FROM tenants WHERE id=:t'
                    if self.engine.dialect.name == 'postgresql': sql += ' FOR UPDATE'
                    if not c.execute(text(sql), {'t': tenant}).first():
                        raise EmailFailure('invalid_tenant')
                yield c
                c.commit()
            except BaseException:
                c.rollback()
                raise

    def audit(self, c, tenant, action):
        c.execute(text('INSERT INTO audit VALUES (:id,:t,:action,:now)'),
                  {'id': secrets.token_hex(16), 't': tenant, 'action': action, 'now': int(time.time())})

    def enqueue(self, tenant, event, config, retention, mailbox_owner=None):
        now = int(time.time())
        fingerprint = hashlib.sha256(json.dumps(event.model_dump(), sort_keys=True).encode()).hexdigest()
        with self.transaction(tenant) as c:
            if mailbox_owner is not None:
                from app.gmail import connections
                if not c.execute(select(connections.c.tenant).where(connections.c.tenant==tenant,
                    connections.c.owner==mailbox_owner)).first():
                    raise EmailFailure('gmail_disconnected')
            existing = c.execute(select(jobs).where(jobs.c.tenant == tenant,
                jobs.c.event_id == event.id)).mappings().first()
            if existing:
                if existing['event_digest'] != fingerprint:
                    raise HTTPException(409, 'Event ID already used for different content')
                return {'execution_id': existing['execution_id'], 'status': existing['status'], 'duplicate': True}
            cfg = c.execute(text("SELECT enabled,guidance FROM agents WHERE tenant=:t AND id='email-support'"),
                            {'t': tenant}).mappings().one()
            if not cfg['enabled']: raise HTTPException(409, 'This agent is disabled')
            state = c.execute(text('SELECT stopped FROM tenants WHERE id=:t'), {'t': tenant}).scalar_one()
            self.admit(c, tenant, now)
            # Prevent unbounded pending content even if model credentials are unavailable.
            pending = c.execute(select(jobs.c.execution_id).where(jobs.c.tenant == tenant,
                jobs.c.status.in_(['QUEUED', 'RUNNING', 'WAITING_FOR_REVIEW'])).limit(100)).all()
            if len(pending) >= 100: raise HTTPException(429, 'Review or clear pending email executions')
            execution = secrets.token_hex(16)
            c.execute(text("INSERT INTO executions VALUES (:id,:t,'email-support','QUEUED',0,0,:now)"),
                      {'id': execution, 't': tenant, 'now': now})
            c.execute(jobs.insert().values(execution_id=execution, tenant=tenant, event_id=event.id,
                event_digest=fingerprint, content=event.content, guidance=cfg['guidance'],
                status='QUEUED', epoch=state, created_at=now, available_at=now,
                expires_at=now + retention, **config))
            self.audit(c, tenant, 'email.queued.' + execution)
        return {'execution_id': execution, 'status': 'QUEUED', 'duplicate': False}

    def admit(self, c, tenant, now):
        c.execute(text('UPDATE tenants SET "window"=:w,requests=0 WHERE id=:t AND "window"<>:w'),
                  {'w': now // 60, 't': tenant})
        row = c.execute(text('SELECT used,budget,requests FROM tenants WHERE id=:t'), {'t': tenant}).mappings().one()
        if row['used'] >= row['budget']: raise EmailFailure('token_allowance_exhausted')
        if row['requests'] >= 20: raise EmailFailure('rate_limit_exceeded')
        c.execute(text('UPDATE tenants SET requests=requests+1 WHERE id=:t'), {'t': tenant})

    def _row(self, c, ctx):
        row = c.execute(select(jobs).where(jobs.c.tenant == ctx['tenant'],
            jobs.c.execution_id == ctx['execution_id'])).mappings().one()
        if row['status'] != 'RUNNING' or row['owner'] != ctx['owner']:
            raise EmailFailure('worker_lease_lost')
        if row['lease_until'] <= int(time.time()): raise EmailFailure('worker_lease_lost')
        return row

    def _active(self, c, ctx):
        row = self._row(c, ctx)
        state = c.execute(text("SELECT a.enabled,t.stopped FROM agents a JOIN tenants t ON t.id=a.tenant "
                               "WHERE a.tenant=:t AND a.id='email-support'"), {'t': ctx['tenant']}).one()
        if not state.enabled or state.stopped != row['epoch']: raise EmailFailure('emergency_stop')
        if row['expires_at'] <= int(time.time()): raise EmailFailure('content_expired')
        return row

    def check_active(self, ctx):
        with self.transaction(ctx['tenant']) as c: self._active(c, ctx)

    def admit_retry(self, ctx):
        with self.transaction(ctx['tenant']) as c:
            self._active(c, ctx)
            self.admit(c, ctx['tenant'], int(time.time()))

    def claim(self, timeout):
        now = int(time.time())
        with self.engine.connect() as c:
            candidates = c.execute(select(jobs.c.tenant, jobs.c.execution_id).where(
                jobs.c.status == 'QUEUED', jobs.c.available_at <= now)
                .order_by(jobs.c.available_at, jobs.c.created_at).limit(20)).mappings().all()
        for candidate in candidates:
            with self.transaction(candidate['tenant']) as c:
                owner = secrets.token_hex(16)
                changed = c.execute(update(jobs).where(jobs.c.tenant == candidate['tenant'],
                    jobs.c.execution_id == candidate['execution_id'], jobs.c.status == 'QUEUED',
                    jobs.c.available_at <= now).values(status='RUNNING', owner=owner,
                    lease_until=now + timeout + 30, started_at=now, attempts=jobs.c.attempts + 1)).rowcount
                if not changed: continue
                row = dict(c.execute(select(jobs).where(jobs.c.tenant == candidate['tenant'],
                    jobs.c.execution_id == candidate['execution_id'])).mappings().one())
                c.execute(text("UPDATE executions SET status='RUNNING' WHERE id=:id AND tenant=:t"),
                          {'id': row['execution_id'], 't': row['tenant']})
                self.audit(c, row['tenant'], 'email.running.' + row['execution_id'])
                return row | {'agent': 'email-support'}

    def reserve(self, ctx, amount):
        with self.transaction(ctx['tenant']) as c:
            row = self._active(c, ctx)
            if row['reserved_tokens']: raise EmailFailure('uncertain_usage')
            changed = c.execute(text('UPDATE tenants SET used=used+:n WHERE id=:t AND used+:n<=budget'),
                                {'n': amount, 't': ctx['tenant']}).rowcount
            if not changed: raise EmailFailure('token_allowance_exhausted')
            c.execute(update(jobs).where(jobs.c.tenant == ctx['tenant'], jobs.c.execution_id == ctx['execution_id'])
                      .values(reserved_tokens=amount))
            c.execute(text('UPDATE executions SET tokens=tokens+:n WHERE id=:id AND tenant=:t'),
                      {'n': amount, 'id': ctx['execution_id'], 't': ctx['tenant']})

    def settle(self, ctx, actual, duration):
        with self.transaction(ctx['tenant']) as c:
            # Usage must settle even after Stop; Stop cannot undo a billable request.
            row = self._row(c, ctx)
            reserved = row['reserved_tokens']
            if type(actual) is not int or actual < 0 or actual > reserved:
                raise EmailFailure('invalid_provider_usage')
            c.execute(text('UPDATE tenants SET used=used+:n WHERE id=:t'),
                      {'n': actual-reserved, 't': ctx['tenant']})
            c.execute(text('UPDATE executions SET tokens=tokens+:n WHERE id=:id AND tenant=:t'),
                      {'n': actual-reserved, 'id': ctx['execution_id'], 't': ctx['tenant']})
            c.execute(update(jobs).where(jobs.c.tenant == ctx['tenant'], jobs.c.execution_id == ctx['execution_id'])
                      .values(reserved_tokens=0, provider_calls=jobs.c.provider_calls+1,
                              provider_latency=jobs.c.provider_latency+duration))

    def provider_failed(self, ctx, duration):
        with self.transaction(ctx['tenant']) as c:
            self._row(c, ctx)
            c.execute(update(jobs).where(jobs.c.tenant==ctx['tenant'],jobs.c.execution_id==ctx['execution_id'])
                .values(provider_latency=jobs.c.provider_latency+duration))

    def finish(self, ctx, answer=None, failure=None):
        now = int(time.time())
        with self.transaction(ctx['tenant']) as c:
            try: row = self._row(c, ctx)
            except EmailFailure: return  # Fenced stale worker cannot publish a late draft.
            try: self._active(c, ctx)
            except EmailFailure as exc: failure, answer = exc, None
            if failure:
                # Replay only a known transient failure before any successful model
                # response. Unknown/crashed in-flight calls are never automatically replayed.
                retry = (failure.transient and row['attempts'] < 3 and row['provider_calls'] == 0)
                status = 'QUEUED' if retry else 'FAILED'
            else:
                status = 'WAITING_FOR_REVIEW'
            calls = c.execute(select(tool_calls.c.id).where(tool_calls.c.tenant == ctx['tenant'],
                tool_calls.c.execution_id == ctx['execution_id'])).all()
            values = dict(status=status, owner=None, lease_until=None, tool_calls_count=len(calls),
                error=failure.code if failure else None, completed_at=None if status=='QUEUED' else now)
            if status == 'QUEUED':
                values.update(available_at=now + 2 ** row['attempts'], reserved_tokens=0,
                              uncertain_tokens=row['uncertain_tokens']+row['reserved_tokens'])
            if answer and status == 'WAITING_FOR_REVIEW':
                values.update(subject=answer.subject, draft=answer.reply, needs_human=answer.needs_human)
            c.execute(update(jobs).where(jobs.c.tenant == ctx['tenant'], jobs.c.execution_id == ctx['execution_id']).values(**values))
            latency = max(0, (now-row['created_at'])*1000)
            c.execute(text('UPDATE executions SET status=:s,latency=:ms WHERE id=:id AND tenant=:t'),
                      {'s': status, 'ms': latency, 'id': ctx['execution_id'], 't': ctx['tenant']})
            self.audit(c, ctx['tenant'], 'email.' + status.lower() + '.' + ctx['execution_id'])
            used = c.execute(text('SELECT tokens FROM executions WHERE id=:id AND tenant=:t'),
                {'id': ctx['execution_id'], 't': ctx['tenant']}).scalar_one()
            allowance = c.execute(text('SELECT used*100.0/budget FROM tenants WHERE id=:t'), {'t':ctx['tenant']}).scalar_one()
        if status != 'QUEUED':
            emit('agent.execution', agent='email-support',
                 status='completed' if status=='WAITING_FOR_REVIEW' else 'failed', tokens=used,
                 usage_kind='reserved' if row['reserved_tokens'] or row['uncertain_tokens'] else 'reported',
                 latency_ms=latency, provider_ms=row['provider_latency'], allowance_percent=allowance,
                 tool_calls_count=len(calls), model=row['model'], agent_version=row['agent_version'])

    def recover(self):
        """Reap expired leases. Never re-send an inference whose outcome is unknown."""
        now = int(time.time())
        with self.engine.connect() as c:
            rows = c.execute(select(jobs.c.tenant, jobs.c.execution_id).where(
                jobs.c.status == 'RUNNING', jobs.c.lease_until <= now)).mappings().all()
        for row in rows:
            with self.transaction(row['tenant']) as c:
                changed = c.execute(update(jobs).where(jobs.c.tenant == row['tenant'],
                    jobs.c.execution_id == row['execution_id'], jobs.c.status == 'RUNNING',
                    jobs.c.lease_until <= now).values(status='FAILED', error='worker_interrupted',
                        completed_at=now, owner=None, lease_until=None)).rowcount
                if changed:
                    count = len(c.execute(select(tool_calls.c.id).where(tool_calls.c.tenant==row['tenant'],
                        tool_calls.c.execution_id==row['execution_id'])).all())
                    c.execute(update(jobs).where(jobs.c.tenant==row['tenant'],jobs.c.execution_id==row['execution_id'])
                        .values(tool_calls_count=count))
                    c.execute(text("UPDATE executions SET status='FAILED',latency=(:now-created)*1000 WHERE id=:id AND tenant=:t"),
                              {'now':now,'id':row['execution_id'],'t':row['tenant']})
                    self.audit(c, row['tenant'], 'email.worker_interrupted.' + row['execution_id'])
                    execution = c.execute(text('SELECT tokens,latency FROM executions WHERE tenant=:t AND id=:id'),
                        {'t':row['tenant'],'id':row['execution_id']}).mappings().one()
                    allowance = c.execute(text('SELECT used*100.0/budget FROM tenants WHERE id=:t'),
                        {'t':row['tenant']}).scalar_one()
                    emit('agent.execution',agent='email-support',status='failed',tokens=execution['tokens'],
                        usage_kind='reserved',latency_ms=execution['latency'],allowance_percent=allowance)
                    emit('email.recovery', status='FAILED')

    def detail(self, tenant, execution):
        with self.engine.connect() as c:
            row = c.execute(select(jobs).where(jobs.c.tenant == tenant,
                jobs.c.execution_id == execution)).mappings().first()
            if not row: raise HTTPException(404, 'Execution not found')
            usage = c.execute(text('SELECT tokens,latency FROM executions WHERE id=:id AND tenant=:t'),
                              {'id':execution,'t':tenant}).mappings().one()
            activity = c.execute(select(tool_calls.c.tool_name, tool_calls.c.status,
                tool_calls.c.duration, tool_calls.c.created_at).where(tool_calls.c.tenant == tenant,
                tool_calls.c.execution_id == execution).order_by(tool_calls.c.created_at)).mappings().all()
        public = {k:row[k] for k in ('execution_id','event_id','status','error','model','agent_version',
            'created_at','completed_at','expires_at','provider_latency','needs_human','content','subject','draft')}
        public['tool_calls_count'] = len(activity)
        public['usage_kind'] = 'reserved' if row['reserved_tokens'] or row['uncertain_tokens'] else 'reported'
        public['uncertain_tokens'] = row['reserved_tokens'] + row['uncertain_tokens']
        if row['expires_at'] <= int(time.time()):
            public.update(content=None, subject=None, draft=None)
        return public | dict(usage) | {'tools': [dict(r) for r in activity]}

    def review(self, tenant, execution, decision):
        with self.transaction(tenant) as c:
            row = c.execute(select(jobs).where(jobs.c.tenant == tenant,
                jobs.c.execution_id == execution)).mappings().first()
            if not row: raise HTTPException(404, 'Execution not found')
            if row['status'] != 'WAITING_FOR_REVIEW': raise HTTPException(409, 'Draft is not awaiting review')
            if row['expires_at'] <= int(time.time()): raise HTTPException(409, 'Draft has expired')
            state = c.execute(text("SELECT a.enabled,t.stopped FROM agents a JOIN tenants t ON t.id=a.tenant "
                "WHERE a.tenant=:t AND a.id='email-support'"), {'t':tenant}).one()
            if decision == 'APPROVED' and (not state.enabled or state.stopped != row['epoch']):
                raise HTTPException(409, 'Agent stopped; this draft cannot be approved')
            c.execute(update(jobs).where(jobs.c.tenant == tenant,jobs.c.execution_id == execution)
                      .values(status=decision))
            c.execute(text('UPDATE executions SET status=:s WHERE id=:id AND tenant=:t'),
                      {'s':decision,'id':execution,'t':tenant})
            self.audit(c,tenant,'email.' + decision.lower() + '.' + execution)
        emit('email.review', status=decision)
        return {'execution_id':execution,'status':decision,'sent':False}

    def purge(self):
        """Keep deduplication tombstones and metadata, remove expired review content."""
        now = int(time.time())
        with self.engine.connect() as c:
            tenants = c.execute(select(jobs.c.tenant).where(jobs.c.expires_at <= now,
                jobs.c.content.is_not(None)).distinct()).scalars().all()
        for tenant in tenants:
            with self.transaction(tenant) as c:
                expired = c.execute(select(jobs.c.execution_id).where(jobs.c.tenant==tenant,
                    jobs.c.expires_at<=now,jobs.c.status.in_(['QUEUED','WAITING_FOR_REVIEW']))).scalars().all()
                if expired:
                    c.execute(update(jobs).where(jobs.c.tenant==tenant,jobs.c.execution_id.in_(expired))
                        .values(status='FAILED',error='content_expired',completed_at=now))
                    for execution in expired:
                        c.execute(text("UPDATE executions SET status='FAILED' WHERE tenant=:t AND id=:id"),
                                  {'t':tenant,'id':execution})
                        self.audit(c,tenant,'email.content_expired.'+execution)
                c.execute(update(jobs).where(jobs.c.tenant==tenant,jobs.c.expires_at<=now,
                    jobs.c.status!='RUNNING').values(content=None,guidance=None,subject=None,draft=None))
