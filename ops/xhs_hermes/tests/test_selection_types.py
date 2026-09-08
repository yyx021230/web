import importlib.util
import pytest
from pathlib import Path
spec = importlib.util.spec_from_file_location('selection_types', Path(__file__).parents[1] / 'selection_types.py')
selection = importlib.util.module_from_spec(spec)
spec.loader.exec_module(selection)

def test_default_selection_keeps_full_pool():
    rows = [{'id': 1, 'title': '车价'}, {'id': 2, 'title': '试驾体验'}]
    assert selection.copy_type_pool(rows, '跟随母文结构') is rows
    assert selection.image_type_pool(rows, None, lambda r: '') is rows

def test_copy_modes_match_reference_not_injected_policy():
    rows = [{'id': 1, 'title': '买车补贴怎么算'}, {'id': 2, 'title': '新车开了一周的驾驶体验'}, {'id': 3, 'title': '两台新车怎么选'}]
    assert [r['id'] for r in selection.copy_type_pool(rows, '政策行情')] == [1]
    assert [r['id'] for r in selection.copy_type_pool(rows, '产品体验')] == [2]
    assert [r['id'] for r in selection.copy_type_pool(rows, '选车对比')] == [3]

def test_image_quote_selection_is_independent():
    rows = [{'id': 1, 'chinese': '配置价格表', 'type': 'multi_config_quote'}, {'id': 2, 'chinese': '文字海报', 'type': 'standard'}, {'id': 3, 'chinese': '户外实车摄影', 'type': 'standard'}]
    classifier = lambda row: row['type']
    assert [r['id'] for r in selection.image_type_pool(rows, '多配置报价单', classifier)] == [1]
    assert [r['id'] for r in selection.image_type_pool(rows, '文字营销海报', classifier)] == [2]
    assert [r['id'] for r in selection.image_type_pool(rows, '实车场景图', classifier)] == [3]

@pytest.mark.parametrize('title,expected', [
    ('新政策补贴来了', 'policy_news'), ('每月月供多少钱', 'price_plan'),
    ('两个版本怎么选', 'car_compare'), ('新手购车避坑攻略', 'buying_guide'),
    ('开了一周的试驾测评', 'drive_review'), ('空间座椅配置亮点', 'product_features'),
    ('周末露营生活日记', 'car_lifestyle'),
])
def test_copy_primary_type_is_not_overridden_by_generic_footer(title, expected):
    row = {'id': 1, 'title': title, 'content': '汽车正文\n最新政策可了解，看看价格和补贴。'}
    assert selection.catalog.classify_copy(row) == expected
    assert selection.copy_type_pool([row], expected) == [row]

@pytest.mark.parametrize('prompt,expected', [
    ('超大标题，汽车海报', 'headline_poster'), ('多配置报价单，配置价格表', 'quote_table'),
    ('参数标注，用引线标注续航', 'feature_infographic'), ('四宫格照片拼贴', 'photo_collage'),
    ('汽车公路户外海报', 'scene_poster'), ('手账便签手写标题', 'note_poster'),
    ('纯色背景棚拍海报', 'studio_poster'),
])
def test_image_types_use_shared_rules(prompt, expected):
    row = {'id': 1, 'chinese': prompt}
    assert selection.catalog.classify_image(row) == expected
    guard = lambda r: 'multi_config_quote' if expected == 'quote_table' else 'standard'
    assert selection.image_type_pool([row], expected, guard) == [row]

def test_no_fallback_unknown_types_and_negative_cues():
    rows = [{'id': 1, 'chinese': '禁止多配置报价单；纯色背景棚拍海报'}]
    assert selection.image_type_pool(rows, 'quote_table', lambda r: 'standard') == []
    assert selection.image_type_pool(rows, 'studio_poster', lambda r: 'standard') == rows
    assert selection.image_type_pool(rows, 'studio_poster', lambda r: 'multi_config_quote') == []
    with pytest.raises(ValueError):
        selection.copy_type_pool([], 'anything')

@pytest.mark.parametrize('text', [
    '暖棕调极简斜切建筑空间，巨幅毛笔手写标题，右下角一张便签纸写咨询',
    '城市街景，汽车海报；标题手写字体；底部贴纸标签',
    '棚拍纯色背景，标题手绘字体',
    '旅行摄影，雪山湖泊，白色手绘涂鸦图标，公路上行驶的汽车，粉色气泡框',
])
def test_handwritten_font_or_small_label_is_not_notebook_layout(text):
    assert selection.catalog.classify_image({'chinese': text}) != 'note_poster'

@pytest.mark.parametrize('text', ['手账便签手写标题', '笔记本纸张拼贴汽车照片', '手帐风格，撕纸拼贴，胶带固定卡片'])
def test_actual_notebook_composition_remains_selectable(text):
    assert selection.catalog.classify_image({'chinese': text}) == 'note_poster'

