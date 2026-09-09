"""Run daily from a job with private database access; never load customer content."""
import time
from sqlalchemy import text
from app.main import engine
with engine.begin() as c:
    c.execute(text('DELETE FROM sessions WHERE expires<:now'),{'now':int(time.time())})
    for table in ['executions','audit']:
        c.execute(text(f'DELETE FROM {table} WHERE created<:cutoff'),{'cutoff':int(time.time())-30*86400})
    c.execute(text('DELETE FROM auth_limits WHERE key<:cutoff'),{'cutoff':str(int(time.time())//3600-24)+':'})
