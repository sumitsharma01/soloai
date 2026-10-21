"""Migration 003: inbox configuration and a separate, durable delivery ledger."""
from sqlalchemy import Table, Column, String, Text, Integer, BigInteger, Boolean, ForeignKeyConstraint, select
from app.email_schema import metadata, versions

labels = Table('inbox_labels', metadata,
    Column('tenant', String(64), primary_key=True), Column('id', String(64), primary_key=True),
    Column('name', String(60), nullable=False), Column('keywords', String(500), nullable=False))
settings = Table('inbox_settings', metadata,
    Column('tenant', String(64), primary_key=True), Column('automatic', Boolean, nullable=False),
    Column('allowed_labels', Text, nullable=False), Column('daily_limit', Integer, nullable=False),
    Column('revision', Integer, nullable=False), Column('enabled_at', BigInteger, nullable=False))
tickets = Table('inbox_tickets', metadata,
    Column('tenant', String(64), primary_key=True), Column('execution_id', String(64), primary_key=True),
    Column('labels', Text, nullable=False), Column('revision', Integer, nullable=False),
    Column('local_guidance', Text, nullable=False), Column('source', Text),
    ForeignKeyConstraint(['tenant','execution_id'], ['email_jobs.tenant','email_jobs.execution_id']))
instructions = Table('inbox_instructions', metadata,
    Column('tenant', String(64), primary_key=True), Column('id', String(64), primary_key=True),
    Column('label_id', String(64)), Column('content', Text, nullable=False),
    Column('active', Boolean, nullable=False), Column('revision', Integer, nullable=False),
    Column('created', BigInteger, nullable=False))
deliveries = Table('inbox_deliveries', metadata,
    Column('tenant', String(64), primary_key=True), Column('execution_id', String(64), primary_key=True),
    Column('status', String(32), nullable=False), Column('actor', String(20), nullable=False),
    Column('created', BigInteger, nullable=False), Column('updated', BigInteger, nullable=False),
    Column('provider_id', String(128)), Column('error', String(80)),
    ForeignKeyConstraint(['tenant','execution_id'], ['email_jobs.tenant','email_jobs.execution_id']))
grants = Table('gmail_send_grants', metadata,
    Column('tenant', String(64), primary_key=True), Column('token_digest', String(64), nullable=False))
consents = Table('gmail_send_consents', metadata,
    Column('state', String(64), primary_key=True), Column('expires', BigInteger, nullable=False))

def migrate(c):
    if not c.execute(select(versions.c.version).where(versions.c.version==3)).first():
        for table in (labels, settings, tickets, instructions, deliveries, grants, consents): table.create(c)
        c.execute(versions.insert().values(version=3))
