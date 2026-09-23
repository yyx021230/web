"""Offline contracts for source-grounded planning and independent criticism."""
from copy import deepcopy
import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).parents[1]))

from copy_editorial import (
    editorial_instruction,
    parse_plans,
    parse_review,
    plan_messages,
    review_messages,
)
from copy_length import copy_budget


@pytest.fixture
def inputs():
    rows = [
        {'key': 'appearance', 'mother': {
            'id': 49, 'title': 'Look at the color before the badge',
            'content': 'Compare the exterior colors in daylight. Look at the cabin next.',
        }},
        {'key': 'finance', 'mother': {
            'id': 75, 'title': 'Check the finance conditions',
            'content': 'Check the loan term and approval requirements before applying.',
        }},
        {'key': 'eligibility', 'mother': {
            'id': '902', 'title': 'Who qualifies for this benefit?',
            'content': 'Confirm your trade-in eligibility before counting a benefit.',
        }},
    ]
    case = {
        'vehicle_model': 'A10',
        'policy_text': (
            'Finance: 24 months at 0%, subject to approval.\n'
            'Trade-in eligibility requires proof of ownership.'
        ),
        'publication_constraints': {'hide_local_subsidy_amounts': True},
        'operator_instruction': 'An operator instruction is not a policy fact.',
    }
    knowledge = {
        'status': 'matched',
        'common_facts': [{'key': 'Exterior color', 'value': 'Blue',
                          'source_excerpt': 'Exterior colors include blue and white.'}],
        'variants': [{'variant': '403', 'facts': [
            {'source_excerpt': '403: optional glass roof.'},
        ]}],
    }
    facts = [
        'Exterior colors include blue and white.',
        'Finance: 24 months at 0%, subject to approval.',
        'Trade-in eligibility requires proof of ownership.',
    ]
    plans = [
        {
            'key': row['key'], 'mother_id': row['mother']['id'],
            'source_topic': row['mother']['title'],
            'source_hook': row['mother']['title'],
            'source_evidence': row['mother']['content'],
            'target_angle': angle, 'reader_takeaway': takeaway,
            'writing_approach': 'Explain this source-specific question naturally.',
            'fact_basis': [{'quote': fact}],
            'avoid_detours': ['Do not turn this into 403 versus 505 version selection.'],
        }
        for row, fact, angle, takeaway in zip(rows, facts, (
            'Exterior color inspection before a showroom visit',
            'Loan term and approval conditions',
            'Ownership documentation needed for trade-in eligibility',
        ), (
            'Compare available colors in person without inventing a test drive.',
            'A quoted loan term does not guarantee approval.',
            'Check the ownership proof before counting a trade-in benefit.',
        ))
    ]
    return rows, case, knowledge, plans


@pytest.fixture
def draft():
    return {'title': 'Inspect exterior colors',
            'content': 'Exterior colors include blue and white. Compare them in daylight.'}


@pytest.fixture
def peers(inputs):
    plan = deepcopy(inputs[3][1])
    plan['key'] = 'accepted-finance'
    return [{'key': plan['key'], 'title': 'Check finance approval',
             'content': 'Finance: 24 months at 0%, subject to approval.',
             'editorial_plan': plan}]


def passing_review():
    return {'topic_preserved': True, 'facts_supported': True,
            'voice_preserved': True,
            'internal_instruction_leak': False, 'duplicate_of': [], 'issues': [],
            'summary': 'Source topic and facts are preserved; the reader problem is distinct.'}


def failed_review(kind, draft, peers):
    result = passing_review()
    if kind == 'topic':
        result['topic_preserved'] = False
    elif kind == 'fact':
        result['facts_supported'] = False
    elif kind == 'leak':
        result['internal_instruction_leak'] = True
    elif kind == 'duplicate':
        result['duplicate_of'] = [peers[0]['key']]
    elif kind == 'voice':
        result['voice_preserved'] = False
    result['issues'] = [{'kind': kind, 'evidence': draft['content'],
                         'reason': f'Repair the {kind} problem without changing the source topic.'}]
    result['summary'] = f'Targeted {kind} repair required.'
    return result


