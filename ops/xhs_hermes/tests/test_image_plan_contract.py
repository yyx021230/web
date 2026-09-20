import json
import sys
from pathlib import Path
from types import SimpleNamespace
import pytest

sys.path.insert(0, str(Path(__file__).parents[1]))
import run_daily_8x5 as runner


@pytest.mark.parametrize('layout', ['四张圆形彩色便利贴分别写报价', '四行配置报价表', '四个悬浮标牌分别写价格'])
def test_quote_instruction_preserves_source_carriers_without_forcing_all_policy_rows(layout):
    template = {'chinese': layout, 'template_type': 'multi_config_quote', 'source_slot_count': 6}
    rows = [{'configuration': f'配置{i}', 'official_guide_price': str(60000+i)} for i in range(5)]
    prompt = runner.image_plan_instruction(
        {'title': '零跑A05', 'content': '试驾前看看'}, template,
        {'brand': '零跑汽车', 'vehicle_model': '零跑A05', 'allow_multi_config_quote': True, 'quote_rows': rows},
        '斜前方', '',
    )
    assert layout in prompt
    assert json.dumps(rows, ensure_ascii=False) in prompt
    assert '多配置报价不等于表格' in prompt
    assert '原本是表格才保留表头、行列' in prompt
    assert '不是必须全部展示的清单' in prompt
    assert '必须保留母版的表头、配置行、价格列' not in prompt
    assert '按相应条件测算' in prompt
    assert '不得为配图反向硬改正文' in prompt
    assert '图片中禁止任何留咨话术' in prompt


def test_plain_image_prompt_still_cannot_add_a_price_table():
    prompt = runner.image_plan_instruction(
        {}, {'chinese': '汽车摄影大字报', 'template_type': 'standard'},
        {'brand': '零跑汽车', 'vehicle_model': '零跑A05', 'allow_multi_config_quote': True}, '斜前方', '',
    )
    assert '不得主动改造成多配置报价表' in prompt
    assert '政策登记是可用数据池' not in prompt


def test_final_image_prompt_does_not_discard_quote_carriers():
    prompt = runner.make_generation_prompt(
        {'adapted_prompt': '四张圆形便利贴上写配置报价', 'text_blocks': ['零跑A05', '购车参考']},
        {'vehicle_model': '零跑A05'},
    )
    assert '不得把承载报价的便利贴/卡片删掉或改成空白装饰' in prompt
    assert '不得另起表格承载其内容' in prompt


def test_copy_slot_rules_keep_facts_in_their_original_roles():
    assert '价格槽只换当前价格' in runner.COPY_SLOT_RULES
    assert '不得拿其它类别的已知事实凑满条数' in runner.COPY_SLOT_RULES
    assert '同步轻改所在小标题与开头/标题的事实姿态' in runner.COPY_SLOT_RULES
    assert '不是套用固定文案' in runner.COPY_SLOT_RULES
    assert '完整保留适用对象' in runner.COPY_SLOT_RULES


def test_one_text_list_derives_blocks_and_keeps_amount_checks(monkeypatch,tmp_path):
    template={'id':324,'chinese':'标题“零跑A10”，小字“购车参考”','template_type':'standard','source_slot_count':2,'source_image_matches_section':False}
    def response(*args,**kwargs):
        return {'adapted_prompt':'零跑A05海报，标题“零跑A05”，小字“购车参考”', 'slot_mappings':[{'source':'零跑A10','output':'零跑A05','action':'最小替换'},{'source':'购车参考','output':'购车参考','action':'保留'}]}
    monkeypatch.setattr(runner,'relay_json',response)
    kwargs=dict(copy={'title':'零跑A05','content':'购车参考'},template=template,case={'vehicle_model':'零跑A05','brand':'零跑汽车'},car_images={'斜前方':'/car.png'},model='test',attempts=1,public_root='https://example.test',trace_dir=tmp_path)
    result=runner.build_image_plan(**kwargs)
    assert result['text_blocks']==['零跑A05','购车参考']
    assert result['selected_prompt_image']==''
    assert list(tmp_path.glob('*.validation.json'))
    monkeypatch.setattr(runner,'relay_json',lambda *a,**kw:{**response(),'text_blocks':['错误的另一份清单']})
    with pytest.raises(RuntimeError, match='独立text_blocks'):
        runner.build_image_plan(**kwargs)
    monkeypatch.setattr(runner,'relay_json',lambda *a,**kw:{'adapted_prompt':'零跑A05海报','text_blocks':['零跑A05','购车参考']})
    with pytest.raises(RuntimeError,match='映射'):
        runner.build_image_plan(**kwargs)
    bad=response(); bad['slot_mappings'][1]['output']='仅需99999元';bad['adapted_prompt']='零跑A05海报，标题“零跑A05”，小字“仅需99999元”'
    monkeypatch.setattr(runner,'relay_json',lambda *a,**kw:bad)
    with pytest.raises(RuntimeError,match='未登记金额'):
        runner.build_image_plan(**kwargs)


