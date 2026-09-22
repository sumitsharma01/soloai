"""Create private local-only MCP demo files. Never prints credentials."""
import argparse
import json
import os
import secrets
from pathlib import Path
from sqlalchemy import create_engine, text


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workspace-email',required=True)
    parser.add_argument('--directory',required=True)
    args=parser.parse_args()
    if os.getenv('SOLOAI_ENV')!='development' or not os.getenv('DATABASE_URL','').startswith('sqlite:'):
        parser.error('Local SQLite development only')
    with create_engine(os.environ['DATABASE_URL']).connect() as c:
        tenant=c.execute(text('SELECT id FROM tenants WHERE email=:email'),{'email':args.workspace_email.lower()}).scalar_one()
    root=Path(args.directory).resolve()
    # Avoid accidental commits of connection secrets.
    repo=Path(__file__).resolve().parents[1]
    if root==repo or repo in root.parents: parser.error('Use a directory outside the repository')
    root.mkdir(parents=True,exist_ok=True,mode=0o700)
    token=secrets.token_urlsafe(32)
    files={
        'client.json':{'allowed_urls':['http://127.0.0.1:8400/mcp'],
            'tenants':{tenant:{'url':'http://127.0.0.1:8400/mcp','token':token}}},
        'server.json':{'tenants':{tenant:{'token':token,'bookings':{
            'BK-2041':{'status':'confirmed','change_allowed':True}}}}}}
    if any((root/name).exists() for name in files): parser.error('Files already exist; reuse them')
    for name,data in files.items():
        with os.fdopen(os.open(root/name,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600),'w') as f:
            json.dump(data,f)
    print('Created private client.json and server.json. No live booking system was connected.')

if __name__=='__main__': main()
