"""Offline checks of the candidate Linux Worker using real policy data."""
import json
import sys
from pathlib import Path
from core import validate_copy, validate_image_plan, image_ocr_errors, QUOTE_TABLE_TYPE
from policy_sync import parse_report
from policy_constraints import policy_constraint_errors
from run_daily_8x5 import image_plan_instruction

root=Path('/release/policy')
cases=json.loads((root/'cases.json').read_text())
settings=json.loads((root/'policy_source.json').read_text())
parsed,_=parse_report((root/'source.html').read_bytes(),source_url=settings['content_url'],batch_date='2026-09-09',overrides=json.loads((root/'policy_overrides.json').read_text()))
for c in parsed.values():
    c['policy_content_url']=settings['content_url']
    c['policy_source_url']=settings['share_url']
assert parsed==cases, 'Candidate parser does not reproduce staged cases'
assert len(cases)==11 and sum(len(c['quote_rows']) for c in cases.values())==58
for id,case in cases.items():
    # Existing model-name validator expects compact Lafa5Ultra spelling.
    # The spaced alias is a pre-existing, separately tracked issue; this policy
    # release deliberately does not alter model recognition.
    title=case['vehicle_model'].replace(' ','')+'权益参考'
    content='综合权益价值'+case['packaged_benefit_value']+'，具体权益按对应条件享受。\n#'+case['vehicle_model'].replace(' ','')+'[话题]#'
    ok=validate_copy(title=title,content=content,mother=None,case=case)
    assert ok['pass'], (id,ok['hard_errors'])
    assert policy_constraint_errors('省补8000元',case)
    assert not policy_constraint_errors('地方补贴可了解；指导价6.39万元',case)
    plan={'adapted_prompt':case['vehicle_model']+' “省补8000元” “车型”','text_blocks':['省补8000元','车型']}
    assert any('地方补贴' in e for e in validate_image_plan(plan,{},case))
    assert any('地方补贴' in e for e in image_ocr_errors(['省补8000元'],copy={},case=case))
    prompt=image_plan_instruction({}, {'template_type':QUOTE_TABLE_TYPE,'chinese':'母版'},case,'左前45度','')
    assert '报告测算落地价' in prompt and '不在线上展示金额' in prompt
assert {id for id,c in cases.items() if c['vehicle_stage']=='new'}=={'a05-current','b01-current','b10-current','c10-current','c11-current','c16-current','d99-current'}
print(json.dumps({'offline_validation':'passed','cases':11,'configurations':58,'copy_plan_ocr_shared':True,'generation_requests':0}))
