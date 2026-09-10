"""Build the approved, fingerprint-bound layout registry and import manifest.

Local data preparation only. Does not contact any service or generate images.
"""
from __future__ import annotations
import argparse
import collections
import hashlib
import importlib.util
import json
import sys
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[2]

# Reviewed multi-version content not reliably recognised by the old quote regex.
# This is a conservative ADDITION to, never an override of, the existing guard.
QUOTE_TASKS = {
    15867, 29994, 24813, 30219, 25514, 14211, 27562, 20030, 26076,
    29002, 17096, 23694, 29086, 30196, 27777, 20135, 19094, 19906,
    28553, 22215, 23182, 23194, 11580, 15392, 20930, 30135, 29993,
    27718, 26232, 30353, 25492, 23597, 23173, 14384, 11381, 15961,
    14627, 10628, 11790, 22645, 16125, 14198,
}

# 22 contact-sheet pages checked against the actual library originals. These
# overrides are about composition, not whether the old claims are accurate.
VISUAL_OVERRIDES = {
    'hero': [2, 6, 11, 12, 13, 35, 126, 127, 230, 268, 271, 502, 516, 525],
    'headline': [38, 47, 57, 58, 66, 67, 99, 107, 122, 212, 231, 236, 237, 291, 430, 490],
    'collage': [119, 120, 142, 152, 153, 255],
    'table': [102, 114, 116, 250, 378, 433, 435, 479, 481],
    'cards': [85, 330, 342, 343, 354, 357, 365, 367, 368, 371, 375, 383, 405, 426, 434, 437, 450, 452, 467, 488, 527, 550],
}
EXISTING_FAMILIES = {
    1: [3], 5: [6], 7: [8], 12: [13], 39: [44], 57: [66], 63: [65], 68: [69],
    90: [91, 95, 96, 192], 99: [107], 114: [102, 116], 119: [120], 152: [153],
    176: [177, 178], 189: [190], 319: [524, 529], 326: [352], 329: [358],
    335: [367, 416, 488], 341: [351], 342: [368, 426, 450, 467],
    346: [364], 349: [359], 357: [365, 375, 383], 380: [401], 382: [404],
    398: [403, 522, 530], 445: [460, 491], 448: [462], 451: [464],
    482: [493, 498], 489: [504], 502: [516], 511: [518],
}
# Only confident visual matches with approved historical representatives.
HISTORY_FAMILY_MATCHES = {568: 28347, 538: 18515, 344: 14627, 527: 14627}


def digest(text):
    return hashlib.sha256(text.strip().encode()).hexdigest()


