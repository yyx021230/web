"""Verify live Worker policy refresh in an isolated temp directory; no tasks."""
import hashlib
import json
import tempfile
from pathlib import Path
from policy_sync import sync_policy

root=Path('/app/web/ops/xhs_hermes')
config=root/'config'
paths=[config/name for name in ('cases.json','policy_source.json','policy_overrides.json')]
paths += [root/'state/policy'/name for name in ('source.html','metadata.json')]
before={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
expected=json.loads((config/'cases.json').read_text())
with tempfile.TemporaryDirectory(prefix='policy-verification-') as temporary:
    destination=Path(temporary)
    meta=sync_policy(settings_path=config/'policy_source.json',cases_path=destination/'cases.json',
                     batch_date='2026-09-09',cache_dir=destination/'cache')
    assert json.loads((destination/'cases.json').read_text())==expected
    assert not meta['used_verified_cache'], 'Live source was not verified'
    assert meta['source_fingerprint']=='b9b93a750e7a1a581e9b2ef0ce25f502ae95ed9aaefe60fba0c334dc55c4a3fb'
assert all(hashlib.sha256(Path(p).read_bytes()).hexdigest()==sha for p,sha in before.items())
result={'live_refresh_verified':True,'production_config_and_cache_unchanged':True,
        'source_sha256':meta['source_fingerprint'],'case_count':len(expected),
        'configuration_count':sum(len(c['quote_rows']) for c in expected.values()),'generation_requests':0}
Path('/tmp/policy-worker.json').write_text(json.dumps(result,indent=2))
print(json.dumps(result))
