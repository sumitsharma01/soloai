"""Run with python -m app.email_worker. Shares the application database, no broker."""
import asyncio
import os
import signal
from app.email_store import EmailStore
from app.email_runtime import process_one
from sqlalchemy.exc import SQLAlchemyError
from app.telemetry import emit


async def serve(engine):
    store = EmailStore(engine)
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM): loop.add_signal_handler(sig, stop.set)
    failures = 0
    while not stop.is_set():
        try:
            store.recover()
            store.purge()
            from app.gmail import sync_one
            await sync_one(store)
            worked = await process_one(store)
            failures = 0
        except SQLAlchemyError:
            # Restore the DB first. Leases reconcile uncertain work when it returns.
            # Keep exception messages/SQL parameters out of worker logs.
            emit('database.unavailable', status='failed')
            failures = min(failures+1,5)
            worked = False
        if not worked:
            try: await asyncio.wait_for(stop.wait(), timeout=min(2**failures,30))
            except TimeoutError: pass


def main():
    from app.main import engine, email_enabled
    if not email_enabled(): raise SystemExit('Set SOLOAI_EMAIL_WORKFLOWS=true; review retention settings first.')
    if engine.dialect.name not in ('postgresql','sqlite'):
        raise SystemExit('Email worker requires PostgreSQL or local SQLite')
    server = None
    # Distinct scrape target from the API; do not start two exporters on one port.
    if os.getenv('SOLOAI_METRICS_PORT'):
        from app.metrics import start
        server, _ = start(int(os.environ['SOLOAI_METRICS_PORT']))
    try: asyncio.run(serve(engine))
    finally:
        if server: server.shutdown(); server.server_close()


if __name__ == '__main__': main()
