"""Offline image verification; no credentials, network or production calls."""
import hashlib
import json
from pathlib import Path
from core import safe_prompt_pool, prompt_template_type, MAX_STANDARD_TEXT_SLOTS, MAX_QUOTE_TEXT_SLOTS
from selection_types import catalog, image_type_pool

fixture = json.loads(Path('/tmp/hermes_curated_layouts.json').read_text())
manifest = json.loads(Path('/tmp/import-manifest.json').read_text())
rows = [{**r, 'id': 100000 + r['id'], 'chinese': r['prompt']} for r in fixture['history']]
assert len(rows) == 108
for row in rows:
    assert catalog.classify_image(row) == row['group']
    assert image_type_pool([row], row['group'], prompt_template_type) == [row]
    for allow_quote in (True, False):
        assert catalog.curated_source(row)['admission']['with_quote' if allow_quote else 'without_quote'] == bool(safe_prompt_pool([row], allow_quote_table=allow_quote))
assert MAX_STANDARD_TEXT_SLOTS == 9 and MAX_QUOTE_TEXT_SLOTS == 30
registry = Path('/app/web/backend/app/data/hermes_image_curation.json')
assert hashlib.sha256(registry.read_bytes()).hexdigest() == manifest['registry_sha256']
accepted = safe_prompt_pool(rows, allow_quote_table=True)
counts = {t['id']: len(image_type_pool(accepted, t['id'], prompt_template_type)) for t in catalog.IMAGE_TYPES}
assert len(counts) == 8 and all(counts.values())
print(json.dumps({'approved_sources': len(rows), 'eligible_by_type_with_complete_quotes': counts, 'registry_matches': True, 'network': False, 'generation_requests': 0}))
