"""Offline regressions for run #9: false positives, repeated plans and stage barriers."""
import copy
import json
import sys
import threading
import time
from collections import Counter
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).parents[1]))
import core
import run_daily_8x5 as runner
import web_worker


def sample_plan():
    return {
        'adapted_prompt': '深蓝色字体，标题“零跑A05”，小字“购车参考”，粉色背景保持不动。',
        'slot_mappings': [
            {'source': '零跑A10', 'output': '零跑A05', 'action': '最小替换'},
            {'source': '购车参考', 'output': '购车参考', 'action': '保留'},
        ],
        'scene_change': '浅粉色背景', 'vehicle_angle': '斜前方',
    }


def plan_kwargs(tmp_path, attempts=2):
    return dict(
        copy={'title': '零跑A05', 'content': '购车参考'},
        template={'id': 509, 'chinese': '标题“零跑A10”，小字“购车参考”',
                  'template_type': 'standard', 'source_slot_count': 2},
        case={'vehicle_model': '零跑A05', 'brand': '零跑汽车'},
        car_images={'斜前方': '/car.png'}, model='mock', attempts=attempts,
        public_root='https://example.test', trace_dir=tmp_path,
    )


@pytest.mark.parametrize('color', ['深蓝色字体', '深蓝灰背景'])
def test_color_is_not_a_competitor(color):
    assert not core.COMPETITOR_RE.search(color)


@pytest.mark.parametrize('brand', ['深蓝汽车', '深蓝S07', '深蓝 L07', '比亚迪', '宝马'])
def test_real_competitors_remain_blocked(brand):
    assert core.COMPETITOR_RE.search(brand)


def test_repeated_rating_stars_are_not_repeated_copy():
    plan = sample_plan()
    plan['slot_mappings'] += [{'source': '星级评分', 'output': '★★★★★'}] * 4
    plan['text_blocks'] = [row['output'] for row in plan['slot_mappings']]
    plan['adapted_prompt'] += '每个评分位置绘制“★★★★★”。'
    plan['selected_prompt_original'] = '零跑A10 购车参考 星级评分'
    errors = core.validate_image_plan(plan, {'title': '零跑A05'}, {'vehicle_model': '零跑A05'})
    assert '图片文字槽重复' not in errors
    plan['text_blocks'] += ['购车参考']
    assert '图片文字槽重复' in core.validate_image_plan(plan, {}, {})


def test_local_patch_preserves_unaffected_layout_and_copy(monkeypatch, tmp_path):
    broken = sample_plan()
    broken['adapted_prompt'] = broken['adapted_prompt'].replace('小字“购车参考”', '小字“出行参考”')
    original = copy.deepcopy(broken)
    prompts = []

    def relay(messages, **kwargs):
        prompts.append(messages[0]['content'])
        if len(prompts) == 1:
            return copy.deepcopy(broken)
        return {'prompt_replacements': [{'old': '小字“出行参考”', 'new': '小字“购车参考”'}]}

    monkeypatch.setattr(runner, 'relay_json', relay)
    result = runner.build_image_plan(**plan_kwargs(tmp_path))
    assert len(prompts) == 2
    assert '本轮只修复' in prompts[1] and '图片文字槽没有逐字写入' in prompts[1]
    assert result['adapted_prompt'] == sample_plan()['adapted_prompt']
    assert result['slot_mappings'] == original['slot_mappings']
    assert result['scene_change'] == original['scene_change']
    assert broken == original


@pytest.mark.parametrize('patch', [
    {'prompt_replacements': [{'old': '不存在', 'new': 'x'}]},
    {'prompt_replacements': [{'old': '', 'new': 'x'}]},
    {'adapted_prompt': '整篇重写'},
    {'prompt_replacements': [{'old': '重复', 'new': 'x'}]},
    {'prompt_replacements': [{'old': '字体', 'new': 'x'}, {'old': '深蓝色字体', 'new': 'y'}]},
])
def test_patch_requires_unique_nonoverlapping_anchors(patch):
    plan = sample_plan()
    plan['adapted_prompt'] += '重复重复'
    with pytest.raises(ValueError):
        runner.apply_image_plan_patch(plan, patch)


