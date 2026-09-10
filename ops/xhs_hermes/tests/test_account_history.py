import random
import sys
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest

sys.path.insert(0, str(Path(__file__).parents[1]))
import run_daily_8x5 as runner
from core import ACCOUNT_HIGH_SIMILARITY, account_repetition_check, select_diverse_rows


BODY = ('第一段先解释日常通勤的实际需要与预算安排，先把用车场景想清楚。\n'
        '第二段再对比续航和座舱的差异，结合周末出游考虑充电频率和路线。\n'
        '第三段讨论试车时的具体观察位置，按照自己的家庭人数选择合适方案。')
OTHER = ('选车不必着急下决定，先列一个小清单记录自己的问题与体验感受。\n'
         '到店绕车走一圈，再看收纳位置和驾驶视野，体会停车以及城市道路操作。\n'
         '周末邀请家人一起参与体验，让乘坐和装载需要都得到充分讨论与确认。')


def note(i, account=42, **kwargs):
    return {'id': i, 'environment_id': account, 'status': 'active',
            'published_at': f'2026-07-{i:02d}T12:00:00Z', 'title': f'帖子{i}',
            'content': BODY, **kwargs}


def test_last15_are_per_account_not_a_recent_day_window():
    rows = [note(i) for i in range(1, 21)] + [note(22, account=27), note(23, status='offline')]
    random.Random(4).shuffle(rows)
    selected = runner.latest_account_posts(rows, 42)
    assert [r['id'] for r in selected] == list(range(20, 5, -1))
    assert {r['environment_id'] for r in selected} == {42}


def test_brief_keeps_15_full_bodies_and_does_not_backfill_missing():
    rows = [note(i, content='' if i == 20 else BODY + '\n正文最后的关键句') for i in range(1, 21)]
    briefs = runner.build_avoidance_briefs([{'account_id':42}, {'account_id':27}], rows)
    brief = briefs[42]
    assert len(brief['recent_posts']) == len(brief['recent_titles']) == 15
    assert brief['recent_posts'][0]['content'] == ''
    assert brief['recent_posts'][1]['content'].endswith('正文最后的关键句')
    assert brief['history_missing_body'] == 1
    assert brief['history_status'] == 'partial_bodies'
    assert briefs[27]['history_status'] == 'no_synced_posts'
    assert not briefs[27]['recent_posts']


def test_history_sort_handles_timezone_and_missing_dates():
    rows = [note(1, published_at='2026-09-01T09:00:00+08:00'),
            note(2, published_at='2026-09-01T02:00:00Z'),
            note(3, published_at=None, sort_index=2), note(4, published_at=None, sort_index=1)]
    assert [r['id'] for r in runner.latest_account_posts(rows,42)] == [2,1,4,3]


def test_history_deduplicates_feed_ids_without_cross_account_leak():
    rows = [note(1, feed_id='same'), note(2, feed_id='same'), note(3, account=27,feed_id='same')]
    assert [r['id'] for r in runner.latest_account_posts(rows,42)] == [2]


def online_stub():
    online = runner.OnlineData.__new__(runner.OnlineData)
    online.backend = 'https://example.test/api/backend'
    online.auth = {'Authorization': 'Bearer test'}
    return online


def test_api_queries_only_selected_accounts_and_no_date_filter(monkeypatch):
    seen = []
    def request(url, **kwargs):
        query = parse_qs(urlparse(url).query)
        seen.append(query)
        assert urlparse(url).path.endswith('/xhs/account-notes')
        assert not {'start_date','end_date','include_items'} & query.keys()
        account = int(query['environment_id'][0])
        return {'data': {'items':[note(i,account=account) for i in range(15,0,-1)], 'total':90}}
    monkeypatch.setattr(runner,'request_json',request)
    rows = online_stub().recent_posts([42,27,42])
    assert len(rows) == 30
    assert {q['environment_id'][0] for q in seen} == {'42','27'}
    assert all(q['limit'] == ['15'] and q['status'] == ['active'] for q in seen)


