"""Choose a disposable database before any test imports the application."""
import os
import tempfile

_database = tempfile.TemporaryDirectory(prefix='soloai-tests-')
os.environ['DATABASE_URL'] = 'sqlite:///' + _database.name + '/test.db'
os.environ['SOLOAI_ENV'] = 'development'
os.environ['SOLOAI_EMAIL_WORKFLOWS'] = 'false'
os.environ['SOLOAI_INIT_SCHEMA'] = 'true'
for key in ('AZURE_OPENAI_ENDPOINT','AZURE_FOUNDRY_PROJECT_ENDPOINT','SOLOAI_METRICS_PORT'):
    os.environ.pop(key, None)
