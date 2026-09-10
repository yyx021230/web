"""Admission counts must not confuse prompt instructions with rendered copy."""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[1]))
from core import MAX_STANDARD_TEXT_SLOTS, safe_prompt_pool, source_slot_count


def test_real_collage_keeps_actual_print_and_not_prompt_chapters():
    fixtures = json.loads((Path(__file__).parents[3] / 'backend/tests/fixtures/hermes_image_layouts.json').read_text())
    row = next(row for row in fixtures if row['id'] == 568)
    assert source_slot_count(row['chinese']) == 7  # Two D19 placements remain conservative.
    admitted = safe_prompt_pool([{**row, 'image_url': '/existing.png'}], allow_quote_table=True)
    assert admitted[0]['source_slot_count'] == 7
    assert MAX_STANDARD_TEXT_SLOTS == 9


@pytest.mark.parametrize('text,count', [
    ('【整体配色】：绿色；【整体风格】：杂志；主标题“零跑A05”副标题“9月新政”', 2),
    ('标题【整体配色】：下方为小字“颜色随心选”', 2),
    ('主标题“以山为背景”；副标题“字体里的力量”', 2),
    ('银色“大饼”轮毂，皮革“细腻”质感；标题“松弛感”', 1),
    ('标题“大饼”轮毂主题海报，底部文字“细腻”质感的力量', 2),
    ('顶部文字“零跑A05”，底部文字“零跑A05”', 2),
    ('【价格信息-可选择性添加在底部】：添加“18.18万起 | 48期0息 | 月供1562元”', 1),
    ('主标题「车型报价」副标题“9月购车”底部【城市】', 3),
    ('主标题“车型】没有配对符号', 0),
    ('【目标】提升点击率\n【画面结构】上下分区\n【文案】\n主标题“新车到店”\n【输出】3:4', 1),
    ('【风格描述，如清新棚拍风】；【背景描述，如浅蓝渐变】；标题「新车」', 1),
    ('标题【目标】，副标题【文案】', 2),
])
def test_quoted_print_is_contextual_not_a_keyword_blacklist(text, count):
    assert source_slot_count(text) == count


def test_dense_real_copy_still_exceeds_standard_budget():
    source = '汽车文字海报；' + '场景布光说明；' * 30 + ''.join(f'标题“文字{i}”' for i in range(10))
    assert source_slot_count(source) == 10
    assert safe_prompt_pool([{'chinese': source, 'image_url': '/existing.png'}], allow_quote_table=True) == []
