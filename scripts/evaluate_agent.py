"""Opt-in synthetic Foundry evaluation. Reports contain checks and metadata only."""
import argparse, hashlib, json, os, sys, time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from app import foundry

def grade(case, reply):
    output=(reply.subject+' '+reply.reply).casefold()
    return {'required_facts':all(x.casefold() in output for x in case['required']),
            'forbidden_phrases_absent':all(x.casefold() not in output for x in case['forbidden']),
            'escalation':case['needs_human'] is None or reply.needs_human==case['needs_human']}

def run(cases, invoke, repeats):
    rows=[]
    for repeat in range(repeats):
        for case in cases:
            start=time.monotonic()
            try:
                answer,tokens=invoke(foundry.envelope(case['agent'],case['guidance'],case['message']))
                checks={'contract':True,**grade(case,answer)}
                row={'checks':checks,'tokens':tokens,'passed':all(checks.values()),'status':'completed'}
            except Exception:
                row={'checks':{'contract':False},'tokens':None,'passed':False,'status':'error'}
            rows.append({'case':case['id'],'category':case['category'],'repeat':repeat+1,'latency_ms':round((time.monotonic()-start)*1000),**row})
    return rows

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--live',action='store_true',help='Authorize billable synthetic Foundry calls')
    parser.add_argument('--repeats',type=int,default=1,choices=range(1,6))
    parser.add_argument('--output',default=str(ROOT/'evals/latest.json'))
    args=parser.parse_args()
    cases=json.loads((ROOT/'evals/cases.json').read_text())
    if not args.live:
        print(f'{len(cases)} synthetic cases ready. Use --live to run paid inference.');return
    rows=run(cases,foundry.invoke,args.repeats)
    report={'schema':1,'created':int(time.time()),'agent':os.environ['AZURE_FOUNDRY_AGENT_NAME'],'version':os.environ['AZURE_FOUNDRY_AGENT_VERSION'],'model':os.environ['AZURE_FOUNDRY_MODEL'],'instructions_sha256':hashlib.sha256(foundry.INSTRUCTIONS.encode()).hexdigest(),'suite_sha256':hashlib.sha256((ROOT/'evals/cases.json').read_bytes()).hexdigest(),'passed':sum(r['passed'] for r in rows),'total':len(rows),'reported_tokens':sum(r['tokens'] or 0 for r in rows),'results':rows,'limitations':'Synthetic phrase checks only. Not a security certification, semantic correctness score or proof of tenant isolation. Error token costs may be unknown.'}
    Path(args.output).write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({k:report[k] for k in ['passed','total','reported_tokens']}))
    if report['passed']!=report['total']: sys.exit(1)
if __name__=='__main__': main()