def test_planning_includes_full_sources_and_reserved_plans_without_mutation(inputs):
    rows, case, knowledge, plans = inputs
    previous = [deepcopy(plans[0])]
    previous[0]['key'] = 'reserved'
    snapshot = deepcopy((inputs, previous))
    messages = plan_messages(rows, case, knowledge, previous)
    assert [message['role'] for message in messages] == ['system', 'user']
    assert json.loads(messages[1]['content']) == {
        'rows': rows, 'case': case, 'product_knowledge': knowledge,
        'previous_plans': previous,
        'copy_budgets': {row['key']: copy_budget(row['mother'], case) for row in rows},
    }
    assert (inputs, previous) == snapshot
    assert json.loads(plan_messages(rows, case, knowledge)[1]['content'])['previous_plans'] == []
    assert plan_messages(rows, case, knowledge, previous) == messages


def test_plans_are_returned_in_row_order_as_independent_copies(inputs):
    rows, case, knowledge, plans = inputs
    payload = {'plans': list(reversed(plans))}
    parsed = parse_plans(payload, rows, case, knowledge)
    assert parsed == plans
    assert parse_plans(json.dumps(payload), rows, case, knowledge) == plans
    parsed[0]['fact_basis'][0]['quote'] = 'changed'
    assert plans[0]['fact_basis'][0]['quote'] != 'changed'


def test_source_quotes_can_be_from_title_and_nested_product_facts(inputs):
    rows, case, knowledge, plans = inputs
    plans[0]['source_evidence'] = rows[0]['mother']['title']
    plans[0]['fact_basis'] = [{'quote': '403: optional glass roof.'}]
    plans[0]['avoid_detours'] = []
    assert parse_plans({'plans': plans}, rows, case, knowledge) == plans


def test_quote_grounding_normalizes_only_whitespace(inputs):
    rows, case, knowledge, plans = inputs
    rows[0]['mother']['content'] = 'Compare\tthe\n exterior\u00a0colors in daylight.'
    plans[0]['source_evidence'] = ' Compare the exterior colors in daylight. '
    knowledge['common_facts'][0]['source_excerpt'] = 'Exterior\ncolors include\tblue and white.'
    plans[0]['fact_basis'][0]['quote'] = 'Exterior colors  include blue and white.'
    assert parse_plans({'plans': plans}, rows, case, knowledge) == plans


@pytest.mark.parametrize('quote', [
    'compare the exterior colors in daylight.',
    'Compare the exterior colors in daylight!',
    'Compare exterior colors in daylight.',
    'Compare ... in daylight.',
    'Comparetheexteriorcolorsindaylight.',
    'Check the loan term and approval requirements before applying.',
    'Exterior colors include blue and white.',
    'Look at the color before the badge Compare the exterior colors in daylight.',
])
def test_source_evidence_rejects_paraphrases_other_mothers_and_stitched_fields(inputs, quote):
    rows, case, knowledge, plans = inputs
    plans[0]['source_evidence'] = quote
    with pytest.raises(ValueError, match='source_evidence'):
        parse_plans({'plans': plans}, rows, case, knowledge)


@pytest.mark.parametrize('quote', [
    'EXTERIOR colors include blue and white.',
    'Exterior colors include blue and white!',
    'Exterior colors include blue...white.',
    'Standard glass roof on every version.',
    'Compare the exterior colors in daylight.',
    'An operator instruction is not a policy fact.',
    'source_excerpt',
    '"value": "Blue"',
    'Blue Exterior colors include blue and white.',
])
def test_fact_basis_rejects_unsupported_and_non_authoritative_quotes(inputs, quote):
    rows, case, knowledge, plans = inputs
    plans[0]['fact_basis'][0]['quote'] = quote
    with pytest.raises(ValueError, match='fact_basis'):
        parse_plans({'plans': plans}, rows, case, knowledge)


