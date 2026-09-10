"""Read-only DB/catalog verification; no workflow or image submissions."""
import argparse
import asyncio
import hashlib
import json
from pathlib import Path
from sqlalchemy import select, text
from app.db.session import async_session, engine
from app.models.prompt import PromptExample
from app.models.hermes_workflow import HermesWorkflowRun, HermesWorkflowPost, HermesWorkflowSchedule
from app.models.user import User
from app.services.hermes_reference_service import reference_catalog
from app.services.hermes_policy_service import _cases_path


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--before', type=Path)
    args = parser.parse_args()
    result = {'row_hashes': {}, 'generation_requests': 0}
    async with async_session() as db:
        await db.execute(text('SET TRANSACTION READ ONLY'))
        for model in (PromptExample, HermesWorkflowRun, HermesWorkflowPost, HermesWorkflowSchedule):
            rows = [dict(row) for row in (await db.execute(select(model.__table__))).mappings()]
            result['row_hashes'][model.__tablename__] = {str(row['id']): digest(row) for row in rows}
        result['runs'] = [dict(r) for r in (await db.execute(text('SELECT status,count(*) FROM hermes_workflow_runs GROUP BY status'))).mappings()]
        result['schedules'] = [dict(r) for r in (await db.execute(text('SELECT id,enabled FROM hermes_workflow_schedules ORDER BY id'))).mappings()]
        for user_id in (1, 3):
            user = await db.get(User, user_id)
            if user is None:
                continue
            catalog = await reference_catalog(db, user)
            result[f'catalog_user_{user_id}'] = {key: catalog[key] for key in ('version', 'library_counts')}
            result[f'catalog_user_{user_id}']['types'] = [{key: row.get(key) for key in ('id','name','reference_count','preview_count','production_reference_count','production_without_quote_count')} for row in catalog['image_types']]
            result[f'catalog_user_{user_id}']['example_ids'] = [r['id'] for t in catalog['image_types'] for r in t['examples']]
            if args.before:
                assert len(catalog['image_types']) == 8
                assert len(result[f'catalog_user_{user_id}']['example_ids']) == len(set(result[f'catalog_user_{user_id}']['example_ids']))
        await db.rollback()
    policy = _cases_path()
    assert policy is not None, 'No policy file resolved'
    result['policy_sha256'] = hashlib.sha256(policy.read_bytes()).hexdigest()
    registry = Path('/app/app/data/hermes_image_curation.json')
    result['registry_sha256'] = hashlib.sha256(registry.read_bytes()).hexdigest() if registry.exists() else None
    if args.before:
        before = json.loads(args.before.read_text())
        changes = []
        for table, rows in before['row_hashes'].items():
            changes += [f'{table}:{id}' for id, sha in rows.items() if result['row_hashes'][table].get(id) != sha]
        result['old_rows_unchanged'] = not changes
        result['changed_old_rows'] = changes
        result['policy_unchanged'] = result['policy_sha256'] == before['policy_sha256']
        assert not changes, 'Existing source/history/schedule rows changed; inspect before proceeding'
        assert result['policy_unchanged'], 'Policy unexpectedly changed'
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2))
    print(json.dumps({k:v for k,v in result.items() if k not in {'row_hashes'} and not k.startswith('catalog_user_')}, ensure_ascii=False))
    await engine.dispose()


if __name__ == '__main__':
    asyncio.run(main())
