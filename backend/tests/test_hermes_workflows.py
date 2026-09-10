from __future__ import annotations

import pytest

from app.config import settings
from app.db.session import async_session
from app.models.hermes_workflow import HermesWorkflowPost
from app.models.user import User
from app.models.user_xhs_env import UserXHSEnvironment
from app.models.xhs_environment import XHSEnvironment
from tests.conftest import make_auth_headers


@pytest.mark.asyncio
async def test_reference_catalog_preserves_originals_deduplicates_and_hides_private(client):
    from app.models.copywriting import Copywriting
    from app.models.prompt import PromptCategory, PromptExample
    user_id, _ = await seed_owner()
    content = '真实试驾记录🚗\n开了一周的驾驶感受\n#试驾[话题]#'
    async with async_session() as db:
        db.add_all([Copywriting(title='原始试驾标题', content=content), Copywriting(title='重复备份标题', content=content)])
        category = PromptCategory(name='测试母图')
        db.add(category)
        await db.flush()
        for public, name in [(True, '公开原始图'), (False, '不公开图')]:
            db.add(PromptExample(category_id=category.id, param_type='test', name=name, image_url='https://example.test/test.png', chinese_example=f'纯色背景棚拍海报 {name}', english_example='', is_public=public))
        await db.commit()
    response = await client.get('/api/v1/hermes-workflows/reference-types', headers=make_auth_headers(user_id))
    assert response.status_code == 200, response.text
    catalog = response.json()['data']
    assert len(catalog['copy_types']) == 7
    assert len(catalog['image_types']) == 8
    copy = next(t for t in catalog['copy_types'] if t['id'] == 'drive_review')
    assert copy['reference_count'] == 1
    assert copy['examples'][0]['content'] == content
    image = next(t for t in catalog['image_types'] if t['id'] == 'hero')
    assert image['reference_count'] == 1
    assert image['examples'][0]['title'] == '公开原始图'
    assert '不公开图' not in response.text


def test_missing_local_reference_images_and_path_traversal_are_not_previewed(monkeypatch, tmp_path):
    from app.services.hermes_reference_service import preview_available
    monkeypatch.setattr(settings, 'storage_path', str(tmp_path))
    (tmp_path / 'existing.png').touch()
    assert preview_available('/uploads/existing.png')
    assert not preview_available('/uploads/missing.png')
    assert not preview_available('/uploads/%2e%2e/secret.png')


@pytest.mark.asyncio
async def test_synced_reference_snapshot_exposes_originals_but_not_private_images(client, monkeypatch, tmp_path):
    import json
    user_id, _ = await seed_owner()
    snapshot = tmp_path / 'references.json'
    body = '原始试驾记录🚗\n开了一周，驾驶感受认真整理\n#试驾[话题]#'
    data = {'schema_version': 1, 'synced_at': '2026-09-08T01:00:00+00:00',
            'copies': [{'id': 901, 'title': '汽车试驾测评', 'content': body}, {'id': 902, 'title': '备份', 'content': body}],
            'images': [{'id': 801, 'name': '公开原图', 'chinese': '简约棚拍，纯色背景，保留原始文字', 'image_url': 'https://example.test/original.png', 'is_public': True},
                       {'id': 802, 'name': '私有原图', 'chinese': '纯色背景棚拍私有', 'image_url': 'https://example.test/private.png', 'is_public': False},
                       {'id': 803, 'name': '权限未知原图', 'chinese': '纯色背景棚拍未知', 'image_url': 'https://example.test/unknown.png'},
                       {'id': 804, 'name': '不安全链接', 'chinese': '纯色背景棚拍', 'image_url': 'javascript:alert(1)', 'is_public': True}]}
    snapshot.write_text(json.dumps(data), encoding='utf-8')
    monkeypatch.setattr(settings, 'hermes_reference_snapshot_path', str(snapshot))
    response = await client.get('/api/v1/hermes-workflows/reference-types', headers=make_auth_headers(user_id))
    assert response.status_code == 200, response.text
    catalog = response.json()['data']
    assert catalog['source'] == 'synced_online_library'
    assert catalog['synced_at'] == data['synced_at']
    copies = next(t for t in catalog['copy_types'] if t['id'] == 'drive_review')
    assert copies['reference_count'] == 1
    assert copies['examples'][0]['content'] == body
    images = next(t for t in catalog['image_types'] if t['id'] == 'hero')
    assert images['reference_count'] == 1
    assert images['examples'][0]['image_url'] == 'https://example.test/original.png'
    assert not any(value in response.text for value in ('私有原图', '权限未知原图', 'javascript:'))


@pytest.mark.asyncio
async def test_corrupt_reference_snapshot_falls_back_without_blocking_page(client, monkeypatch, tmp_path):
    user_id, _ = await seed_owner()
    snapshot = tmp_path / 'broken.json'
    snapshot.write_text('{partial', encoding='utf-8')
    monkeypatch.setattr(settings, 'hermes_reference_snapshot_path', str(snapshot))
    response = await client.get('/api/v1/hermes-workflows/reference-types', headers=make_auth_headers(user_id))
    assert response.status_code == 200
    assert response.json()['data']['source'] == 'current_web_library'
    assert response.json()['data']['synced_at'] is None


@pytest.mark.asyncio
async def test_section_preview_does_not_show_an_unmatched_image(client, monkeypatch, tmp_path):
    import json
    user_id, _ = await seed_owner()
    snapshot = tmp_path / 'section.json'
    original = '方案 10：手账便签风\n保留原提示词，不伪造新图'
    snapshot.write_text(json.dumps({'schema_version': 1, 'synced_at': '2026-09-08T01:00:00+00:00', 'copies': [], 'images': [],
        'sections': [{'id': 324, 'chinese': original, 'source_section_title': '方案10', 'is_public': True,
                      'image_url': '', 'preview_note': '原图未对应此方案'}]}), encoding='utf-8')
    monkeypatch.setattr(settings, 'hermes_reference_snapshot_path', str(snapshot))
    response = await client.get('/api/v1/hermes-workflows/reference-types', headers=make_auth_headers(user_id))
    entry = next(t for t in response.json()['data']['image_types'] if t['id'] == 'cards')['examples'][0]
    assert entry['content'] == original
    assert not entry['image_url']
    assert entry['preview_note'] == '原图未对应此方案'