def test_mother_template_lead_slot_is_rewritten_before_generation(monkeypatch, tmp_path):
    lead = '点击下方【立即咨询】了解更多车型报价和本月优惠政策'
    template = {
        'id': 126,
        'chinese': f'标题“旧车型”，底部小字“{lead}”',
        'template_type': 'standard',
        'source_slot_count': 2,
    }
    monkeypatch.setattr(runner, 'relay_json', lambda *args, **kwargs: {
        'adapted_prompt': f'零跑A05海报，标题“零跑A05”，底部小字“{lead}”',
        'slot_mappings': [
            {'source': '旧车型', 'output': '零跑A05', 'action': '最小替换'},
            {'source': lead, 'output': lead, 'action': '保留'},
        ],
    })
    result = runner.build_image_plan(
        copy={'title': '零跑A05近期政策', 'content': '车型与权益参考'},
        template=template,
        case={'vehicle_model': '零跑A05', 'brand': '零跑汽车'},
        car_images={'斜前方': '/car.png'}, model='test', attempts=1,
        public_root='https://example.test', trace_dir=tmp_path,
    )
    assert result['lead_language_sanitized'] is True
    assert result['slot_mappings'][1]['source'] == lead
    assert result['slot_mappings'][1]['output'] == '购车信息参考'
    assert result['text_blocks'] == ['零跑A05', '购车信息参考']
    assert '咨询' not in result['adapted_prompt']


def test_lead_wording_in_layout_description_is_scrubbed_when_slots_are_safe(monkeypatch, tmp_path):
    template = {
        'id': 567, 'chinese': '获客引流海报，标题“旧车型”，小字“配置参考”',
        'template_type': 'standard', 'source_slot_count': 2,
    }
    monkeypatch.setattr(runner, 'relay_json', lambda *args, **kwargs: {
        'adapted_prompt': '客资引流海报，标题“零跑D19”，小字“配置参考”',
        'slot_mappings': [
            {'source': '旧车型', 'output': '零跑D19', 'action': '最小替换'},
            {'source': '配置参考', 'output': '配置参考', 'action': '保留'},
        ],
    })
    result = runner.build_image_plan(
        copy={'title': '零跑D19', 'content': '配置参考'}, template=template,
        case={'vehicle_model': '零跑D19', 'brand': '零跑汽车'},
        car_images={'斜前方': '/car.png'}, model='test', attempts=1,
        public_root='https://example.test', trace_dir=tmp_path,
    )
    assert result['lead_language_sanitized'] is True
    assert result['text_blocks'] == ['零跑D19', '配置参考']
    assert '引流' not in result['adapted_prompt']


def test_explicit_plan_retry_preserves_copy_and_source(monkeypatch,tmp_path):
    initial={'batch_date':'2026-09-07','posts':{'p':{'copy':{'ok':True,'title':'原文','content':'不动正文'},'prompt_template':{'id':324},'image_plan':{'ok':False,'errors':['schema mismatch']},'status':'image_plan_failed'}}}
    path=tmp_path/'checkpoint.json';path.write_text(json.dumps(initial))
    run=runner.ProductionRun.__new__(runner.ProductionRun)
    run.checkpoint_path=path;run.run_dir=tmp_path;run.policy_fingerprints=lambda:{};run.save=lambda:None
    run.args=SimpleNamespace(batch_date='2026-09-07',redo_keys=[],retry_image_keys=[],retry_image_plan_keys=['p'])
    monkeypatch.setattr(runner,'emit',lambda *a,**kw:None)
    run.load_or_plan()
    row=run.state['posts']['p']
    assert row['copy']==initial['posts']['p']['copy']
    assert row['prompt_template']=={'id':324}
    assert 'image_plan' not in row
    assert row['superseded_image_runs'][0]['image_plan']['errors']==['schema mismatch']


