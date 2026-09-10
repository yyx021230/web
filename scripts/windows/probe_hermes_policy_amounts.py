"""Read-only API policy and historical-row fingerprints before/after update."""
import argparse
import asyncio
import hashlib
import json
from pathlib import Path
from sqlalchemy import select,text
from app.db.session import async_session,engine
from app.models.prompt import PromptExample
from app.models.copywriting import Copywriting
from app.models.hermes_workflow import HermesWorkflowRun,HermesWorkflowPost,HermesWorkflowSchedule
from app.services.hermes_policy_service import _cases_path,load_policy_cases,policy_summaries


def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False,default=str).encode()).hexdigest()


async def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--before',type=Path)
    parser.add_argument('--expected-cases',type=Path)
    args=parser.parse_args()
    result={'row_hashes':{},'generation_requests':0}
    async with async_session() as db:
        await db.execute(text('SET TRANSACTION READ ONLY'))
        for model in (PromptExample,Copywriting,HermesWorkflowRun,HermesWorkflowPost,HermesWorkflowSchedule):
            rows=(await db.execute(select(model.__table__))).mappings()
            result['row_hashes'][model.__tablename__]={str(r['id']):digest(dict(r)) for r in rows}
        result['runs']=[dict(r) for r in (await db.execute(text('SELECT status,count(*) FROM hermes_workflow_runs GROUP BY status'))).mappings()]
        result['schedules']=[dict(r) for r in (await db.execute(text('SELECT id,enabled FROM hermes_workflow_schedules ORDER BY id'))).mappings()]
        await db.rollback()
    cases=load_policy_cases()
    result['policy_sha256']=hashlib.sha256(_cases_path().read_bytes()).hexdigest()
    result['policies']=[{'case':id,'model':c['vehicle_model'],'rows':len(c['quote_rows']),'source':c['policy_source_url'],'benefits':c.get('packaged_benefit_value')} for id,c in cases.items()]
    if args.expected_cases:
        expected=json.loads(args.expected_cases.read_text())
        assert cases==expected, 'API reads a different policy file'
        summaries=policy_summaries()
        assert len(summaries)==11
        assert sum(len(c['quote_rows']) for c in summaries)==58
        assert all(r['provincial_trade_in_after_price'].startswith('¥') for c in summaries for r in c['quote_rows'])
        assert cases['a05-current']['quote_rows'][0]['provincial_trade_in_after_price']=='¥58,788'
        assert all(not c['publication_constraints']['hide_local_subsidy_amounts'] for c in cases.values())
    if args.before:
        before=json.loads(args.before.read_text())
        changed=[f'{table}:{id}' for table,rows in before['row_hashes'].items() for id,sha in rows.items() if result['row_hashes'][table].get(id)!=sha]
        result['old_rows_unchanged']=not changed
        result['changed_old_rows']=changed
        assert not changed, 'Historical data changed; inspect, do not overwrite user activity'
    args.output.write_text(json.dumps(result,ensure_ascii=False,indent=2))
    print(json.dumps({k:v for k,v in result.items() if k!='row_hashes'},ensure_ascii=False))
    await engine.dispose()


if __name__=='__main__':
    asyncio.run(main())
