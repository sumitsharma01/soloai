"""Live, synthetic email-agent evaluation in a disposable SQLite database.
No mailbox connector is configured and no reply is sent. Azure inference is billable.
"""
import argparse,asyncio,hashlib,json,os,secrets,tempfile,time
from pathlib import Path

CASES=json.loads((Path(__file__).resolve().parents[1]/'evals/email-cases.json').read_text())


def assess(case, detail):
    draft=(detail.get('draft') or '').lower()
    blocked=detail['status']=='FAILED' and detail.get('error')=='model_safety_blocked'
    if blocked and case.get('allow_safety_block'):
        return True, 'safety_blocked'
    checks=[detail['status']=='WAITING_FOR_REVIEW',bool(draft),
        all(term.lower() in draft for term in case.get('required',[])),
        not any(term.lower() in draft for term in case.get('forbidden',[])),
        case['review'] is None or detail.get('needs_human')==case['review'],
        all(name in [tool['tool_name'] for tool in detail['tools']] for name in case.get('tools',[]))]
    return all(checks), 'draft_checked' if all(checks) else 'check_failed'

async def evaluate():
    # Import after choosing an isolated database; never touch the operator's workspace.
    from fastapi.testclient import TestClient
    from sqlalchemy import text
    from app.main import app,engine,IncomingEvent
    from app.email_store import EmailStore
    from app.email_runtime import process_one,configuration,INSTRUCTIONS
    rows=[]
    with TestClient(app) as client:
        result=client.post('/api/auth/register',json={'email':'synthetic@example.test','password':secrets.token_urlsafe(24),'name':'Synthetic evaluation'})
        if result.status_code!=200:raise RuntimeError('Evaluation registration failed')
        client.patch('/api/agents/email-support',json={'enabled':True,'guidance':'Use only approved information.'})
        with engine.begin() as c:
            tenant=c.execute(text('SELECT id FROM tenants')).scalar_one()
            c.execute(text('UPDATE tenants SET budget=100000 WHERE id=:t'),{'t':tenant})
        store=EmailStore(engine)
        for case in CASES:
            client.patch('/api/agents/email-support',json={'enabled':True,'guidance':case['guidance']})
            event=store.enqueue(tenant,IncomingEvent(id=case['id'],type='email.received',content=case['message']),configuration(),3600)
            start=time.monotonic();await process_one(store)
            detail=store.detail(tenant,event['execution_id'])
            passed,outcome=assess(case,detail)
            rows.append({'case':case['id'],'passed':passed,'outcome':outcome,'usage_kind':detail['usage_kind'],'needs_human':detail.get('needs_human'),'status':detail['status'],'error':detail.get('error'),'tokens':detail.get('tokens'),'latency_ms':round((time.monotonic()-start)*1000)})
    return {'created':int(time.time()),'model':os.getenv('AZURE_FOUNDRY_MODEL') or os.getenv('AZURE_OPENAI_DEPLOYMENT'),'agent_version':os.getenv('AZURE_FOUNDRY_EMAIL_AGENT_VERSION'),'instructions_sha256':hashlib.sha256(INSTRUCTIONS.encode()).hexdigest(),'results':rows,'total_tokens_or_reserved':sum(row['tokens'] for row in rows),'p95_latency_ms':sorted(row['latency_ms'] for row in rows)[__import__('math').ceil(len(rows)*.95)-1],'passed':sum(row['passed'] for row in rows),'total':len(rows),'limitations':'Synthetic phrase and escalation checks, not a security certification or semantic accuracy guarantee.'}

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--live',action='store_true');parser.add_argument('--output',default='evals/email-latest.json');args=parser.parse_args()
    if not args.live:print(f'{len(CASES)} synthetic cases ready. Pass --live to authorize billable inference.');return
    with tempfile.TemporaryDirectory(prefix='soloai-evaluation-') as directory:
        os.environ.update(SOLOAI_ENV='development',DATABASE_URL='sqlite:///'+directory+'/evaluation.db',SOLOAI_EMAIL_WORKFLOWS='true',SOLOAI_INIT_SCHEMA='true')
        for key in ('GMAIL_CLIENT_FILE','OUTLOOK_CLIENT_FILE','SOLOAI_MCP_CONFIG_FILE','SOLOAI_METRICS_PORT'):os.environ.pop(key,None)
        report=asyncio.run(evaluate())
        Path(args.output).write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({'passed':report['passed'],'total':report['total']}))
    if report['passed']!=report['total']:raise SystemExit(1)
if __name__=='__main__':main()
