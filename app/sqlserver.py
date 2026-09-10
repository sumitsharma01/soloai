"""SQL Server equivalents for the few SQLite/PostgreSQL-specific statements."""
import re

def statement(sql):
    if sql.startswith('CREATE TABLE IF NOT EXISTS '):
        name=sql.split()[5]
        sql=sql.replace('CREATE TABLE IF NOT EXISTS','CREATE TABLE').replace('TEXT','NVARCHAR(255)')
        sql=re.sub(r'\b(id|tenant|token|salt|password) NVARCHAR\(255\)', r'\1 VARCHAR(64)',sql)
        sql=sql.replace('key NVARCHAR(255)','key VARCHAR(128)')
        sql=sql.replace('guidance NVARCHAR(255)','guidance NVARCHAR(MAX)')
        sql=f"IF OBJECT_ID(N'dbo.{name}', N'U') IS NULL BEGIN {sql} END"
    elif sql.startswith('CREATE INDEX IF NOT EXISTS '):
        name=sql.split()[5]
        sql=f"IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name=N'{name}') BEGIN "+sql.replace('CREATE INDEX IF NOT EXISTS','CREATE INDEX')+' END'
    elif 'ON CONFLICT (key) DO NOTHING' in sql:
        # Range lock serializes concurrent first requests for the same limiter key.
        sql='IF NOT EXISTS (SELECT 1 FROM auth_limits WITH (UPDLOCK,HOLDLOCK) WHERE [key]=:key) INSERT INTO auth_limits ([key],count) VALUES (:key,0)'
    if 'LIMIT ' in sql:
        match=re.search(r' LIMIT (\d+)$',sql)
        if match: sql=sql[:match.start()].replace('SELECT ',f'SELECT TOP {match[1]} ',1)
    return re.sub(r'(?<!:)\bkey\b','[key]',sql).replace('[[key]]','[key]')
