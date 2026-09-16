import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))

from creative_profiles import (
    adaptation_contract,
    interpretive_layout_by_id,
    interpretive_layout_direction,
    normalize_adaptation_level,
    visual_change_contract_errors,
)


def test_profile_contracts_are_versioned_and_unknown_values_are_safe():
    assert normalize_adaptation_level(None) == 'replica'
    assert normalize_adaptation_level('unknown') == 'replica'
    contracts = [adaptation_contract(level) for level in ('replica', 'light', 'interpretive')]
    assert [item['label'] for item in contracts] == ['精准复刻', '轻度微改', '灵感改编']
    assert {item['version'] for item in contracts} == {'hermes-adaptation-v4'}
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
