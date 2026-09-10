"""Prepare a policy-only release from the supplied report; no generation calls."""
import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'ops/xhs_hermes'))
from policy_sync import parse_report, atomic_write
from policy_constraints import policy_constraint_errors


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--batch-date', required=True)
    args = parser.parse_args()
    config = ROOT / 'ops/xhs_hermes/config'
    settings = json.loads((config / 'policy_source.json').read_text())
    overrides = json.loads((config / 'policy_overrides.json').read_text())
    source = args.source.read_bytes()
    cases, metadata = parse_report(source, source_url=settings['content_url'], batch_date=args.batch_date, overrides=overrides)
    assert len(cases) == 11 and sum(len(c['quote_rows']) for c in cases.values()) == 58
    assert set(cases) == set(settings['required_case_ids'])
    metadata.update(used_verified_cache=False, case_ids=sorted(cases), share_url=settings['share_url'])
    for case in cases.values():
        case['policy_content_url'] = settings['content_url']
        case['policy_source_url'] = settings['share_url']
    expected_benefits = {'a05':23824,'a10':23832,'b10':34936,'b01':34216,'c10':37976,'c11':39016,'c16':39840,'d19':67966,'d99':79379,'lafa5':39456,'lafa5ultra':35416}
    old = json.loads((config / 'cases.json').read_text())
    summary = []
    for id, case in cases.items():
        assert int(case['packaged_benefit_value'].replace('¥','').replace(',','')) == expected_benefits[id.removesuffix('-current')]
        assert case['allow_multi_config_quote']
        assert case['publication_constraints']['hide_local_subsidy_amounts']
        for row in case['quote_rows']:
            assert row['provincial_trade_in_after_price'] == '不在线上展示金额'
            assert 'estimated_national_scrappage_on_road_price' in row
            assert row['configuration'] in case['policy_text']
        assert policy_constraint_errors('省补8000元', case)
        assert not policy_constraint_errors('地方补贴可了解；指导价6.39万元', case)
        assert policy_constraint_errors('综合权益价值999999元', case)
        summary.append({'case_id':id,'vehicle_model':case['vehicle_model'],'stage':case['vehicle_stage'],
                        'rows':len(case['quote_rows']),'packaged_benefit_value':case['packaged_benefit_value'],
                        'old_policy_sha256':hashlib.sha256(json.dumps(old.get(id),sort_keys=True,ensure_ascii=False).encode()).hexdigest()})
    args.output.mkdir(parents=True, exist_ok=True)
    artifacts = {'cases.json':cases,'policy_source.json':settings,'policy_overrides.json':overrides,'metadata.json':metadata}
    for name, value in artifacts.items():
        atomic_write(args.output / name, json.dumps(value,ensure_ascii=False,indent=2).encode() + b'\n')
    atomic_write(args.output / 'source.html', source)
    receipt = {'source_sha256':hashlib.sha256(source).hexdigest(),'share_url':settings['share_url'],
               'effective_period':args.batch_date[:7],'case_count':11,'configuration_count':58,
               'generation_requests':0,'summary':summary,
               'files':{name:hashlib.sha256((args.output/name).read_bytes()).hexdigest() for name in artifacts}}
    atomic_write(args.output/'prepared.json',json.dumps(receipt,ensure_ascii=False,indent=2).encode()+b'\n')
    print(json.dumps(receipt,ensure_ascii=False))


if __name__ == '__main__':
    main()
