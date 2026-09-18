"""Explicit migration, retention cleanup and local fixture setup. Run as a module."""
import argparse
from sqlalchemy import text
from app.main import engine, init_db, PROD
from app.email_schema import migrate, bookings, policies
from app.email_store import EmailStore


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['migrate','purge','seed-demo'])
    parser.add_argument('--workspace-email', help='Existing local demo workspace only')
    args = parser.parse_args()
    if args.action == 'migrate':
        init_db()
        migrate(engine)
    elif args.action == 'purge': EmailStore(engine).purge()
    else:
        if PROD or engine.dialect.name != 'sqlite': raise SystemExit('Demo fixtures are restricted to local SQLite.')
        if not args.workspace_email: raise SystemExit('--workspace-email is required')
        with engine.begin() as c:
            tenant = c.execute(text('SELECT id FROM tenants WHERE email=:email'),
                               {'email':args.workspace_email.lower().strip()}).scalar_one()
            if not c.execute(bookings.select().where(bookings.c.tenant==tenant,bookings.c.booking_id=='BK-2041')).first():
                c.execute(bookings.insert().values(tenant=tenant,booking_id='BK-2041',status='confirmed',change_allowed=True))
            if not c.execute(policies.select().where(policies.c.tenant==tenant,policies.c.id=='demo-changes')).first():
                c.execute(policies.insert().values(tenant=tenant,id='demo-changes',title='Demo booking changes',
                    content='Confirmed bookings may be changed subject to availability. A human must review all changes.'))
    print('Email administration completed.')


if __name__ == '__main__': main()