@pytest.mark.asyncio
async def test_explicit_types_validated_and_preserved_independently(client):
    user_id, environment_id = await seed_owner()
    payload = {'account_id': environment_id, 'vehicle_model': '零跑A05', 'post_count': 1, 'copy_type': 'drive_review', 'image_type': 'note_poster'}
    headers = make_auth_headers(user_id)
    result = await client.post('/api/v1/hermes-workflows/runs', headers=headers, json=payload)
    assert result.status_code == 200, result.text
    params = result.json()['data']['parameters']
    assert params['copy_type'] == 'drive_review'
    assert params['image_type'] == 'note_poster'
    assert params['selection_contract']['copy_label'] == '试驾测评'
    assert params['selection_contract']['image_label'] == '手账便签风'
    rejected = await client.post('/api/v1/hermes-workflows/runs', headers=headers, json={**payload, 'copy_type': 'random_unknown_type'})
    assert rejected.status_code == 400


@pytest.mark.asyncio
async def test_quote_type_id_cannot_bypass_complete_price_requirement(client, monkeypatch):
    user_id, environment_id = await seed_owner()
    monkeypatch.setattr('app.services.hermes_workflow_service.policy_summaries', lambda: [{'vehicle_model': '零跑A05', 'allow_multi_config_quote': False, 'quote_rows': []}])
    result = await client.post('/api/v1/hermes-workflows/runs', headers=make_auth_headers(user_id), json={
        'account_id': environment_id, 'vehicle_model': '零跑A05', 'post_count': 1, 'copy_type': 'drive_review', 'image_type': 'quote_table',
    })
    assert result.status_code == 400
    assert '完整配置价格' in result.text


async def seed_owner() -> tuple[int, int]:
    async with async_session() as db:
        user = User(
            username="hermes_owner",
            email="hermes-owner@example.test",
            hashed_password="unused",
            role="xhs_ops",
            is_active=True,
        )
        db.add(user)
        await db.flush()
        environment = XHSEnvironment(
            shop_id="hermes-env-1",
            account_name="Hermes测试账号",
            status="active",
            department="xhs",
        )
        db.add(environment)
        await db.flush()
        db.add(UserXHSEnvironment(user_id=user.id, environment_id=environment.id))
        await db.commit()
    return int(user.id), int(environment.id)


async def streaming_run(client, monkeypatch, count=2):
    user_id, env_id = await seed_owner()
    headers = make_auth_headers(user_id)
    created = await client.post('/api/v1/hermes-workflows/runs', headers=headers, json={
        'account_id': env_id, 'vehicle_model': '零跑A05', 'post_count': count})
    assert created.status_code == 200, created.text
    run_id = created.json()['data']['id']
    monkeypatch.setattr(settings, 'xhs_worker_internal_token', 'stream-token')
    worker_headers = {'X-XHS-Worker-Token': 'stream-token'}
    claimed = await client.post('/api/v1/hermes-workflows/worker/claim', headers=worker_headers,
                                json={'worker_id': 'stream-worker'})
    assert claimed.status_code == 200
    items = [{'account_id': env_id, 'slot': slot, 'vehicle_model': '零跑A05',
              'title': f'第{slot}篇标题', 'content': f'第{slot}篇完整正文🚗\n#零跑A05[话题]#',
              'image_url': f'https://example.test/{slot}.png', 'hard_pass': True,
              'mother_copy_id': 500 + slot, 'image_task_id': f'task-{slot}'}
             for slot in range(1, count + 1)]
    return run_id, headers, worker_headers, items


@pytest.mark.asyncio
async def test_progress_exposes_checked_post_before_batch_finishes_and_is_idempotent(client, monkeypatch):
    run_id, headers, worker_headers, items = await streaming_run(client, monkeypatch)
    items[0]['ocr_lines'] = [{'text': '405悅享版', 'confidence': .9234}]
    items[0]['ocr_config_comparison'] = {'rule': 'ocr-config-script-equivalence-v1',
                                       'ocr_changes': [{'from': '405悅享版', 'to': '405悦享版'}]}
    url = f'/api/v1/hermes-workflows/worker/runs/{run_id}/progress'
    body = {'worker_id': 'stream-worker', 'delivery': {'posts': items[:1]}}
    response = await client.post(url, headers=worker_headers, json=body)
    assert response.status_code == 200, response.text
    run = response.json()['data']
    assert run['generated_posts'] == 1 and run['status'] == 'running' and run['finished_at'] is None
    assert [p['status'] for p in run['posts']] == ['review_pending', 'generating']
    assert run['posts'][0]['image_url'] == items[0]['image_url']
    assert run['posts'][0]['source_detail']['ocr_lines'] == items[0]['ocr_lines']
    assert run['posts'][0]['source_detail']['ocr_config_comparison'] == items[0]['ocr_config_comparison']
    assert run['posts'][1]['title'] is None
    original_version = run['posts'][0]['version']
    duplicate = await client.post(url, headers=worker_headers, json={
        'worker_id': 'stream-worker', 'delivery': {'posts': [{**items[0], 'title': '迟到的新标题不能覆盖'}]}})
    assert duplicate.json()['data']['posts'][0]['title'] == items[0]['title']
    assert duplicate.json()['data']['posts'][0]['version'] == original_version
    listed = (await client.get('/api/v1/hermes-workflows/runs', headers=headers)).json()['data']['items'][0]
    assert listed['assigned_generated'] == 1 and listed['assigned_status'] == 'running'
    workers = (await client.get('/api/v1/hermes-workflows/worker/status', headers=worker_headers)).json()['data']
    assert 'stream-worker' in str(workers) and 'running' in str(workers)


