from app.sqlserver import statement

def test_ddl_uses_bounded_index_keys_and_unicode_guidance():
    result=statement("CREATE TABLE IF NOT EXISTS agents (tenant TEXT NOT NULL, id TEXT NOT NULL, guidance TEXT NOT NULL, PRIMARY KEY (tenant,id))")
    assert "OBJECT_ID" in result and 'tenant VARCHAR(64)' in result
    assert 'guidance NVARCHAR(MAX)' in result
    assert 'IF NOT EXISTS agents' not in result

def test_limit_and_atomic_limiter_translation():
    assert statement('SELECT id FROM executions ORDER BY created DESC LIMIT 30')=='SELECT TOP 30 id FROM executions ORDER BY created DESC'
    sql=statement('INSERT INTO auth_limits (key,count) VALUES (:key,0) ON CONFLICT (key) DO NOTHING')
    assert 'UPDLOCK,HOLDLOCK' in sql and 'WHERE [key]=:key' in sql
    assert statement('UPDATE auth_limits SET count=count+1 WHERE key=:key')=='UPDATE auth_limits SET count=count+1 WHERE [key]=:key'