def test_cta_does_not_turn_price_copy_into_driving_review():
    assert selection.catalog.classify_copy({'title': '小米 SU7 这样最划算', 'content': '首付3.2万，月供607元\n试驾预约、金融方案、补贴明细'}) == 'price_plan'
    assert selection.catalog.classify_copy({'title': '高中数学从68到120，全靠刘权龙', 'content': '刘老师讲得透，还讲优缺点'}) is None
    assert selection.catalog.classify_copy({'title': '别错过这次新车政策更新', 'content': '本月购车权益已出\n#购车攻略 #买车避坑 #版本怎么选'}) == 'policy_news'
    assert selection.catalog.classify_copy({'title': '从此不坐经济舱', 'content': '家人出游旅行，商务舱特价优惠'}) is None

def test_dynamic_fallback_and_preflight_apply_type_filters():
    # Structural regression guard: a retry must not re-open the full prompt pool.
    import ast
    module = ast.parse((Path(__file__).parents[1] / 'run_daily_8x5.py').read_text())
    methods = {n.name: n for n in ast.walk(module) if isinstance(n, ast.FunctionDef)}
    def calls(name):
        return {n.func.id for n in ast.walk(methods[name]) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
    assert 'image_type_pool' in calls('image_planner')
    assert {'copy_type_pool', 'image_type_pool'} <= calls('check_catalogs')
    assert {'copy_type_pool', 'image_type_pool'} <= calls('prepare_portfolio')
    assert 'required_prompt_count' in calls('prepare_portfolio') & calls('check_catalogs')

@pytest.mark.parametrize('has_matching_fallback', [True, False])
def test_failed_primary_uses_only_same_type_dynamic_backup(monkeypatch, has_matching_fallback, tmp_path):
    import sys
    from types import SimpleNamespace
    monkeypatch.syspath_prepend(str(Path(__file__).parents[1]))
    import run_daily_8x5 as runner
    production = runner.ProductionRun.__new__(runner.ProductionRun)
    import threading
    production.lock = threading.RLock()
    production.run_dir = tmp_path
    production.config = {'requested_image_type': 'note_poster', 'image_plan_extra_templates': 2, 'image_plan_workers': 1}
    production.cases = {'case': {'allow_multi_config_quote': False}}
    candidates = [{'id': 3, 'chinese': '纯色背景棚拍海报，不应被选中'}]
    if has_matching_fallback:
        candidates.append({'id': 4, 'chinese': '手账便签拼贴轻盈视觉母版'})
    production.online = SimpleNamespace(prompts=lambda: candidates, public_root='https://example.test')
    production.save = lambda: None
    production.state = {'posts': {'p': {'key': 'p', 'case_id': 'case', 'copy': {'ok': True}, 'prompt_template': {'id': 1, 'chinese': '手写纸张标题设计'}, 'reserve_prompt_template': {'id': 2, 'chinese': '便签纸张汽车原图'}}}, 'car_images': {'case': []}}
    monkeypatch.setattr(runner, 'safe_prompt_pool', lambda rows, **kwargs: rows)
    monkeypatch.setattr(runner, 'emit', lambda *args, **kwargs: None)
    attempts = []
    def plan(**kwargs):
        template_id = kwargs['template']['id']
        attempts.append(template_id)
        if template_id in {1, 2}:
            raise RuntimeError('simulated primary failure')
        return {'selected_prompt_id': template_id}
    monkeypatch.setattr(runner, 'build_image_plan', plan)
    if has_matching_fallback:
        production.image_plan_stage()
        assert production.state['posts']['p']['image_plan']['selected_prompt_id'] == 4
        assert attempts == [1, 2, 4]
    else:
        with pytest.raises(RuntimeError, match='image plan stage'):
            production.image_plan_stage()
        assert attempts == [1, 2]
    assert 3 not in attempts

def test_worker_passes_independent_types_and_account_plan(tmp_path):
    worker_spec = importlib.util.spec_from_file_location('web_worker_test', Path(__file__).parents[1] / 'web_worker.py')
    worker = importlib.util.module_from_spec(worker_spec)
    worker_spec.loader.exec_module(worker)
    config, date = worker.build_run_config({'created_at': '2026-09-07T10:00:00', 'parameters': {
        'copy_type': 'drive_review', 'image_type': 'quote_table',
        'instruction': '用户审核不通过：车型配置条件需修正；原稿仅作问题上下文',
        'accounts': [{'environment_id': 7, 'account_name': '测试', 'vehicle_models': ['零跑A05'], 'post_count': 1}],
    }}, tmp_path / 'config.json')
    assert config['requested_copy_type'] == 'drive_review'
    assert config['requested_image_type'] == 'quote_table'
    assert config['accounts'][0]['post_count'] == 1
    assert config['operator_instruction'] == '用户审核不通过：车型配置条件需修正；原稿仅作问题上下文'

def test_approved_section_preserves_original_and_quote_guard(monkeypatch):
    import hashlib
    from core import prompt_template_type
    original = ('方案 9：山水海报。方案 10：潮流拼贴手账风（马卡龙色，年轻活力） '
                '手账拼贴海报，纸张标题“零跑A10”，拍立得相框，四张便利贴。 '
                '粉色便利贴：403舒享版 65,800元。 蓝色便利贴：403悦享版 69,800元。 '
                '💡 最终建议：后期修改价格。')
    monkeypatch.setattr(selection, 'APPROVED_SOURCE_SHA256', hashlib.sha256(original.encode()).hexdigest())
    row = {'id': 324, 'chinese': original, 'image_url': '/parent.png'}
    output = selection.image_type_pool([row], 'note_poster', prompt_template_type)
    assert len(output) == 1
    assert output[0]['template_type'] == 'multi_config_quote'
    assert output[0]['source_full_original'] == row['chinese'] == original
    assert '方案 9' not in output[0]['chinese'] and '最终建议' not in output[0]['chinese']
    assert output[0]['source_image_matches_section'] is False
    assert selection.image_type_pool([row], None, prompt_template_type)[0] is row
    assert selection.approved_note_section({**row, 'chinese': original+'changed'}, prompt_template_type)['chinese'].endswith('changed')

def test_single_approved_section_can_run_without_wrong_style_backup(monkeypatch):
    from types import SimpleNamespace
    import run_daily_8x5 as runner
    mother={'id': 11, 'title':'汽车试驾感受', 'content':'汽车体验\n留【城市】了解车型\n#汽车[话题]#'}
    template={'id':324,'chinese':'手账便签风海报', 'source_section_title':'方案10', 'template_type':'multi_config_quote'}
    monkeypatch.setattr(runner,'safe_prompt_pool',lambda rows,**kwargs:rows)
    monkeypatch.setattr(runner,'image_type_pool',lambda rows,*args:rows)
    monkeypatch.setattr(runner,'copy_type_pool',lambda rows,*args:rows)
    task={'key':'p','case_id':'c','account_id':42,'account_name':'测试','slot':1}
    result=runner.prepare_portfolio(config={},cases={'c':{'brand':'零跑汽车','vehicle_model':'零跑A05','allow_multi_config_quote':True}},tasks=[task],mothers=[mother],prompts=[template],recent=[],mother_ledger=[],prompt_ledger=[],vehicle_terms=[],online=SimpleNamespace(car_images=lambda *args:{'斜前方':'car.png'}),batch_date='2026-09-07')
    assert result['assignments']['p']['reserve_prompt_template'] is None
    assert result['assignments']['p']['prompt_template']['id']==324


@pytest.mark.parametrize('requested,total,case_count,pool_count,expected', [
    ('photo_collage', 1, 1, 1, 1), ('feature_infographic', 1, 1, 1, 1),
    ('多图拼贴', 1, 1, 1, 1), ('photo_collage', 1, 1, 2, 2),
    ('photo_collage', 1, 1, 0, 2), ('photo_collage', 2, 1, 1, 2),
    ('photo_collage', 2, 2, 1, 4), (None, 1, 1, 1, 2),
    ('auto', 1, 1, 1, 2), ('跟随母图结构', 1, 1, 1, 2),
])
def test_single_source_policy_is_not_a_batch_or_empty_pool_bypass(requested, total, case_count, pool_count, expected):
    rows = [{'id': i} for i in range(pool_count)]
    assert selection.required_prompt_count(rows, requested=requested, total_tasks=total, case_tasks=case_count) == expected


@pytest.mark.parametrize('template_id,requested', [(568, 'photo_collage'), (332, 'feature_infographic')])
def test_precise_single_real_mother_can_run_without_unrelated_reserve(template_id, requested):
    import json
    from types import SimpleNamespace
    import run_daily_8x5 as runner
    fixtures = json.loads((Path(__file__).parents[3] / 'backend/tests/fixtures/hermes_image_layouts.json').read_text())
    template = next(row for row in fixtures if row['id'] == template_id)
    mother = {'id': 11, 'title': '汽车试驾感受', 'content': '汽车体验\n留【城市】了解车型\n#汽车[话题]#'}
    task = {'key': 'p', 'case_id': 'c', 'account_id': 42, 'account_name': '测试', 'slot': 1}
    portfolio = runner.prepare_portfolio(
        config={'requested_image_type': requested},
        cases={'c': {'brand': '零跑汽车', 'vehicle_model': '零跑A05', 'allow_multi_config_quote': True}},
        tasks=[task], mothers=[mother], prompts=[{**template, 'image_url': '/existing.png'}],
        recent=[], mother_ledger=[], prompt_ledger=[], vehicle_terms=[],
        online=SimpleNamespace(car_images=lambda *args: {'斜前方': 'car.png'}), batch_date='2026-09-08',
    )
    assert portfolio['assignments']['p']['prompt_template']['id'] == template_id
    assert portfolio['assignments']['p']['reserve_prompt_template'] is None
