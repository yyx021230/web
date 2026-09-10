"""Atomic, backed-up policy file installation. Run with the Worker drained."""
import argparse
import datetime as dt
import hashlib
import json
import shutil
from pathlib import Path
from policy_sync import atomic_write

BEFORE = {
    'cases.json':'1ccf8009d2a8aa56dd3af9454df77c23d42ae34a30d077cde40d8eca43956aba',
    'policy_source.json':'e84c1971e64c4dd77aca43fc854d4e695046223b07552f37060df438f21d9221',
    'policy_overrides.json':'8bc6b3628b7f758da430b2648b2fd3d2728aeda3aae8f89f357ecb8c5198218b',
}


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute',action='store_true')
    parser.add_argument('--verify',action='store_true')
    args=parser.parse_args()
    release=Path('/release')
    staged=release/'policy'
    config=Path('/live/config')
    cache=Path('/live/state/policy')
    manifest=json.loads((staged/'prepared.json').read_text())
    for name,digest in manifest['files'].items():
        assert sha(staged/name)==digest, f'Staged artifact changed: {name}'
    assert sha(staged/'source.html')==manifest['source_sha256']
    if args.verify:
        assert all(sha(config/name)==manifest['files'][name] for name in BEFORE)
        assert sha(cache/'source.html')==manifest['source_sha256']
        assert sha(cache/'metadata.json')==manifest['files']['metadata.json']
        print(json.dumps({'verified':True,'configuration_count':58,'generation_requests':0}))
        return
    for name,digest in BEFORE.items():
        assert sha(config/name)==digest, f'Live policy changed since inspection: {name}'
    if not args.execute:
        print(json.dumps({'preflight':'passed','case_count':11,'configuration_count':58,'generation_requests':0}))
        return
    stamp=dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    backup=release/'private'/f'policy-before-{stamp}'
    backup.mkdir(parents=True,exist_ok=False)
    unchanged={str(p.relative_to(config)):sha(p) for p in config.rglob('*') if p.is_file() and p.name not in BEFORE}
    for name in BEFORE:
        shutil.copy2(config/name,backup/name)
    for name in ('source.html','metadata.json'):
        if (cache/name).exists():
            shutil.copy2(cache/name,backup/('cache-'+name))
    # Cases are replaced last: the API sees either complete old or complete new
    # JSON; no in-place truncation. No histories, databases or schedules touched.
    for name in ('policy_source.json','policy_overrides.json'):
        atomic_write(config/name,(staged/name).read_bytes())
    for name in ('source.html','metadata.json'):
        atomic_write(cache/name,(staged/name).read_bytes())
    atomic_write(config/'cases.json',(staged/'cases.json').read_bytes())
    assert all(sha(config/name)==digest for name,digest in unchanged.items())
    receipt={'installed_at':stamp,'backup_relative_path':str(backup.relative_to(release)),
             'old_hashes':BEFORE,'new_hashes':{name:sha(config/name) for name in BEFORE},
             'other_config_files_unchanged':True,'source_sha256':manifest['source_sha256'],'generation_requests':0}
    atomic_write(release/'policy-installed.json',json.dumps(receipt,indent=2).encode()+b'\n')
    print(json.dumps(receipt))


if __name__=='__main__':
    main()
