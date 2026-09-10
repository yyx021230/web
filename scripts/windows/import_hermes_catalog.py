"""Idempotent, audited import of the 108 approved historical layout sources.

Run inside Hermes API. Default: read-only validation. --execute is the only
write mode. Existing prompts, images, runs, policies and schedules are untouched.
"""
from __future__ import annotations
import argparse
import asyncio
import datetime as dt
import hashlib
import json
from pathlib import Path
from urllib.parse import urlsplit

from sqlalchemy import select, text
from app.db.session import async_session, engine
from app.models.ai_task import AITask
from app.models.prompt import PromptCategory, PromptExample
from app.models.prompt_moderation import PromptAuditLog
from app.models.user import User

CATEGORY = '历史任务精选 · 版式参考'


def fingerprint(value):
    return hashlib.sha256(value.strip().encode()).hexdigest()


async def import_entries(db, items, operator_id, *, execute=False):
    admin = await db.get(User, operator_id)
    if admin is None or admin.role != 'admin':
        raise ValueError('Import operator is not an administrator')
    if len({row['source_task_id'] for row in items}) != len(items):
        raise ValueError('Duplicate manifest source ID')
    # Validate ALL sources before adding even one prompt/category.
    for row in items:
        source = await db.get(AITask, row['source_task_id'])
        if source is None or source.status != 'completed' or source.prompt != row['chinese']:
            raise ValueError(f'Source prompt changed: {row["source_task_id"]}')
        if fingerprint(row['chinese']) != row['prompt_sha256']:
            raise ValueError('Manifest fingerprint mismatch')
        image_path = urlsplit(row['image_url']).path
        if not image_path.startswith('/uploads/ai-images/') or '..' in image_path.split('/'):
            raise ValueError('Unexpected historical image path')
        if image_path not in {urlsplit(url).path for url in source.result_urls or []}:
            raise ValueError(f'Source image mismatch: {row["source_task_id"]}')
    # An active category is required too; a hidden/private original isn't made public.
    old = list((await db.execute(select(PromptExample).join(PromptCategory).where(
        PromptExample.deleted_at.is_(None), PromptCategory.deleted_at.is_(None),
        PromptExample.is_public.is_(True),
    ).order_by(PromptExample.id))).scalars())
    by_hash = {}
    for prompt in old:
        by_hash.setdefault(fingerprint(prompt.chinese_example), prompt)
    category = await db.scalar(select(PromptCategory).where(PromptCategory.name == CATEGORY, PromptCategory.deleted_at.is_(None)))
    results = []
    for row in items:
        prompt = by_hash.get(row['prompt_sha256'])
        reused = prompt is not None
        if not reused and execute:
            if category is None:
                category = PromptCategory(name=CATEGORY, start_intro='已确认的历史成图版式；仅复用结构，旧车型和政策不作为当前事实。', sort_order=0)
                db.add(category)
                await db.flush()
            prompt = PromptExample(category_id=category.id, param_type=row['group'],
                name=row['name'], chinese_example=row['chinese'], english_example='',
                image_url=urlsplit(row['image_url']).path, is_public=True,
                created_by=operator_id, updated_by=operator_id,
                ul_list=[f'来源：历史生图任务 #{row["source_task_id"]}', row['requirements']], sort_order=0)
            db.add(prompt)
            await db.flush()
            by_hash[row['prompt_sha256']] = prompt
            db.add(PromptAuditLog(prompt_id=prompt.id, action='import', operator_id=operator_id,
                details=json.dumps({'source': 'approved-cleaned-final-20260908', 'source_task_id': row['source_task_id'],
                                    'prompt_sha256': row['prompt_sha256'], 'group': row['group'],
                                    'merged_task_ids': row.get('merged_task_ids', [])}, ensure_ascii=False)))
        results.append({'source_task_id': row['source_task_id'], 'prompt_id': prompt.id if prompt else None,
                        'action': 'reuse' if reused else 'create', 'group': row['group'], 'prompt_sha256': row['prompt_sha256']})
    return {'items': results, 'new': sum(r['action'] == 'create' for r in results),
            'reused': sum(r['action'] == 'reuse' for r in results), 'generation_requests': 0}


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--receipt', type=Path, required=True)
    parser.add_argument('--execute', action='store_true')
    parser.add_argument('--operator-id', type=int, default=1)
    args = parser.parse_args()
    manifest = json.loads(args.manifest.read_text(encoding='utf-8'))
    if manifest['version'] != 1 or len(manifest['items']) != 108:
        raise ValueError('Expected the approved 108-entry manifest')
    registry = Path('/app/app/data/hermes_image_curation.json')
    if args.execute and hashlib.sha256(registry.read_bytes()).hexdigest() != manifest['registry_sha256']:
        raise ValueError('Running classifier and manifest registry differ')
    async with async_session() as db:
        if args.execute:
            await db.execute(text('SELECT pg_advisory_xact_lock(20260908, 322)'))
        else:
            await db.execute(text('SET TRANSACTION READ ONLY'))
        result = await import_entries(db, manifest['items'], args.operator_id, execute=args.execute)
        result.update(executed=args.execute, manifest_sha256=hashlib.sha256(args.manifest.read_bytes()).hexdigest(),
                      at=dt.datetime.now(dt.timezone.utc).isoformat())
        # A prepared receipt remains useful if commit response is lost. Retry is
        # idempotent by original text; it never adds an ambiguous second copy.
        prepared = args.receipt.with_suffix('.prepared.json')
        prepared.parent.mkdir(parents=True, exist_ok=True)
        prepared.write_text(json.dumps(result, ensure_ascii=False, indent=2))
        if args.execute:
            await db.commit()
        else:
            await db.rollback()
    args.receipt.write_text(json.dumps(result, ensure_ascii=False, indent=2))
    print(json.dumps({k: v for k, v in result.items() if k != 'items'}, ensure_ascii=False))
    await engine.dispose()


if __name__ == '__main__':
    asyncio.run(main())
