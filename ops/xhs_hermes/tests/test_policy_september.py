"""Policy-only tests: no agents, remote APIs, queue claims or generation."""
import copy
import json
import sys
from pathlib import Path
from unittest.mock import patch
import pytest

sys.path.insert(0, str(Path(__file__).parents[1]))
from policy_sync import parse_report, sync_policy
from policy_constraints import policy_constraint_errors, policy_constraints_instruction
from core import validate_copy, validate_image_plan, image_ocr_errors, QUOTE_TABLE_TYPE
from run_daily_8x5 import image_plan_instruction

SOURCE = '''<html><title>九月政策</title><body>
<p>权益有效期至2026年9月30日</p>
<h4>厂家宣传规范</h4><p>地方性补贴可以提，但具体金额不得在线上体现。不得提及内部价、底价、最优惠、至高可省、半价理想。</p>
<div class="report-section" id="a05"><div class="report-title">零跑A05<span>轿车</span></div>
<div class="report-subtitle">CLTC续航405/510km</div>
<div class="benefit-banner"><b class="value">¥23,824</b><span class="source">9月·新车型</span></div>
<table><tr><th>车型</th><th>官方指导价</th><th>国补后价格</th><th>省补后价格</th><th>权益</th></tr>
<tr><td>405舒享版<span>纯电</span></td><td>¥63,900</td><td>¥56,232</td><td>¥58,788</td><td><span class="item">首任非营运车主享终身质保</span></td></tr>
<tr><td>510S<span>纯电</span></td><td>¥90,900</td><td>¥79,992</td><td>¥83,628</td></tr></table>
<div class="landing-detail"><table><tr><th>车型</th><th>指导价</th><th>现金优惠</th><th>裸车价</th><th>国补优惠</th><th>保险</th><th>购置税</th><th>上牌费</th><th>国补后落地价</th></tr>
<tr><td>510S纯电</td><td>¥90,900</td><td>¥0</td><td>¥90,900</td><td>¥10,908</td><td>¥3,182</td><td>¥4,022.12</td><td>¥200</td><td>¥87,396.12</td></tr>
<tr><td>405舒享版纯电</td><td>¥63,900</td><td>¥0</td><td>¥63,900</td><td>¥7,668</td><td>¥2,237</td><td>¥2,827.43</td><td>¥200</td><td>¥61,496.43</td></tr></table></div>
</div></body></html>'''.encode()


@pytest.fixture
def case():
    return parse_report(SOURCE, source_url='https://example.test/new.html', batch_date='2026-09-09')[0]['a05-current']


def test_parse_matches_configuration_not_row_order_and_separates_audit(case):
    cases, metadata = parse_report(SOURCE, source_url='https://example.test/new.html', batch_date='2026-09-09')
    assert case['quote_rows'][0]['estimated_national_scrappage_on_road_price'] == '¥61,496.43'
    assert case['quote_rows'][1]['estimated_national_scrappage_on_road_price'] == '¥87,396.12'
    assert case['vehicle_stage'] == 'new' and case['allow_multi_config_quote']
    assert case['packaged_benefit_value'] == '¥23,824' and case['public_deadline'] == '9月底前'
    assert case['quote_rows'][0]['provincial_trade_in_after_price'] == '不在线上展示金额'
    assert '58,788' not in case['policy_text']
    assert case['display_quote_rows'][0]['provincial_trade_in_after_price'] == '¥58,788'
    assert metadata['source_rows_for_audit_only']['a05-current']['source_quote_rows'][0]['provincial_trade_in_after_price'] == '¥58,788'
    assert '首任非营运' in case['policy_text']


@pytest.mark.parametrize('bad', [
    SOURCE.replace('510S纯电'.encode(), '错误配置'.encode()),
    SOURCE.replace('<th>保险</th>'.encode(), '<th>服务费</th>'.encode()),
    SOURCE.replace('<td>¥0</td><td>¥90,900</td>'.encode(), '<td>¥0</td>'.encode()),
])
def test_incomplete_or_changed_table_never_silently_misaligns(bad):
    with pytest.raises(ValueError):
        parse_report(bad, source_url='x', batch_date='2026-09-09')


def test_wrong_month_rejected_even_if_source_bytes_changed():
    with pytest.raises(ValueError, match='effective period'):
        parse_report(SOURCE + b' ', source_url='x', batch_date='2026-10-01')


