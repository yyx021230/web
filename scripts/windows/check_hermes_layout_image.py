"""Offline release-image admission checks. No model, network or database calls."""
import json
import sys
from pathlib import Path

sys.path.insert(0, '/app/web/ops/xhs_hermes')
from core import source_slot_count, safe_prompt_pool, prompt_template_type
from selection_types import catalog, image_type_pool, required_prompt_count

rows = json.loads(Path('/fixtures/hermes_image_layouts.json').read_text())
for row in rows:
    assert catalog.classify_image(row) == row['expected'], row['id']
checks = []
for number, kind in [(568, 'photo_collage'), (332, 'feature_infographic')]:
    row = next(row for row in rows if row['id'] == number)
    safe = safe_prompt_pool([{**row, 'image_url': '/existing.png'}], allow_quote_table=True)
    selected = image_type_pool(safe, kind, prompt_template_type)
    assert len(selected) == 1
    assert required_prompt_count(selected, requested=kind, total_tasks=1, case_tasks=1) == 1
    assert required_prompt_count(selected, requested=kind, total_tasks=2, case_tasks=1) == 2
    checks.append({'mother': number, 'kind': kind, 'source_slots': source_slot_count(row['chinese'])})
assert len(catalog.IMAGE_TYPES) == 9
print(json.dumps({'fixture_cases': len(rows), 'image_types': 9, 'admission': checks, 'network_calls': 0}))
