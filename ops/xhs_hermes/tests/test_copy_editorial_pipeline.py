"""Production routing regressions: independent review, retries and race-free admission."""
import concurrent.futures
import json
from pathlib import Path
import sys
import threading
import time

import pytest

sys.path.insert(0, str(Path(__file__).parents[1]))
import run_daily_8x5 as runner


def make_run(tmp_path, level='interpretive'):
    run = runner.ProductionRun.__new__(runner.ProductionRun)
    run.config = {'adaptation_level':level, 'copy_attempts_per_mother':2}
    run.run_dir = tmp_path
    run.checkpoint_path = tmp_path / 'checkpoint.json'
    run.lock = threading.RLock()
    run.cases = {'car':{'policy_text':'车色有绿色。'}}
    run.state = {'posts':{key:{'key':key, 'case_id':'car', 'mother':{'id':i,'title':'车色','content':'看看绿色。'}}
                          for i,key in enumerate(['one','two'],1)}}
    return run


def plan(row, mother):
    return {'key':row['key'], 'mother_id':mother['id'], 'source_topic':'车色',
            'source_hook':'绿色', 'source_evidence':'看看绿色。', 'target_angle':'看车色',
            'reader_takeaway':'观察绿色', 'writing_approach':'直说颜色',
            'fact_basis':[{'quote':'车色有绿色。'}], 'avoid_detours':[]}


def passing():
    return {'topic_preserved':True,'facts_supported':True,'internal_instruction_leak':False,'voice_preserved':True,
            'duplicate_of':[],'issues':[],'summary':'话题与事实一致。'}


def test_rejected_draft_is_revised_not_delivered(monkeypatch, tmp_path):
    run = make_run(tmp_path)
    monkeypatch.setattr(run, 'editorial_plan', plan)
    payloads = []
    def write(payload, *args):
        payloads.append(payload)
        return {'ok':True, 'title':'车色', 'content':'看看绿色。'}
    verdicts = iter([{'ok':False,'feedback':'不要改成版本选择'}, {'ok':True,'feedback':''}])
    monkeypatch.setattr(runner, 'run_copy_subprocess', write)
    monkeypatch.setattr(run, 'review_copy', lambda *args:next(verdicts))
    _, result = run.copy_job(run.state['posts']['one'])
    assert result['ok'] and len(payloads) == 2
    assert payloads[1]['revision']['content'] == '看看绿色。'
    assert '版本选择' in payloads[1]['revision']['feedback']
    assert len(result['previous_failures']) == 1


def test_critic_outage_is_bounded_and_cannot_pass(monkeypatch, tmp_path):
    run = make_run(tmp_path)
    monkeypatch.setattr(run, 'editorial_plan', plan)
    calls = []
    def write(*args):
        calls.append(1)
        return {'ok':True, 'title':'车色', 'content':'看看绿色。'}
    monkeypatch.setattr(runner, 'run_copy_subprocess', write)
    monkeypatch.setattr(run, 'review_copy', lambda *args: (_ for _ in ()).throw(ValueError('invalid review')))
    _, result = run.copy_job(run.state['posts']['one'])
    assert not result['ok'] and len(calls) == 2
    assert all(row['content'] == '看看绿色。' for row in result['failures'])


def test_voice_review_flows_back_into_actual_worker_revision(monkeypatch, tmp_path):
    run = make_run(tmp_path)
    monkeypatch.setattr(run, 'editorial_plan', plan)
    monkeypatch.setattr('vehicle_knowledge.knowledge_for_case', lambda *args: {})
    payloads = []
    def write(payload, *args):
        payloads.append(payload)
        return {'ok': True, 'title': '车色', 'content': '看看绿色。'}
    def relay(messages, **kwargs):
        if len(payloads) == 1:
            return {**passing(), 'voice_preserved': False, 'issues': [
                {'kind': 'voice', 'evidence': '看看绿色。', 'reason': '保留母文的心动，不写检查项。'}
            ]}
        return passing()
    monkeypatch.setattr(runner, 'run_copy_subprocess', write)
    monkeypatch.setattr(runner, 'relay_json', relay)
    _, result = run.copy_job(run.state['posts']['one'])
    assert result['ok'] and len(payloads) == 2
    assert '[voice]' in payloads[1]['revision']['feedback']
    assert payloads[1]['revision']['content'] == '看看绿色。'
    assert not result['previous_failures'][0]['editorial_review']['voice_preserved']


