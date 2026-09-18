"""Additive migration 001: durable email jobs and support data. No existing tables are replaced."""
from sqlalchemy import (MetaData, Table, Column, String, Text, Integer, BigInteger,
                        Boolean, ForeignKey, ForeignKeyConstraint, UniqueConstraint, CheckConstraint, Index, select)

metadata = MetaData()
# Reference existing tables without recreating or altering their data.
Table('tenants', metadata, Column('id', Text, primary_key=True))
Table('executions', metadata, Column('id', Text, primary_key=True))
versions = Table('soloai_migrations', metadata, Column('version', Integer, primary_key=True))
jobs = Table('email_jobs', metadata,
    Column('execution_id', String(64), ForeignKey('executions.id'), primary_key=True),
    Column('tenant', String(64), ForeignKey('tenants.id'), nullable=False),
    Column('event_id', String(128), nullable=False),
    Column('event_digest', String(64), nullable=False),
    Column('content', Text), Column('guidance', Text),
    Column('subject', Text), Column('draft', Text), Column('needs_human', Boolean),
    Column('status', String(32), nullable=False), Column('error', String(64)),
    Column('epoch', Integer, nullable=False), Column('attempts', Integer, nullable=False, default=0),
    Column('available_at', BigInteger, nullable=False), Column('lease_until', BigInteger),
    Column('owner', String(64)), Column('started_at', BigInteger),
    Column('created_at', BigInteger, nullable=False), Column('completed_at', BigInteger),
    Column('expires_at', BigInteger, nullable=False),
    Column('model', String(128), nullable=False), Column('agent_name', String(128), nullable=False),
    Column('agent_version', String(64), nullable=False),
    Column('reserved_tokens', Integer, nullable=False, default=0),
    Column('uncertain_tokens', Integer, nullable=False, default=0),
    Column('provider_calls', Integer, nullable=False, default=0),
    Column('provider_latency', Integer, nullable=False, default=0),
    Column('tool_calls_count', Integer, nullable=False, default=0),
    UniqueConstraint('tenant', 'event_id', name='uq_email_tenant_event'),
    UniqueConstraint('tenant', 'execution_id', name='uq_email_tenant_execution'),
    CheckConstraint("status IN ('QUEUED','RUNNING','WAITING_FOR_REVIEW','APPROVED','REJECTED','FAILED','COMPLETED')", name='ck_email_status'),
    CheckConstraint('reserved_tokens >= 0 AND uncertain_tokens >= 0', name='ck_email_tokens'))
Index('ix_email_queue', jobs.c.status, jobs.c.available_at)
Index('ix_email_review', jobs.c.tenant, jobs.c.created_at)
tool_calls = Table('email_tool_calls', metadata,
    Column('id', String(64), primary_key=True), Column('tenant', String(64), nullable=False),
    Column('execution_id', String(64), nullable=False),
    Column('tool_name', String(32), nullable=False), Column('status', String(32), nullable=False),
    Column('duration', Integer, nullable=False), Column('created_at', BigInteger, nullable=False),
    ForeignKeyConstraint(['tenant','execution_id'],['email_jobs.tenant','email_jobs.execution_id']))
bookings = Table('support_bookings', metadata,
    Column('tenant', String(64), ForeignKey('tenants.id'), primary_key=True), Column('booking_id', String(80), primary_key=True),
    Column('status', String(40), nullable=False), Column('change_allowed', Boolean, nullable=False))
policies = Table('support_policies', metadata,
    Column('tenant', String(64), ForeignKey('tenants.id'), primary_key=True), Column('id', String(64), primary_key=True),
    Column('title', String(200), nullable=False), Column('content', Text, nullable=False))


def migrate(engine):
    if engine.dialect.name not in ('postgresql', 'sqlite'):
        raise RuntimeError('Email workflows require PostgreSQL (SQLite for development only)')
    # A deployment runs migrations once, before API/worker rollout. PostgreSQL also
    # serializes concurrent migration invocations with a transaction-scoped lock.
    with engine.begin() as c:
        if engine.dialect.name == 'postgresql':
            from sqlalchemy import text
            c.execute(text('SELECT pg_advisory_xact_lock(72651001)'))
        versions.create(c, checkfirst=True)
        if not c.execute(select(versions.c.version).where(versions.c.version == 1)).first():
            for table in (jobs, tool_calls, bookings, policies):
                table.create(c)
            c.execute(versions.insert().values(version=1))
        from app.gmail import migrate as migrate_gmail
        migrate_gmail(c)
