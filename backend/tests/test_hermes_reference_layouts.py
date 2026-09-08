import json
from pathlib import Path

import pytest
from app.config import settings
from app.services.hermes_reference_types import image_layout_analysis
from tests.test_hermes_workflows import seed_owner
from tests.conftest import make_auth_headers


@pytest.mark.asyncio
async def test_catalog_uses_real_layouts_and_shared_source_sections(client, monkeypatch, tmp_path):
    user_id, _ = await seed_owner()
    fixtures = json.loads((Path(__file__).parent / 'fixtures/hermes_image_layouts.json').read_text())
    rows = [{**r, 'is_public': True, 'name': f"原始母版{r['id']}", 'image_url': f"https://example.test/{r['id']}.png",
             'preview_type': 'note_poster'} for r in fixtures if r['id'] in [335, 324, 353, 535, 568, 332, 554, 573]]
    path = tmp_path / 'snapshot.json'
    path.write_text(json.dumps({'schema_version': 1, 'synced_at': '2026-09-08T07:24:31+00:00', 'copies': [], 'images': rows}))
    monkeypatch.setattr(settings, 'hermes_reference_snapshot_path', str(path))
    response = await client.get('/api/v1/hermes-workflows/reference-types', headers=make_auth_headers(user_id))
    assert response.status_code == 200
    types = {t['id']: t for t in response.json()['data']['image_types']}
    assert types['quote_cards']['examples'][0]['id'] == 335
    assert types['quote_table']['examples'][0]['id'] == 554
    assert types['photo_collage']['examples'][0]['id'] == 568
    assert types['feature_infographic']['examples'][0]['id'] == 332
    assert {r['id'] for r in types['scene_poster']['examples']} == {353, 535}
    assert types['price_highlight']['examples'][0]['id'] == 573
    note = types['note_poster']['examples'][0]
    assert note['id'] == 324 and note['source_section_title'].startswith('方案 10')
    assert note['image_url'] == '' and note['preview_note']
    assert types['note_poster']['requires_quote_data'] is True
    for key, group in types.items():
        for example in group['examples']:
            assert image_layout_analysis(example)['type'] == key
            assert example['classification_reason']
    assert json.loads(path.read_text())['images'] == rows


@pytest.mark.asyncio
@pytest.mark.parametrize('image_type', ['quote_cards', '卡片报价单'])
async def test_new_card_quote_type_preserves_existing_policy_gate(client, monkeypatch, image_type):
    user_id, environment_id = await seed_owner()
    monkeypatch.setattr('app.services.hermes_workflow_service.policy_summaries', lambda: [{'vehicle_model': '零跑A05', 'allow_multi_config_quote': False, 'quote_rows': []}])
    response = await client.post('/api/v1/hermes-workflows/runs', headers=make_auth_headers(user_id), json={
        'account_id': environment_id, 'vehicle_model': '零跑A05', 'post_count': 1,
        'copy_type': 'drive_review', 'image_type': image_type,
    })
    assert response.status_code == 400
    assert '缺少完整配置价格' in response.json()['detail']