def test_image_instructions_change_fidelity_without_relaxing_hard_guards():
    copy = {'title': '零跑A05近期参考', 'content': '配置参考'}
    template = {'chinese': '汽车海报，主标题与车辆主体', 'source_slot_count': 2}
    case = {'vehicle_model': '零跑A05', 'brand': '零跑汽车'}
    replica = runner.image_plan_instruction(copy, template, case, '斜前方', '', adaptation_level='replica')
    interpretive = runner.image_plan_instruction(copy, template, case, '斜前方', '', adaptation_level='interpretive')
    assert '完整复刻蓝图' in replica
    assert '全新版式原型' in interpretive
    assert 'visual_changes必须列出5至7项' in interpretive
    assert 'layout_archetype必须逐字返回' in interpretive
    assert '母图功能类型硬锁定' in interpretive
    assert '不得跨成其他功能类型' in interpretive
    for prompt in (replica, interpretive):
        assert '车辆外形、车标、灯组、轮毂和比例严格跟随' in prompt
        assert '不得出现明确禁用词' in prompt
        assert '不画二维码、联系方式' in prompt


def test_interpretive_quote_table_keeps_table_type_while_redesigning_style():
    template = {
        'id': 901,
        'chinese': (
            '多配置报价表格，共同表头为配置和国补后价格，四行车型版本使用横线和纵线组成单元格，'
            '右下角放条件备注。'
        ),
        'template_type': 'multi_config_quote',
        'source_slot_count': 10,
    }
    rows = [
        {'configuration': '405舒享版', 'national_scrappage_after_price': '56232'},
        {'configuration': '510悦享版', 'national_scrappage_after_price': '66792'},
    ]
    prompt = runner.image_plan_instruction(
        {'title': '零跑A05报价参考', 'content': '不同配置按政策条件测算。'},
        template,
        {
            'brand': '零跑汽车', 'vehicle_model': '零跑A05',
            'allow_multi_config_quote': True, 'quote_rows': rows,
        },
        '斜前方', '', adaptation_level='interpretive',
        required_layout_archetype='spatial_installation',
    )
    assert '母图功能类型硬锁定为【表格对照（table）】' in prompt
    assert 'layout_type必须逐字返回“table”' in prompt
    assert '表格仍使用共同表头、行列和配置—价格对应关系' in prompt
    assert '不得在表格、卡片、纯大字价格海报之间互相转换' in prompt
    # spatial_installation is incompatible with tables and must be replaced.
    assert 'layout_archetype必须逐字返回“spatial_installation”' not in prompt


def test_interpretive_layout_type_contract_rejects_cross_type_drift():
    template = {
        'chinese': '共同表头和四行配置报价表格，横线纵线构成规整单元格。',
    }
    contract = runner.source_layout_contract(template)
    assert contract['id'] == 'table'
    good = {
        'layout_type': 'table',
        'adapted_prompt': contract['marker'] + ' 使用非对称编辑排版重做表头、行距、材质与车辆裁切。',
    }
    assert runner.image_layout_type_contract_errors(good, template, 'interpretive') == []

    wrong_field = {**good, 'layout_type': 'cards'}
    errors = runner.image_layout_type_contract_errors(wrong_field, template, 'interpretive')
    assert '灵感改编必须保持母图功能类型：table' in errors

    drifted = {
        'layout_type': 'table',
        'adapted_prompt': '四张独立权益卡片并排排列，每张卡片内部写一项价格。',
    }
    errors = runner.image_layout_type_contract_errors(drifted, template, 'interpretive')
    assert any('第一句必须声明并锁定母图功能类型' in error for error in errors)
    assert any('实际识别为cards' in error for error in errors)


def test_interpretive_layout_type_contract_accepts_single_poster_emphasis_shift():
    template = {'chinese': '汽车占据停车场画面中央，完整车图为主，顶部保留标题。'}
    contract = runner.source_layout_contract(template)
    assert contract['id'] == 'hero'
    plan = {
        'layout_type': 'hero',
        'adapted_prompt': contract['marker'] + ' 使用醒目的巨型标题与完整单车主视觉，保留汽车主体和留白。',
    }
    assert runner.image_layout_type_contract_errors(plan, template, 'interpretive') == []