@pytest.mark.parametrize('field', [
    'key', 'mother_id', 'source_topic', 'source_hook', 'source_evidence',
    'target_angle', 'reader_takeaway', 'writing_approach', 'fact_basis', 'avoid_detours',
])
def test_every_plan_field_is_mandatory(inputs, field):
    rows, case, knowledge, plans = inputs
    del plans[0][field]
    with pytest.raises(ValueError):
        parse_plans({'plans': plans}, rows, case, knowledge)


@pytest.mark.parametrize('field', [
    'key', 'source_topic', 'source_hook', 'source_evidence',
    'target_angle', 'reader_takeaway', 'writing_approach',
])
@pytest.mark.parametrize('value', ['', ' \n\t', None, False, 17, [], {}])
def test_plan_text_fields_are_strict_nonempty_strings(inputs, field, value):
    rows, case, knowledge, plans = inputs
    plans[0][field] = value
    with pytest.raises(ValueError):
        parse_plans({'plans': plans}, rows, case, knowledge)


@pytest.mark.parametrize('field,value', [
    ('mother_id', '49'), ('mother_id', True), ('mother_id', 49.0), ('mother_id', 999),
    ('mother_id', None), ('mother_id', {}),
    ('fact_basis', []), ('fact_basis', None), ('fact_basis', 'quote'),
    ('fact_basis', [None]), ('fact_basis', [{}]), ('fact_basis', [{'quote': ''}]),
    ('fact_basis', [{'quote': True}]),
    ('fact_basis', [{'quote': 'Blue', 'source': 'invented'}]),
    ('avoid_detours', None), ('avoid_detours', 'none'),
    ('avoid_detours', ['']), ('avoid_detours', [1]),
])
def test_plan_identifier_and_nested_shapes_fail_closed(inputs, field, value):
    rows, case, knowledge, plans = inputs
    plans[0][field] = value
    with pytest.raises(ValueError):
        parse_plans({'plans': plans}, rows, case, knowledge)


@pytest.mark.parametrize('mutation', ['missing', 'extra', 'duplicate', 'unknown', 'swapped_ids'])
def test_plans_require_exact_row_coverage(inputs, mutation):
    rows, case, knowledge, plans = inputs
    if mutation == 'missing':
        plans.pop()
    elif mutation == 'extra':
        plans.append(deepcopy(plans[0]))
    elif mutation == 'duplicate':
        plans[1] = deepcopy(plans[0])
    elif mutation == 'unknown':
        plans[0]['key'] = 'unrequested'
    else:
        plans[0]['mother_id'], plans[1]['mother_id'] = plans[1]['mother_id'], plans[0]['mother_id']
    with pytest.raises(ValueError):
        parse_plans({'plans': plans}, rows, case, knowledge)


@pytest.mark.parametrize('location', ['root', 'plan'])
def test_planning_rejects_unknown_fields(inputs, location):
    rows, case, knowledge, plans = inputs
    response = {'plans': plans}
    (response if location == 'root' else plans[0])['ok'] = True
    with pytest.raises(ValueError, match='unknown'):
        parse_plans(response, rows, case, knowledge)


@pytest.mark.parametrize('malformed', [None, True, [], 1, {}, '', '{', 'null', '[]',
    '{"plans": null}', '{"plans": {}}', '{"plans": [null]}',
    '```json\n{"plans": []}\n```', 'Here is the result: {"plans": []}',
    '{"plans": []} trailing', '{"plans": [], "plans": []}', '{"plans": NaN}',
])
def test_malformed_plan_responses_raise_value_error(inputs, malformed):
    rows, case, knowledge, _ = inputs
    with pytest.raises(ValueError):
        parse_plans(malformed, rows, case, knowledge)


def test_duplicate_nested_json_fields_are_not_silently_overwritten(inputs):
    rows, case, knowledge, plans = inputs
    response = json.dumps({'plans': plans}).replace('"key": "appearance"',
        '"key": "unrequested", "key": "appearance"', 1)
    with pytest.raises(ValueError, match='duplicate JSON field'):
        parse_plans(response, rows, case, knowledge)


