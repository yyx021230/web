from __future__ import annotations

import asyncio
import io
import json
import uuid
from datetime import timedelta

import pytest
from PIL import Image
from sqlalchemy import delete, func, select

from app.adapters.storage.local import LocalStorageAdapter
from app.config import settings
from app.db.session import async_session
from app.models.hermes_publish import HermesPublishJob
from app.models.hermes_workflow import HermesWorkflowPost, HermesWorkflowRun
from app.models.user import User
from app.models.user_xhs_env import UserXHSEnvironment
from app.models.xhs_environment import XHSEnvironment
from app.services.hermes_publish_service import HermesPublishWorker
from app.services.hermes_workflow_service import post_version
from app.utils.timezone import cst_now_naive
from tests.conftest import make_auth_headers
from tests.test_cloud_phone_publish import FakePhone
from tests.test_hermes_workflows import seed_owner


def picture(color='blue', kind='PNG'):
    stream = io.BytesIO()
    Image.new('RGB', (24, 32), color).save(stream, format=kind)
    return stream.getvalue()


@pytest.fixture
def upload_config(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, 'storage_path', str(tmp_path / 'uploads'))
    monkeypatch.setattr(settings, 'phone_cloud_publish_snapshot_path', str(tmp_path / 'private'))
    monkeypatch.setattr(settings, 'phone_cloud_publish_enabled', True)
    monkeypatch.setattr(settings, 'phone_cloud_publish_verified_xhs_ids', 'stable-test-account')
    monkeypatch.setattr(settings, 'phone_cloud_publish_max_images', 5)
    storage = LocalStorageAdapter()
    monkeypatch.setattr('app.services.hermes_upload_service.get_storage', lambda: storage)
    return storage


def metadata(env_id, **values):
    return {'environment_id': env_id, 'request_id': str(uuid.uuid4()),
            'title': '周末看车指南', 'content': '分享看车体验，保留原始文案。#看车', **values}


async def upload(client, headers, data, images=None):
    return await client.post('/api/v1/hermes-workflows/upload-post', headers=headers,
                             data={'metadata': json.dumps(data)},
                             files=[('files', (name, content, mime)) for name, content, mime in
                                    (images if images is not None else [('image.png', picture(), 'image/png')])])


@pytest.mark.asyncio
async def test_upload_review_schedule_worker_order_and_durability(client, upload_config):
    user_id, env_id = await seed_owner()
    headers = make_auth_headers(user_id)
    response = await upload(client, headers, metadata(env_id), [
        ('cover.png', picture('red'), 'image/png'), ('second.jpg', picture('green', 'JPEG'), 'image/jpeg')])
    assert response.status_code == 200, response.text
    post = response.json()['data']
    assert post['status'] == 'review_pending' and post['source_kind'] == 'user_upload'
    assert post['reviewed_at'] is None and post['reviewed_by'] is None
    assert len(post['image_urls']) == 2 and post['image_url'] == post['image_urls'][0]
    assert post['source_detail']['validation_scope'] == 'file_integrity_only'
    assert post['source_detail']['events'][0]['action'] == 'upload'
    async with async_session() as db:
        assert await db.scalar(select(func.count()).select_from(HermesPublishJob)) == 0
        assert (await db.get(HermesWorkflowRun, post['run_id'])).status == 'review_pending'
    # Uploaded drafts are recoverable here, but are not AI production history.
    drafts = (await client.get('/api/v1/hermes-workflows/publish-candidates', headers=headers)).json()['data']
    assert drafts['items'][0]['image_urls'] == post['image_urls']
    assert (await client.get('/api/v1/hermes-workflows/runs', headers=headers)).json()['data']['total'] == 0
    item = {'post_id': post['id'], 'environment_id': env_id, 'expected_version': post['version'],
            'scheduled_at': (cst_now_naive() + timedelta(minutes=5)).isoformat()}
    assert (await client.post('/api/v1/hermes-workflows/publish-plan', headers=headers, json={'items': [item]})).status_code == 409
    assert (await client.post(f"/api/v1/hermes-workflows/posts/{post['id']}/review", headers=headers,
                              json={'action': 'approve', 'expected_version': post['version']})).status_code == 200
    post = (await client.get('/api/v1/hermes-workflows/publish-candidates', headers=headers)).json()['data']['items'][0]
    item['expected_version'] = post['version']
    response = await client.post('/api/v1/hermes-workflows/publish-plan', headers=headers, json={'items': [item]})
    assert response.status_code == 200, response.text
    async with async_session() as db:
        job = await db.scalar(select(HermesPublishJob))
        assert len(job.snapshot['images']) == 2 and job.snapshot['image_urls'] == post['image_urls']
        job.scheduled_at = cst_now_naive() - timedelta(seconds=1)
        await db.commit()
    phone = FakePhone()
    phone.device_rows[0]['xhsAccounts'][0]['xhsId'] = 'stable-test-account'
    await HermesPublishWorker(async_session, phone).tick()
    assert len(phone.created) == 1
    assert [value.split(';')[0] for value in phone.created[0][2]] == ['data:image/png', 'data:image/jpeg']
    phone.rows[0]['status'] = 'succeeded'
    await HermesPublishWorker(async_session, phone).tick()
    assert (await client.get('/api/v1/hermes-workflows/publish-jobs', headers=headers)).json()['data']['items'][0]['status'] == 'submitted'
    await HermesPublishWorker(async_session, phone).tick()
    assert len(phone.created) == 1


