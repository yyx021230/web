import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import func, select
from app.db.session import async_session
from app.models.ai_task import AITask
from app.models.prompt import PromptCategory, PromptExample
from app.models.prompt_moderation import PromptAuditLog
from app.models.user import User

spec = importlib.util.spec_from_file_location('catalog_import', Path(__file__).parents[2] / 'scripts/windows/import_hermes_catalog.py')
importer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(importer)


@pytest.mark.asyncio
async def test_import_is_additive_idempotent_and_keeps_original_task(client):
    async with async_session() as db:
        admin = User(username='catalog-admin', email='catalog-admin@example.test', hashed_password='unused', role='admin')
        db.add(admin)
        await db.flush()
        source = AITask(user_id=admin.id, model_name='existing', prompt='历史原始提示词，不改写', status='completed', result_urls=['/uploads/ai-images/existing.png'])
        db.add(source)
        await db.flush()
        row = {'source_task_id': source.id, 'chinese': source.prompt, 'image_url': 'http://approved.test/uploads/ai-images/existing.png',
               'prompt_sha256': importer.fingerprint(source.prompt), 'name': '原始参考', 'group': 'cards', 'requirements': '只参考结构'}
        await db.commit()
        dry = await importer.import_entries(db, [row], admin.id)
        assert dry['new'] == 1 and await db.scalar(select(func.count()).select_from(PromptExample)) == 0
        first = await importer.import_entries(db, [row], admin.id, execute=True)
        await db.commit()
        second = await importer.import_entries(db, [row], admin.id, execute=True)
        await db.commit()
        assert first['new'] == 1 and second['new'] == 0 and second['reused'] == 1
        prompt = await db.get(PromptExample, first['items'][0]['prompt_id'])
        assert prompt.chinese_example == source.prompt == row['chinese']
        assert source.status == 'completed' and source.result_urls == ['/uploads/ai-images/existing.png']
        assert await db.scalar(select(func.count()).select_from(PromptAuditLog)) == 1
        with pytest.raises(ValueError, match='Source prompt changed'):
            await importer.import_entries(db, [{**row, 'chinese': '被修改的文字'}], admin.id, execute=True)
        assert await db.scalar(select(func.count()).select_from(PromptExample)) == 1


@pytest.mark.asyncio
async def test_invalid_last_source_prevents_partial_import(client):
    async with async_session() as db:
        admin = User(username='catalog-validation-admin', email='catalog-validation@example.test', hashed_password='unused', role='admin')
        db.add(admin)
        await db.flush()
        source = AITask(user_id=admin.id, model_name='existing', prompt='原始文案', status='completed', result_urls=['/uploads/ai-images/source.png'])
        db.add(source)
        await db.flush()
        row = {'source_task_id': source.id, 'chinese': source.prompt, 'image_url': '/uploads/ai-images/source.png',
               'prompt_sha256': importer.fingerprint(source.prompt), 'name': '原图', 'group': 'hero', 'requirements': ''}
        with pytest.raises(ValueError):
            await importer.import_entries(db, [row, {**row, 'source_task_id': source.id + 1}], admin.id, execute=True)
        assert await db.scalar(select(func.count()).select_from(PromptExample)) == 0
        assert await db.scalar(select(func.count()).select_from(PromptCategory)) == 0