def test_absent_knowledge_does_not_allow_mother_facts_to_be_reused(inputs):
    rows, _, _, plans = inputs
    with pytest.raises(ValueError, match='fact_basis'):
        parse_plans({'plans': plans}, rows, {}, {})
    assert parse_plans({'plans': []}, [], {}, {}) == []


def test_row_scoped_knowledge_supports_batch_planning_and_individual_review(inputs, draft, peers):
    rows, case, knowledge, plans = inputs
    scoped = {row['key']: knowledge if row['key'] == 'appearance' else {} for row in rows}
    assert json.loads(plan_messages(rows, case, scoped)[1]['content'])['product_knowledge'] == scoped
    parsed = parse_plans({'plans': plans}, rows, case, scoped)
    assert parsed == plans
    assert review_messages(rows[0]['mother'], case, knowledge, draft, parsed[0], peers)


@pytest.mark.parametrize('missing', [False, True])
def test_scoped_facts_cannot_be_borrowed_from_another_row(inputs, missing):
    rows, case, knowledge, plans = inputs
    scoped = {'finance': knowledge, 'eligibility': {}}
    if not missing:
        scoped['appearance'] = {}
    with pytest.raises(ValueError, match='fact_basis'):
        parse_plans({'plans': plans}, rows, case, scoped)


def test_duplicate_input_keys_are_rejected_before_prompting_or_parsing(inputs):
    rows, case, knowledge, plans = inputs
    rows[1]['key'] = rows[0]['key']
    with pytest.raises(ValueError, match='duplicate row key'):
        plan_messages(rows, case, knowledge)
    with pytest.raises(ValueError, match='duplicate row key'):
        parse_plans({'plans': plans}, rows, case, knowledge)


def test_editorial_instruction_carries_the_individual_plan_and_free_structure(inputs):
    rows, case, knowledge, plans = inputs
    plan = parse_plans({'plans': plans}, rows, case, knowledge)[0]
    before = deepcopy(plan)
    instruction = editorial_instruction(plan)
    assert instruction.endswith(json.dumps(plan, ensure_ascii=False))
    assert 'Structure is free' in instruction
    assert 'never pad to the maximum' in instruction
    assert 'no\nfixed narrative styles' in instruction
    assert 'must not turn into version selection' in instruction
    assert 'Internal writing instructions' in instruction
    assert 'Never\ninvent experiences' in instruction
    assert plan == before


def test_planner_and_critic_share_source_topic_and_semantic_duplicate_boundaries(inputs, draft, peers):
    rows, case, knowledge, plans = inputs
    prompts = [plan_messages(rows, case, knowledge)[0]['content'],
               review_messages(rows[0]['mother'], case, knowledge, draft, plans[0], peers)[0]['content']]
    for prompt in prompts:
        assert 'meaningful subpoint actually present' in prompt
        assert 'appearance/color/interior/space' in prompt
        assert '403-versus-505' in prompt
        assert 'same reader\nproblem + core reasoning/evidence combination + conclusion' in prompt
        assert 'Shared vehicle, policy, price, broad topic, legal facts or CTA alone are NOT' in prompt
        assert 'Meaningfully different subtopics are allowed' in prompt
        assert 'optional-versus-standard' in prompt
        assert 'mutually exclusive conditions' in prompt
        assert 'Missing facts may become concrete observation questions' in prompt
        assert 'publication_constraints' in prompt
    assert 'independent, skeptical editorial critic' in prompts[1]
    assert 'not a rubber stamp' in prompts[1]