def test_patch_cannot_bypass_amount_validation(monkeypatch, tmp_path):
    broken = sample_plan()
    broken['adapted_prompt'] = broken['adapted_prompt'].replace('购车参考', '出行参考')
    bad_mappings = copy.deepcopy(broken['slot_mappings'])
    bad_mappings[1]['output'] = '仅需99999元'
    responses = iter([broken, {'prompt_replacements': [
        {'old': '出行参考', 'new': '仅需99999元'}], 'slot_mappings': bad_mappings}])
    monkeypatch.setattr(runner, 'relay_json', lambda *a, **kw: next(responses))
    with pytest.raises(RuntimeError, match='未登记金额'):
        runner.build_image_plan(**plan_kwargs(tmp_path))


@pytest.mark.parametrize('raw', [None, '', 'not-json', '[]'])
def test_unusable_relay_response_is_not_a_template_failure(monkeypatch, tmp_path, raw):
    monkeypatch.setenv('INTERNAL_RELAY_API_KEY', 'offline-test')
    monkeypatch.setattr(runner, 'request_json', lambda *a, **kw: {
        'choices': [{'message': {'content': raw}, 'finish_reason': 'stop'}]})
    with pytest.raises(runner.ImagePlanResponseError):
        runner.relay_json([], model='mock', trace_path=tmp_path / 'trace.json')
    assert 'elapsed_seconds' in json.loads((tmp_path / 'trace.json').read_text())


def test_empty_response_retries_same_template_then_succeeds(monkeypatch, tmp_path):
    calls = []

    def relay(*a, **kw):
        calls.append(kw['trace_path'].name)
        if len(calls) == 1:
            raise runner.ImagePlanResponseError('empty')
        return sample_plan()

    monkeypatch.setattr(runner, 'relay_json', relay)
    result = runner.build_image_plan(**plan_kwargs(tmp_path))
    assert result['selected_prompt_id'] == 509 and result['plan_attempt'] == 2
    assert len(calls) == 2 and all(name.startswith('prompt-509-') for name in calls)


def make_run(tmp_path, keys, monkeypatch):
    run = runner.ProductionRun.__new__(runner.ProductionRun)
    run.run_dir = tmp_path
    run.checkpoint_path = tmp_path / 'checkpoint.json'
    run.lock = threading.RLock()
    run.config = {'copy_workers': 2, 'image_plan_workers': 2, 'image_workers': 2, 'text_workers': 4}
    run.online = SimpleNamespace(public_root='https://example.test', prompts=lambda: [])
    run.cases = {'a05': {'vehicle_model': '零跑A05', 'brand': '零跑汽车'}}
    run.args = SimpleNamespace(batch_date='2026-09-07', copy_only=False, plan_only=False)
    run.state = {'batch_date': '2026-09-07', 'car_images': {'a05': {'斜前方': '/car.png'}}, 'posts': {
        key: {'key': key, 'case_id': 'a05', 'account_id': 42, 'account_name': '测试账号',
              'slot': i, 'mother': {'id': i}, 'prompt_template': {'id': i, 'chinese': '母版原文'},
              'reserve_prompt_template': {'id': 100 + i}} for i, key in enumerate(keys, 1)}}
    run.tasks = list(run.state['posts'].values())
    run.policy_metadata = {}
    run.policy_fingerprints = lambda: {}
    monkeypatch.setattr(runner, 'compile_ocr', lambda path: path / 'fake-ocr')
    monkeypatch.setattr(runner, 'emit', lambda *a, **kw: None)
    return run


def test_empty_upstream_does_not_burn_through_other_templates(monkeypatch, tmp_path):
    run = make_run(tmp_path, ['p'], monkeypatch)
    run.state['posts']['p']['copy'] = {'ok': True}
    called = []

    def plan(**kwargs):
        called.append(kwargs['template']['id'])
        raise runner.ImagePlanResponseError('empty twice')

    monkeypatch.setattr(runner, 'build_image_plan', plan)
    with pytest.raises(RuntimeError):
        run.image_plan_stage()
    assert called == [1]
    assert run.state['posts']['p']['image_plan']['retry_template']['id'] == 1
    with pytest.raises(RuntimeError):
        run.image_plan_stage()
    assert called == [1, 1]


