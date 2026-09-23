import datetime as dt
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))
from core import validate_copy
from vehicle_knowledge import editorial_knowledge, knowledge_for_case, parse_variants


def snapshot(segments):
    return {'document_enabled': True, 'indexing_status': 'completed', 'document_id': 'd',
            'exported_at': dt.datetime.now(dt.timezone.utc).isoformat(),
            'segments': [{'id': str(i), 'position': i, 'enabled': True, 'status': 'completed', 'content': content} for i, content in enumerate(segments, 1)]}


def test_chunks_keep_exact_model_boundaries_and_source_ids():
    data = snapshot(['品牌: 零跑汽车 | 车型: 零跑A10 | 版本: 2026款 403舒享版\n- 电池: 39.8kWh\n品牌:零跑汽车|车型:零跑B01|版本:2027款590舒享版\n- 电池:56kWh', '- 车机:8155\n- 官方指导价:99999元\n- 电机功率:以官方为准'])
    rows = parse_variants(data)
    assert len(rows) == 2
    assert [f['value'] for f in rows[0]['facts']] == ['39.8kWh']
    assert [f['value'] for f in rows[1]['facts']] == ['56kWh', '8155']
    assert rows[1]['facts'][-1]['source_id'] == '2'
    data['segments'][1]['position'] = 3
    assert len(parse_variants(data)[1]['facts']) == 1


def test_exact_model_year_trim_and_no_price_leakage(tmp_path):
    data = snapshot(['品牌:零跑汽车|车型:零跑A10|版本:2026款403舒享版\n- 电池:39.8kWh\n- 续航:403km\n- 售价:¥65,800\n- 质保:四年', '品牌:零跑汽车|车型:零跑A10|版本:2026款505悦享版\n- 电池:53kWh\n- 续航:505km'])
    path=tmp_path/'kb.json'; path.write_text(json.dumps(data))
    case={'brand':'零跑汽车','vehicle_model':'零跑A10','policy_text':'2026款；政策价格63900元','quote_rows':[{'configuration':'403舒享版'},{'configuration':'505悦享版'}]}
    result=knowledge_for_case(case,{'content':'续航电池对比'},path)
    assert result['status']=='matched'
    assert result['common_facts']==[]
    assert len(result['variants'])==2
    assert '65,800' not in json.dumps(result)
    assert case['policy_text']=='2026款；政策价格63900元'
    assert knowledge_for_case({**case,'vehicle_model':'零跑A05'},path=path)['status']=='missing'
    assert knowledge_for_case({**case,'policy_text':'2027款'},path=path)['status']=='missing'
    assert knowledge_for_case({**case,'quote_rows':[{'configuration':'510旗舰版'}]},path=path)['status']=='missing'
    assert all(not r['facts'] for r in knowledge_for_case(case,{'content':'购车礼遇'},path)['variants'])
    data['document_enabled']=False; path.write_text(json.dumps(data))
    assert knowledge_for_case(case,path=path)['status']=='missing'


def test_partial_trim_coverage_does_not_claim_all_trims(tmp_path):
    data=snapshot(['品牌:零跑汽车|车型:零跑A10|版本:2026款403舒享版\n- 电池:39.8kWh'])
    path=tmp_path/'kb.json'; path.write_text(json.dumps(data))
    result=knowledge_for_case({'vehicle_model':'零跑A10','quote_rows':[{'configuration':'403舒享版'},{'configuration':'505悦享版'}]}, {'content':'电池对比'},path)
    assert result['common_facts']==[]
    assert result['missing_policy_variants']==['505悦享版']


def test_currency_spelling_and_real_configuration_validation():
    case={'vehicle_model':'零跑A05','policy_text':'官方指导价¥63,900；405舒享版、405悦享版、510悦享版。','allowed_months':[9]}
    def errors(text):
        return validate_copy(title='零跑A05购车参考',content=text+'\n#零跑A05[话题]#',mother=None,case=case)['hard_errors']
    assert errors('官方指导价6.39w，优先看510悦享版，重点看405舒享版，建议对比405悦享版，可以从入门版了解')==[]
    assert errors('官方指导价6.39万元')==[]
    assert errors('官方指导价6.38w')==['政策未提供的金额：6.38w']
    assert errors('优先看510旗舰版')==['政策未提供的配置名：510旗舰版']
    assert errors('优先看510 舒享版')==['政策未提供的配置名：510 舒享版']
    assert errors('交付积分63900积分')==['政策未提供的金额：63900积分']
    case['policy_text']='提供2000积分'
    assert errors('补贴2000元')==['政策未提供的金额：2000元']