@pytest.mark.parametrize('level',['replica','light'])
def test_other_levels_do_not_call_editorial_model(monkeypatch, tmp_path, level):
    run = make_run(tmp_path, level)
    monkeypatch.setattr(run, 'editorial_plan', lambda *a: pytest.fail('unexpected editorial call'))
    monkeypatch.setattr(runner, 'run_copy_subprocess', lambda *a: {'ok':True})
    assert run.copy_job(run.state['posts']['one'])[1]['ok']


def test_parallel_admission_observes_first_accepted_peer(monkeypatch, tmp_path):
    run = make_run(tmp_path)
    snapshots = []
    monkeypatch.setattr('vehicle_knowledge.knowledge_for_case', lambda *args:{})
    def relay(messages, **kwargs):
        data = json.loads(messages[1]['content'])
        snapshots.append(data['peers'])
        time.sleep(.02)
        if data['peers']:
            return {**passing(), 'duplicate_of':[data['peers'][0]['key']],
                    'issues':[{'kind':'duplicate', 'evidence':'看看绿色。', 'reason':'与先通过稿意义相同'}]}
        return passing()
    monkeypatch.setattr(runner, 'relay_json', relay)
    def review(row):
        return run.review_copy(row, row['mother'], {'ok':True,'title':'车色','content':'看看绿色。'},
                               plan(row,row['mother']), row['key'])
    with concurrent.futures.ThreadPoolExecutor(2) as pool:
        results = list(pool.map(review, run.state['posts'].values()))
    assert sum(item['ok'] for item in results) == 1
    assert sorted(len(items) for items in snapshots) == [0,1]


def test_resume_includes_older_accepted_copy_without_plan(monkeypatch, tmp_path):
    run = make_run(tmp_path)
    run.state['posts']['one']['copy'] = {'ok':True, 'title':'车色', 'content':'看看绿色。'}
    monkeypatch.setattr('vehicle_knowledge.knowledge_for_case', lambda *args:{})
    def relay(messages, **kwargs):
        assert json.loads(messages[1]['content'])['peers'][0]['key'] == 'one'
        return passing()
    monkeypatch.setattr(runner, 'relay_json', relay)
    row = run.state['posts']['two']
    assert run.review_copy(row, row['mother'], {'ok':True,'title':'另稿','content':'另一观察'},
                           plan(row,row['mother']), 'resume')['ok']


def test_legacy_narrative_does_not_override_actual_mother(tmp_path):
    run = make_run(tmp_path)
    row = {'creative_direction':{'narrative':{'name':'版本选择', 'brief':'比较403和505'}}}
    assert run.copy_operator_instruction(row) == ''


def test_plans_cached_for_peers_and_resume_without_extra_calls(monkeypatch, tmp_path):
    run = make_run(tmp_path)
    monkeypatch.setattr('vehicle_knowledge.knowledge_for_case', lambda *args:{})
    calls = []
    def relay(messages, **kwargs):
        data = json.loads(messages[1]['content'])
        calls.append(data)
        return {'plans':[plan(row,row['mother']) for row in data['rows']]}
    monkeypatch.setattr(runner, 'relay_json', relay)
    one, two = run.state['posts'].values()
    assert run.editorial_plan(one, one['mother'])['key'] == 'one'
    assert run.editorial_plan(two, two['mother'])['key'] == 'two'
    assert len(calls) == 1
    resumed = make_run(tmp_path)
    resumed.state = json.loads(run.checkpoint_path.read_text())
    row = resumed.state['posts']['one']
    assert resumed.editorial_plan(row, row['mother'])['key'] == 'one'
    assert len(calls) == 1