@pytest.mark.asyncio
async def test_final_callback_preserves_early_edit_review_and_missing_successful_sibling(client, monkeypatch):
    run_id, headers, worker_headers, items = await streaming_run(client, monkeypatch)
    base = f'/api/v1/hermes-workflows/worker/runs/{run_id}'
    streamed = await client.post(base + '/progress', headers=worker_headers,
                                json={'worker_id': 'stream-worker', 'delivery': {'posts': items[:1]}})
    post = streamed.json()['data']['posts'][0]
    edited = await client.patch(f"/api/v1/hermes-workflows/posts/{post['id']}", headers=headers, json={
        'title': '运营修改的标题', 'content': '运营修改的完整正文\n#零跑A05[话题]#',
        'comment': '按实际信息修正', 'expected_version': post['version']})
    assert edited.status_code == 200, edited.text
    version = edited.json()['data']['version']
    reviewed = await client.post(f"/api/v1/hermes-workflows/posts/{post['id']}/review", headers=headers,
                                  json={'action': 'approve', 'expected_version': version})
    assert reviewed.status_code == 200, reviewed.text
    await client.post(base + '/progress', headers=worker_headers,
                      json={'worker_id': 'stream-worker', 'delivery': {'posts': items}})
    completed = await client.post(base + '/complete', headers=worker_headers,
                                  json={'worker_id': 'stream-worker', 'delivery': {'production_ready': True, 'posts': items[1:]}})
    assert completed.status_code == 200, completed.text
    run = completed.json()['data']
    assert run['generated_posts'] == 2 and run['finished_at']
    first = run['posts'][0]
    assert first['title'] == '运营修改的标题' and first['status'] == 'approved' and first['revision'] == 2
    assert [e['action'] for e in first['source_detail']['events']] == ['edit', 'approve']
    assert run['posts'][1]['status'] == 'review_pending'
    late = await client.post(base + '/progress', headers=worker_headers,
                             json={'worker_id': 'stream-worker', 'delivery': {'posts': items}})
    assert late.json()['data']['posts'][0]['version'] == first['version']


@pytest.mark.asyncio
async def test_progress_checks_worker_ownership_and_rejects_invalid_pairs_atomically(client, monkeypatch):
    run_id, headers, worker_headers, items = await streaming_run(client, monkeypatch)
    base = f'/api/v1/hermes-workflows/worker/runs/{run_id}/progress'
    denied = await client.post(base, headers=headers, json={'worker_id': 'stream-worker', 'delivery': {'posts': items}})
    assert denied.status_code in (401, 403)
    stale = await client.post(base, headers=worker_headers, json={'worker_id': 'other-worker', 'delivery': {'posts': items}})
    assert stale.status_code == 409
    for bad in [{**items[1], 'vehicle_model': '零跑B10'}, {**items[1], 'image_url': ''},
                {**items[1], 'hard_pass': False}, {**items[1], 'account_id': 999}, items[0]]:
        result = await client.post(base, headers=worker_headers,
                                   json={'worker_id': 'stream-worker', 'delivery': {'posts': [items[0], bad]}})
        assert result.status_code == 400, result.text
        run = (await client.get(f'/api/v1/hermes-workflows/runs/{run_id}', headers=headers)).json()['data']
        assert run['generated_posts'] == 0 and all(p['status'] == 'generating' for p in run['posts'])


@pytest.mark.asyncio
async def test_all_posts_can_be_reviewed_before_final_ack_without_losing_worker_lease(client, monkeypatch):
    run_id, headers, worker_headers, items = await streaming_run(client, monkeypatch, count=1)
    base = f'/api/v1/hermes-workflows/worker/runs/{run_id}'
    response = await client.post(base + '/progress', headers=worker_headers,
                                 json={'worker_id': 'stream-worker', 'delivery': {'posts': items}})
    assert response.status_code == 200, response.text
    run = response.json()['data']
    assert run['finished_at'] is None and run['status'] == 'review_pending'
    await client.post(f"/api/v1/hermes-workflows/posts/{run['posts'][0]['id']}/review", headers=headers,
                      json={'action': 'approve', 'expected_version': run['posts'][0]['version']})
    complete = await client.post(base + '/complete', headers=worker_headers,
                                 json={'worker_id': 'stream-worker', 'delivery': {'production_ready': True, 'posts': items}})
    assert complete.status_code == 200, complete.text
    assert complete.json()['data']['status'] == 'approved' and complete.json()['data']['finished_at']


@pytest.mark.asyncio
async def test_terminal_failure_marks_only_unfinished_posts_after_partial_delivery(client, monkeypatch):
    run_id, headers, worker_headers, items = await streaming_run(client, monkeypatch)
    base = f'/api/v1/hermes-workflows/worker/runs/{run_id}'
    await client.post(base + '/progress', headers=worker_headers,
                      json={'worker_id': 'stream-worker', 'delivery': {'posts': items[:1]}})
    failed = await client.post(base + '/fail', headers=worker_headers,
                               json={'worker_id': 'stream-worker', 'error': '未完成篇失败'})
    assert failed.status_code == 200, failed.text
    run = failed.json()['data']
    assert run['status'] == 'partial_failed' and run['generated_posts'] == 1
    assert [p['status'] for p in run['posts']] == ['review_pending', 'generation_failed']


@pytest.mark.asyncio
async def test_manual_run_is_distributed_to_owner_review_and_worker_flow(client, monkeypatch):
    user_id, environment_id = await seed_owner()
    headers = make_auth_headers(user_id)

    created = await client.post(
        "/api/v1/hermes-workflows/runs",
        headers=headers,
        json={
            "account_id": environment_id,
            "vehicle_model": "零跑A05",
            "post_count": 1,
            "instruction": "城市通勤场景",
        },
    )
    assert created.status_code == 200, created.text
    run_id = created.json()["data"]["id"]
    assert created.json()["data"]["status"] == "queued"

    monkeypatch.setattr(settings, "xhs_worker_internal_token", "worker-test-token")
    worker_headers = {"X-XHS-Worker-Token": "worker-test-token"}
    claimed = await client.post(
        "/api/v1/hermes-workflows/worker/claim",
        headers=worker_headers,
        json={"worker_id": "test-worker", "capabilities": {"models": ["零跑A05"]}},
    )
    assert claimed.status_code == 200, claimed.text
    assert claimed.json()["data"]["id"] == run_id

    completed = await client.post(
        f"/api/v1/hermes-workflows/worker/runs/{run_id}/complete",
        headers=worker_headers,
        json={
            "worker_id": "test-worker",
            "delivery": {
                "production_ready": True,
                "posts": [{
                    "account_id": environment_id,
                    "slot": 1,
                    "case_id": "a05-current",
                    "vehicle_model": "零跑A05",
                    "title": "零跑A05看车记录",
                    "content": "正文\n#零跑A05[话题]#",
                    "image_url": "https://example.test/a05.png",
                    "hard_pass": True,
                    "mother_copy_id": 519,
                    "account_history": {"account_id": environment_id, "history_limit": 15, "history_posts": 15, "history_missing_body": 3},
                    "account_repetition": {"status": "allowed", "score": 0.55, "blocking": False},
                }],
            }
        },
    )
    assert completed.status_code == 200, completed.text
    post = completed.json()["data"]["posts"][0]
    assert post["status"] == "review_pending"
    assert post['source_detail']['account_history']['account_id'] == environment_id
    assert post['source_detail']['account_history']['history_posts'] == 15
    assert post['source_detail']['account_repetition']['blocking'] is False

    reviewed = await client.post(
        f"/api/v1/hermes-workflows/posts/{post['id']}/review",
        headers=headers,
        json={"action": "approve"},
    )
    assert reviewed.status_code == 200, reviewed.text

    detail = await client.get(f"/api/v1/hermes-workflows/runs/{run_id}", headers=headers)
    assert detail.status_code == 200, detail.text
    assert detail.json()["data"]["posts"][0]["status"] == "approved"
    assert detail.json()["data"]["assigned_status"] == "approved"


