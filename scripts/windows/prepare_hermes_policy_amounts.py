"""Prepare the explicitly approved September amount override; no generation."""
import hashlib
import json
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'ops/xhs_hermes'))
from policy_sync import parse_report,atomic_write

previous=ROOT/'artifacts/hermes-policy-20260909'
output=ROOT/'artifacts/hermes-policy-amounts-20260909'
config=ROOT/'ops/xhs_hermes/config'
settings=json.loads((config/'policy_source.json').read_text())
overrides=json.loads((config/'policy_overrides.json').read_text())
source=(previous/'source.html').read_bytes()
assert hashlib.sha256(source).hexdigest()=='b9b93a750e7a1a581e9b2ef0ce25f502ae95ed9aaefe60fba0c334dc55c4a3fb'
old=json.loads((previous/'cases.json').read_text())
cases,metadata=parse_report(source,source_url=settings['content_url'],batch_date='2026-09-09',overrides=overrides)
metadata.update(used_verified_cache=False,case_ids=sorted(cases),share_url=settings['share_url'])
for id,c in cases.items():
    c['policy_source_url']=settings['share_url']
    c['policy_content_url']=settings['content_url']
    original=metadata['source_rows_for_audit_only'][id]['source_quote_rows']
    assert not c['publication_constraints']['hide_local_subsidy_amounts']
    assert c['publication_constraints']['operator_override']==overrides['_publication']
    assert c['quote_rows']==[{**old_row,'provincial_trade_in_after_price':raw['provincial_trade_in_after_price']}
                            for old_row,raw in zip(old[id]['quote_rows'],original)]
    for key in old[id]:
        if key not in ('policy_text','publication_constraints','quote_rows'):
            assert c[key]==old[id][key],(id,key)
    for key in old[id]['publication_constraints']:
        if key not in ('rules','hide_local_subsidy_amounts'):
            assert c['publication_constraints'][key]==old[id]['publication_constraints'][key],(id,key)
assert len(cases)==11 and sum(len(c['quote_rows']) for c in cases.values())==58
assert cases['a05-current']['quote_rows'][0]['provincial_trade_in_after_price']=='¥58,788'
assert '不在线上展示金额' not in json.dumps(cases,ensure_ascii=False)
output.mkdir(parents=True,exist_ok=True)
for name,value in {'cases.json':cases,'policy_source.json':settings,'policy_overrides.json':overrides,'metadata.json':metadata}.items():
    atomic_write(output/name,json.dumps(value,ensure_ascii=False,indent=2).encode()+b'\n')
atomic_write(output/'source.html',source)
receipt={'case_count':11,'configuration_count':58,'source_sha256':hashlib.sha256(source).hexdigest(),
    'share_url':settings['share_url'],'approved_override':overrides['_publication'],'generation_requests':0,
    'files':{name:hashlib.sha256((output/name).read_bytes()).hexdigest() for name in ('cases.json','policy_source.json','policy_overrides.json','metadata.json')}}
atomic_write(output/'prepared.json',json.dumps(receipt,ensure_ascii=False,indent=2).encode()+b'\n')
print(json.dumps(receipt,ensure_ascii=False))