def test_review_preserves_every_peer_and_full_1000_character_body(inputs, draft, peers):
    rows, case, knowledge, plans = inputs
    peers[0]['content'] = 'x' * 970 + 'The decisive final conclusion.'
    peers[0]['content'] = peers[0]['content'].ljust(1000, '!')
    peers.extend({**deepcopy(peers[0]), 'key': f'accepted-{number}'} for number in range(8))
    draft['validation'] = {'pass': True}
    before = deepcopy((inputs, draft, peers))
    messages = review_messages(rows[0]['mother'], case, knowledge, draft, plans[0], peers)
    payload = json.loads(messages[1]['content'])
    assert [message['role'] for message in messages] == ['system', 'user']
    assert payload['peers'] == peers
    assert payload['mother'] == rows[0]['mother']
    assert payload['case'] == case
    assert payload['product_knowledge'] == knowledge
    assert payload['editorial_plan'] == plans[0]
    assert payload['draft'] == {key: draft[key] for key in ('title', 'content')}
    assert 'self-reported verdicts' in messages[0]['content']
    assert (inputs, draft, peers) == before


def test_review_refuses_to_silently_truncate_peer_conclusions(inputs, draft, peers):
    rows, case, knowledge, plans = inputs
    peers[0]['content'] = 'x' * 1001
    with pytest.raises(ValueError, match='1000-character'):
        review_messages(rows[0]['mother'], case, knowledge, draft, plans[0], peers)


def test_review_revalidates_plan_grounding_before_prompting(inputs, draft, peers):
    rows, case, knowledge, plans = inputs
    plans[0]['fact_basis'][0]['quote'] = 'Made-up factual authority.'
    with pytest.raises(ValueError, match='fact_basis'):
        review_messages(rows[0]['mother'], case, knowledge, draft, plans[0], peers)


def test_passing_review_has_boolean_ok_and_no_rewrite_feedback(draft, peers):
    response = passing_review()
    assert parse_review(response, draft, peers) == {**response, 'ok': True, 'feedback': ''}
    assert parse_review(json.dumps(response), draft, peers)['ok'] is True
    assert parse_review(response, draft, [])['ok'] is True


@pytest.mark.parametrize('kind', ['topic', 'fact', 'leak', 'duplicate', 'voice'])
def test_each_supported_failure_produces_targeted_feedback(kind, draft, peers):
    response = failed_review(kind, draft, peers)
    before = deepcopy((response, draft, peers))
    result = parse_review(response, draft, peers)
    assert result['ok'] is False
    assert f'[{kind}]' in result['feedback']
    assert response['summary'] in result['feedback']
    assert response['issues'][0]['reason'] in result['feedback']
    assert response['issues'][0]['evidence'] in result['feedback']
    if kind == 'duplicate':
        assert peers[0]['key'] in result['feedback']
    assert (response, draft, peers) == before
    result['issues'][0]['reason'] = 'changed'
    assert response == before[0]


def test_multiple_failing_dimensions_need_independent_evidence(draft, peers):
    result = passing_review()
    result.update(topic_preserved=False, facts_supported=False,
                  internal_instruction_leak=True, duplicate_of=[peers[0]['key']])
    result['issues'] = [failed_review(kind, draft, peers)['issues'][0]
                        for kind in ('topic', 'fact', 'leak', 'duplicate')]
    assert parse_review(result, draft, peers)['ok'] is False
    result['issues'].pop()
    with pytest.raises(ValueError, match='duplicate verdict'):
        parse_review(result, draft, peers)


@pytest.mark.parametrize('field', ['topic_preserved', 'facts_supported', 'internal_instruction_leak', 'voice_preserved'])
@pytest.mark.parametrize('value', [0, 1, 'true', 'false', None, [], {}])
def test_review_requires_real_booleans_not_truthiness(draft, peers, field, value):
    response = passing_review()
    response[field] = value
    with pytest.raises(ValueError, match='must be a boolean'):
        parse_review(response, draft, peers)


@pytest.mark.parametrize('kind', ['topic', 'fact', 'leak', 'duplicate', 'voice'])
def test_failed_dimension_without_issue_is_malformed_not_a_verdict(draft, peers, kind):
    response = failed_review(kind, draft, peers)
    response['issues'] = []
    with pytest.raises(ValueError, match='inconsistent'):
        parse_review(response, draft, peers)


