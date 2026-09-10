"""Create an allow-listed container context, excluding secrets and local history."""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import shutil
import subprocess
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parents[1]
HERMES_COMMIT = '29112bef099274229cadff79cdff7bf7b99c4b77'
SCRIPTS = ('core.py', 'run_daily_8x5.py', 'web_worker.py', 'worker_runtime.py', 'ocr_backend.py',
           'container_entrypoint.py', 'compare_ocr.py', 'policy_sync.py', 'vehicle_knowledge.py',
           'selection_types.py', 'sync_reference_previews.py', 'ocr_image.swift')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--hermes-repo', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    if output.exists():
        raise SystemExit('Use a new directory; existing build contexts are not overwritten')
    actual = subprocess.check_output(['git', '-C', str(args.hermes_repo), 'rev-parse', 'HEAD'], text=True).strip()
    if actual != HERMES_COMMIT:
        raise SystemExit('Hermes source revision differs from the tested revision')
    output.mkdir(parents=True)
    archive = subprocess.check_output(['git', '-C', str(args.hermes_repo), 'archive', HERMES_COMMIT])
    source = output / 'hermes-agent'
    source.mkdir()
    with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
        tar.extractall(source, filter='data')
    dest = output / 'web/ops/xhs_hermes'
    dest.mkdir(parents=True)
    for name in SCRIPTS:
        shutil.copyfile(ROOT / name, dest / name)
    shutil.copytree(ROOT / 'tests', dest / 'tests', ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    common = 'backend/app/services/hermes_reference_types.py'
    (output / 'web' / common).parent.mkdir(parents=True)
    shutil.copyfile(REPO / common, output / 'web' / common)
    seed = output / 'seed'
    for directory, names in (
        ('config', ('cases.json', 'daily_8x5.json', 'policy_source.json', 'policy_overrides.json', 'vehicle_knowledge.json')),
        ('state/policy', ('metadata.json', 'source.html')),
        ('hermes_home', ('config.yaml', 'SOUL.md', 'plugins/xhs-copy-tools/plugin.yaml',
                         'plugins/xhs-copy-tools/__init__.py', 'plugins/xhs-copy-tools/skills/xhs-copy/SKILL.md')),
    ):
        for name in names:
            target = seed / directory / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / directory / name, target)
    # Bake seeds as well: offline image validation works without production volumes.
    shutil.copytree(seed, dest, dirs_exist_ok=True)
    shutil.copyfile(ROOT / 'docker/Dockerfile', output / 'Dockerfile')
    shutil.copyfile(ROOT / 'docker/.dockerignore', output / '.dockerignore')
    # This checked-in lock combines this exact Hermes uv.lock and the OCR pins.
    # Normal packaging must not resolve newer transitive packages from PyPI.
    shutil.copyfile(ROOT / 'docker/requirements-linux.lock', output / 'requirements-linux.lock')
    manifest = {'hermes_commit': HERMES_COMMIT, 'files': {
        str(path.relative_to(output)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(output.rglob('*')) if path.is_file()}}
    (output / 'build-manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2))
    print(json.dumps({'output': str(output), 'hermes_commit': HERMES_COMMIT,
                      'files': len(manifest['files']), 'secrets_included': False}))


if __name__ == '__main__':
    main()
