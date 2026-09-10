"""Independent approved gallery labels, shared preview/Worker family rules."""
import copy
import json
import sys
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).parents[1]))
from core import safe_prompt_pool, prompt_template_type, MAX_STANDARD_TEXT_SLOTS, MAX_QUOTE_TEXT_SLOTS
from selection_types import catalog, image_type_pool

FIXTURE = json.loads((Path(__file__).parents[3] / 'backend/tests/fixtures/hermes_curated_layouts.json').read_text())
HISTORY = [{**r, 'id': 100000 + r['id'], 'chinese': r['prompt']} for r in FIXTURE['history']]


@pytest.mark.parametrize('row', HISTORY, ids=lambda r: str(r['id'] - 100000))
def test_approved_gallery_type_is_shared_and_original_untouched(row):
    before = copy.deepcopy(row)
    assert catalog.classify_image(row) == row['group']
    assert image_type_pool([row], row['group'], prompt_template_type) == [row]
    assert row == before


def test_user_reported_variants_share_one_entry_in_preview_and_production():
    rows = [r for r in HISTORY if r['id'] in {108652, 115691}]
    variants = [{**r, 'id': 100000 + r['id'], 'chinese': r['prompt']} for r in FIXTURE['variants']]
    assert {r['id'] for r in catalog.dedupe_image_sources(variants + rows)} == {108652, 115691}
    assert {r['id'] for r in image_type_pool(variants + rows, None, prompt_template_type)} == {108652, 115691}


def test_existing_catalog_uses_new_groups_and_dedupes_without_deleting():
    rows = copy.deepcopy(FIXTURE['existing'])
    expected = {5: 'hero', 6: 'hero', 14: 'hero', 152: 'collage', 153: 'collage', 325: 'table',
                342: 'cards', 368: 'cards', 439: 'cards', 503: 'dialog'}
    assert {r['id']: catalog.classify_image(r) for r in rows} == expected
    assert {r['id'] for r in catalog.dedupe_image_sources(rows)} == {5, 14, 152, 325, 342, 439, 503}
    assert rows == FIXTURE['existing']


def test_edited_prompt_and_untrusted_type_do_not_inherit_review():
    row = HISTORY[0]
    changed = {**row, 'chinese': '原提示词已被修改为其他内容', 'preview_type': 'hero', 'visual_reviewed': True}
    assert catalog.curated_source(changed) == {}
    assert catalog.image_layout_analysis(changed)['visual_reviewed'] is False


def test_reviewed_chat_recognised_without_relaxing_text_or_quote_budget():
    row = next(r for r in HISTORY if r['id'] == 116315)
    accepted = safe_prompt_pool([row], allow_quote_table=False)
    assert len(accepted) == 1 and catalog.classify_image(accepted[0]) == 'dialog'
    assert MAX_STANDARD_TEXT_SLOTS == 9 and MAX_QUOTE_TEXT_SLOTS == 30
    too_dense = {**row, 'chinese': row['chinese'] + ''.join(f'标题“更多文字{i}”' for i in range(40))}
    assert safe_prompt_pool([too_dense], allow_quote_table=True) == []
    quote = next(r for r in HISTORY if r['id'] == 129994)
    assert catalog.image_layout_analysis(quote)['requires_quote_data'] is True
    assert safe_prompt_pool([quote], allow_quote_table=False) == []


def test_all_eight_types_have_candidates_with_complete_data():
    accepted = safe_prompt_pool(HISTORY, allow_quote_table=True)
    assert {catalog.classify_image(r) for r in accepted} == {t['id'] for t in catalog.IMAGE_TYPES}
    for row in HISTORY:
        admission = catalog.curated_source(row)['admission']
        for allowed in (True, False):
            assert admission['with_quote' if allowed else 'without_quote'] == bool(safe_prompt_pool([row], allow_quote_table=allowed))
