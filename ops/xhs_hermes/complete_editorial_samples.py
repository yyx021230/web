#!/usr/bin/env python3
"""Complete accepted local copy samples through the real image pipeline.

Only submits image tasks. Never creates workflow, account-sync or publish jobs.
The existing checkpoint and idempotency keys preserve submitted tasks on resume.
"""
from __future__ import annotations

import argparse
from collections import Counter
from copy import deepcopy
import hashlib
import html
import json
import os
from pathlib import Path
import threading
from types import SimpleNamespace

from core import safe_prompt_pool, validate_copy
from creative_profiles import interpretive_layout_direction
from run_daily_8x5 import OnlineData, ProductionRun, ROOT, atomic_json, source_layout_contract
from worker_runtime import load_dotenv


# Fixed visual coverage for this acceptance batch, not production selection rules.
TEMPLATES = {
    ('a10-current', 49): 2197, ('b10-current', 49): 636, ('c10-current', 49): 623,
    ('a10-current', 75): 662, ('b10-current', 75): 606, ('c10-current', 75): 667,
    ('a10-current', 1158): 674, ('b10-current', 1158): 619, ('c10-current', 1158): 625,
}


def render_samples(run: ProductionRun) -> None:
    delivery = run.delivery_manifest()
    atomic_json(run.run_dir / 'sample-results.json', delivery)
    cards = []
    escape = lambda value: html.escape(str(value or ''))
    for row in run.state['posts'].values():
        copy, plan, image = (row.get(stage) or {} for stage in ('copy', 'image_plan', 'image'))
        complete = all(result.get('ok') for result in (copy, plan, image))
        image_path = image.get('local_image')
        media = (f'<a href="{escape(image_path)}" target="_blank"><img src="{escape(image_path)}" alt="{escape(copy.get("title"))}" loading="lazy"></a>'
                 if image_path else '<div class="placeholder">配图尚未通过完整校验</div>')
        template_image = plan.get('selected_prompt_image') or row['prompt_template'].get('image_url')
        notes = f'<p class="note">文案复核：{escape(row.get("quality_note"))}</p>' if row.get('quality_note') else ''
        if row.get('visual_revision'):
            notes += f'<p class="note">配图修订：{escape(row["visual_revision"]["instruction"])}</p>'
        errors = '' if complete else escape(json.dumps({stage:row.get(stage) for stage in ('image_plan','image')},ensure_ascii=False,indent=2))
        cards.append(f'''<article><header><span>{escape(run.cases[row['case_id']]['vehicle_model'])} · 母文 #{row['mother']['id']} / 母图 #{plan.get('selected_prompt_id') or row['prompt_template']['id']}</span><b>{'图文自动校验通过，待审核' if complete else escape(row.get('status') or '待处理')}</b></header>
<div class="pair"><section>{media}</section><section><h2>{escape(copy.get('title'))}</h2><pre>{escape(copy.get('content'))}</pre>{notes}
<p class="meta">文字：沿用上一轮已生成新稿<br>图像：本轮新生成 · {escape(image.get('task_id'))}<br>图片规划 {escape(plan.get('stage_elapsed_seconds'))} 秒 / 生图及OCR {escape(image.get('stage_elapsed_seconds'))} 秒</p></section></div>
<details><summary>查看参考母图、车型原图和检查记录</summary><div class="references"><img src="{escape(template_image)}" alt="内部提示词母图"><img src="{escape((plan.get('vehicle_image') or {}).get('url'))}" alt="车型图库参考图"></div>
<pre>{escape(json.dumps({'layout':row.get('creative_direction'), 'image_text':plan.get('text_blocks'), 'ocr':image.get('ocr_lines'), 'ocr_errors':image.get('ocr_hard_errors'), 'attempts':image.get('previous_failures') or image.get('failures')},ensure_ascii=False,indent=2))}</pre></details>
{'<details><summary>未完成原因</summary><pre>'+errors+'</pre></details>' if errors else ''}</article>''')
    page = f'''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>灵感改编 · 完整图文校样</title><style>
*{{box-sizing:border-box}}body{{margin:0;background:#f3f4ef;color:#23362e;font-family:"PingFang SC",sans-serif}}main{{max-width:1320px;margin:auto;padding:30px 24px}}h1{{font:38px/1.4 "Songti SC",serif}}.intro,.meta{{color:#6a786e;font-size:13px;line-height:1.8}}article{{background:#fff;border:1px solid #e1e7df;border-radius:18px;padding:22px;margin:24px 0}}header{{display:flex;justify-content:space-between;gap:16px;margin-bottom:20px;font-size:12px;color:#66776d}}header b{{color:#297759}}.pair{{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:30px}}section{{min-width:0}}h2{{font-size:23px;margin:6px 0 20px}}img{{display:block;width:100%;height:auto;border-radius:12px}}pre{{white-space:pre-wrap;overflow-wrap:anywhere;font:15px/1.95 "PingFang SC",sans-serif}}.note{{font-size:13px;background:#fff5df;padding:14px;border-radius:8px;line-height:1.8}}.meta{{border-top:1px solid #e6ebe5;padding-top:16px}}details{{border-top:1px solid #e6ebe5;margin-top:18px;padding-top:14px;font-size:13px}}summary{{cursor:pointer}}.references{{display:grid;grid-template-columns:1fr 1fr;gap:20px;margin-top:16px}}.references img{{max-height:500px;object-fit:contain}}.placeholder{{min-height:380px;display:grid;place-items:center;background:#f5f6f2;color:#899287;border-radius:12px}}@media(max-width:760px){{main{{padding:16px}}article{{padding:16px}}.pair{{grid-template-columns:1fr}}header{{flex-wrap:wrap}}}}
</style></head><body><main><h1>灵感改编 · 图文一起看</h1><p class="intro">A10 / B10 / C10 · 完整通过 {delivery['completed']} / {delivery['expected']} 篇<br>本地校样，不发布。沿用上一轮9篇新稿，本轮完成图片规划、车型参考图生图与OCR检查。点击成图可查看原图。<br>全部母图来自内部库，汽车参考图来自车型库。政策使用项目快照；自动校验通过不等于完成内容、视觉或真实市场信息审核。</p>{''.join(cards)}</main></body></html>'''
    (run.run_dir / 'comparison.html').write_text(page, encoding='utf-8')


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--env', type=Path, required=True)
    parser.add_argument('--copy-run', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--prepare-only', action='store_true')
    parser.add_argument('--revise-image', help='Accepted sample key to replan and regenerate once')
    parser.add_argument('--revision-instruction', default='')
    args = parser.parse_args()
    if bool(args.revise_image) != bool(args.revision_instruction):
        parser.error('--revise-image and --revision-instruction must be supplied together')
    load_dotenv(args.env)
    run = ProductionRun.__new__(ProductionRun)
    run.run_dir = args.output.resolve()
    run.run_dir.mkdir(parents=True, exist_ok=True)
    run.checkpoint_path = run.run_dir / 'checkpoint.json'
    run.lock = threading.RLock()
    run.online = OnlineData()
    run.policy_metadata = {'source':'project snapshot; local acceptance only'}
    run.config = json.loads((ROOT/'config/daily_8x5.json').read_text())
    run.config.update(adaptation_level='interpretive', text_workers=3, image_plan_workers=3, image_workers=3)
    snapshot_path = run.run_dir/'cases.snapshot.json'
    if not snapshot_path.exists():
        atomic_json(snapshot_path, json.loads((ROOT/'config/cases.json').read_text()))
    run.cases = json.loads(snapshot_path.read_text())
    os.environ['XHS_CASES_PATH'] = str(snapshot_path)
    os.environ['XHS_VEHICLE_KNOWLEDGE_PATH'] = str(ROOT/'config/vehicle_knowledge.json')
    fingerprint = {name:hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in (
        'run_daily_8x5.py','core.py','creative_profiles.py','copy_editorial.py','copy_length.py',
        'copy_voice.py','vehicle_knowledge.py','policy_constraints.py','selection_types.py')}
    fingerprint['copy_checkpoint'] = hashlib.sha256((args.copy_run/'checkpoint.json').read_bytes()).hexdigest()
    fingerprint_path = run.run_dir/'implementation.json'
    if fingerprint_path.exists() and json.loads(fingerprint_path.read_text()) != fingerprint:
        raise RuntimeError('Implementation or source copy changed; use another output directory.')
    atomic_json(fingerprint_path, fingerprint)
    catalog = json.loads((run.run_dir/'catalog.snapshot.json').read_text())
    if catalog['backend'] != run.online.backend:
        raise RuntimeError('Backend changed; refusing to resume image tasks on another server.')
    run._prompt_catalog = [p for p in catalog['prompts'] if p.get('source_kind')=='internal']
    safe = safe_prompt_pool(run._prompt_catalog, allow_quote_table=True)
    pool = {int(p['id']):p for p in safe}
    if run.checkpoint_path.exists():
        run.state = json.loads(run.checkpoint_path.read_text())
    else:
        source = json.loads((args.copy_run/'checkpoint.json').read_text())
        notes_path = args.copy_run/'review_notes.json'
        notes = json.loads(notes_path.read_text()) if notes_path.exists() else {}
        run.state = {'batch_date':source['batch_date'],'car_images':catalog['car_images'],'posts':{}}
        used, layout_counts = set(TEMPLATES.values()), Counter()
        for original in source['posts'].values():
            row = deepcopy(original)
            result = validate_copy(title=row['copy']['title'],content=row['copy']['content'],mother=row['mother'],case=run.cases[row['case_id']],adaptation_level='interpretive')
            if not row['copy'].get('ok') or not result['pass']:
                raise RuntimeError('Source copy is not accepted: '+row['key'])
            pair = (row['case_id'],int(row['mother']['id']))
            template = deepcopy(pool[TEMPLATES[pair]])
            source_type = source_layout_contract(template)['id']
            reserves = [p for p in safe if p['id'] not in used and source_layout_contract(p)['id']==source_type]
            reserve = deepcopy(reserves[0]) if reserves else None
            if reserve:
                used.add(reserve['id'])
            row.update(key=f"pair-{row['case_id']}-m{row['mother']['id']}",prompt_template=template,reserve_prompt_template=reserve,
                       account_id=901+('a10-current','b10-current','c10-current').index(row['case_id']),
                       account_name=run.cases[row['case_id']]['vehicle_model']+' 本地校样',
                       status='copy_ready',quality_note=notes.get(original['key'],''))
            layout = interpretive_layout_direction(row['key'],template['id'],source_layout_type=source_type,usage_counts=layout_counts)
            layout_counts[layout['id']] += 1
            row['creative_direction'] = {'layout':layout,'source_layout_type':source_type}
            run.state['posts'][row['key']] = row
        run.save()
    run.args = SimpleNamespace(batch_date=run.state['batch_date'])
    run.tasks = list(run.state['posts'].values())
    if args.revise_image:
        row = run.state['posts'][args.revise_image]
        revision = row.get('visual_revision')
        if revision and revision['instruction'] != args.revision_instruction:
            raise RuntimeError('Revision instruction changed; refusing to reuse its image task ID.')
        if not revision:
            if not row.get('image', {}).get('ok'):
                raise RuntimeError('Finish the original image task before requesting visual revision.')
            template_id = int(row['image_plan']['selected_prompt_id'])
            template = next(p for p in run._prompt_catalog if int(p['id']) == template_id)
            archive = run.run_dir/'revisions'/f'{row["key"]}-original.json'
            atomic_json(archive, deepcopy(row))
            revision = {'instruction':args.revision_instruction,
                        'archive':str(archive.relative_to(run.run_dir)),
                        'attempt':int(row['image']['attempt']) + 1}
            row['visual_revision'] = revision
            row['image_plan'] = {'ok':False,'retry_template':template}
            row['image'] = {'attempt':revision['attempt']}
            row['status'] = 'visual_revision_pending'
            run.save()
        run.config['operator_instruction'] = args.revision_instruction
        run.config['image_plan_extra_templates'] = 0
        run.config['image_attempts'] = revision['attempt']
    for row in run.tasks:
        request_stub = f"hermes-{run.args.batch_date}-{row['key']}-a{run.config['image_attempts']}-{'0' * 12}"
        if len(request_stub) > 64:
            raise RuntimeError('Image request ID exceeds the API limit: '+row['key'])
    render_samples(run)
    if args.prepare_only:
        print(json.dumps({'prepared':len(run.tasks),'image_submissions':0},ensure_ascii=False),flush=True)
        return 0
    error = None
    try:
        run.production_pipeline()
    except Exception as exc:
        error = str(exc)
        run.state['last_error'] = error
        run.save()
    finally:
        render_samples(run)
    print(json.dumps({'completed':run.delivery_manifest()['completed'],'expected':len(run.tasks),'error':error},ensure_ascii=False),flush=True)
    return 1 if error else 0


if __name__ == '__main__':
    raise SystemExit(main())
