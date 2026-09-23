import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))

from creative_profiles import (
    adaptation_contract,
    interpretive_layout_by_id,
    interpretive_layout_compatible,
    interpretive_layout_direction,
    interpretive_narrative_direction,
    normalize_adaptation_level,
    visual_change_contract_errors,
)


def test_profile_contracts_are_versioned_and_unknown_values_are_safe():
    assert normalize_adaptation_level(None) == 'replica'
    assert normalize_adaptation_level('unknown') == 'replica'
    contracts = [adaptation_contract(level) for level in ('replica', 'light', 'interpretive')]
    assert [item['label'] for item in contracts] == ['精准复刻', '轻度微改', '灵感改编']
    assert {item['version'] for item in contracts} == {'hermes-adaptation-v10'}
    assert all('不因档位放宽' in item['hard_guard'] for item in contracts)


def test_visual_change_contract_makes_freer_levels_visibly_distinct():
    light = {
        'visual_changes': [
            {'dimension': 'palette', 'from': '粉色', 'to': '琥珀色'},
            {'dimension': 'material', 'from': '丝绸', 'to': '磨砂玻璃'},
        ],
    }
    assert visual_change_contract_errors(light, 'light') == []
    assert visual_change_contract_errors({'visual_changes': light['visual_changes'][:1]}, 'light')
    interpretive = {
        'layout_archetype': 'asymmetric_editorial',
        'required_layout_archetype': 'asymmetric_editorial',
        'visual_changes': [
            {'dimension': 'palette', 'from': '粉色', 'to': '深海蓝'},
            {'dimension': 'scene', 'from': '棚拍', 'to': '夜间建筑'},
            {'dimension': 'lighting', 'from': '柔光', 'to': '轮廓光'},
            {'dimension': 'typography', 'from': '书法体', 'to': '几何无衬线'},
            {'dimension': 'composition', 'from': '上下居中', 'to': '非对称分栏'},
        ],
    }
    assert visual_change_contract_errors(interpretive, 'interpretive') == []
    interpretive['visual_changes'][0]['dimension'] = 'decoration'
    assert '灵感改编必须更换主色体系' in visual_change_contract_errors(interpretive, 'interpretive')


def test_interpretive_layout_direction_is_reproducible_and_auditable():
    first = interpretive_layout_direction(191, '粉色丝绸', '零跑A05别只看低配', '零跑A05')
    second = interpretive_layout_direction(191, '粉色丝绸', '零跑A05别只看低配', '零跑A05')
    assert first == second
    assert first['id']
    assert first['name']
    assert '车辆' in first['brief']
    assert interpretive_layout_by_id(first['id']) == first
    assert interpretive_layout_by_id('missing') is None


def test_interpretive_layouts_are_constrained_by_source_functional_type():
    first = interpretive_layout_direction(
        191, '四列配置报价表', '零跑A05报价参考', '零跑A05',
        source_layout_type='table',
    )
    second = interpretive_layout_direction(
        191, '四列配置报价表', '零跑A05报价参考', '零跑A05',
        source_layout_type='table',
    )
    assert first == second
    assert first['id'] in {'technical_dossier', 'asymmetric_editorial', 'modular_grid', 'comparison_axis'}
    assert interpretive_layout_compatible(first['id'], 'table') is True
    assert interpretive_layout_compatible('spatial_installation', 'table') is False
    assert interpretive_layout_by_id('spatial_installation', 'table') is None


def test_interpretive_directions_balance_batch_usage_and_avoid_local_repeats():
    layout_usage: dict[str, int] = {}
    narrative_usage: dict[str, int] = {}
    used_layouts: set[str] = set()
    used_narratives: set[str] = set()
    layouts: list[str] = []
    narratives: list[str] = []
    for slot in range(3):
        layout = interpretive_layout_direction(
            'account-1', slot,
            source_layout_type='hero',
            usage_counts=layout_usage,
            excluded_ids=used_layouts,
        )
        narrative = interpretive_narrative_direction(
            'account-1', slot,
            usage_counts=narrative_usage,
            excluded_ids=used_narratives,
        )
        layouts.append(layout['id'])
        narratives.append(narrative['id'])
        used_layouts.add(layout['id'])
        used_narratives.add(narrative['id'])
        layout_usage[layout['id']] = layout_usage.get(layout['id'], 0) + 1
        narrative_usage[narrative['id']] = narrative_usage.get(narrative['id'], 0) + 1
    assert len(set(layouts)) == 3
    assert len(set(narratives)) == 3