def test_powertrain_and_seat_aliases_never_mix(tmp_path):
    data=snapshot(['品牌:零跑汽车|车型:零跑D19|版本:2026款720智尊版六座\n- 电池:100kWh', '品牌:零跑汽车|车型:零跑D19增程|版本:2026款500智尊版六座\n- 电池:80kWh'])
    path=tmp_path/'kb.json'; path.write_text(json.dumps(data))
    case={'vehicle_model':'零跑D19','policy_text':'2026款','quote_rows':[{'configuration':'纯电720智尊版 6座'},{'configuration':'增程500智尊版 6座'}]}
    result=knowledge_for_case(case,{'content':'电池续航'},path)
    assert len(result['variants'])==2
    assert result['missing_policy_variants']==[]
    assert {r['policy_configuration']:r['facts'][0]['value'] for r in result['variants']}=={'纯电720智尊版 6座':'100kWh','增程500智尊版 6座':'80kWh'}
    case['quote_rows']=[{'configuration':'纯电500智尊版 6座'}]
    assert knowledge_for_case(case,path=path)['status']=='missing'


def test_imported_live_snapshot_has_a05_gap_not_historical_substitution():
    # The real imported source remains original chunks (not a synthesized summary).
    path=Path(__file__).parents[1]/'config/vehicle_knowledge.json'
    data=json.loads(path.read_text())
    assert len(data['segments'])==62
    rows=parse_variants(data)
    assert len(rows)==51
    assert not any(r['model']=='零跑A05' for r in rows)
    assert any(r['model']=='零跑A10' for r in rows)


def test_related_facts_after_18_and_acc_are_not_lost(tmp_path):
    facts = [f'- 辅助功能{i}:标配' for i in range(20)] + ['- 泊车辅助(APA):标配', '- 全速自适应巡航(ACC):标配']
    data = snapshot(['品牌:零跑汽车|车型:零跑A10|版本:2026款505激光雷达版\n'+'\n'.join(facts)])
    path = tmp_path/'facts.json'
    path.write_text(json.dumps(data))
    result = knowledge_for_case({'vehicle_model':'零跑A10', 'policy_text':'2026款',
        'quote_rows':[{'configuration':'505激光雷达版'}]}, {'content':'新手智驾'}, path)
    assert len(result['variants'][0]['facts']) == 22
    assert len(result['common_facts']) == 22
    compacted = editorial_knowledge(result)
    assert compacted['variants'][0]['facts'] == facts
    assert compacted['variants'][0]['policy_configuration'] == '505激光雷达版'


def test_actual_a10_high_trim_apa_is_retrieved():
    cases = json.loads((Path(__file__).parents[1]/'config/cases.json').read_text())
    knowledge = knowledge_for_case(cases['a10-current'], {'content':'新手智驾泊车'})
    if knowledge['status'] == 'refresh_required':
        return  # Synthetic coverage above is independent of snapshot expiry.
    high = next(row for row in knowledge['variants'] if row.get('policy_configuration') == '505激光雷达版')
    assert any(f['key'] == '泊车辅助(APA)' and f['value']=='标配' for f in high['facts'])
    assert any('ACC' in f['key'] for f in high['facts'])


def test_price_only_mother_still_has_scoped_vehicle_identity(tmp_path):
    data = snapshot(['品牌:零跑汽车|车型:零跑A10|版本:2026款403舒享版\n'
                     '- 能源类型:纯电\n- 车身结构:5门5座\n- 电池:39.8kWh\n'
                     '品牌:零跑汽车|车型:零跑C10|版本:2026款290智享版\n- 车身结构:5门5座'])
    path = tmp_path/'identity.json'
    path.write_text(json.dumps(data))
    result = knowledge_for_case({'vehicle_model':'零跑A10','policy_text':'2026款',
                                 'quote_rows':[{'configuration':'403舒享版'}]},
                                {'content':'本月全系报价'}, path)
    assert len(result['variants']) == 1
    assert {fact['key'] for fact in result['variants'][0]['facts']} == {'能源类型', '车身结构'}
    assert {fact['key'] for fact in result['common_facts']} == {'能源类型', '车身结构'}


def test_ratio_in_fact_name_is_not_the_key_value_delimiter():
    data = snapshot(['品牌:零跑汽车|车型:零跑B10|版本:2027款540舒享版\n'
                     '- 第二排座椅4:6分体放倒: 标配\n'
                     '- 第二排座椅4：6分体放倒：选配\n'
                     '- 第三排座椅5:5分体放倒:标配\n'
                     '- 压缩比:13:1\n- 参数1:23'])
    facts = parse_variants(data)[0]['facts']
    assert [(fact['key'], fact['value']) for fact in facts] == [
        ('第二排座椅4:6分体放倒', '标配'), ('第二排座椅4：6分体放倒', '选配'),
        ('第三排座椅5:5分体放倒', '标配'),
        ('压缩比', '13:1'), ('参数1', '23'),
    ]
    assert facts[0]['source_excerpt'] == '- 第二排座椅4:6分体放倒: 标配'


def test_imported_snapshot_keeps_all_seat_ratio_fields_intact():
    data = json.loads((Path(__file__).parents[1]/'config/vehicle_knowledge.json').read_text())
    facts = [(fact, re.search(r'\d+[:：]\d+分体放倒', fact['source_excerpt']))
             for row in parse_variants(data) for fact in row['facts']
             if re.search(r'\d+[:：]\d+分体放倒', fact['source_excerpt'])]
    assert facts
    assert all(match.group() in fact['key'] and fact['value'] in ('标配', '选配', '无') for fact, match in facts)
