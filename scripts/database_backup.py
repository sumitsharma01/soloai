"""Explicit backup/restore. Restore requires a separate, empty target database."""
import argparse,os,sqlite3,subprocess
from pathlib import Path
from sqlalchemy import create_engine,inspect
from sqlalchemy.engine import make_url


def pg_environment(url):
    parsed=make_url(url);env=dict(os.environ)
    env.update(PGHOST=parsed.host or '',PGPORT=str(parsed.port or 5432),PGUSER=parsed.username or '',PGPASSWORD=parsed.password or '',PGDATABASE=parsed.database or '')
    for key in ('sslmode','sslrootcert'):
        if key in parsed.query:env['PG'+key.upper()]=parsed.query[key]
    return env


def backup(url,output):
    path=Path(output)
    # Never overwrite an earlier backup. File access is owner-only from creation.
    fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600);os.close(fd)
    parsed=make_url(url)
    try:
        if parsed.get_backend_name()=='sqlite':
            with sqlite3.connect('file:'+str(Path(parsed.database).resolve())+'?mode=ro',uri=True) as source,sqlite3.connect(path) as target:source.backup(target)
        elif parsed.get_backend_name()=='postgresql':
            subprocess.run(['pg_dump','--format=custom','--file='+str(path)],env=pg_environment(url),check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        else:raise ValueError('Only PostgreSQL and local SQLite are supported')
    except BaseException:
        path.unlink(missing_ok=True);raise


def restore(source_url,target_url,backup_file):
    if make_url(source_url)==make_url(target_url):raise ValueError('Restore target must differ from source')
    parsed=make_url(target_url)
    if parsed.get_backend_name()=='sqlite':
        path=Path(parsed.database)
        if path.exists():raise ValueError('SQLite restore target must not exist')
        fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600);os.close(fd)
        with sqlite3.connect('file:'+str(Path(backup_file).resolve())+'?mode=ro',uri=True) as source,sqlite3.connect(path) as target:
            source.backup(target)
            if target.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise ValueError('Integrity check failed')
    elif parsed.get_backend_name()=='postgresql':
        engine=create_engine(target_url)
        try:
            if any(inspect(engine).get_table_names(schema=s) for s in inspect(engine).get_schema_names() if s not in ('information_schema','pg_catalog')):raise ValueError('Restore target must be empty')
            subprocess.run(['pg_restore','--exit-on-error','--single-transaction','--no-owner','--no-privileges','--dbname='+str(parsed.database),str(backup_file)],env=pg_environment(target_url),check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        finally:engine.dispose()
    else:raise ValueError('Unsupported database')


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('action',choices=['backup','restore']);parser.add_argument('file');args=parser.parse_args()
    try:
        if args.action=='backup':backup(os.environ['DATABASE_URL'],args.file)
        else:restore(os.environ['DATABASE_URL'],os.environ['SOLOAI_RESTORE_DATABASE_URL'],args.file)
    except Exception:raise SystemExit('Database operation failed. Check tools, permissions, source and empty restore target. No credentials are logged.') from None
    print('Database '+args.action+' completed. Validate application access before using the restored database.')
if __name__=='__main__':main()
