"""Local, paged visual audit of ALL current library entries; no server writes."""
import html
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'ops/xhs_hermes'))
from selection_types import catalog

source = json.loads((ROOT / 'artifacts/hermes-catalog-v4-20260908/existing.json').read_text())['images']
destination = ROOT / 'artifacts/task-materials-20260908/preview/existing-v4'
destination.mkdir(parents=True, exist_ok=True)
groups = {t['id']: t['name'] for t in catalog.IMAGE_TYPES}
PAGE_SIZE = 24
for index in range(0, len(source), PAGE_SIZE):
    body = []
    for row in source[index:index+PAGE_SIZE]:
        url = row['image_url'] or ''
        if url.startswith('/uploads/'):
            url = 'http://192.168.10.107:3000' + url
        for origin in ['http://47.98.127.132:18080', 'http://backend:8000']:
            url = url.replace(origin, 'http://192.168.10.107:3000')
        analysis = catalog.image_layout_analysis(row)
        body.append(f'<article><header>#{row["id"]} · {groups.get(analysis["type"], "待核对")}</header><a href="{html.escape(url,quote=True)}" target="_blank"><img src="{html.escape(url,quote=True)}"></a><details><summary>原提示词</summary><pre>{html.escape(row["chinese"])}</pre></details></article>')
    page = index // PAGE_SIZE + 1
    nav = ''.join(f'<a href="{n}.html">{n}</a> ' for n in range(1, (len(source)+PAGE_SIZE-1)//PAGE_SIZE+1))
    document = f'''<!doctype html><meta charset="utf-8"><title>旧库全量版式核对 {page}</title>
<style>*{{box-sizing:border-box}}body{{margin:0;padding:8px;background:#f1f0ec;color:#242722;font:11px system-ui}}nav{{margin-bottom:8px}}nav a{{padding:4px}}.grid{{display:grid;grid-template-columns:repeat(6,minmax(0,1fr));gap:6px}}article{{background:white;padding:4px;border-radius:6px}}header{{font-weight:600;margin-bottom:3px}}img{{width:100%;height:130px;object-fit:contain;background:#faf9f6}}summary{{font-size:9px;color:#888}}pre{{white-space:pre-wrap;font-size:11px}}</style>
<nav>旧库 525 条 · 第 {page} 页　{nav}</nav><div class="grid">{''.join(body)}</div>'''
    (destination / f'{page}.html').write_text(document)
print(f'{len(source)} originals, {(len(source)+PAGE_SIZE-1)//PAGE_SIZE} visual pages; no changes to originals')
