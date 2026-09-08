"""Bounded, user-authorized layout acceptance; default is read-only.

Run in the Hermes API container. Queue through the same validated service used
by Web routes as administrator 1, preserving account 42's owner 3. No login or
account assignment changes. Never approve/publish, alter policy or turn on cron.
Each explicitly requested type can create only one named acceptance run.
"""
import argparse
import asyncio
import json

from sqlalchemy import select, text
from app.db.session import async_session
from app.models.hermes_workflow import HermesWorkflowRun, HermesWorkflowSchedule
from app.models.user import User
from app.services.hermes_workflow_service import HermesWorkflowService, serialize_run

TYPES = {'photo_collage': 568, 'feature_infographic': 332}


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--create', choices=list(TYPES))
    args = parser.parse_args()
    async with async_session() as db:
        assert not await db.scalar(select(HermesWorkflowSchedule.id).where(HermesWorkflowSchedule.enabled.is_(True)))
        admin = await db.get(User, 1)
        assert admin and admin.role == 'admin'
        service = HermesWorkflowService(db)
        if args.create:
            # Serialise this acceptance command; an uncertain POST is never repeated.
            await db.execute(text('SELECT pg_advisory_xact_lock(20260908, 321)'))
        results = []
        for kind, expected in TYPES.items():
            name = f'图片分类上线验收 0.3.21 · {kind}'
            run = await db.scalar(select(HermesWorkflowRun).where(HermesWorkflowRun.parameters['name'].as_string() == name))
            if run is None and args.create == kind:
                accounts = await service.validate_accounts([{
                    'environment_id': 42, 'vehicle_model': '零跑A05', 'case_id': 'a05-current',
                }], owner_user_id=None)
                assert len(accounts) == 1 and accounts[0]['owner_user_id'] == 3
                run = await service.create_run(
                    source='manual', requested_by=admin.id, accounts=accounts,
                    posts_per_account=1, name=name, image_type=kind,
                    copy_type='product_features' if kind == 'feature_infographic' else 'policy_news',
                )
            if run is None:
                continue
            full = serialize_run(run)
            entry = {key: full.get(key) for key in ('id', 'status', 'total_posts', 'generated_posts', 'error', 'started_at', 'finished_at')}
            entry['image_type'] = kind
            entry['expected_mother_id'] = expected
            entry['posts'] = []
            for post in run.posts:
                source = post.source_detail or {}
                entry['posts'].append({
                    'id': post.id, 'status': post.status, 'title': post.title,
                    'image_url': post.image_url, 'hard_pass': post.hard_pass,
                    'selected_prompt_id': source.get('selected_prompt_id'),
                    'mother_copy_id': source.get('mother_copy_id'),
                    'publish_status': post.publish_status,
                })
            results.append(entry)
        print(json.dumps({'schedule_enabled': False, 'runs': results}))


if __name__ == '__main__':
    asyncio.run(main())
