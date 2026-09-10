"""Approved OCR-only script equivalence; no fuzzy facts or image/copy edits."""
import copy
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).parents[1]))
import core
import run_daily_8x5 as runner


@pytest.mark.parametrize('raw,expected', [
    ('405悅享版', '405悦享版'), ('510激光雷達版', '510激光雷达版'),
    ('480旗艦版', '480旗舰版'), ('620智駕版', '620智驾版'),
    ('豪華版', '豪华版'), ('標準版', '标准版'), ('入門版', '入门版'),
    ('長續航版', '长续航版'), ('純電版', '纯电版'), ('405 悅享版', '405 悦享版'),
])
def test_only_script_equivalent_configs_pass(raw, expected):
    lines = [{'text': raw, 'confidence': .93}]
    before = copy.deepcopy(lines)
    audit = {}
    errors = core.image_ocr_errors(lines, copy={'content': expected}, case={'vehicle_model': '零跑A05'},
                                   expected_text_blocks=[expected], configuration_audit=audit)
    assert errors == []
    assert lines == before
    assert audit['rule'] == core.OCR_CONFIG_SCRIPT_RULE
    assert audit['ocr_audit_source_text'] == raw
    assert audit['ocr_comparison_text'] == expected
    assert audit['ocr_changes'] == [{'start': 0, 'end': len(raw), 'from': raw, 'to': expected}]


def test_no_whole_document_conversion_or_character_guessing():
    raw = '悅耳配色，純電車，電池，國家，免費，底價，9月31日，￥67,900，4O5悅享版，405悅豪版'
    assert core.ocr_configuration_comparison(raw) == {'text': raw, 'changes': []}
    mixed = core.ocr_configuration_comparison('悅耳配色\n405悅享版 ￥67,900\n9月31日')
    assert mixed['text'] == '悅耳配色\n405悦享版 ￥67,900\n9月31日'
    assert mixed['changes'] == [{'start': 5, 'end': 11, 'from': '405悅享版', 'to': '405悦享版'}]


@pytest.mark.parametrize('wrong', ['403悅享版', '405舒享版', '4O5悅享版', '405悅豪版', '405悅享型', '510s', '405悅享版6座'])
def test_no_fuzzy_config_or_digit_repair(wrong):
    # Seats are not made equivalent by this rule. Existing generic config audit
    # does not separately parse seat counts, so test that conversion preserves them.
    if wrong.endswith('6座'):
        assert core.ocr_configuration_comparison(wrong)['text'] == '405悦享版6座'
        return
    errors = core.image_ocr_errors([{'text': wrong, 'confidence': .99}], copy={'content': '405悦享版'},
                                   case={'vehicle_model': '零跑A05'}, expected_text_blocks=['405悦享版'])
    assert any('未完整识别计划配置名' in error for error in errors)


@pytest.mark.parametrize('risk,expected', [
    ('￥67,901', '未登记金额'), ('9月31日', '具体日期'), ('免费咨询', '禁用词'),
    ('底价', '禁用词'), ('比亚迪', '竞品品牌'), ('零跑B10', '其他零跑车型'),
])
def test_other_hard_checks_unchanged(risk, expected):
    errors = core.image_ocr_errors([{'text': '405悅享版', 'confidence': .93}, {'text': risk, 'confidence': .95}],
                                   copy={'content': '405悦享版 ￥67,900'}, case={'vehicle_model': '零跑A05'},
                                   expected_text_blocks=['405悦享版'])
    assert any(expected in error for error in errors)


def test_missing_amounts_still_fail():
    errors = core.image_ocr_errors([{'text': '405悅享版', 'confidence': .93}], copy={'content': '405悦享版 ￥67,900'},
                                   case={}, expected_text_blocks=['405悦享版', '￥67,900'])
    assert errors == ['OCR未完整识别计划金额：67900']


def test_low_confidence_boundary_unchanged():
    kw = dict(copy={'content': '405悦享版'}, case={}, expected_text_blocks=['405悦享版'])
    assert core.image_ocr_errors([{'text': '405悅享版', 'confidence': .25}], **kw) == []
    assert core.image_ocr_errors([{'text': '405悅享版', 'confidence': .24}], **kw) == ['OCR未完整识别计划配置名：405悦享版']


def test_policy_support_not_automatically_granted_to_non_quote_images():
    case = {'vehicle_model': '零跑A05', 'quote_rows': [{'configuration': '405悦享版', 'price': '￥67,900'}]}
    lines = [{'text': '405悅享版 ￥67,900', 'confidence': .93}]
    kw = dict(copy={'content': '看看实车'}, case=case, expected_text_blocks=['405悦享版', '￥67,900'])
    assert core.image_ocr_errors(lines, allow_policy_facts=True, **kw) == []
    errors = core.image_ocr_errors(lines, allow_policy_facts=False, **kw)
    assert any('未登记金额' in error for error in errors)
    assert any('未登记配置名' in error for error in errors)


def test_script_equivalence_on_reference_side_and_no_changes_for_simplified():
    assert core.image_ocr_errors(['405悦享版'], copy={'content': '405悅享版'}, case={},
                                 expected_text_blocks=['405悅享版']) == []
    audit = {}
    assert core.image_ocr_errors(['405悦享版'], copy={'content': '405悦享版'}, case={},
                                 expected_text_blocks=['405悦享版'], configuration_audit=audit) == []
    assert audit['ocr_changes'] == [] and audit['ocr_comparison_text'] is None


@pytest.mark.parametrize('amount,ok', [('￥67,900', True), ('￥67,901', False)])
def test_image_job_retains_raw_ocr_and_records_comparison(monkeypatch, tmp_path, amount, ok):
    run = runner.ProductionRun.__new__(runner.ProductionRun)
    run.config = {'image_attempts': 1}
    run.cases = {'a05': {'vehicle_model': '零跑A05'}}
    run.run_dir = tmp_path
    run.online = SimpleNamespace(absolute_url=lambda value: value)
    submitted = []
    def submit(row, attempt, correction):
        submitted.append(row['image_plan']['adapted_prompt'])
        return 'offline-image-task', {'prompt': row['image_plan']['adapted_prompt']}
    run.submit_image = submit
    run.wait_image_task = lambda *args: {'status': 'completed', 'image_urls': ['https://example.test/original.png']}
    run.download_image = lambda *args: None
    original = [{'text': '405悅享版', 'confidence': .9234}, {'text': amount, 'confidence': .99}]
    frozen = copy.deepcopy(original)
    monkeypatch.setattr(runner, 'ocr_image', lambda *args: original)
    row = {'key': '42-01', 'account_id': 42, 'slot': 1, 'case_id': 'a05',
           'copy': {'title': '零跑A05', 'content': '405悦享版 ￥67,900'},
           'image_plan': {'adapted_prompt': '保留的原生图提示词', 'text_blocks': ['405悦享版', '￥67,900']}}
    _, result = run.image_job(row, object())
    assert result['ok'] is ok and original == frozen
    assert submitted == ['保留的原生图提示词']
    record = result if ok else result['failures'][0]
    assert record['ocr_lines'] == frozen
    assert record['ocr_config_comparison']['ocr_changes'][0]['from'] == '405悅享版'
    assert record['ocr_config_comparison']['ocr_changes'][0]['to'] == '405悦享版'