def test_ready_post_starts_image_before_slow_copy_or_slow_plan_finishes(monkeypatch, tmp_path):
    run = make_run(tmp_path, ['fast', 'slow-copy', 'slow-plan', 'failed-plan'], monkeypatch)
    fast_image = threading.Event()
    events = []

    def copy_job(row):
        if row['key'] == 'slow-copy':
            assert fast_image.wait(3), 'fast image waited for every copy'
        events.append(('copy', row['key']))
        return row['key'], {'ok': True, 'title': '零跑A05', 'content': '测试正文'}

    def plan_job(row):
        if row['key'] == 'slow-plan':
            assert fast_image.wait(3), 'fast image waited for every plan'
        events.append(('plan', row['key']))
        return row['key'], {'ok': row['key'] != 'failed-plan', 'selected_prompt_id': 1}

    def image_job(row, binary):
        events.append(('image', row['key']))
        if row['key'] == 'fast':
            fast_image.set()
        return row['key'], {'ok': True, 'status': 'completed', 'image_url': '/image.png'}

    run.copy_job = copy_job
    run.image_planner = lambda pending: plan_job
    run.image_job = image_job
    with pytest.raises(RuntimeError, match='1 incomplete posts'):
        run.production_pipeline()
    assert events.index(('image', 'fast')) < events.index(('copy', 'slow-copy'))
    assert events.index(('image', 'fast')) < events.index(('plan', 'slow-plan'))
    assert ('image', 'failed-plan') not in events
    for key in ['fast', 'slow-copy', 'slow-plan']:
        assert run.state['posts'][key]['image']['ok']
        assert set(run.state['posts'][key]['timings']) == {'copy', 'image_plan', 'image'}
    manifest, _ = run.render()
    delivery = json.loads(manifest.read_text())
    assert delivery['completed'] == 3 and not delivery['production_ready']
    assert web_worker.retryable_image_keys(delivery) == ['failed-plan']
    assert web_worker.image_recovery_arguments(delivery) == []


def test_resume_preserves_good_plans_and_completed_siblings(monkeypatch, tmp_path):
    run = make_run(tmp_path, ['done', 'ready-plan', 'failed-plan'], monkeypatch)
    for row in run.state['posts'].values():
        row['copy'] = {'ok': True, 'title': '原题', 'content': '原正文'}
    run.state['posts']['done'].update(image_plan={'ok': True, 'selected_prompt_id': 11},
                                     image={'ok': True, 'task_id': 'existing', 'status': 'completed'})
    run.state['posts']['ready-plan']['image_plan'] = {'ok': True, 'selected_prompt_id': 12}
    run.state['posts']['failed-plan']['image_plan'] = {'ok': False}
    original = copy.deepcopy(run.state['posts'])
    calls = []
    run.copy_job = lambda row: pytest.fail('completed copy must not regenerate')

    def planner(pending):
        assert [row['key'] for row in pending] == ['failed-plan']
        def job(row):
            calls.append(('plan', row['key']))
            return row['key'], {'ok': True, 'selected_prompt_id': 13}
        return job

    def image_job(row, binary):
        calls.append(('image', row['key']))
        return row['key'], {'ok': True, 'status': 'completed'}

    run.image_planner = planner
    run.image_job = image_job
    run.production_pipeline()
    assert Counter(calls) == Counter([('plan', 'failed-plan'), ('image', 'ready-plan'), ('image', 'failed-plan')])
    assert run.state['posts']['done'] == original['done']
    assert run.state['posts']['ready-plan']['image_plan'] == original['ready-plan']['image_plan']
    assert all(row['copy'] == original[key]['copy'] for key, row in run.state['posts'].items())
    run.production_pipeline()
    assert len(calls) == 3


def test_40_post_pipeline_obeys_separate_concurrency_limits(monkeypatch, tmp_path):
    run = make_run(tmp_path, [f'p{i}' for i in range(40)], monkeypatch)
    lock = threading.Lock()
    active = Counter()
    peak = Counter()
    calls = Counter()
    barriers = {stage: threading.Barrier(2, timeout=3) for stage in ['copy', 'plan', 'image']}

    def job(stage, row):
        with lock:
            active[stage] += 1
            peak[stage] = max(peak[stage], active[stage])
            calls[(stage, row['key'])] += 1
        barriers[stage].wait()
        with lock:
            active[stage] -= 1
        return row['key'], {'ok': True, 'status': 'completed'}

    run.copy_job = lambda row: job('copy', row)
    run.image_planner = lambda pending: lambda row: job('plan', row)
    run.image_job = lambda row, binary: job('image', row)
    run.production_pipeline()
    assert peak == {'copy': 2, 'plan': 2, 'image': 2}
    assert len(calls) == 120 and set(calls.values()) == {1}
    assert all(row['image']['ok'] for row in run.state['posts'].values())


