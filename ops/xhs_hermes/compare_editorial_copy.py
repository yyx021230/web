#!/usr/bin/env python3
"""Local, real-provider copy acceptance. Never submits workflow/image/publish tasks."""
from __future__ import annotations

import argparse
import concurrent.futures
from datetime import date
import html
import hashlib
import json
import os
from pathlib import Path
import re
import threading
import time
from types import SimpleNamespace

from run_daily_8x5 import ProductionRun, ROOT, atomic_json
from copy_editorial import parse_review, review_messages
from copy_length import copy_lengths
from vehicle_knowledge import knowledge_for_case
from worker_runtime import load_dotenv


def report(run: ProductionRun) -> None:
    cards = []
    notes_path = run.run_dir / 'review_notes.json'
    review_notes = json.loads(notes_path.read_text(encoding='utf-8')) if notes_path.exists() else {}
    recheck_path = run.run_dir / 'validation-recheck.json'
    rechecks = {row['key']: row['hard_errors'] for row in json.loads(recheck_path.read_text(encoding='utf-8'))} if recheck_path.exists() else {}
    vehicles = sorted({run.cases[row['case_id']]['vehicle_model'] for row in run.state['posts'].values()})
    counts = {'total': len(run.state['posts']), 'passed': 0, 'failed': 0, 'pending': 0}
    for row in run.state['posts'].values():
        result = row.get('copy', {})
        blocked = rechecks.get(row['key'], [])
        accepted = result.get('ok') and not blocked
        status = '通过自动检查，待人工验收' if accepted else '旧版审稿通过，当前规则未通过' if blocked else '未通过' if result else '待生成'
        counts['passed' if accepted else 'failed' if result else 'pending'] += 1
        plan = result.get('editorial_plan') or next(iter(row.get('editorial_plans', {}).values()), {})
        failures = result.get('previous_failures') or result.get('failures') or []
        escape = lambda value: html.escape(str(value or ''))
        visible = result if result.get('title') else next((item for item in reversed(failures) if item.get('content')), result)
        kind = 'passed' if accepted else 'failed' if result else 'pending'
        original = ''
        note = ''
        if row['key'] in review_notes:
            note = f'<p class="quality-note"><strong>复核发现，不能只看模型通过：</strong>{escape(review_notes[row["key"]])}</p>'
        if blocked:
            note += f'<p class="quality-note"><strong>当前规则回检：</strong>{escape("；".join(blocked))}</p>'
        if row.get('original_content'):
            original = f"<details><summary>对照旧线上成稿：{escape(row.get('original_title'))}</summary><pre>{escape(row['original_content'])}</pre></details>"
        comparison = ''
        left_label = f"文案库母文 #{row['mother']['id']}"
        left_title = row['mother']['title']
        left_content = row['mother']['content']
        if row.get('previous_content') and visible.get('content'):
            before = copy_lengths(row['previous_content'])['body_chars']
            after = copy_lengths(visible.get('content') or '')['body_chars']
            comparison = f'<p class="angle">正文 {before} → {after} 字（不含空白与话题）；完整新稿如下，未折叠或截断。</p>'
            left_label = '上一版成稿'
            left_title = row.get('previous_title')
            left_content = row['previous_content']
            original += f"<details><summary>文案库母文 #{row['mother']['id']}：{escape(row['mother']['title'])}</summary><pre>{escape(row['mother']['content'])}</pre></details>"
        cards.append(f'''<article data-vehicle="{escape(run.cases[row['case_id']]['vehicle_model'])}" data-status="{kind}"><header><span>{escape(row['key'])}</span><b>{status}</b></header>
<h2>{escape(run.cases[row['case_id']]['vehicle_model'])} · 第{row['round']}轮</h2>
<p class="angle">{escape(plan.get('source_topic'))} → {escape(plan.get('target_angle'))}</p>{comparison}{note}
<div class="pair"><section><small>{escape(left_label)}</small><h3>{escape(left_title)}</h3>
<pre>{escape(left_content)}</pre></section><section><small>本地真实模型成稿 · {escape(result.get('test_elapsed_seconds'))} 秒</small>
<h3>{escape(visible.get('title'))}</h3><pre>{escape(visible.get('content') or result.get('error'))}</pre>
<p class="review">{escape(result.get('editorial_review', {}).get('summary') or ('未放行：'+str(visible.get('feedback') or result.get('error')) if result and not result.get('ok') else ''))}</p></section></div>{original}
<details><summary>依据、审稿与重试记录（{len(failures)}次未通过）</summary><pre>{escape(json.dumps({'plan':plan, 'review':result.get('editorial_review'), 'attempts':failures}, ensure_ascii=False, indent=2))}</pre></details></article>''')
    body = f'''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>灵感改编 · 多车型实测</title><style>
*{{box-sizing:border-box}}body{{margin:0;background:radial-gradient(ellipse at 0 0,#e4eee7,transparent 600px),#f4f3ef;color:#24332e;font-family:"PingFang SC",sans-serif;line-height:1.8}}
main{{max-width:1400px;margin:auto;padding:36px 24px}}h1{{font:44px/1.4 "Songti SC",serif;margin:12px 0}}h2{{font-size:21px}}h3{{font-size:18px}}
.intro{{margin-bottom:32px;color:#60726a}}article{{background:#fff;border:1px solid #e1e6df;border-radius:18px;padding:24px;margin:24px 0}}
header{{display:flex;justify-content:space-between;font-size:12px;color:#65776f}}header b{{color:#267b5c}}.pair{{display:grid;grid-template-columns:1fr 1fr;gap:28px}}
section{{min-width:0}}section+section{{border-left:1px solid #e6ebe7;padding-left:28px}}pre{{white-space:pre-wrap;overflow-wrap:anywhere;font:14px/1.95 "PingFang SC",sans-serif}}
small{{color:#7c8a83}}.angle,.review{{background:#eff5f1;padding:12px 16px;border-radius:8px;font-size:13px}}details{{border-top:1px solid #e6ebe7;padding-top:14px;margin-top:18px;color:#68766f}}
.quality-note{{background:#fff4df;border-left:3px solid #bc863e;padding:12px 16px;color:#735227;font-size:13px}}
nav{{display:flex;align-items:center;gap:14px;position:sticky;top:0;z-index:2;padding:16px;background:#f4f3eff5;border-bottom:1px solid #dce2db;backdrop-filter:blur(12px)}}select{{background:white;color:#24332e;border:1px solid #cbd6ce;border-radius:7px;padding:10px 16px;font:14px "PingFang SC",sans-serif}}label{{font-size:13px}}article[hidden]{{display:none}}article[data-status=failed] header b{{color:#995036}}article[data-status=failed] .review{{background:#fbf0e8}}summary{{cursor:pointer}}section small{{letter-spacing:.06em}}
@media(max-width:720px){{.pair{{grid-template-columns:1fr}}section+section{{border-left:0;border-top:1px solid #ddd;padding:18px 0 0}}main{{padding:16px}}article{{padding:18px}}}}
</style><main><small>LOCAL ACCEPTANCE / 不写入线上、不生成图片</small><h1>灵感改编校样</h1>
<p class="intro">计划 {counts['total']} 篇 · 自动检查通过 {counts['passed']} · 未通过 {counts['failed']} · 待生成 {counts['pending']}<br>
左侧优先显示上一版成稿，没有旧稿时显示母文；右侧是本地新稿。母文可展开查看，可能含过期事实或违规用语，仅供表达方式对照。模型通过不代表已完成人工质量验收。<br>
同一车型第二轮也会对照第一轮成稿去重。金额和参数使用项目当前政策与知识库快照，不是公开购车建议。</p>
<nav><label>车型 <select id="vehicle"><option value="all">全部车型</option>{''.join(f'<option>{html.escape(v)}</option>' for v in vehicles)}</select></label>
<label>结果 <select id="status"><option value="all">全部记录</option><option value="passed">已通过，待人工确认</option><option value="failed">未放行</option><option value="pending">待生成</option></select></label><small id="visible-count"></small></nav>
{''.join(cards)}</main><script>
const vehicle=document.getElementById('vehicle'),status=document.getElementById('status');
function filter(){{let n=0;document.querySelectorAll('article').forEach(card=>{{card.hidden=!(vehicle.value==='all'||card.dataset.vehicle===vehicle.value)||!(status.value==='all'||card.dataset.status===status.value);if(!card.hidden)n++}});document.getElementById('visible-count').textContent=n+' 篇';}}
vehicle.addEventListener('change',filter);status.addEventListener('change',filter);filter();
</script></html>'''
    (run.run_dir / 'comparison.html').write_text(body, encoding='utf-8')
    atomic_json(run.run_dir / 'summary.json', counts)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--env', type=Path, help='Existing local secret env; never copied to output')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--regression', type=Path)
    parser.add_argument('--sources', type=Path)
    parser.add_argument('--combine', type=Path, nargs='+', help='Render existing checkpoints only; no model/API calls')
    parser.add_argument('--workers', type=int, default=3)
    parser.add_argument('--batch-date', default=date.today().isoformat())
    parser.add_argument('--rounds', type=int, default=2)
    parser.add_argument('--mother-ids', type=int, nargs='+', default=[49, 1155, 75, 1158])
    parser.add_argument('--key-prefix', default='', help='Keep follow-up samples distinct in a combined report')
    parser.add_argument('--previous', type=Path, help='Completed local checkpoint for before/after copy comparison')
    parser.add_argument('--audit-originals-only', action='store_true')
    parser.add_argument('--production-replay', action='store_true', help='Regenerate all ten real mothers from run 89')
    args = parser.parse_args()
    if not 1 <= args.rounds <= 10 or not 1 <= args.workers <= 8:
        parser.error('--rounds must be 1..10 and --workers must be 1..8')
    if not re.fullmatch(r'[A-Za-z0-9_-]*', args.key_prefix):
        parser.error('--key-prefix supports only ASCII letters, digits, underscore and hyphen')
    if args.combine:
        run = SimpleNamespace(run_dir=args.output.resolve(), state={'posts':{}},
                              cases=json.loads((ROOT / 'config/cases.json').read_text()))
        run.run_dir.mkdir(parents=True,exist_ok=True)
        for folder in args.combine:
            state = json.loads((folder / 'checkpoint.json').read_text())
            for key,row in state['posts'].items():
                if key in run.state['posts']:
                    raise ValueError('Duplicate result key: '+key)
                run.state['posts'][key] = row
        if args.regression:
            old = {f"original-{row['id']}":row for row in json.loads(args.regression.read_text())}
            for key,row in run.state['posts'].items():
                if key in old:
                    row.update(original_title=old[key]['title'],original_content=old[key]['content'])
        atomic_json(run.run_dir/'checkpoint.json',run.state)
        report(run)
        return
    if not args.env or not args.regression or not args.sources:
        parser.error('--env, --regression and --sources are required for a live model run')
    load_dotenv(args.env)
    if not os.environ.get('INTERNAL_RELAY_API_KEY'):
        raise RuntimeError('Missing local test-provider key')
    run = ProductionRun.__new__(ProductionRun)
    run.run_dir = args.output.resolve()
    run.run_dir.mkdir(parents=True, exist_ok=True)
    fingerprint = {path.name: hashlib.sha256(path.read_bytes()).hexdigest()
                   for path in (ROOT / name for name in ('core.py', 'creative_profiles.py', 'copy_editorial.py', 'copy_length.py', 'copy_voice.py', 'run_daily_8x5.py', 'vehicle_knowledge.py', 'hermes_home/plugins/xhs-copy-tools/__init__.py'))}
    fingerprint_path = run.run_dir / 'implementation.json'
    if fingerprint_path.exists() and json.loads(fingerprint_path.read_text()) != fingerprint:
        raise RuntimeError('Implementation changed: use a new output directory for a clean acceptance run')
    atomic_json(fingerprint_path, fingerprint)
    run.checkpoint_path = run.run_dir / 'checkpoint.json'
    run.lock = threading.RLock()
    run.config = {'adaptation_level': 'interpretive', 'copy_model': 'gpt-5.5', 'copy_attempts_per_mother': 2}
    run.cases = json.loads((ROOT / 'config/cases.json').read_text())
    run.args = SimpleNamespace(batch_date=args.batch_date)
    old = json.loads(args.regression.read_text())
    mothers = {int(row['mother_id']): {'id':int(row['mother_id']), 'title':row['mother_title'], 'content':row['mother_content']} for row in old}
    sources = json.loads(args.sources.read_text())['sources']
    mothers.update({int(item['mother']['id']): item['mother'] for item in sources})
    if missing := set(args.mother_ids) - mothers.keys():
        parser.error('Unknown mother ids: '+str(sorted(missing)))
    context = run.run_dir / 'run_context.json'
    atomic_json(context, {'mothers':list(mothers.values())})
    os.environ['XHS_ASSIGNED_MOTHERS_PATH'] = str(context)
    os.environ['XHS_CASES_PATH'] = str((ROOT / 'config/cases.json').resolve())
    os.environ['XHS_VEHICLE_KNOWLEDGE_PATH'] = str((ROOT / 'config/vehicle_knowledge.json').resolve())
    if run.checkpoint_path.exists():
        run.state = json.loads(run.checkpoint_path.read_text())
    else:
        run.state = {'batch_date':args.batch_date, 'posts':{}}
        if args.production_replay:
            for slot, original in enumerate(old, 1):
                key = f"original-{original['id']}"
                run.state['posts'][key] = {'key':key, 'case_id':'a10-current', 'round':1,
                    'account_id':900, 'account_name':'原线上母文重放', 'slot':slot,
                    'mother':mothers[int(original['mother_id'])], 'avoidance_brief':{},
                    'original_title':original['title'], 'original_content':original['content']}
        for round_number in (() if args.production_replay else range(1, args.rounds + 1)):
            for slot, mother_id in enumerate(dict.fromkeys(args.mother_ids), 1):
                for case_id in ('a10-current', 'b10-current', 'c10-current'):
                    key = f'{args.key_prefix}{case_id}-r{round_number}-m{mother_id}'
                    run.state['posts'][key] = {'key':key,'case_id':case_id,'round':round_number,
                        'account_id':900+round_number,'account_name':'仅本地测试','slot':slot,
                        'mother':mothers[mother_id], 'avoidance_brief':{}}
    if args.previous:
        previous = {
            (old['case_id'], old['round'], str(old['mother']['id'])): old.get('copy') or {}
            for old in json.loads(args.previous.read_text())['posts'].values()
        }
        for row in run.state['posts'].values():
            old_key = (row['case_id'], row['round'], str(row['mother']['id']))
            old_copy = previous.get(old_key, {})
            if old_copy.get('content'):
                row.update(previous_title=old_copy['title'], previous_content=old_copy['content'])
    if args.audit_originals_only:
        audits = []
        for original_id in (449,453):
            original = next(item for item in old if item['id'] == original_id)
            row = run.state['posts'][f"a10-current-r1-m{original['mother_id']}"]
            editorial_plan = row['editorial_plans'][str(original['mother_id'])]
            draft = {key:original[key] for key in ('title','content')}
            peers = [{'key':str(item['id']), 'title':item['title'], 'content':item['content'], 'editorial_plan':{}}
                     for item in old if item['id'] != original_id]
            case = run.cases['a10-current']
            verdict = run.editorial_request(
                review_messages(row['mother'], case, knowledge_for_case(case,row['mother']), draft, editorial_plan, peers),
                lambda raw:parse_review(raw,draft,peers), f'original-{original_id}-regression',
            )
            audits.append({'original_id':original_id, 'verdict':verdict})
            print(json.dumps({'original_id':original_id, 'ok':verdict['ok'], 'summary':verdict['summary']},ensure_ascii=False),flush=True)
        atomic_json(run.run_dir / 'original-regression.json', audits)
        return
    run.save()
    report(run)
    for round_number in range(1, args.rounds + 1):
        pending = [row for row in run.state['posts'].values() if row['round'] == round_number and 'copy' not in row]
        def job(row):
            start = time.monotonic()
            key, result = run.copy_job(row)
            result['test_elapsed_seconds'] = round(time.monotonic()-start, 1)
            return key, result
        with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
            futures = {pool.submit(job, row):row for row in pending}
            for future in concurrent.futures.as_completed(futures):
                key, result = future.result()
                with run.lock:
                    run.state['posts'][key]['copy'] = result
                    run.save()
                    report(run)
                print(json.dumps({'key':key,'ok':result.get('ok'), 'title':result.get('title'),
                    'seconds':result['test_elapsed_seconds'], 'error':result.get('error')},ensure_ascii=False),flush=True)
    report(run)


if __name__ == '__main__':
    main()
