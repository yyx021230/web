"""Three user-requested production posts through the normal queue service.

No workflow edits, approval, publishing, scheduling or manual regeneration.
Default is read-only status; --create is idempotent and bounded to these names.
"""
import argparse
import asyncio
import hashlib
import json
from pathlib import Path
from sqlalchemy import select,text
from app.db.session import async_session,engine
from app.models.hermes_workflow import HermesWorkflowRun,HermesWorkflowSchedule
from app.models.user import User
from app.services.hermes_workflow_service import HermesWorkflowService,serialize_run,serialize_post
from app.services.hermes_policy_service import _cases_path,load_policy_cases

SPECS=[('a05-current','零跑A05','price_plan','table'),
       ('c10-current','零跑C10','policy_news','headline'),
       ('lafa5-current','零跑Lafa5','buying_guide','cards')]
PREFIX='9月具体金额实测 0.3.24'


async def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--create',action='store_true')
    parser.add_argument('--export',type=Path)
    args=parser.parse_args()
    async with async_session() as db:
        service=HermesWorkflowService(db)
        if args.create:
            await db.execute(text('SELECT pg_advisory_xact_lock(20260909,32403)'))
            assert hashlib.sha256(_cases_path().read_bytes()).hexdigest()=='1313390f3d30568d5551206034ca923a162a2c388d092182a5404f903e8abb37'
            assert not await db.scalar(select(HermesWorkflowSchedule.id).where(HermesWorkflowSchedule.enabled.is_(True)))
            admin=await db.get(User,1)
            assert admin and admin.is_active and admin.role=='admin'
        results=[]
        for case_id,model,copy_type,image_type in SPECS:
            name=PREFIX+' · '+model
            run=await db.scalar(select(HermesWorkflowRun).where(HermesWorkflowRun.parameters['name'].as_string()==name))
            if run is None and args.create:
                accounts=await service.validate_accounts([{'environment_id':42,'vehicle_model':model,'case_id':case_id}])
                assert len(accounts)==1 and accounts[0]['owner_user_id']==3
                case=load_policy_cases()[case_id]
                assert not case['publication_constraints']['hide_local_subsidy_amounts']
                instruction='复刻母文母图原有结构。原文或原图已有省补、置换或价格槽时，可引用当前9月原表对应车型配置的具体金额，保留适用条件及测算口径；没有金额槽就不要硬加，不把补贴后车价当落地价，不自行叠加权益。'
                run=await service.create_run(source='manual',requested_by=admin.id,accounts=accounts,
                    posts_per_account=1,name=name,copy_type=copy_type,image_type=image_type,
                    instruction=instruction,commit=False)
            if run:
                run=await service.get_run(run.id)
                full=serialize_run(run)
                full['posts']=[serialize_post(p) for p in run.posts]
                results.append(full)
        if args.create:
            await db.commit()
        else:
            await db.rollback()
    if args.export:
        args.export.write_text(json.dumps({'runs':results},ensure_ascii=False,indent=2))
    summary=[]
    for r in results:
        entry={k:r.get(k) for k in ('id','status','total_posts','generated_posts','failed_posts','error','created_at','started_at','finished_at')}
        entry['posts']=[{k:p.get(k) for k in ('id','account_name','vehicle_model','status','title','image_url','hard_pass','error','publish_status')} for p in r['posts']]
        summary.append(entry)
    print(json.dumps({'expected_posts':3,'runs':summary,'manual_regenerations':0,'publishing_requested':False},ensure_ascii=False))
    await engine.dispose()


if __name__=='__main__':
    asyncio.run(main())