def build(approved, existing):
    sources = {r['id']: r for r in approved['source_items']}
    kept = {r['id']: r for r in approved['items']}
    assert len(kept) == 108 and approved['complete'] is True
    by_hash = {}
    for decision in approved['decisions']:
        row = sources[decision['id']]
        representative = kept.get(decision.get('representative_id'))
        group = representative['group'] if representative else row['group']
        entry = {
            'group': group, 'reason': representative['reason'] if representative else decision['reason'],
            'source_task_id': row['id'], 'action': decision['action'],
            'family': f"history-task:{representative['id']}" if representative else f"history-task:{row['id']}",
            'representative_task_id': representative['id'] if representative else None,
            'preferred_image_path': urlsplit(representative['image_url']).path if representative else None,
            'visual_reviewed': True,
            'requires_quote_data': bool(row['id'] in QUOTE_TASKS or (representative and representative['id'] in QUOTE_TASKS)),
            'requirements': (representative or row).get('requirements', ''),
        }
        key = digest(row['prompt'])
        # One exact text can occur in several tasks; approved keeps take priority.
        if key not in by_hash or entry['action'] == 'keep':
            by_hash[key] = entry
    spec = importlib.util.spec_from_file_location('catalog_rules', ROOT / 'backend/app/services/hermes_reference_types.py')
    rules = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(rules)
    # Avoid accidentally using a registry from an earlier preparation run.
    rules.curated_registry = lambda: {}
    override = {number: group for group, numbers in VISUAL_OVERRIDES.items() for number in numbers}
    old_index = {r['id']: r for r in existing}
    for row in existing:
        key = digest(row['chinese'])
        if key in by_hash:
            continue
        analysis = rules.image_layout_analysis(row)
        group = override.get(row['id'], analysis['type'])
        if group is None:
            # Mixed #324 remains an explicit approved section; missing layout
            # descriptions do not get invented merely to eliminate unknowns.
            continue
        by_hash[key] = {
            'group': group, 'reason': (f'原图版式核对：{next(t["name"] for t in rules.IMAGE_TYPES if t["id"] == group)}。' if row['id'] in override else analysis['reason']),
            'source_prompt_id': row['id'], 'action': 'existing',
            'family': f'prompt:{key}', 'visual_reviewed': row['id'] != 14,
            'requires_quote_data': bool(analysis['requires_quote_data']),
        }
        if row['id'] in {2, 11, 12, 13, 35}:
            by_hash[key]['production_block_reason'] = '原提示词未确定唯一版式或缺少完整结构，仅保留原图浏览；不改写原文补造母版。'
        if row['id'] == 14:
            by_hash[key]['production_block_reason'] = '本轮原图未能读取，保留原记录，暂不用于生产。'
    for representative, variants in EXISTING_FAMILIES.items():
        target = by_hash[digest(old_index[representative]['chinese'])]
        for number in [representative] + variants:
            entry = by_hash[digest(old_index[number]['chinese'])]
            entry.update(group=target['group'], family=f'library-family:{representative}',
                         action='existing' if number == representative else 'merge',
                         preferred_library_id=representative,
                         reason=target['reason'] + ' 同版变体按原图核对合并，原记录保留。')
    source_by_url = {urlsplit(r['image_url']).path: r for r in approved['source_items']}
    decision_by_id = {r['id']: r for r in approved['decisions']}
    for row in existing:
        related = source_by_url.get(urlsplit(row['image_url'] or '').path)
        task_id = HISTORY_FAMILY_MATCHES.get(row['id'])
        if related:
            task_id = decision_by_id[related['id']].get('representative_id')
        if task_id is None or task_id not in kept:
            continue
        entry = by_hash[digest(row['chinese'])]
        representative = kept[task_id]
        entry.update(group=representative['group'], family=f'history-task:{task_id}',
                     representative_task_id=task_id, preferred_image_path=urlsplit(representative['image_url']).path,
                     requires_quote_data=bool(entry.get('requires_quote_data') or task_id in QUOTE_TASKS))
        if digest(row['chinese']) != digest(representative['prompt']):
            entry['action'] = 'merge'
    if 324 in old_index:
        section = rules.approved_image_section(old_index[324])
        if section.get('source_section_title'):
            by_hash[digest(section['chinese'])] = {
                'group': 'cards', 'reason': '已批准的方案10，与散落便签代表图为同一手账结构。',
                'source_prompt_id': 324, 'action': 'merge', 'family': 'history-task:29994',
                'representative_task_id': 29994, 'requires_quote_data': True, 'visual_reviewed': False,
            }
    manifest = []
    old = collections.defaultdict(list)
    for row in existing:
        old[digest(row['chinese'])].append(row['id'])
    for row in approved['items']:
        manifest.append({
            'source_task_id': row['id'], 'group': row['group'],
            'name': f"历史任务 #{row['id']} · {row['label']}",
            'chinese': row['prompt'], 'image_url': row['image_url'],
            'prompt_sha256': digest(row['prompt']), 'existing_prompt_ids': old[digest(row['prompt'])],
            'source_role': row.get('source_role'), 'merged_task_ids': row.get('merged_ids', []),
            'requirements': row.get('requirements', ''), 'production_ready': False,
        })
    # Static admission uses the EXACT production implementation, without calls
    # to models or image services. Unknown future entries stay "not verified".
    sys.path.insert(0, str(ROOT / 'ops/xhs_hermes'))
    import selection_types
    from core import safe_prompt_pool
    selection_types.catalog.curated_registry = lambda: by_hash
    candidates = existing + [{**r, 'id': 100000 + r['id'], 'chinese': r['prompt']} for r in approved['source_items']]
    for row in candidates:
        meta = by_hash.get(digest(row['chinese']))
        if meta is not None:
            meta['admission'] = {'with_quote': bool(safe_prompt_pool([row], allow_quote_table=True)),
                                 'without_quote': bool(safe_prompt_pool([row], allow_quote_table=False))}
    return {'version': 1, 'source': 'approved-cleaned-final-20260908', 'by_prompt_sha256': by_hash}, manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / 'artifacts/hermes-catalog-v4-20260908')
    args = parser.parse_args()
    approved_path = ROOT / 'artifacts/task-materials-20260908/cleaned/catalog.json'
    approved = json.loads(approved_path.read_text())
    existing = json.loads((args.output / 'existing.json').read_text())['images']
    registry, manifest = build(approved, existing)
    registry_path = ROOT / 'backend/app/data/hermes_image_curation.json'
    registry_path.write_text(json.dumps(registry, ensure_ascii=False, indent=2))
    out = {'version': 1, 'approved_source_sha256': hashlib.sha256(approved_path.read_bytes()).hexdigest(),
           'registry_sha256': hashlib.sha256(registry_path.read_bytes()).hexdigest(), 'items': manifest}
    (args.output / 'import-manifest.json').write_text(json.dumps(out, ensure_ascii=False, indent=2))
    fixture = {'history': [{k: r[k] for k in ('id', 'prompt', 'image_url', 'group')} for r in approved['items']],
               'variants': [{k: r[k] for k in ('id', 'prompt', 'image_url', 'group')} for r in approved['source_items'] if r['id'] in {8651, 8646, 8671, 15690, 15689, 15686}],
               'existing': [r for r in existing if r['id'] in {5, 6, 14, 152, 153, 325, 342, 368, 439, 503}]}
    (ROOT / 'backend/tests/fixtures/hermes_curated_layouts.json').write_text(json.dumps(fixture, ensure_ascii=False, indent=2))
    print(json.dumps({'kept': len(manifest), 'new': sum(not r['existing_prompt_ids'] for r in manifest),
                      'reuse': sum(bool(r['existing_prompt_ids']) for r in manifest),
                      'registry_fingerprints': len(registry['by_prompt_sha256']), 'generation_requests': 0}))


if __name__ == '__main__':
    main()