@pytest.mark.asyncio
async def test_upload_idempotency_and_conflicting_payload(client, upload_config):
    user_id, env_id = await seed_owner()
    headers, data = make_auth_headers(user_id), metadata(env_id)
    first = await upload(client, headers, data)
    replay = await upload(client, headers, data)
    assert first.status_code == replay.status_code == 200
    assert first.json()['data']['id'] == replay.json()['data']['id']
    assert (await upload(client, headers, {**data, 'title': '不同内容'})).status_code == 409
    assert (await upload(client, headers, data, [('different.png', picture('red'), 'image/png')])).status_code == 409
    async with async_session() as db:
        assert await db.scalar(select(func.count()).select_from(HermesWorkflowPost)) == 1
    assert len(list(upload_config.storage_path.rglob('*.png'))) == 1


@pytest.mark.asyncio
async def test_account_permissions_and_admin_owner(client, upload_config):
    user_id, env_id = await seed_owner()
    async with async_session() as db:
        stranger = User(username='stranger', email='stranger@example.test', hashed_password='unused', role='viewer', is_active=True)
        admin = User(username='admin-upload', email='admin-upload@example.test', hashed_password='unused', role='admin', is_active=True)
        db.add_all([stranger, admin])
        await db.commit()
    assert (await upload(client, {}, metadata(env_id))).status_code == 401
    assert (await upload(client, make_auth_headers(stranger.id), metadata(env_id))).status_code == 403
    result = await upload(client, make_auth_headers(admin.id), metadata(env_id))
    assert result.status_code == 200, result.text
    assert result.json()['data']['owner_user_id'] == user_id
    assert (await client.get('/api/v1/hermes-workflows/publish-candidates', headers=make_auth_headers(stranger.id))).json()['data']['total'] == 0
    assert (await client.get('/api/v1/hermes-workflows/publish-candidates', headers=make_auth_headers(user_id))).json()['data']['total'] == 1


@pytest.mark.asyncio
@pytest.mark.parametrize('change', ['inactive', 'missing_xhs_id', 'inactive_owner', 'unassigned'])
async def test_unavailable_targets_rejected(client, upload_config, change):
    user_id, env_id = await seed_owner()
    async with async_session() as db:
        env = await db.get(XHSEnvironment, env_id)
        if change == 'inactive':
            env.status = 'deleted'
        elif change == 'missing_xhs_id':
            env.xhs_account_id = ''
        elif change == 'inactive_owner':
            user = await db.get(User, user_id)
            user.is_active = False
        else:
            await db.execute(delete(UserXHSEnvironment).where(UserXHSEnvironment.environment_id == env_id))
        await db.commit()
    response = await upload(client, make_auth_headers(user_id), metadata(env_id))
    assert response.status_code in {400, 401, 403, 409}
    assert not list(upload_config.storage_path.rglob('*.png'))


