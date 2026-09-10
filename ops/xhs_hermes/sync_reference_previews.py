#!/usr/bin/env python3
"""Refresh only Web type previews from the existing library; never generate."""
from __future__ import annotations
import argparse
import concurrent.futures
import datetime as dt
import json
import os
import shutil
from pathlib import Path
from urllib.parse import urlsplit
from dotenv import dotenv_values
from run_daily_8x5 import OnlineData
from core import prompt_template_type
from selection_types import approved_note_section



def make_snapshot(copies, images, public_root):
    origin = urlsplit(public_root)
    if origin.scheme not in {'http', 'https'} or not origin.hostname or origin.username or origin.password:
        raise ValueError('Invalid library origin')
    public_root = f'{origin.scheme}://{origin.netloc}'
    def image_url(raw):
        value = str(raw or '').strip()
        if value.startswith('/uploads/'):
            return public_root + value
        parsed = urlsplit(value)
        if parsed.scheme in {'https', 'http'} and parsed.hostname and not parsed.username and not parsed.password:
            return value
        return ''
    snapshot = {
        'schema_version': 1,
        'synced_at': dt.datetime.now(dt.timezone.utc).isoformat(),
        'source_origin': public_root,
        'copies': [{key: row.get(key) for key in ('id', 'title', 'content')} for row in copies],
        'images': [{**{key: row.get(key) for key in ('id', 'title', 'name', 'chinese')},
                    'is_public': row.get('is_public') is True,
                    'image_url': image_url(row.get('image_url'))} for row in images],
        'sections': [],
    }
    for row in snapshot['images']:
        section = approved_note_section(row, prompt_template_type)
        if section.get('source_section_title'):
            snapshot['sections'].append({
                'id': row['id'], 'name': section['name'], 'chinese': section['chinese'],
                'source_section_title': section['source_section_title'], 'is_public': row['is_public'],
                'image_url': '', 'preview_note': '原提示词方案10节选；库内原图未对应此方案，暂不展示原图。',
            })
    return snapshot


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--env-file', type=Path, default=Path(__file__).with_name('.env'))
    parser.add_argument('--output', type=Path, default=Path(__file__).resolve().parents[2] / 'backend/reference_previews/online.json')
    parser.add_argument('--expected-origin', required=True, help='Explicitly approved credential destination')
    args = parser.parse_args()
    for key, value in dotenv_values(args.env_file).items():
        if key.startswith('XHS_BACKEND_') and value is not None:
            os.environ[key] = value
    base = urlsplit(os.getenv('XHS_BACKEND_BASE_URL') or 'http://47.98.127.132:18080/api/backend')
    if f'{base.scheme}://{base.netloc}' != args.expected_origin:
        raise SystemExit('Credential destination does not match the approved origin')
    online = OnlineData()
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        copies, images = list(pool.map(lambda fetch: fetch(), [online.mothers, online.prompts]))
    snapshot = make_snapshot(copies, images, online.public_root)
    if not copies or not images:
        raise SystemExit('Empty upstream library; previous preview snapshot retained')
    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix('.tmp')
    with temporary.open('w', encoding='utf-8') as handle:
        os.chmod(temporary, 0o600)
        json.dump(snapshot, handle, ensure_ascii=False)
    if output.exists():
        shutil.copy2(output, output.with_suffix('.previous.json'))
    temporary.replace(output)
    print(json.dumps({'output': str(output), 'copies': len(copies), 'images': len(images), 'synced_at': snapshot['synced_at'], 'generated': 0}, ensure_ascii=False))


if __name__ == '__main__':
    main()