def test_bad_peer_plan_falls_back_to_single_mother(monkeypatch, tmp_path):
    run = make_run(tmp_path)
    monkeypatch.setattr('vehicle_knowledge.knowledge_for_case', lambda *args:{})
    counts = []
    def relay(messages, **kwargs):
        data = json.loads(messages[1]['content'])
        counts.append(len(data['rows']))
        return {'plans':[] if len(data['rows']) > 1 else [plan(data['rows'][0],data['rows'][0]['mother'])]}
    monkeypatch.setattr(runner, 'relay_json', relay)
    row = run.state['posts']['one']
    assert run.editorial_plan(row, row['mother'])['key'] == 'one'
    assert counts == [2,2,1]
    assert 'editorial_plans' not in run.state['posts']['two']


def test_bad_primary_can_use_grounded_reserved_mother(monkeypatch, tmp_path):
    run = make_run(tmp_path)
    row = run.state['posts']['one']
    row['reserve_mother'] = {'id':9,'title':'车色','content':'看看绿色。'}
    seen = []
    def planning(row, mother):
        seen.append(mother['id'])
        if mother['id'] == 1:
            raise ValueError('unsupported source topic')
        return plan(row,mother)
    monkeypatch.setattr(run, 'editorial_plan', planning)
    monkeypatch.setattr(runner, 'run_copy_subprocess', lambda payload,*a:{'ok':True,'selected_mother_id':payload['mother_id']})
    monkeypatch.setattr(run, 'review_copy', lambda *a:{'ok':True})
    result = run.copy_job(row)[1]
    assert result['ok'] and result['used_reserve_mother'] and result['mother']['id'] == 9
    assert seen == [1,9]


def test_weekly_usage_reads_sibling_runs_today_but_not_itself(tmp_path):
    def put(run_id, day, name, posts):
        runner.atomic_json(tmp_path / f'run-{run_id}' / day / name, {'posts':posts})
    put(1,'2026-09-20','delivery.json',[{'mother_copy_id':1,'hard_pass':True}])
    put(1,'2026-09-20','delivery_candidate.json',[{'mother_copy_id':1,'hard_pass':True}])
    put(2,'2026-09-20','delivery_candidate.json',[{'mother_copy_id':2,'hard_pass':True}, {'mother_copy_id':3,'hard_pass':False}])
    put(3,'2026-09-19','delivery.json',[{'mother_copy_id':4,'hard_pass':True}])
    put(4,'2026-09-13','delivery.json',[{'mother_copy_id':5,'hard_pass':True}])
    put(9,'2026-09-20','delivery.json',[{'mother_copy_id':9,'hard_pass':True}])
    rows = runner.current_week_ledger_rows(tmp_path / 'run-9', '2026-09-20')
    assert [row['mother_copy_id'] for row in rows] == [1,2,4]


@pytest.mark.parametrize('text',[
    '我觉得A10这篇不用硬聊成“选哪一款”', '政策期写到9月底前。',
    '按照母文要求只替换车型。',
    '它不是大七座那种叙事，更像一台家用小车。',
    '别拿SUV那套空间故事硬套。',
    '政策时间写到9月底前，保留当前权益。',
    '线上别把它和国补混成一个价。',
])
def test_explicit_editorial_language_from_live_samples_is_detected(text):
    from core import INTERNAL_COPY_INSTRUCTION_RE
    assert INTERNAL_COPY_INSTRUCTION_RE.search(text)


@pytest.mark.parametrize('text',[
    '这篇只要看懂补贴条件就行。', '本篇整理9月底前的购车权益。',
    '我会先看绿色，照片和实车可能有色差。',
    '别拿指导价直接当落地价。',
    '政策时间到9月底前。',
])
def test_reader_language_is_not_an_editorial_leak(text):
    from core import INTERNAL_COPY_INSTRUCTION_RE
    assert not INTERNAL_COPY_INSTRUCTION_RE.search(text)