@pytest.mark.asyncio
async def test_user_cannot_dispatch_to_unassigned_account(client):
    user_id, _ = await seed_owner()
    async with async_session() as db:
        other = XHSEnvironment(
            shop_id="hermes-unassigned",
            account_name="未分配账号",
            status="active",
            department="xhs",
        )
        db.add(other)
        await db.commit()
        other_id = int(other.id)

    response = await client.post(
        "/api/v1/hermes-workflows/runs",
        headers=make_auth_headers(user_id),
        json={"account_id": other_id, "vehicle_model": "零跑A05", "post_count": 1},
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_batch_run_supports_per_account_count_and_rotating_models(client):
    user_id, environment_id = await seed_owner()
    headers = make_auth_headers(user_id)

    bootstrap = await client.get("/api/v1/hermes-workflows/bootstrap", headers=headers)
    assert bootstrap.status_code == 200, bootstrap.text
    assert "零跑A05" in bootstrap.json()["data"]["vehicle_models"]
    assert "零跑C16" in bootstrap.json()["data"]["vehicle_models"]
    assert len(bootstrap.json()["data"]["policies"]) >= 10

    created = await client.post(
        "/api/v1/hermes-workflows/runs/batch",
        headers=headers,
        json={
            "accounts": [{"environment_id": environment_id, "post_count": 3}],
            "vehicle_models": ["零跑A05", "零跑B10"],
        },
    )
    assert created.status_code == 200, created.text
    run_id = created.json()["data"]["id"]
    detail = await client.get(f"/api/v1/hermes-workflows/runs/{run_id}", headers=headers)
    assert detail.status_code == 200, detail.text
    assert [post["vehicle_model"] for post in detail.json()["data"]["posts"]] == [
        "零跑A05", "零跑B10", "零跑A05",
    ]


@pytest.mark.asyncio
async def test_batch_allows_different_counts_and_auto_name(client):
    user_id, first_env = await seed_owner()
    async with async_session() as db:
        second = XHSEnvironment(shop_id='hermes-env-2', account_name='第二测试账号', status='active', department='xhs')
        db.add(second)
        await db.flush()
        second_env = int(second.id)
        db.add(UserXHSEnvironment(user_id=user_id, environment_id=second_env))
        await db.commit()
    headers = make_auth_headers(user_id)
    created = await client.post('/api/v1/hermes-workflows/runs/batch', headers=headers, json={
        'accounts': [
            {'environment_id': first_env, 'post_count': 2},
            {'environment_id': second_env, 'post_count': 3},
        ],
        'vehicle_models': ['零跑A05', '零跑B10'],
        'instruction': '在母文允许范围内参考通勤场景',
    })
    assert created.status_code == 200, created.text
    row = created.json()['data']
    assert row['name'].endswith('5篇')
    assert row['total_posts'] == 5
    assert [a['post_count'] for a in row['parameters']['accounts']] == [2, 3]
    assert row['parameters']['instruction'] == '在母文允许范围内参考通勤场景'
    detail = (await client.get(f"/api/v1/hermes-workflows/runs/{row['id']}", headers=headers)).json()['data']
    assert [p['environment_id'] for p in detail['posts']] == [first_env, first_env, second_env, second_env, second_env]
    assert all(p['owner_user_id'] == user_id for p in detail['posts'])


@pytest.mark.asyncio
async def test_approved_post_can_be_added_to_publish_plan(client):
    user_id, environment_id = await seed_owner()
    headers = make_auth_headers(user_id)
    created = await client.post(
        "/api/v1/hermes-workflows/runs",
        headers=headers,
        json={"account_id": environment_id, "vehicle_model": "零跑A05", "post_count": 1},
    )
    run_id = created.json()["data"]["id"]
    detail = await client.get(f"/api/v1/hermes-workflows/runs/{run_id}", headers=headers)
    post_id = detail.json()["data"]["posts"][0]["id"]
    async with async_session() as db:
        post = await db.get(HermesWorkflowPost, post_id)
        post.status = "approved"
        post.hard_pass = True
        post.title = "待排期内容"
        post.content = "完整正文\n#零跑A05[话题]#"
        post.image_url = "https://example.test/image.png"
        await db.commit()

    candidates = await client.get("/api/v1/hermes-workflows/publish-candidates", headers=headers)
    assert candidates.status_code == 200, candidates.text
    assert [row["id"] for row in candidates.json()["data"]["items"]] == [post_id]

    planned = await client.post(
        "/api/v1/hermes-workflows/publish-plan",
        headers=headers,
        json={"items": [{
            "post_id": post_id,
            "environment_id": environment_id,
            "scheduled_at": "2030-09-05T09:30",
        }]},
    )
    assert planned.status_code == 200, planned.text
    row = planned.json()["data"]["items"][0]
    assert row["publish_status"] == "scheduled"
    assert row["publish_target_environment_id"] == environment_id
    assert row["scheduled_publish_at"] == "2030-09-05T09:30:00"
    assert row['status'] == 'approved'


async def prepared_posts(client, headers, environment_id, count=1):
    result = await client.post('/api/v1/hermes-workflows/runs', headers=headers, json={
        'account_id': environment_id, 'vehicle_model': '零跑A05', 'post_count': count,
        'name': '回归测试任务', 'copy_type': '产品体验', 'image_type': '跟随母图结构',
    })
    assert result.status_code == 200, result.text
    run_id = result.json()['data']['id']
    detail = (await client.get(f'/api/v1/hermes-workflows/runs/{run_id}', headers=headers)).json()['data']
    async with async_session() as db:
        for item in detail['posts']:
            post = await db.get(HermesWorkflowPost, item['id'])
            post.status = 'review_pending'
            post.hard_pass = True
            post.title = '原标题'
            post.content = '原正文💌\n#零跑A05[话题]#'
            post.image_url = 'https://example.test/vehicle.png'
            post.source_detail = {'mother_title': '原母文', 'mother_content': '参考完整正文', 'mother_copy_id': 123}
        await db.commit()
    return (await client.get(f'/api/v1/hermes-workflows/runs/{run_id}', headers=headers)).json()['data']


@pytest.mark.asyncio
async def test_edit_review_version_and_schedule_invalidation(client):
    user_id, env_id = await seed_owner()
    headers = make_auth_headers(user_id)
    run = await prepared_posts(client, headers, env_id)
    post = run['posts'][0]
    approved = await client.post(f"/api/v1/hermes-workflows/posts/{post['id']}/review", headers=headers, json={'action': 'approve', 'expected_version': post['version']})
    assert approved.status_code == 200
    await client.post('/api/v1/hermes-workflows/publish-plan', headers=headers, json={'items': [{'post_id': post['id'], 'environment_id': env_id, 'scheduled_at': '2030-09-05T09:30:00+08:00'}]})
    current = (await client.get(f"/api/v1/hermes-workflows/runs/{run['id']}", headers=headers)).json()['data']['posts'][0]
    payload = {'title': '新的标题', 'content': '调整后的完整正文💌\n#零跑A05[话题]#', 'comment': '替换车型描述', 'expected_version': current['version']}
    edited = await client.patch(f"/api/v1/hermes-workflows/posts/{post['id']}", headers=headers, json=payload)
    assert edited.status_code == 200, edited.text
    updated = edited.json()['data']
    assert updated['revision'] == 2
    assert updated['status'] == 'review_pending'
    assert updated['scheduled_publish_at'] is None
    assert updated['publish_status'] == 'not_requested'
    assert updated['image_url'] == current['image_url']
    assert updated['source_detail']['mother_content'] == '参考完整正文'
    assert updated['source_detail']['events'][-1]['title'] == '原标题'
    event = updated['source_detail']['events'][-1]
    assert event['user_name'] == 'hermes_owner'
    assert event['user_id'] == user_id and event['at']
    assert event['revision'] == 1 and event['result_revision'] == 2
    assert set(event['changes']) == {'title', 'content'}
    for field in ['title', 'content']:
        change = event['changes'][field]
        assert change['before'] == current[field]
        assert change['after'] == payload[field]
        assert ''.join(s['text'] for s in change['segments'] if s['kind'] != 'added') == current[field]
        assert ''.join(s['text'] for s in change['segments'] if s['kind'] != 'removed') == payload[field]
    stale = await client.patch(f"/api/v1/hermes-workflows/posts/{post['id']}", headers=headers, json=payload)
    assert stale.status_code == 409
    stale_review = await client.post(f"/api/v1/hermes-workflows/posts/{post['id']}/review", headers=headers, json={'action': 'approve', 'expected_version': post['version']})
    assert stale_review.status_code == 409


@pytest.mark.asyncio
async def test_reject_without_regeneration_keeps_original_and_removes_plan(client):
    user_id, env_id = await seed_owner()
    headers = make_auth_headers(user_id)
    run = await prepared_posts(client, headers, env_id)
    post = run['posts'][0]
    await client.post(f"/api/v1/hermes-workflows/posts/{post['id']}/review", headers=headers, json={'action': 'approve'})
    await client.post('/api/v1/hermes-workflows/publish-plan', headers=headers, json={'items': [{'post_id': post['id'], 'environment_id': env_id, 'scheduled_at': '2030-09-05T09:30:00+08:00'}]})
    current = (await client.get(f"/api/v1/hermes-workflows/runs/{run['id']}", headers=headers)).json()['data']['posts'][0]
    result = await client.post(f"/api/v1/hermes-workflows/posts/{post['id']}/review", headers=headers, json={'action': 'reject', 'comment': '图片条件标注不全', 'expected_version': current['version'], 'regenerate': False})
    assert result.status_code == 200, result.text
    saved = (await client.get(f"/api/v1/hermes-workflows/runs/{run['id']}", headers=headers)).json()['data']['posts'][0]
    assert saved['status'] == 'rejected'
    assert (saved['title'], saved['content'], saved['image_url']) == (post['title'], post['content'], post['image_url'])
    assert saved['scheduled_publish_at'] is None
    assert saved['source_detail']['events'][-1]['action'] == 'reject'
    assert saved['source_detail']['events'][-1]['comment'] == '图片条件标注不全'
    assert (await client.get('/api/v1/hermes-workflows/runs', headers=headers)).json()['data']['total'] == 1


@pytest.mark.asyncio
async def test_reject_regenerates_exactly_one_post_and_worker_returns_new_pending_version(client, monkeypatch):
    user_id, env_id = await seed_owner()
    headers = make_auth_headers(user_id)
    run = await prepared_posts(client, headers, env_id, 2)
    post = run['posts'][0]
    reason = '正文第二段和图中配置条件需修正'
    payload = {'action': 'reject', 'comment': reason, 'expected_version': post['version'], 'regenerate': True}
    result = await client.post(f"/api/v1/hermes-workflows/posts/{post['id']}/review", headers=headers, json=payload)
    assert result.status_code == 200, result.text
    original = result.json()['data']
    regenerated_id = original['regenerated_run_id']
    original = (await client.get(f"/api/v1/hermes-workflows/runs/{run['id']}", headers=headers)).json()['data']
    assert regenerated_id != run['id']
    assert [p['status'] for p in original['posts']] == ['rejected', 'review_pending']
    assert original['posts'][0]['title'] == post['title']
    assert original['posts'][0]['content'] == post['content']
    assert original['posts'][0]['image_url'] == post['image_url']
    assert original['posts'][0]['source_detail']['events'][-1]['regenerated_run_id'] == regenerated_id
    child = (await client.get(f'/api/v1/hermes-workflows/runs/{regenerated_id}', headers=headers)).json()['data']
    assert child['source'] == 'regeneration' and child['status'] == 'queued'
    assert len(child['posts']) == 1
    assert child['posts'][0]['owner_user_id'] == user_id
    assert child['posts'][0]['environment_id'] == env_id
    assert child['posts'][0]['vehicle_model'] == post['vehicle_model']
    assert child['parameters']['copy_type'] == run['parameters']['copy_type']
    assert child['parameters']['image_type'] == run['parameters']['image_type']
    assert child['parameters']['regeneration']['post_id'] == post['id']
    assert reason in child['parameters']['instruction']
    assert '不能作为政策' in child['parameters']['instruction']
    stale = await client.post(f"/api/v1/hermes-workflows/posts/{post['id']}/review", headers=headers, json=payload)
    assert stale.status_code == 409
    duplicate = await client.post(f"/api/v1/hermes-workflows/posts/{post['id']}/review", headers=headers, json={**payload, 'expected_version': original['posts'][0]['version']})
    assert duplicate.status_code == 409
    assert (await client.get('/api/v1/hermes-workflows/runs', headers=headers)).json()['data']['total'] == 2
    monkeypatch.setattr(settings, 'xhs_worker_internal_token', 'regeneration-test-token')
    worker_headers = {'X-XHS-Worker-Token': 'regeneration-test-token'}
    claimed = await client.post('/api/v1/hermes-workflows/worker/claim', headers=worker_headers, json={'worker_id': 'regen-worker'})
    assert claimed.json()['data']['id'] == regenerated_id
    assert reason in claimed.json()['data']['parameters']['instruction']
    completed = await client.post(f'/api/v1/hermes-workflows/worker/runs/{regenerated_id}/complete', headers=worker_headers, json={'worker_id': 'regen-worker', 'delivery': {'production_ready': True, 'posts': [{'account_id': env_id, 'slot': 1, 'vehicle_model': post['vehicle_model'], 'title': '重生新标题', 'content': '新正文💌\n#零跑A05[话题]#', 'image_url': 'https://example.test/new.png', 'hard_pass': True}]}})
    assert completed.status_code == 200, completed.text
    new_post = completed.json()['data']['posts'][0]
    assert new_post['status'] == 'review_pending' and new_post['id'] != post['id']
    assert new_post['source_detail']['regenerated_from']['post_id'] == post['id']
    old = (await client.get(f"/api/v1/hermes-workflows/runs/{run['id']}", headers=headers)).json()['data']['posts'][0]
    assert old['status'] == 'rejected' and old['content'] == post['content']


@pytest.mark.asyncio
async def test_regeneration_failure_rolls_back_rejection_and_does_not_enqueue(client, monkeypatch):
    from app.models.hermes_workflow import HermesWorkflowRun
    user_id, env_id = await seed_owner()
    headers = make_auth_headers(user_id)
    run = await prepared_posts(client, headers, env_id)
    post = run['posts'][0]
    async with async_session() as db:
        original = await db.get(HermesWorkflowRun, run['id'])
        original.parameters = {**original.parameters, 'image_type': 'quote_table'}
        await db.commit()
    monkeypatch.setattr('app.services.hermes_workflow_service.policy_summaries', lambda: [])
    result = await client.post(f"/api/v1/hermes-workflows/posts/{post['id']}/review", headers=headers, json={'action': 'reject', 'comment': '报价资料需要完善', 'expected_version': post['version'], 'regenerate': True})
    assert result.status_code == 400
    saved = (await client.get(f"/api/v1/hermes-workflows/runs/{run['id']}", headers=headers)).json()['data']['posts'][0]
    assert saved['status'] == 'review_pending' and saved['version'] == post['version']
    assert not saved['source_detail'].get('events')
    assert (await client.get('/api/v1/hermes-workflows/runs', headers=headers)).json()['data']['total'] == 1


@pytest.mark.asyncio
async def test_regeneration_requires_reason_version_and_reject_action(client):
    user_id, env_id = await seed_owner()
    headers = make_auth_headers(user_id)
    run = await prepared_posts(client, headers, env_id)
    post = run['posts'][0]
    url = f"/api/v1/hermes-workflows/posts/{post['id']}/review"
    assert (await client.post(url, headers=headers, json={'action': 'approve', 'expected_version': post['version'], 'regenerate': True})).status_code == 422
    assert (await client.post(url, headers=headers, json={'action': 'reject', 'comment': '原因', 'regenerate': True})).status_code == 422
    assert (await client.post(url, headers=headers, json={'action': 'reject', 'comment': '  ', 'expected_version': post['version'], 'regenerate': True})).status_code == 400


@pytest.mark.asyncio
async def test_noop_edit_does_not_create_revision_or_audit_event(client):
    user_id, env_id = await seed_owner()
    headers = make_auth_headers(user_id)
    run = await prepared_posts(client, headers, env_id)
    post = run['posts'][0]
    result = await client.patch(f"/api/v1/hermes-workflows/posts/{post['id']}", headers=headers, json={'title': post['title'], 'content': post['content'], 'comment': '没有实际改动', 'expected_version': post['version']})
    assert result.status_code == 400
    saved = (await client.get(f"/api/v1/hermes-workflows/runs/{run['id']}", headers=headers)).json()['data']['posts'][0]
    assert saved['revision'] == 1 and saved['version'] == post['version']
    assert not saved['source_detail'].get('events')


@pytest.mark.asyncio
async def test_history_modules_split_before_pagination_and_keep_legacy_regeneration_lineage(client):
    from app.models.hermes_workflow import HermesWorkflowRun
    user_id, env_id = await seed_owner()
    headers = make_auth_headers(user_id)
    single = (await client.post('/api/v1/hermes-workflows/runs', headers=headers, json={
        'account_id': env_id, 'vehicle_model': '零跑A05', 'post_count': 1,
    })).json()['data']
    batch = (await client.post('/api/v1/hermes-workflows/runs/batch', headers=headers, json={
        'accounts': [{'environment_id': env_id, 'post_count': 1}], 'vehicle_models': ['零跑A05'],
    })).json()['data']
    assert single['workflow_mode'] == 'single'
    assert batch['workflow_mode'] == 'batch'  # One post is still a batch entry.
    roots = {'single': single['id'], 'batch': batch['id']}
    expected = {mode: {run_id} for mode, run_id in roots.items()}
    async with async_session() as db:
        for mode, root_id in roots.items():
            parent = root_id
            for level in range(2):
                child = HermesWorkflowRun(run_key=f'legacy-{mode}-{level}', source='regeneration', status='queued',
                                         requested_by=user_id, parameters={'regeneration': {'run_id': parent}}, total_posts=1)
                db.add(child)
                await db.flush()
                expected[mode].add(child.id)
                parent = child.id
        await db.commit()
    for mode in ('batch', 'single'):
        seen = set()
        for page in (1, 2):
            response = await client.get(f'/api/v1/hermes-workflows/runs?workflow_mode={mode}&limit=2&page={page}', headers=headers)
            assert response.status_code == 200, response.text
            data = response.json()['data']
            assert data['total'] == 3
            assert all(row['workflow_mode'] == mode for row in data['items'])
            seen.update(row['id'] for row in data['items'])
        assert seen == expected[mode]
        for run_id in seen:
            detail = (await client.get(f'/api/v1/hermes-workflows/runs/{run_id}', headers=headers)).json()['data']
            assert detail['workflow_mode'] == mode
    mismatch = await client.get('/api/v1/hermes-workflows/runs?workflow_mode=single&source=manual_batch', headers=headers)
    assert mismatch.json()['data']['total'] == 0
    assert (await client.get('/api/v1/hermes-workflows/runs?workflow_mode=unknown', headers=headers)).status_code == 422
    assert (await client.get('/api/v1/hermes-workflows/runs', headers=headers)).json()['data']['total'] == 6


@pytest.mark.asyncio
async def test_history_pagination_search_sources_and_failed_counts(client):
    user_id, env_id = await seed_owner()
    headers = make_auth_headers(user_id)
    run = await prepared_posts(client, headers, env_id, 2)
    async with async_session() as db:
        failed = await db.get(HermesWorkflowPost, run['posts'][1]['id'])
        failed.status = 'generation_failed'
        failed.hard_pass = False
        await db.commit()
    response = await client.get('/api/v1/hermes-workflows/runs?search=回归&status=failed&source=manual&page=1&limit=1', headers=headers)
    assert response.status_code == 200, response.text
    payload = response.json()['data']
    assert payload['total'] == 1
    assert len(payload['items']) == 1
    row = payload['items'][0]
    assert row['assigned_status'] == 'partial_failed'
    assert row['assigned_generated'] == 1
    assert row['assigned_failed'] == 1
    assert row['assigned_pending_review'] == 1
    assert row['parameters']['copy_type'] == '产品体验'
    assert row['parameters']['policy_fingerprint']
    assert 'policy_snapshot' not in row['parameters']
    assert 'posts' not in row
    none = await client.get('/api/v1/hermes-workflows/runs?source=manual_batch', headers=headers)
    assert none.json()['data']['total'] == 0


@pytest.mark.asyncio
async def test_publish_time_conflicts_timezone_and_stale_version(client):
    user_id, env_id = await seed_owner()
    headers = make_auth_headers(user_id)
    run = await prepared_posts(client, headers, env_id, 2)
    for post in run['posts']:
        r = await client.post(f"/api/v1/hermes-workflows/posts/{post['id']}/review", headers=headers, json={'action': 'approve'})
        assert r.status_code == 200
    posts = (await client.get(f"/api/v1/hermes-workflows/runs/{run['id']}", headers=headers)).json()['data']['posts']
    async def plan(post, when, version=None):
        return await client.post('/api/v1/hermes-workflows/publish-plan', headers=headers, json={'items': [{'post_id': post['id'], 'environment_id': env_id, 'scheduled_at': when, 'expected_version': version}]})
    past = await plan(posts[0], '2020-01-01T09:00')
    assert past.status_code == 400
    ok = await plan(posts[0], '2030-09-05T01:30:00Z', posts[0]['version'])
    assert ok.status_code == 200, ok.text
    assert ok.json()['data']['items'][0]['scheduled_publish_at'] == '2030-09-05T09:30:00'
    duplicate = await plan(posts[1], '2030-09-05T09:30')
    assert duplicate.status_code == 409
    stale = await plan(posts[0], '2030-09-05T12:30', posts[0]['version'])
    assert stale.status_code == 409


@pytest.mark.asyncio
async def test_worker_cannot_silently_change_vehicle_or_accept_empty_delivery(client, monkeypatch):
    user_id, env_id = await seed_owner()
    headers = make_auth_headers(user_id)
    created = await client.post('/api/v1/hermes-workflows/runs', headers=headers, json={'account_id': env_id, 'vehicle_model': '零跑A05', 'post_count': 2})
    run_id = created.json()['data']['id']
    monkeypatch.setattr(settings, 'xhs_worker_internal_token', 'test-token')
    worker_headers = {'X-XHS-Worker-Token': 'test-token'}
    await client.post('/api/v1/hermes-workflows/worker/claim', headers=worker_headers, json={'worker_id': 'test-worker'})
    response = await client.post(f'/api/v1/hermes-workflows/worker/runs/{run_id}/complete', headers=worker_headers, json={'worker_id': 'test-worker', 'delivery': {'production_ready': True, 'posts': [
        {'account_id': env_id, 'slot': 1, 'vehicle_model': '零跑C16', 'title': '错误车型', 'content': '正文', 'image_url': 'https://example.test/a.png', 'hard_pass': True},
        {'account_id': env_id, 'slot': 2, 'vehicle_model': '零跑A05', 'title': '无图片', 'content': '正文', 'hard_pass': True},
    ]}})
    assert response.status_code == 200, response.text
    row = response.json()['data']
    assert row['generated_posts'] == 0
    assert row['failed_posts'] == 2
    assert all(p['vehicle_model'] == '零跑A05' and not p['hard_pass'] for p in row['posts'])


@pytest.mark.asyncio
async def test_queue_cancel_preserves_records_and_cannot_be_claimed(client, monkeypatch):
    user_id, env_id = await seed_owner()
    headers = make_auth_headers(user_id)
    run = (await client.post('/api/v1/hermes-workflows/runs', headers=headers, json={'account_id': env_id, 'vehicle_model': '零跑A05'})).json()['data']
    response = await client.post(f"/api/v1/hermes-workflows/runs/{run['id']}/cancel", headers=headers)
    assert response.status_code == 200
    assert response.json()['data']['status'] == 'cancelled'
    monkeypatch.setattr(settings, 'xhs_worker_internal_token', 'cancel-test-token')
    claimed = await client.post('/api/v1/hermes-workflows/worker/claim', headers={'X-XHS-Worker-Token': 'cancel-test-token'}, json={'worker_id': 'test-worker'})
    assert claimed.json()['data'] is None
    detail = (await client.get(f"/api/v1/hermes-workflows/runs/{run['id']}", headers=headers)).json()['data']
    assert len(detail['posts']) == 1
    assert detail['assigned_generated'] == 0


@pytest.mark.asyncio
async def test_publish_candidates_pagination_does_not_hide_older_500_posts(client):
    user_id, env_id = await seed_owner()
    headers = make_auth_headers(user_id)
    run = await prepared_posts(client, headers, env_id)
    async with async_session() as db:
        db.add_all([HermesWorkflowPost(
            run_id=run['id'], environment_id=env_id, owner_user_id=user_id,
            slot=slot, account_name='历史测试账号', vehicle_model='零跑A05',
            status='approved', title=f'历史帖子{slot}', content='正文💌\n#零跑A05[话题]#',
            image_url='https://example.test/post.png', hard_pass=True,
        ) for slot in range(2, 507)])
        await db.commit()
    response = await client.get('/api/v1/hermes-workflows/publish-candidates?page=13&limit=40&planned=false&search=历史帖子', headers=headers)
    assert response.status_code == 200, response.text
    payload = response.json()['data']
    assert payload['total'] == 505
    assert len(payload['items']) == 25
    assert payload['items'][-1]['slot'] == 2
    planned = await client.get('/api/v1/hermes-workflows/publish-candidates?planned=true', headers=headers)
    assert planned.json()['data']['total'] == 0


@pytest.mark.asyncio
async def test_other_user_cannot_edit_review_or_read_owner_posts(client):
    user_id, env_id = await seed_owner()
    run = await prepared_posts(client, make_auth_headers(user_id), env_id)
    post = run['posts'][0]
    async with async_session() as db:
        other = User(username='other_owner', email='other@example.test', hashed_password='unused', role='xhs_ops', is_active=True)
        db.add(other)
        await db.commit()
        other_id = other.id
    headers = make_auth_headers(other_id)
    detail = await client.get(f"/api/v1/hermes-workflows/runs/{run['id']}", headers=headers)
    assert detail.status_code in (403, 404)
    edited = await client.patch(f"/api/v1/hermes-workflows/posts/{post['id']}", headers=headers, json={
        'title': '不能越权', 'content': '正文', 'comment': '修改', 'expected_version': post['version'],
    })
    assert edited.status_code == 403
    reviewed = await client.post(f"/api/v1/hermes-workflows/posts/{post['id']}/review", headers=headers, json={'action': 'approve', 'expected_version': post['version']})
    assert reviewed.status_code == 403
    regenerated = await client.post(f"/api/v1/hermes-workflows/posts/{post['id']}/review", headers=headers, json={'action': 'reject', 'comment': '不能越权重生', 'expected_version': post['version'], 'regenerate': True})
    assert regenerated.status_code == 403
    assert (await client.get('/api/v1/hermes-workflows/publish-candidates', headers=headers)).json()['data']['total'] == 0


@pytest.mark.asyncio
async def test_admin_edit_and_regeneration_preserve_assigned_owner(client):
    user_id, env_id = await seed_owner()
    owner_headers = make_auth_headers(user_id)
    run = await prepared_posts(client, owner_headers, env_id)
    post = run['posts'][0]
    async with async_session() as db:
        admin = User(username='review_admin', display_name='审核管理员', email='review-admin@example.test', hashed_password='unused', role='admin', is_active=True)
        db.add(admin)
        await db.commit()
        admin_id = admin.id
    headers = make_auth_headers(admin_id)
    edited = await client.patch(f"/api/v1/hermes-workflows/posts/{post['id']}", headers=headers, json={'title': '管理员修订标题', 'content': post['content'], 'comment': '纠正标题', 'expected_version': post['version']})
    assert edited.status_code == 200, edited.text
    current = edited.json()['data']
    assert current['source_detail']['events'][-1]['user_name'] == '审核管理员'
    assert set(current['source_detail']['events'][-1]['changes']) == {'title'}
    rejected = await client.post(f"/api/v1/admin/hermes-workflows/posts/{post['id']}/review", headers=headers, json={'action': 'reject', 'comment': '图中文字也需修正', 'expected_version': current['version'], 'regenerate': True})
    assert rejected.status_code == 200, rejected.text
    new_id = rejected.json()['data']['regenerated_run_id']
    child = (await client.get(f'/api/v1/hermes-workflows/runs/{new_id}', headers=owner_headers)).json()['data']
    assert child['requested_by'] == admin_id
    assert child['posts'][0]['owner_user_id'] == user_id
    assert child['posts'][0]['environment_id'] == env_id
    old = (await client.get(f"/api/v1/hermes-workflows/runs/{run['id']}", headers=owner_headers)).json()['data']['posts'][0]
    assert old['title'] == '管理员修订标题' and old['status'] == 'rejected'


@pytest.mark.asyncio
async def test_published_post_cannot_be_edited_or_rejected_for_regeneration(client):
    user_id, env_id = await seed_owner()
    headers = make_auth_headers(user_id)
    run = await prepared_posts(client, headers, env_id)
    post = run['posts'][0]
    async with async_session() as db:
        saved = await db.get(HermesWorkflowPost, post['id'])
        saved.status = 'published'
        await db.commit()
    current = (await client.get(f"/api/v1/hermes-workflows/runs/{run['id']}", headers=headers)).json()['data']['posts'][0]
    edited = await client.patch(f"/api/v1/hermes-workflows/posts/{post['id']}", headers=headers, json={'title': '新标题', 'content': post['content'], 'comment': '修改', 'expected_version': current['version']})
    assert edited.status_code == 409
    rejected = await client.post(f"/api/v1/hermes-workflows/posts/{post['id']}/review", headers=headers, json={'action': 'reject', 'comment': '重生', 'expected_version': current['version'], 'regenerate': True})
    assert rejected.status_code == 409
    assert (await client.get('/api/v1/hermes-workflows/runs', headers=headers)).json()['data']['total'] == 1


@pytest.mark.asyncio
async def test_admin_publish_manifest_includes_only_approved_subset_without_executing(client):
    user_id, env_id = await seed_owner()
    headers = make_auth_headers(user_id)
    run = await prepared_posts(client, headers, env_id, 2)
    approved = await client.post(f"/api/v1/hermes-workflows/posts/{run['posts'][0]['id']}/review", headers=headers, json={'action': 'approve'})
    assert approved.status_code == 200
    async with async_session() as db:
        admin = User(username='hermes_admin', email='admin@example.test', hashed_password='unused', role='admin', is_active=True)
        db.add(admin)
        await db.commit()
        admin_id = admin.id
    response = await client.post(f"/api/v1/admin/hermes-workflows/runs/{run['id']}/publish", headers=make_auth_headers(admin_id))
    assert response.status_code == 200, response.text
    payload = response.json()['data']
    assert payload['publish_manifest']['executed'] is False
    assert len(payload['publish_manifest']['posts']) == 1
    assert payload['publish_manifest']['posts'][0]['post_id'] == run['posts'][0]['id']
    assert [p['status'] for p in payload['run']['posts']] == ['approved', 'review_pending']