def test_new_link_never_falls_back_to_old_policy_cache(tmp_path):
    settings = tmp_path / 'source.json'
    settings.write_text(json.dumps({'content_url':'https://example.test/new.html'}))
    cache = tmp_path / 'cache'
    cache.mkdir()
    (cache / 'source.html').write_bytes(SOURCE)
    (cache / 'metadata.json').write_text(json.dumps({'source_url':'https://example.test/old.html','effective_period':'2026-09'}))
    with patch('policy_sync.download', side_effect=TimeoutError), pytest.raises(RuntimeError, match="previous document"):
        sync_policy(settings_path=settings, cases_path=tmp_path / 'cases.json', batch_date='2026-09-09', cache_dir=cache)
    assert not (tmp_path / 'cases.json').exists()


@pytest.mark.parametrize('text', ['省补后价格58,788元', '地方补贴至高8000元', '省补8%', '8%的省补', '省补\n¥58,788', '综合权益优惠23824元', '综合权益价值30000元', '门店有现车可提', '试驾礼价值100元', '内部价参考', '落地价61496.43元', '报告测算落地价56232元'])
def test_explicit_hard_errors(text, case):
    assert policy_constraint_errors(text, case)


@pytest.mark.parametrize('text', ['地方补贴可了解；指导价6.39万元', '地方补贴可了解，官方指导价63900元', '国补按条件测算7668元', '本品增换购3000元', '综合权益价值23824元', '报告测算落地价61496.43元', '暂无现车可提', '母文没提权益，不要硬加'])
def test_valid_general_or_known_price_content_not_overblocked(text, case):
    assert not policy_constraint_errors(text, case)


def test_old_cars_can_use_benefit_discount_and_legacy_cases_unchanged(case):
    old = copy.deepcopy(case)
    old['publication_constraints']['new_vehicle_no_benefit_discount'] = False
    assert not policy_constraint_errors('综合权益优惠23824元', old)
    assert not policy_constraint_errors('地方补贴8000元', {})


def test_mutually_exclusive_and_unknown_stacking(case):
    case['publication_constraints']['mutually_exclusive_benefits'] = [{'left':'本品增换购','right':'超级置换'}]
    assert policy_constraint_errors('本品增换购和超级置换同时享受',case)
    assert not policy_constraint_errors('本品增换购与超级置换二选一',case)
    case['publication_constraints']['finance_cash_stacking_unconfirmed'] = True
    assert policy_constraint_errors('金融0息叠加现金优惠',case)
    assert not policy_constraint_errors('金融0息与现金优惠是否叠加需确认',case)


def test_copy_plan_ocr_share_restrictions_before_image_submission(case):
    content = '省补8000元\n#零跑A05[话题]#'
    validation = validate_copy(title='零跑A05',content=content,mother=None,case=case)
    assert any('地方补贴' in e for e in validation['hard_errors'])
    plan = {'adapted_prompt':'零跑A05 "省补8000元" "参考"','text_blocks':['省补8000元','参考']}
    assert any('地方补贴' in e for e in validate_image_plan(plan,{},case))
    assert any('地方补贴' in e for e in image_ocr_errors(['省补8000元'],copy={},case=case))
    prompt = image_plan_instruction({}, {'chinese':'报价单','template_type':QUOTE_TABLE_TYPE}, case, '左前45度', '')
    assert '不在线上展示金额' in prompt and '报告测算落地价' in prompt
    assert '58,788' not in prompt
    assert '不新增段落' in policy_constraints_instruction(case)


AUTHORIZED = {'_publication': {'allow_local_subsidy_amounts': True,
    'effective_period': '2026-09', 'approved_on': '2026-09-09', 'approved_by': 'user'}}


def test_legacy_override_cannot_expose_provincial_prices_to_generation(case):
    cases, metadata = parse_report(SOURCE, source_url='x', batch_date='2026-09-09', overrides=AUTHORIZED)
    approved = cases['a05-current']
    assert approved['quote_rows'][0]['provincial_trade_in_after_price'] == '不在线上展示金额'
    assert approved['display_quote_rows'][0]['provincial_trade_in_after_price'] == '¥58,788'
    assert '国补后价格（按政策条件测算）¥56,232' in approved['policy_text']
    assert '按置换更新' not in approved['policy_text']
    assert approved['publication_constraints']['hide_local_subsidy_amounts']
    for field in ('new_vehicle_no_stock','no_trial_gift_amount','explicit_banned_terms',
                  'new_vehicle_no_benefit_discount','mutually_exclusive_benefits','finance_cash_stacking_unconfirmed'):
        assert approved['publication_constraints'][field] == case['publication_constraints'][field]
    assert metadata['source_rows_for_audit_only']['a05-current']['source_quote_rows'][0]['provincial_trade_in_after_price']=='¥58,788'


