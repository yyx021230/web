"""Offline Linux smoke load: two imported Hermes runtimes plus real-image OCR.

This is not a generation-speed benchmark. It never instantiates an agent turn
or calls the relay/image API. Run with Docker --network none and memory limits.
"""
from __future__ import annotations

import argparse
import json
import select
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, '/app/web/ops/xhs_hermes')
from worker_runtime import hermes_python
from ocr_backend import RapidOCRCPU


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('images', type=Path, nargs='+')
    args = parser.parse_args()
    children = []
    timings = []
    started = time.monotonic()
    try:
        for _ in range(2):
            child = subprocess.Popen([str(hermes_python()), '-c',
                "import sys; from run_agent import AIAgent; from hermes_cli.plugins import discover_plugins; "
                "discover_plugins(); print('ready', flush=True); sys.stdin.read()"],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            children.append(child)
            if not select.select([child.stdout], [], [], 30)[0] or child.stdout.readline().strip() != 'ready':
                raise RuntimeError('Hermes runtime import did not become ready')
        engine = RapidOCRCPU()
        for path in args.images:
            start = time.monotonic()
            lines = engine.recognize(path)
            timings.append({'path': str(path), 'seconds': round(time.monotonic() - start, 3), 'lines': len(lines)})
        if any(child.poll() is not None for child in children):
            raise RuntimeError('A resident Hermes runtime exited unexpectedly')
        cgroup = Path('/sys/fs/cgroup')
        metrics = {name: (cgroup / name).read_text().strip() for name in
                   ('memory.peak', 'memory.max', 'memory.events', 'cpu.max') if (cgroup / name).exists()}
        print(json.dumps({'offline_only': True, 'resident_hermes_imports': len(children), 'ocr': engine.metadata,
                          'timings': timings, 'elapsed_seconds': round(time.monotonic() - started, 3),
                          'cgroup': metrics}, ensure_ascii=False))
    finally:
        for child in children:
            if child.stdin:
                child.stdin.close()
            try:
                child.wait(timeout=10)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait()


if __name__ == '__main__':
    main()
