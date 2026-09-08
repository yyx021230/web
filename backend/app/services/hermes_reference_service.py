"""Read-only, role-filtered examples from the synced online library or local DB."""
from __future__ import annotations
import hashlib
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import unquote, urlsplit
from typing import Any
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.config import settings
from app.core.roles import has_role
from app.models.copywriting import Copywriting
from app.models.prompt import PromptCategory, PromptExample
from app.models.user import User
from app.services.hermes_reference_types import COPY_TYPES, IMAGE_TYPES, TAXONOMY_VERSION, classify_copy, image_layout_analysis, approved_image_section

logger = logging.getLogger(__name__)


def online_snapshot() -> dict[str, Any] | None:
    """No network or credentials in a page request. Invalid caches fail local."""
    if not settings.hermes_reference_snapshot_path:
        return None
    path = Path(settings.hermes_reference_snapshot_path)
    if not path.is_file():
        return None
    try:
        if path.stat().st_size > 20_000_000:
            raise ValueError('Preview snapshot exceeds size limit')
        data = json.loads(path.read_text(encoding='utf-8'))
        if not isinstance(data, dict) or data.get('schema_version') != 1:
            raise ValueError('Unsupported preview snapshot')
        for key in ('copies', 'images'):
            if not isinstance(data.get(key), list) or not all(isinstance(row, dict) for row in data[key]):
                raise ValueError('Invalid preview library rows')
        if not isinstance(data.get('sections', []), list) or not all(isinstance(row, dict) for row in data.get('sections', [])):
            raise ValueError('Invalid preview sections')
        datetime.fromisoformat(data['synced_at']).astimezone(timezone.utc)
        return data
    except (OSError, ValueError, KeyError, TypeError):
        logger.warning('Online reference snapshot unavailable; using local examples')
        return None


def preview_available(url: str) -> bool:
    if not url.startswith('/uploads/'):
        return True  # Do not fetch arbitrary remote library URLs from the server.
    root = Path(settings.storage_path).resolve()
    candidate = (root / unquote(urlsplit(url).path.removeprefix('/uploads/'))).resolve()
    return root in candidate.parents and candidate.is_file()


async def reference_catalog(db: AsyncSession, user: User) -> dict[str, Any]:
    snapshot = online_snapshot()
    if snapshot:
        copies = snapshot['copies']
        images = [row for row in snapshot['images'] if has_role(user, 'admin') or row.get('is_public') is True]
        sections = [row for row in snapshot.get('sections', []) if has_role(user, 'admin') or row.get('is_public') is True]
    else:
        local_copies = list((await db.execute(select(Copywriting).where(Copywriting.deleted_at.is_(None)).order_by(Copywriting.id.desc()))).scalars())
        conditions = [PromptExample.deleted_at.is_(None), PromptCategory.deleted_at.is_(None)]
        if not has_role(user, 'admin'):
            conditions.append(PromptExample.is_public.is_(True))
        local_images = list((await db.execute(select(PromptExample).join(PromptCategory).where(*conditions).order_by(PromptExample.id.desc()))).scalars())
        copies = [{'id': item.id, 'title': item.title, 'content': item.content} for item in local_copies]
        images = [{'id': item.id, 'name': item.name, 'chinese': item.chinese_example, 'image_url': item.image_url} for item in local_images]
        sections = []
    groups: dict[str, list[dict[str, Any]]] = {item['id']: [] for item in COPY_TYPES + IMAGE_TYPES}
    seen: set[str] = set()
    for item in copies:
        if not item.get('id') or not isinstance(item.get('content'), str) or not isinstance(item.get('title'), str):
            continue
        row = {'id': item['id'], 'title': item['title'], 'content': item['content'], 'kind': 'copy'}
        category = classify_copy(row)
        fingerprint = 'copy:' + hashlib.sha256(item['content'].strip().encode()).hexdigest()
        if category and fingerprint not in seen:
            seen.add(fingerprint)
            groups[category].append(row)
    for item in images + sections:
        item = approved_image_section(item)
        if not item.get('id') or not (item.get('image_url') or item.get('source_section_title')) or not isinstance(item.get('chinese'), str):
            continue
        url = '' if item.get('source_image_matches_section') is False else str(item.get('image_url') or '')
        if url.startswith('/'):
            url = str(settings.uploads_public_base_url or '').rstrip('/') + url
        # No arbitrary schemes in an example image/link supplied from the library.
        parsed = urlsplit(url)
        if parsed.username or parsed.password or (url and not (url.startswith('/uploads/') or (parsed.scheme in {'https', 'http'} and parsed.hostname))):
            continue
        row = {'id': item['id'], 'title': item.get('name') or item.get('title') or f'提示词 #{item["id"]}', 'content': item['chinese'], 'chinese': item['chinese'], 'image_url': url, 'kind': 'image'}
        if item.get('source_section_title'):
            row.update(source_section_title=item['source_section_title'], preview_note=item.get('preview_note'))
        analysis = image_layout_analysis(row)
        category = analysis['type']
        row.update(classification_reason=analysis['reason'], style_tags=analysis['style_tags'], requires_quote_data=analysis['requires_quote_data'])
        fingerprint = 'image:' + hashlib.sha256(item['chinese'].strip().encode()).hexdigest()
        if category and fingerprint not in seen:
            seen.add(fingerprint)
            groups[category].append(row)
    def cards(definitions):
        result = []
        for definition in definitions:
            rows = groups[definition['id']]
            available = [row for row in rows if not row.get('image_url') or preview_available(row['image_url'])]
            result.append({**definition, 'reference_count': len(rows), 'preview_count': len(available),
                           'requires_quote_data': bool(definition.get('requires_quote_data') or (rows and all(r.get('requires_quote_data') for r in rows))),
                           'examples': available[:3]})
        return result
    return {
        'version': TAXONOMY_VERSION,
        'source': 'synced_online_library' if snapshot else 'current_web_library',
        'synced_at': snapshot['synced_at'] if snapshot else None,
        'source_note': ('案例来自线上文案库/提示词库的只读预览缓存。' if snapshot else '案例来自当前 Web 文案库/提示词库。') + '预览与生产共用版式分类；按原文去重，数字为归类数量，不是通过生产校验的数量。每例展示归类依据，不代表当前车型成品或逐图视觉验收；旧车型、旧政策不会直接沿用。',
        'copy_types': cards(COPY_TYPES), 'image_types': cards(IMAGE_TYPES),
        'library_counts': {'copy': len(copies), 'image': len(images)},
    }