@pytest.mark.parametrize('kind', ['topic', 'fact', 'leak', 'duplicate'])
def test_issue_cannot_be_hidden_behind_a_passing_dimension(draft, peers, kind):
    response = passing_review()
    response['issues'] = failed_review(kind, draft, peers)['issues']
    with pytest.raises(ValueError, match='inconsistent'):
        parse_review(response, draft, peers)


@pytest.mark.parametrize('duplicate_of', [
    None, 'accepted-finance', {}, ['missing'], [1], [True], [''],
    ['accepted-finance', 'accepted-finance'], ['accepted-finance', 'missing'],
])
def test_invalid_duplicate_references_are_rejected(draft, peers, duplicate_of):
    response = failed_review('duplicate', draft, peers)
    response['duplicate_of'] = duplicate_of
    with pytest.raises(ValueError):
        parse_review(response, draft, peers)


def test_duplicate_without_peers_cannot_pass(draft, peers):
    with pytest.raises(ValueError, match='duplicate_of key'):
        parse_review(failed_review('duplicate', draft, peers), draft, [])


def test_duplicate_peer_keys_fail_closed_in_both_review_apis(inputs, draft, peers):
    rows, case, knowledge, plans = inputs
    peers.append(deepcopy(peers[0]))
    with pytest.raises(ValueError, match='duplicate peer key'):
        parse_review(passing_review(), draft, peers)
    with pytest.raises(ValueError, match='duplicate peer key'):
        review_messages(rows[0]['mother'], case, knowledge, draft, plans[0], peers)


@pytest.mark.parametrize('evidence', [
    '', ' \n', None, 1, ['Exterior colors'],
    'EXTERIOR colors include blue and white.',
    'Exterior colors include blue ... white.',
    'Exterior  colors include blue and white.',
    'Finance: 24 months at 0%, subject to approval.',
    'Compare the exterior colors in daylight.',
    'Inspect exterior colors\nExterior colors include blue and white.',
])
def test_review_evidence_must_be_exactly_in_actual_draft(draft, peers, evidence):
    response = failed_review('fact', draft, peers)
    response['issues'][0]['evidence'] = evidence
    with pytest.raises(ValueError):
        parse_review(response, draft, peers)


def test_review_accepts_title_evidence_and_plain_text_drafts(inputs, draft, peers):
    rows, case, knowledge, plans = inputs
    response = failed_review('topic', draft, peers)
    response['issues'][0]['evidence'] = draft['title']
    assert parse_review(response, draft, peers)['ok'] is False
    response['issues'][0]['evidence'] = draft['content']
    assert parse_review(response, draft['content'], peers)['ok'] is False
    payload = json.loads(review_messages(rows[0]['mother'], case, knowledge,
        draft['content'], plans[0], peers)[1]['content'])
    assert payload['draft'] == draft['content']


@pytest.mark.parametrize('field', [
    'topic_preserved', 'facts_supported', 'internal_instruction_leak',
    'duplicate_of', 'issues', 'summary', 'voice_preserved',
])
def test_every_review_field_is_required(draft, peers, field):
    response = passing_review()
    del response[field]
    with pytest.raises(ValueError):
        parse_review(response, draft, peers)


@pytest.mark.parametrize('field,value', [
    ('issues', None), ('issues', {}), ('issues', [None]), ('issues', [{}]),
    ('summary', ''), ('summary', ' \n'), ('summary', False), ('summary', 1),
    ('ok', True), ('feedback', 'pass'), ('pass', True),
])
def test_review_schema_cannot_smuggle_pass_flags_or_empty_assessments(draft, peers, field, value):
    response = passing_review()
    response[field] = value
    with pytest.raises(ValueError):
        parse_review(response, draft, peers)


