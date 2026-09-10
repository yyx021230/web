"""Read the actual production catalog; do not instantiate or run a production task."""
import json
from pathlib import Path
from collections import Counter
from run_daily_8x5 import OnlineData, ROOT, load_dotenv
from core import safe_prompt_pool, prompt_template_type
from selection_types import catalog, image_type_pool

load_dotenv(ROOT / '.env')
online = OnlineData()
rows = online.prompts()
receipt = json.loads(Path('/tmp/catalog-import.json').read_text())
expected = {r['prompt_id'] for r in receipt['items']}
assert expected <= {r['id'] for r in rows}, 'Imported materials missing from actual Worker data source'
result = {'live_library_count': len(rows), 'approved_references_visible': len(expected), 'generation_requests': 0, 'modes': {}}
for quotes in (True, False):
    safe = safe_prompt_pool(rows, allow_quote_table=quotes)
    counts = {t['id']: len(image_type_pool(safe, t['id'], prompt_template_type)) for t in catalog.IMAGE_TYPES}
    assert len(safe) == sum(counts.values())
    families = [catalog.curated_source(r).get('family') or catalog.prompt_fingerprint(r) for r in safe]
    assert len(families) == len(set(families)), 'Duplicate family in actual production candidate pool'
    result['modes']['with_quote' if quotes else 'without_quote'] = {'total': len(safe), 'counts': counts}
assert all(result['modes']['with_quote']['counts'].values())
after = json.loads(Path('/tmp/catalog-after.json').read_text())
disagreements = []
for t in after['catalog_user_1']['types']:
    for mode, field in [('with_quote','production_reference_count'), ('without_quote','production_without_quote_count')]:
        if t[field] is not None and t[field] != result['modes'][mode]['counts'][t['id']]:
            disagreements.append({'type': t['id'], 'mode': mode, 'api': t[field], 'worker': result['modes'][mode]['counts'][t['id']]})
result['preview_production_count_differences'] = disagreements
assert not disagreements, 'UI candidate counts and actual Worker pool differ'
Path('/tmp/catalog-worker.json').write_text(json.dumps(result, ensure_ascii=False, indent=2))
print(json.dumps(result, ensure_ascii=False))
