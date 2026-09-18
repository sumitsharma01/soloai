"""Run daily from a job with private database access; never load customer content."""
import time
from sqlalchemy import text, inspect
from app.main import engine

def cleanup(database=engine):
    has_email = inspect(database).has_table('email_jobs')
    if has_email:
        from app.email_store import EmailStore
        EmailStore(database).purge()
    with database.begin() as c:
        c.execute(text('DELETE FROM sessions WHERE expires<:now'),{'now':int(time.time())})
        for table in ['executions','audit']:
            sql = f'DELETE FROM {table} WHERE created<:cutoff'
            if table == 'executions' and has_email:
                # Preserve email execution/tombstone identity even when the feature
                # is disabled; deleting it would break deduplication and review FKs.
                sql += ' AND NOT EXISTS (SELECT 1 FROM email_jobs j WHERE j.tenant=executions.tenant AND j.execution_id=executions.id)'
            c.execute(text(sql),{'cutoff':int(time.time())-30*86400})
        c.execute(text('DELETE FROM auth_limits WHERE key<:cutoff'),{'cutoff':str(int(time.time())//3600-24)+':'})

if __name__ == '__main__': cleanup()