@pytest.mark.parametrize('override', [{}, {'_publication':{'allow_local_subsidy_amounts':False,'effective_period':'2026-09'}},
    {'_publication':{'allow_local_subsidy_amounts':'true','effective_period':'2026-09'}},
    {'_publication':{'allow_local_subsidy_amounts':True,'effective_period':'2026-08'}}])
def test_only_explicit_current_period_override_unhides_prices(override):
    cases,_=parse_report(SOURCE,source_url='x',batch_date='2026-09-09',overrides=override)
    assert cases['a05-current']['publication_constraints']['hide_local_subsidy_amounts']


def test_legacy_authorization_never_enters_production_cases(tmp_path):
    settings=tmp_path/'policy_source.json'
    settings.write_text(json.dumps({'content_url':'https://example.test/current.html'}))
    (tmp_path/'policy_overrides.json').write_text(json.dumps(AUTHORIZED))
    with patch('policy_sync.download',return_value=SOURCE):
        sync_policy(settings_path=settings,cases_path=tmp_path/'cases.json',batch_date='2026-09-09',cache_dir=tmp_path/'cache')
    approved=json.loads((tmp_path/'cases.json').read_text())['a05-current']
    display=json.loads((tmp_path/'policy_display.json').read_text())['a05-current']
    assert approved['quote_rows'][0]['provincial_trade_in_after_price']=='不在线上展示金额'
    assert 'display_quote_rows' not in approved
    assert display[0]['provincial_trade_in_after_price']=='¥58,788'
    october=SOURCE.replace('2026年9月30日'.encode(),'2026年10月31日'.encode())
    cases,_=parse_report(october,source_url='x',batch_date='2026-10-01',overrides=AUTHORIZED)
    assert cases['a05-current']['publication_constraints']['hide_local_subsidy_amounts']


def test_provincial_amount_is_rejected_by_copy_image_plan_and_ocr():
    cases,_=parse_report(SOURCE,source_url='x',batch_date='2026-09-09',overrides=AUTHORIZED)
    case=cases['a05-current']
    copy={'title':'零跑A05价格参考','content':'405舒享版省补后价格¥58,788。\n#零跑A05[话题]#'}
    assert not validate_copy(**copy,mother=None,case=case)['pass']
    blocks=['零跑A05','405舒享版','¥58,788','按置换更新条件测算']
    plan={'adapted_prompt':'；'.join(f'“{x}”' for x in blocks),'text_blocks':blocks,
        'slot_mappings':[{'source':x,'output':x,'action':'保留或最小替换'} for x in blocks],
        'selected_prompt_original':'；'.join(blocks),'source_slot_count':4,'template_type':QUOTE_TABLE_TYPE}
    assert validate_image_plan(plan,copy,case)
    assert image_ocr_errors(blocks,copy=copy,case=case,expected_text_blocks=blocks,allow_policy_facts=True)
    safe_copy={'title':'零跑A05价格参考','content':'405舒享版国补后价格按政策条件测算¥56,232。\n#零跑A05[话题]#'}
    prompt=image_plan_instruction(safe_copy,{'template_type':QUOTE_TABLE_TYPE,'chinese':'报价单'},case,'左前45度','')
    assert '¥58,788' not in prompt and '不在线上展示金额' in prompt
    assert policy_constraint_errors('综合权益价值999999元',case)
    assert policy_constraint_errors('内部价参考',case)
    bad_copy={**copy,'content':copy['content'].replace('58,788','58,777')}
    assert any('未提供的金额' in e for e in validate_copy(**bad_copy,mother=None,case=case)['hard_errors'])
    assert image_ocr_errors(['省补58777元'],copy=copy,case=case,allow_policy_facts=True)


@pytest.mark.parametrize('lead', ['留言【城市＋车型】获取报价', '咨询最新政策', '扫码领取资料', '了解本月方案'])
def test_image_lead_language_is_blocked_before_and_after_generation(lead, case):
    plan = {'adapted_prompt': f'零跑A05海报，文字“零跑A05”“{lead}”',
            'text_blocks': ['零跑A05', lead],
            'slot_mappings': [{'source': '车型', 'output': '零跑A05'}, {'source': '说明', 'output': lead}],
            'selected_prompt_original': '车型；说明', 'source_slot_count': 2}
    assert any('留咨' in error for error in validate_image_plan(plan, {'title': '零跑A05', 'content': lead}, case))
    assert any('留咨' in error for error in image_ocr_errors([lead], copy={'title': '零跑A05', 'content': lead}, case=case))
    assert any('留咨' in error for error in image_ocr_errors(
        [{'text': lead, 'confidence': 0.3}], copy={'title': '零跑A05', 'content': lead}, case=case))