@pytest.mark.parametrize('field,value', [
    ('kind', 'style'), ('kind', 'topic|fact|leak|duplicate'), ('kind', None), ('kind', []),
    ('reason', ''), ('reason', '\n'), ('reason', False), ('reason', {}),
    ('peer_key', 'accepted-finance'),
])
def test_review_issue_schema_is_strict(draft, peers, field, value):
    response = failed_review('fact', draft, peers)
    response['issues'][0][field] = value
    with pytest.raises(ValueError):
        parse_review(response, draft, peers)


@pytest.mark.parametrize('field', ['kind', 'evidence', 'reason'])
def test_review_issue_fields_are_mandatory(draft, peers, field):
    response = failed_review('fact', draft, peers)
    del response['issues'][0][field]
    with pytest.raises(ValueError):
        parse_review(response, draft, peers)


@pytest.mark.parametrize('response', [None, True, [], 1, '', '{', 'null', '[]',
    '```json\n{}\n```', 'result: {}', '{} trailing', '{"issues": Infinity}',
])
def test_malformed_review_json_is_not_silently_salvaged(draft, peers, response):
    with pytest.raises(ValueError):
        parse_review(response, draft, peers)


def test_repeated_review_boolean_cannot_override_an_earlier_failure(draft, peers):
    response = json.dumps(passing_review()).replace('"topic_preserved": true',
        '"topic_preserved": false, "topic_preserved": true')
    with pytest.raises(ValueError, match='duplicate JSON field'):
        parse_review(response, draft, peers)


def test_public_functions_do_not_access_files_environment_or_network(inputs, draft, peers, monkeypatch):
    import builtins
    import os
    import urllib.request

    def forbidden(*args, **kwargs):
        raise AssertionError('Editorial helpers must remain pure and offline')

    rows, case, knowledge, plans = inputs
    with monkeypatch.context() as patch:
        patch.setattr(builtins, 'open', forbidden)
        patch.setattr(os, 'getenv', forbidden)
        patch.setattr(urllib.request, 'urlopen', forbidden)
        plan_messages(rows, case, knowledge)
        parsed = parse_plans({'plans': plans}, rows, case, knowledge)
        editorial_instruction(parsed[0])
        review_messages(rows[0]['mother'], case, knowledge, draft, parsed[0], peers)
        assert parse_review(passing_review(), draft, peers)['ok'] is True


def test_voice_is_reviewed_from_source_without_style_quotas(inputs, draft, peers):
    rows, case, knowledge, plans = inputs
    planning = plan_messages(rows, case, knowledge)[0]['content']
    writing = editorial_instruction(plans[0])
    review = review_messages(rows[0]['mother'], case, knowledge, draft, plans[0], peers)[0]['content']
    for instruction in (planning, writing, review):
        assert '情绪起点' in instruction
        assert '不设数量要求' in instruction
        assert '不要编造看过实车' in instruction
        assert '现有字数预算' in instruction
    assert '报价表不要因表格数据生硬而拒绝' in review
    assert '只写“缺少网感”' in review


def test_voice_does_not_reduce_emotion_to_product_summary(inputs, draft, peers):
    rows, case, knowledge, plans = inputs
    planning = plan_messages(rows, case, knowledge)[0]['content']
    writing = editorial_instruction(plans[0])
    review = review_messages(rows[0]['mother'], case, knowledge, draft, plans[0], peers)[0]['content']
    for instruction in (planning, writing, review):
        assert '不负责充当选题' in instruction
        assert '不必走完颜色、空间、配置、价格' in instruction
        assert '不追加相应的合规说明段' in instruction
    assert "not from the publishing" in planning
    assert '口语开场+不相关配置清单+万能总结' in review
    assert '实际条件与整篇念定义要区分' in review


def test_voice_cannot_override_factual_failure(draft, peers):
    result = failed_review('fact', draft, peers)
    assert result['voice_preserved']
    assert not parse_review(result, draft, peers)['ok']
    result = failed_review('voice', draft, peers)
    assert result['facts_supported']
    assert not parse_review(result, draft, peers)['ok']
    result['voice_preserved'] = True
    with pytest.raises(ValueError, match='voice verdict'):
        parse_review(result, draft, peers)