@pytest.mark.asyncio
@pytest.mark.parametrize('failure_at', [1, 2])
async def test_storage_failure_can_retry_same_request_without_orphan_draft(client, upload_config, monkeypatch, failure_at):
    user_id, env_id = await seed_owner()
    data = metadata(env_id)
    original_save = upload_config.save
    calls = 0
    files = [('cover.png', picture(), 'image/png'), ('second.png', picture('red'), 'image/png')]

    async def failed_save(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == failure_at:
            raise OSError('simulated storage failure')
        return await original_save(*args, **kwargs)

    monkeypatch.setattr(upload_config, 'save', failed_save)
    failed = await upload(client, make_auth_headers(user_id), data, files)
    assert failed.status_code == 503
    assert 'simulated storage failure' not in failed.text
    async with async_session() as db:
        assert await db.scalar(select(func.count()).select_from(HermesWorkflowRun)) == 0
        assert await db.scalar(select(func.count()).select_from(HermesWorkflowPost)) == 0
    assert not list(upload_config.storage_path.rglob('*.png'))
    monkeypatch.setattr(upload_config, 'save', original_save)
    result = await upload(client, make_auth_headers(user_id), data, files)
    assert result.status_code == 200, result.text


@pytest.mark.asyncio
async def test_concurrent_identical_uploads_reserve_one_draft(client, upload_config, monkeypatch):
    user_id, env_id = await seed_owner()
    data = metadata(env_id)
    original_save = upload_config.save

    async def slow_save(*args, **kwargs):
        await asyncio.sleep(0.02)
        return await original_save(*args, **kwargs)

    monkeypatch.setattr(upload_config, 'save', slow_save)
    responses = await asyncio.gather(*(upload(client, make_auth_headers(user_id), data) for _ in range(3)))
    assert all(response.status_code == 200 for response in responses)
    assert len({response.json()['data']['id'] for response in responses}) == 1
    assert len(list(upload_config.storage_path.rglob('*.png'))) == 1
    async with async_session() as db:
        assert await db.scalar(select(func.count()).select_from(HermesWorkflowRun)) == 1
        assert await db.scalar(select(func.count()).select_from(HermesWorkflowPost)) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize('case', ['corrupt', 'empty', 'large', 'gif', 'six', 'missing', 'blank', 'uuid', 'emoji_title'])
async def test_invalid_upload_has_no_saved_draft(client, upload_config, case):
    user_id, env_id = await seed_owner()
    data, files = metadata(env_id), [('image.png', picture(), 'image/png')]
    if case in {'corrupt', 'empty', 'large'}:
        files = [('image.png', {'corrupt': b'<svg>unsafe</svg>', 'empty': b'', 'large': b'0' * 3_000_001}[case], 'image/png')]
    elif case == 'gif':
        files = [('image.gif', picture(kind='GIF'), 'image/gif')]
    elif case == 'six':
        files *= 6
    elif case == 'missing':
        files = []
    elif case == 'blank':
        data['content'] = '   '
    elif case == 'uuid':
        data['request_id'] = 'bad-id'
    else:
        data['title'] = '🚗' * 60
    response = await upload(client, make_auth_headers(user_id), data, files)
    assert response.status_code in {400, 422}, response.text
    async with async_session() as db:
        assert await db.scalar(select(func.count()).select_from(HermesWorkflowRun)) == 0
    assert not list(upload_config.storage_path.rglob('*.png'))


@pytest.mark.asyncio
async def test_filename_is_not_trusted_and_order_changes_version(client, upload_config):
    user_id, env_id = await seed_owner()
    result = await upload(client, make_auth_headers(user_id), metadata(env_id), [
        ('../../anything.html', picture(), 'text/html'), ('second.png', picture('red'), 'image/png')])
    assert result.status_code == 200
    post = result.json()['data']
    assert all(url.endswith('.png') and '..' not in url for url in post['image_urls'])
    async with async_session() as db:
        saved = await db.get(HermesWorkflowPost, post['id'])
        before = post_version(saved)
        saved.source_detail = {**saved.source_detail, 'image_urls': list(reversed(saved.source_detail['image_urls']))}
        assert post_version(saved) != before
    result = await client.post(f"/api/v1/hermes-workflows/posts/{post['id']}/review", headers=make_auth_headers(user_id),
                               json={'action': 'reject', 'comment': '调整', 'regenerate': True, 'expected_version': post['version']})
    assert result.status_code == 400
