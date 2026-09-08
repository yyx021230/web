"""Real library regressions: classify the composition, not isolated words."""
import copy
import json
import sys
from pathlib import Path

import pytest
sys.path.insert(0, str(Path(__file__).parents[1]))
from selection_types import catalog, image_type_pool, approved_note_section
from core import prompt_template_type

FIXTURES = json.loads((Path(__file__).parents[3] / 'backend/tests/fixtures/hermes_image_layouts.json').read_text())


@pytest.mark.parametrize('row', FIXTURES, ids=lambda r: f"prompt-{r['id']}")
def test_real_library_layout_regressions(row):
    before = copy.deepcopy(row)
    assert catalog.classify_image(row) == row['expected']
    assert row == before
    analysis = catalog.image_layout_analysis(row)
    assert analysis['reason']
    assert isinstance(analysis['requires_quote_data'], bool)


@pytest.mark.parametrize('negative', ['无便利贴风格', '取消手账拼贴', '去掉手帐风格', '不要手账风', '和原图粉调便利贴风格区分开'])
def test_discarded_notebook_style_is_not_positive_evidence(negative):
    row = {'chinese': negative + '；四块配置价格卡片，403舒享版指导价65800；403悦享版指导价69800。'}
    assert catalog.classify_image(row) == 'quote_cards'


@pytest.mark.parametrize('text', [
    '白色与粉色拼接的文字，雪山湖泊汽车场景',
    '蓝色幕墙，灰色拼接地坪，城市街景中的汽车',
    '三角拼接建筑立面，汽车停在停车场',
    '单张汽车场景海报，四宫格政策标签写补贴和试驾，不是照片',
])
def test_non_photo_splices_do_not_become_collages(text):
    assert catalog.classify_image({'chinese': text}) == 'scene_poster'


def test_preview_only_override_cannot_change_worker_classification():
    row = next(r for r in FIXTURES if r['id'] == 335)
    assert catalog.classify_image({**row, 'preview_type': 'studio_poster'}) == 'quote_cards'
    assert image_type_pool([row], 'note_poster', prompt_template_type) == []
    assert image_type_pool([row], 'quote_cards', prompt_template_type) == [row]


def test_quote_table_does_not_borrow_card_or_scene_templates():
    rows = [r for r in FIXTURES if r['id'] in [554, 335, 523, 535]]
    assert [r['id'] for r in image_type_pool(rows, 'quote_table', prompt_template_type)] == [554]
    assert [r['id'] for r in image_type_pool(rows, 'quote_cards', prompt_template_type)] == [335]
    assert sorted(r['id'] for r in image_type_pool(rows, '多配置报价单', prompt_template_type)) == [335, 554]


def test_real_paper_layout_keeps_notebook_type_even_with_quote_content():
    row = {'chinese': '手账拼贴海报，四张圆形便利贴用胶带粘贴：403舒享版指导价65800元；403悦享版指导价69800元。'}
    assert catalog.classify_image(row) == 'note_poster'
    assert catalog.image_layout_analysis(row)['requires_quote_data']
    assert image_type_pool([row], 'note_poster', prompt_template_type) == [row]


def test_approved_section_is_identical_for_preview_and_generation():
    row = next(r for r in FIXTURES if r['id'] == 324)
    preview = catalog.approved_image_section(row)
    production = approved_note_section(row, prompt_template_type)
    assert preview is not row
    assert preview['chinese'] == production['chinese']
    assert catalog.classify_image(preview) == catalog.classify_image(production) == 'note_poster'
    assert preview['source_image_matches_section'] is False
    assert preview['source_full_original'] == row['chinese']
    assert '方案 9' not in preview['chinese']
    assert catalog.image_layout_analysis(preview)['requires_quote_data']
    changed = {**row, 'chinese': row['chinese'] + 'new revision'}
    assert catalog.approved_image_section(changed) is changed


def test_untyped_batch_selection_is_unchanged_and_does_not_mutate_sources():
    rows = copy.deepcopy(FIXTURES)
    assert image_type_pool(rows, None, prompt_template_type) is rows
    assert rows == FIXTURES


@pytest.mark.parametrize('type_id', ['quote_table', 'quote_cards', '表格报价单', '卡片报价单', '多配置报价单'])
def test_all_explicit_quote_aliases_require_complete_prices(type_id):
    assert catalog.type_requires_quote_data(type_id)
    catalog.validate_type('image', type_id)
