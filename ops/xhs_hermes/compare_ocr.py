"""Read-only replay of saved images. Never submits generation or changes deliveries.

Apple OCR is a comparison baseline, not ground truth. Any disagreement must be
reviewed against the image before accepting a backend change.
"""
from __future__ import annotations

import argparse
import json
import resource
import time
from pathlib import Path

import core
from ocr_backend import prepare_ocr


def facts(lines):
    text = '\n'.join(row['text'] for row in lines)
    return {'amounts': sorted(core.numeric_tokens(text)),
            'configs': sorted(set(core.precise_config_mentions(text))),
            'dates': sorted(set(match.group(0) for match in core.DAY_DATE_RE.finditer(text)))}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('checkpoints', type=Path, nargs='+')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--cases', type=Path, default=Path(__file__).parent / 'config/cases.json')
    args = parser.parse_args()
    if args.output.exists():
        raise SystemExit('Refusing to overwrite an existing comparison report')
    started = time.monotonic()
    engine = prepare_ocr(args.output.parent / 'ocr-cache')
    report = {'runtime': engine.metadata, 'initialization_seconds': round(time.monotonic() - started, 3), 'images': []}
    cases = json.loads(args.cases.read_text())
    seen = set()
    for checkpoint in args.checkpoints:
        state = json.loads(checkpoint.read_text())
        for key, row in state.get('posts', {}).items():
            saved = row.get('image') or {}
            if not saved.get('local_image') or not saved.get('ocr_lines'):
                continue
            path = (checkpoint.parent / saved['local_image']).resolve()
            if path in seen or not path.is_file():
                continue
            seen.add(path)
            item = {'checkpoint': str(checkpoint), 'key': key, 'path': str(path), 'previously_passed': bool(saved.get('ok')),
                    'baseline_lines': saved['ocr_lines'], 'baseline_facts': facts(saved['ocr_lines'])}
            start = time.monotonic()
            try:
                lines = engine.recognize(path)
                item.update({'lines': lines, 'facts': facts(lines)})
                item['facts_equal'] = item['facts'] == item['baseline_facts']
                case = cases.get(row.get('case_id')) or {}
                fingerprint = state.get('policy_fingerprints', {}).get(row.get('case_id'))
                if fingerprint and fingerprint == case.get('policy_fingerprint'):
                    kwargs = dict(copy=row.get('copy') or {}, case=case,
                                  expected_text_blocks=(row.get('image_plan') or {}).get('text_blocks'),
                                  allow_policy_facts=(row.get('image_plan') or {}).get('template_type') == core.QUOTE_TABLE_TYPE)
                    baseline_audit, audit = {}, {}
                    item['baseline_validation'] = core.image_ocr_errors(
                        saved['ocr_lines'], configuration_audit=baseline_audit, **kwargs)
                    item['validation'] = core.image_ocr_errors(lines, configuration_audit=audit, **kwargs)
                    item['baseline_config_comparison'] = baseline_audit
                    item['ocr_config_comparison'] = audit
                else:
                    item['validation_skipped'] = 'Historical policy fingerprint differs; do not audit against another policy.'
            except Exception as exc:
                item['error'] = f'{type(exc).__name__}: {exc}'
            item['seconds'] = round(time.monotonic() - start, 3)
            report['images'].append(item)
            print(json.dumps({'key': key, 'seconds': item['seconds'], 'facts_equal': item.get('facts_equal'),
                              'error': item.get('error'), 'validation': item.get('validation')}, ensure_ascii=False), flush=True)
    report['total_seconds'] = round(time.monotonic() - started, 3)
    report['max_rss_platform_units'] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    report['summary'] = {'images': len(report['images']),
                         'errors': sum(bool(row.get('error')) for row in report['images']),
                         'fact_disagreements': sum(row.get('facts_equal') is False for row in report['images'])}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(json.dumps(report['summary']))
    return int(bool(report['summary']['errors']))


if __name__ == '__main__':
    raise SystemExit(main())
