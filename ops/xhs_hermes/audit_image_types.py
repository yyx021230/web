"""Read-only prompt-library classification audit. Never submits generation jobs."""
from __future__ import annotations

import argparse
import collections
import datetime as dt
import html
import importlib.util
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('image_taxonomy_audit', ROOT / 'backend/app/services/hermes_reference_types.py')
taxonomy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(taxonomy)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--refresh', action='store_true', help='Read the existing approved online prompt library only')
    parser.add_argument('--input', type=Path, default=ROOT / 'backend/reference_previews/online.json')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.refresh:
        from dotenv import dotenv_values
        from run_daily_8x5 import OnlineData
        for key, value in dotenv_values(ROOT / 'ops/xhs_hermes/.env').items():
            if key.startswith('XHS_BACKEND_') and value is not None:
                os.environ[key] = value
        # Existing service authorized by the user. Do not use a different configured destination.
        destination = 'http://47.98.127.132:18080/api/backend'
        if os.environ.get('XHS_BACKEND_BASE_URL', destination).rstrip('/') != destination:
            raise SystemExit('Configured credential destination differs from the approved library; stopped')
        os.environ['XHS_BACKEND_BASE_URL'] = destination
        online = OnlineData()
        rows = online.prompts()
        data = {'synced_at': dt.datetime.now(dt.timezone.utc).isoformat(), 'images': rows}
    else:
        data = json.loads(args.input.read_text())
        rows = data['images'] if isinstance(data, dict) else data
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / 'prompts.json').write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')
    grouped = collections.defaultdict(list)
    source_views = list(rows)
    for row in rows:
        section = taxonomy.approved_image_section(row)
        if section is not row:
            source_views.append(section)
    decisions = []
    for row in source_views:
        analysis = taxonomy.image_layout_analysis(row)
        key = str(row['id']) + (':section10' if row.get('source_section_title') else '')
        grouped[analysis['type']].append(key)
        decisions.append({'source': key, **analysis})
    from core import safe_prompt_pool, prompt_template_type
    from selection_types import image_type_pool, required_prompt_count
    eligible = safe_prompt_pool(rows, allow_quote_table=True)
    worker_counts = {t['id']: len(image_type_pool(eligible, t['id'], prompt_template_type)) for t in taxonomy.IMAGE_TYPES}
    single_ready = {t['id']: len(pool) >= required_prompt_count(pool, requested=t['id'], total_tasks=1, case_tasks=1)
                    for t in taxonomy.IMAGE_TYPES
                    for pool in [image_type_pool(eligible, t['id'], prompt_template_type)]}
    report = {'taxonomy': taxonomy.TAXONOMY_VERSION, 'read_at': data.get('synced_at'), 'total': len(rows),
              'groups': dict(grouped), 'counts': {key: len(ids) for key, ids in grouped.items()},
              'decisions': decisions, 'existing_worker_filter_counts': worker_counts,
              'precise_single_catalog_ready': single_ready,
              'eligibility_note': 'Read-only offline admission check; not end-to-end generation. A precise single may retry its sole matching mother within existing attempt limits; batches retain reserves.',
              'generation_requests': 0}
    (args.output / 'classification.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    picks = [576,574,573,569,568,561,554,542,540,535,523,519,513,477,469,441,438,403,379,356,353,335,331,325,324,186,137,118]
    index = {row['id']: row for row in rows}
    names = {item['id']: item['name'] for item in taxonomy.IMAGE_TYPES}
    cards = []
    for number in picks:
        row = index.get(number)
        if not row:
            continue
        url = row.get('image_url') or ''
        if url.startswith('/uploads/'):
            url = 'http://47.98.127.132:18080' + url
        if url.startswith('http://backend:8000/uploads/'):
            url = url.replace('http://backend:8000/', 'http://47.98.127.132:18080/', 1)
        text = row.get('chinese') or row.get('chinese_example') or ''
        label = names.get(taxonomy.classify_image(row), '未分类')
        cards.append(f'<article><header>#{number} · {html.escape(label)}</header><a href="{html.escape(url, quote=True)}" target="_blank"><img src="{html.escape(url, quote=True)}" alt="提示词 {number}" loading="eager"></a><details><summary>提示词原文</summary><pre>{html.escape(text)}</pre></details></article>')
    document = '''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>图片类型实图核对</title>
<style>*{box-sizing:border-box}body{margin:0;padding:24px;background:#f3f1ed;color:#292823;font:14px system-ui}h1{font-size:22px;margin:0 0 6px}p{color:#716d63;margin:0 0 22px}.grid{display:grid;grid-template-columns:repeat(6,minmax(0,1fr));gap:12px}article{background:white;border:1px solid #e3dfd6;border-radius:10px;padding:10px}header{font-size:12px;font-weight:700;margin-bottom:8px}img{width:100%;height:235px;object-fit:contain;background:#faf9f6}summary{font-size:11px;cursor:pointer;margin-top:8px;color:#706b61}pre{font:12px/1.6 system-ui;white-space:pre-wrap}details[open]{grid-column:span 3}@media(max-width:900px){.grid{grid-template-columns:repeat(4,minmax(0,1fr))}img{height:200px}}</style>
<h1>图片类型 · 原图核对</h1><p>真实提示词库示例；仅用于核对分类，没有新生图。卡片标注当前规则分类，展开可读原文。</p><div class="grid">''' + ''.join(cards) + '</div></html>'
    (args.output / '原图分类核对.html').write_text(document, encoding='utf-8')
    print(json.dumps({key: value for key, value in report.items() if key not in {'groups', 'decisions'}}, ensure_ascii=False))


if __name__ == '__main__':
    main()