@pytest.mark.parametrize('response,message', [
    ({'data':{'items':[note(1,account=27)],'total':1}}, 'another account'),
    ({'data':{'items':[],'total':15}}, 'incomplete'),
    ({'data':{}}, 'invalid list'),
])
def test_bad_history_response_is_not_silently_empty(monkeypatch,response,message):
    monkeypatch.setattr(runner,'request_json',lambda *a,**kw:response)
    with pytest.raises(RuntimeError,match=message):
        online_stub().recent_posts([42])


def test_no_history_is_allowed_but_request_failure_is_not(monkeypatch):
    monkeypatch.setattr(runner,'request_json',lambda *a,**kw:{'data':{'items':[],'total':0}})
    assert online_stub().recent_posts([42]) == []
    def failed(*a,**kw): raise TimeoutError('upstream unavailable')
    monkeypatch.setattr(runner,'request_json',failed)
    with pytest.raises(TimeoutError): online_stub().recent_posts([42])


def test_highly_similar_whole_post_is_recorded_but_not_a_hard_error():
    result = account_repetition_check('新标题', BODY, [note(1)])
    assert result['status'] == 'high_similarity'
    assert result['closest_note_id'] == 1
    assert result['blocking'] is False
    assert result['compared_bodies'] == 1


def test_shared_topics_and_cta_do_not_make_different_posts_duplicates():
    footer = '\n扣【城市+车型】，了解当地购车参考\n#零跑A05[话题]# #购车攻略[话题]#'
    result = account_repetition_check('零跑A05怎么选', BODY+footer, [note(1,content=OTHER+footer)])
    assert result['status'] == 'allowed'
    assert result['score'] < ACCOUNT_HIGH_SIMILARITY
    result = account_repetition_check('标题', BODY, [note(1,content='')])
    assert result['status'] == 'insufficient_history'


class FixedRandom:
    def __init__(self): self.value = 0
    def shuffle(self, rows): pass
    def random(self):
        self.value += 1
        return self.value / 100


def select(pool, history, account=42, window=1):
    return select_diverse_rows(pool,count=1,historical_texts_by_account=history,
        task_account_ids=[account],vehicle_terms=[],candidate_window=window,
        near_duplicate_cap=.85,account_near_duplicate_cap=.85,
        tolerate_moderate_similarity=True,rng=FixedRandom())[0]


def test_high_account_overlap_expands_window_and_selects_different_mother():
    pool = [{'id':1,'title':'帖子1','content':BODY}, {'id':2,'title':'另一篇','content':OTHER}]
    selected = select(pool,{42:['帖子1\n'+BODY]})
    assert selected['id'] == 2
    assert selected['selection_note'] == 'expanded_for_diversity'
    assert not selected['selection_relaxed']
    # A different account is not incorrectly treated as this account's history.
    assert select(pool,{27:['帖子1\n'+BODY]})['id'] == 1


def test_moderate_similarity_is_allowed_without_forcing_least_similar():
    medium = BODY.split('\n')[0]+'\n'+BODY.split('\n')[1]+'\n'+OTHER.split('\n')[2]
    report = account_repetition_check('帖子1',medium,[note(1)])
    assert .3 < report['score'] < .85
    pool = [{'id':1,'title':'帖子1','content':medium},{'id':2,'title':'别的','content':OTHER}]
    assert select(pool,{42:['帖子1\n'+BODY]},window=2)['id'] == 1


def test_only_high_overlap_available_relaxes_once_instead_of_looping():
    selected = select([{'id':1,'title':'帖子1','content':BODY}],{42:['帖子1\n'+BODY]})
    assert selected['id'] == 1
    assert selected['selection_relaxed']
    assert selected['selection_note'] == 'near_duplicate_cap_relaxed'
