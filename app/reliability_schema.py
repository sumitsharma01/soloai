"""Migration 005: restricted connectors, explicit customer verification and alert delivery."""
from sqlalchemy import Table,Column,String,Text,Integer,BigInteger,Boolean,ForeignKeyConstraint,Index,select
from app.email_schema import metadata,versions
connectors=Table('booking_connections',metadata,
    Column('tenant',String(64),primary_key=True),Column('url',String(300),nullable=False),
    Column('secret',Text,nullable=False),Column('revision',Integer,nullable=False),Column('created',BigInteger,nullable=False))
identities=Table('email_verified_customers',metadata,
    Column('tenant',String(64),primary_key=True),Column('execution_id',String(64),primary_key=True),
    Column('customer_id',String(100),nullable=False),Column('expires',BigInteger,nullable=False),
    ForeignKeyConstraint(['tenant','execution_id'],['email_jobs.tenant','email_jobs.execution_id']))
alerts=Table('email_alert_outbox',metadata,
    Column('id',String(64),primary_key=True),Column('tenant',String(64),nullable=False),
    Column('kind',String(40),nullable=False),Column('subject_id',String(64),nullable=False),
    Column('status',String(20),nullable=False),Column('attempts',Integer,nullable=False),
    Column('available',BigInteger,nullable=False),Column('owner',String(64)),Column('created',BigInteger,nullable=False))
Index('ix_email_alert_available',alerts.c.status,alerts.c.available)

def migrate(c):
    if not c.execute(select(versions.c.version).where(versions.c.version==5)).first():
        for table in (connectors,identities,alerts):table.create(c)
        c.execute(versions.insert().values(version=5))