def test_worker_only_replaces_confirmed_exhausted_image_plans():
    def post(key, **extra):
        return {'key': key, 'title': '标题', 'content': '正文', 'copy_ok': True, **extra}
    delivery = {'posts': [
        post('done', image_url='/ok.png', hard_pass=True),
        post('bad-copy', copy_ok=False),
        post('plan-ready', image_plan_ok=True),
        post('plan-failed', image_plan_ok=False),
        post('submitted', image_plan_ok=True, image_status='submitted'),
        post('image-failed', image_plan_ok=True, image_status='failed'),
    ]}
    assert web_worker.retryable_image_keys(delivery) == ['plan-ready', 'plan-failed', 'submitted', 'image-failed']
    assert web_worker.image_recovery_arguments(delivery) == ['--retry-image-keys', 'image-failed']
    assert web_worker.image_recovery_arguments({'posts': [post('legacy')]}) == []


def test_pipeline_does_not_double_shared_gpt_concurrency(monkeypatch, tmp_path):
    run = make_run(tmp_path, [f'p{i}' for i in range(40)], monkeypatch)
    run.config = {'copy_workers': 8, 'image_plan_workers': 8, 'image_workers': 5}
    lock = threading.Lock()
    active = 0
    peak = 0

    def text(row):
        nonlocal active, peak
        with lock:
            active += 1
            peak = max(peak, active)
        time.sleep(0.002)
        with lock:
            active -= 1
        return row['key'], {'ok': True}

    run.copy_job = text
    run.image_planner = lambda pending: text
    run.image_job = lambda row, binary: (row['key'], {'ok': True})
    run.production_pipeline()
    assert 1 < peak <= 8


def test_ready_plan_has_priority_over_copy_backlog(monkeypatch, tmp_path):
    run = make_run(tmp_path, ['first', 'second', 'third'], monkeypatch)
    run.config = {'copy_workers': 1, 'image_plan_workers': 1, 'image_workers': 1, 'text_workers': 1}
    calls = []

    def job(stage, row):
        calls.append((stage, row['key']))
        return row['key'], {'ok': True}

    run.copy_job = lambda row: job('copy', row)
    run.image_planner = lambda pending: lambda row: job('plan', row)
    run.image_job = lambda row, binary: job('image', row)
    run.production_pipeline()
    assert calls.index(('plan', 'first')) < calls.index(('copy', 'second'))
    assert calls.index(('plan', 'second')) < calls.index(('copy', 'third'))


def test_outer_worker_resumes_without_resetting_ready_plans_or_sleeping(monkeypatch, tmp_path):
    monkeypatch.setenv('HERMES_IMAGE_RECOVERY_ROUNDS', '2')
    monkeypatch.setattr(web_worker, 'build_run_config', lambda *a: ({}, '2026-09-07'))
    monkeypatch.setattr(web_worker, 'capabilities', lambda: {})
    monkeypatch.setattr(web_worker, 'request_json', lambda *a, **kw: {'id': 10})
    monkeypatch.setattr(web_worker.time, 'sleep', lambda *a: pytest.fail('unnecessary completion polling sleep'))
    commands = []
    reports = []
    monkeypatch.setattr(web_worker, 'send_report', lambda base, token, path: reports.append(json.loads(path.read_text())))
    output = tmp_path / 'run-10' / '2026-09-07'
    candidates = {'posts': [
        {'key': 'ready-plan', 'title': '标题', 'content': '正文', 'copy_ok': True, 'image_plan_ok': True},
        {'key': 'failed-plan', 'title': '标题', 'content': '正文', 'copy_ok': True, 'image_plan_ok': False},
    ]}

    class Process:
        def __init__(self, command, **kwargs):
            commands.append(command)
            self.number = len(commands)
            self.returncode = None

        def poll(self):
            return self.returncode

        def wait(self, timeout):
            output.mkdir(parents=True, exist_ok=True)
            name = 'delivery_candidate.json' if self.number == 1 else 'delivery.json'
            payload = candidates if self.number == 1 else {'production_ready': True, 'posts': []}
            (output / name).write_text(json.dumps(payload))
            self.returncode = 1 if self.number == 1 else 0
            return self.returncode

    monkeypatch.setattr(web_worker.subprocess, 'Popen', Process)
    assert web_worker.run_once('https://example.test', 'offline', 'test', tmp_path)
    assert len(commands) == 2 and commands[0] == commands[1]
    assert all('--retry-image-keys' not in command for command in commands)
    assert reports[0]['path'].endswith('/complete')
    assert reports[0]['body']['delivery']['production_ready'] is True


