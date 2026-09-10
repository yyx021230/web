"""Candidate-image verification of restored prices and unchanged hard guards."""
import json
from pathlib import Path
from policy_sync import parse_report
from core import validate_copy,validate_image_plan,image_ocr_errors,QUOTE_TABLE_TYPE
from policy_constraints import policy_constraint_errors
from run_daily_8x5 import image_plan_instruction
root=Path('/release/policy')
settings=json.loads((root/'policy_source.json').read_text())
cases=json.loads((root/'cases.json').read_text())
parsed,meta=parse_report((root/'source.html').read_bytes(),source_url=settings['content_url'],batch_date='2026-09-09',overrides=json.loads((root/'policy_overrides.json').read_text()))
for c in parsed.values():
    c['policy_source_url']=settings['share_url'];c['policy_content_url']=settings['content_url']
assert parsed==cases
for id,c in cases.items():
    assert not c['publication_constraints']['hide_local_subsidy_amounts']
    title=c['vehicle_model'].replace(' ','')+'价格参考'
    for row in c['quote_rows']:
        price=row['provincial_trade_in_after_price']
        copy={'title':title,'content':row['configuration']+'按置换更新条件测算'+price+'。\n#'+c['vehicle_model'].replace(' ','')+'[话题]#'}
        result=validate_copy(**copy,mother=None,case=c)
        assert result['pass'],(id,row['configuration'],result)
        blocks=[c['vehicle_model'].replace(' ',''),row['configuration'],price,'按置换更新条件测算']
        plan={'adapted_prompt':'；'.join('“'+x+'”' for x in blocks),'text_blocks':blocks,
            'slot_mappings':[{'source':x,'output':x,'action':'保留或最小替换'} for x in blocks],
            'selected_prompt_original':'；'.join(blocks),'source_slot_count':4,'template_type':QUOTE_TABLE_TYPE}
        assert not validate_image_plan(plan,copy,c),(id,row['configuration'])
        assert not image_ocr_errors(blocks,copy=copy,case=c,expected_text_blocks=blocks,allow_policy_facts=True),(id,row['configuration'])
    prompt=image_plan_instruction({}, {'template_type':QUOTE_TABLE_TYPE,'chinese':'报价单'},c,'左前45度','')
    assert '不在线上展示金额' not in prompt and c['quote_rows'][0]['provincial_trade_in_after_price'] in prompt
    assert policy_constraint_errors('综合权益价值999999元',c)
    assert policy_constraint_errors('内部价参考',c)
    assert validate_copy(title=title,content='省补999999元\n#零跑[话题]#',mother=None,case=c)['hard_errors']
print(json.dumps({'offline_validation':'passed','cases':len(cases),'configurations':sum(len(c['quote_rows']) for c in cases.values()),'copy_plan_ocr_checks':174,'generation_requests':0}))
