"""Container lifecycle only: seed data, offline preflight, then the existing worker."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

from worker_runtime import hermes_python, hermes_repo

ROOT = Path(__file__).resolve().parent
HEALTH = ROOT / 'state' / 'container-health.json'


def seed_missing(seed_root: Path, destination: Path) -> None:
    # User-updated policy/checkpoints always win over release seeds.
    for source in seed_root.rglob('*'):
        if not source.is_file():
            continue
        target = destination / source.relative_to(seed_root)
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists():
            with target.open('xb') as stream:
                stream.write(source.read_bytes())


def refresh_managed_home(seed_root: Path, destination: Path) -> None:
    # These are release-owned prompts/plugin code, not learned memories or data.
    # Persisting a home volume must not pin an old plugin forever after upgrade.
    for relative in ('config.yaml', 'SOUL.md', 'plugins/xhs-copy-tools/plugin.yaml',
                     'plugins/xhs-copy-tools/__init__.py', 'plugins/xhs-copy-tools/skills/xhs-copy/SKILL.md'):
        source, target = seed_root / relative, destination / relative
        if source.is_file():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)


def offline_preflight() -> dict:
    for path in [ROOT / 'config/cases.json', ROOT / 'config/vehicle_knowledge.json',
                 ROOT / 'hermes_home/config.yaml', ROOT / 'hermes_home/plugins/xhs-copy-tools/plugin.yaml',
                 ROOT / 'hermes_home/plugins/xhs-copy-tools/__init__.py',
                 ROOT / 'hermes_home/plugins/xhs-copy-tools/skills/xhs-copy/SKILL.md',
                 hermes_repo() / 'run_agent.py', hermes_python()]:
        if not path.is_file():
            raise RuntimeError(f'Missing worker file: {path}')
    env = dict(os.environ, PYTHONPATH=str(hermes_repo()))
    probe = ('from run_agent import AIAgent; '
             'from hermes_cli.plugins import discover_plugins; '
             'from tools.registry import registry; discover_plugins(); '
             "assert set(registry.get_tool_names_for_toolset('xhs_copy')) == "
             "{'xhs_get_copy_case','xhs_sanitize_copy','xhs_validate_copy'}, 'XHS plugin tools missing'")
    subprocess.run([str(hermes_python()), '-c', probe],
                   check=True, timeout=60, capture_output=True, env=env)
    from ocr_backend import prepare_ocr
    engine = prepare_ocr(ROOT / 'state/ocr')
    return engine.metadata


def health() -> int:
    try:
        value = json.loads(HEALTH.read_text())
        return int(time.time() - value['last_api_success'] > 150)
    except (OSError, ValueError, KeyError):
        return 1


def main() -> int:
    mode = sys.argv[1] if len(sys.argv) > 1 else 'worker'
    if mode == 'health':
        return health()
    if mode not in ('worker', 'preflight', 'seed'):
        raise SystemExit('Choose worker, preflight, seed or health')
    seed_missing(Path('/opt/hermes-seed'), ROOT)
    refresh_managed_home(Path('/opt/hermes-seed/hermes_home'), ROOT / 'hermes_home')
    if mode == 'seed':
        return 0
    metadata = offline_preflight()
    print(json.dumps({'preflight': 'ok', 'ocr': metadata}), flush=True)
    if mode == 'preflight':
        return 0
    # No schedules or generation here. Web queue claim remains the only trigger.
    os.environ['HERMES_CONTAINER_HEALTH_PATH'] = str(HEALTH)
    os.execv(sys.executable, [sys.executable, str(ROOT / 'web_worker.py')])
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