def test_pipeline_reconnect_waits_existing_image_task_without_resubmitting(monkeypatch, tmp_path):
    run = make_run(tmp_path, ['submitted'], monkeypatch)
    row = run.state['posts']['submitted']
    row.update(copy={'ok': True}, image_plan={'ok': True, 'text_blocks': []}, image={
        'ok': False, 'status': 'submitted', 'attempt': 1, 'task_id': 'existing-123',
        'generation_prompt': '原提示词'})
    run.online.absolute_url = lambda url: url
    run.submit_image = lambda *a: pytest.fail('must reconnect to accepted image task')
    seen = []
    def wait(task_id, model):
        seen.append(task_id)
        return {'status': 'completed', 'image_urls': ['https://example.test/image.png']}
    run.wait_image_task = wait
    run.download_image = lambda *a: None
    monkeypatch.setattr(runner, 'ocr_image', lambda *a: [])
    monkeypatch.setattr(runner, 'image_ocr_errors', lambda *a, **kw: [])
    run.production_pipeline()
    assert seen == ['existing-123']
    assert row['image']['task_id'] == 'existing-123' and row['image']['ok']


def test_progress_snapshot_is_written_for_one_ready_post_without_finishing_siblings(monkeypatch, tmp_path):
    run = make_run(tmp_path, ['first', 'still-running'], monkeypatch)
    row = run.state['posts']['first']
    row.update(copy={'ok': True, 'title': '完整标题', 'content': '完整正文'}, image_plan={'ok': True})
    run.record_stage_result('image', 'first', {'ok': True, 'status': 'completed',
                                              'image_url': 'https://example.test/image.png'})
    progress = json.loads((tmp_path / 'progress.json').read_text())
    assert progress['completed'] == 1 and progress['expected'] == 2
    assert [p['key'] for p in progress['posts']] == ['first']
    assert progress['posts'][0]['hard_pass'] and not progress['production_ready']
    assert not (tmp_path / 'delivery.json').exists()
    assert 'image' not in run.state['posts']['still-running']


def test_progress_retry_advances_digest_only_after_ack_and_does_not_call_complete(monkeypatch, tmp_path):
    snapshot = tmp_path / 'progress.json'
    snapshot.write_text(json.dumps({'posts': [{'key': 'first', 'hard_pass': True}]}))
    calls = []
    def request(base, path, token, body, **kwargs):
        calls.append((path, body, kwargs))
        if len(calls) == 1:
            raise TimeoutError('simulated lost acknowledgement')
        return {}
    monkeypatch.setattr(web_worker, 'request_json', request)
    with pytest.raises(TimeoutError):
        web_worker.send_progress('https://example.test', 'offline', 10, 'worker', tmp_path, None)
    digest = web_worker.send_progress('https://example.test', 'offline', 10, 'worker', tmp_path, None)
    assert web_worker.send_progress('https://example.test', 'offline', 10, 'worker', tmp_path, digest) == digest
    assert len(calls) == 2 and calls[0] == calls[1]
    assert calls[0][0].endswith('/progress') and calls[0][2]['timeout'] == 5
    assert snapshot.exists()


def test_worker_sends_partial_results_while_producer_is_still_running(monkeypatch, tmp_path):
    output = tmp_path / 'run-10' / '2026-09-07'
    events = []
    processes = []
    monkeypatch.setattr(web_worker, 'build_run_config', lambda *a: ({}, '2026-09-07'))
    monkeypatch.setattr(web_worker, 'capabilities', lambda: {})

    class Process:
        returncode = None
        def __init__(self, *a, **kw):
            processes.append(self)
            output.mkdir(parents=True)
            (output / 'progress.json').write_text(json.dumps({'completed': 3, 'expected': 4,
                'posts': [{'key': f'p{i}', 'hard_pass': True} for i in range(3)]}))
        def poll(self):
            return self.returncode
        def wait(self, timeout):
            assert 'progress' in events, 'must deliver the first three before the fourth finishes'
            self.returncode = 0
            (output / 'delivery.json').write_text(json.dumps({'production_ready': True, 'posts': []}))
            return 0

    def request(base, path, token, body, **kwargs):
        if path.endswith('/claim'):
            return {'id': 10}
        if path.endswith('/progress'):
            assert processes[0].returncode is None
            assert body['delivery']['completed'] == 3
            events.append('progress')
        if path.endswith('/complete'):
            events.append('complete')
        return {}

    monkeypatch.setattr(web_worker, 'request_json', request)
    monkeypatch.setattr(web_worker.subprocess, 'Popen', Process)
    assert web_worker.run_once('https://example.test', 'offline', 'worker', tmp_path)
    assert events == ['progress', 'complete']
