from __future__ import annotations

import hashlib
import json

import pytest
from sqlalchemy import func, select

from app.db.session import async_session
from app.models.prompt import PromptCategory, PromptExample
from app.scripts.import_reviewed_external_catalog import import_rows, load_manifest


def _row(index: int, checksum: str) -> dict[str, object]:
    return {
        "external_id": f"reviewed-v1:item-{index}",
        "prompt_zh": f"中文提示词 {index}",
        "prompt_en": f"English prompt {index}",
        "image_url": f"/uploads/prompts/reviewed-v1/item-{index}.webp",
        "image_sha256": checksum,
        "name": f"素材 {index}",
        "category": "汽车视觉",
        "param_type": "汽车视觉",
        "source_name": "Test source",
        "source_url": "https://example.test/source",
        "source_license": "CC0 1.0",
        "source_author": "Tester",
        "tags": ["汽车", "海报"],
    }


def test_reviewed_manifest_validates_dynamic_count_and_checksums(tmp_path):
    content = b"test-image"
    checksum = hashlib.sha256(content).hexdigest()
    item_path = tmp_path / "prompts/reviewed-v1/item-1.webp"
    item_path.parent.mkdir(parents=True)
    item_path.write_bytes(content)
    manifest = tmp_path / "catalog.json"
    manifest.write_text(
        json.dumps({"batch": "reviewed-v1", "count": 1, "items": [_row(1, checksum)]}),
        encoding="utf-8",
    )

    batch, rows = load_manifest(manifest, tmp_path.resolve())

    assert batch == "reviewed-v1"
    assert rows[0]["prompt_en"] == "English prompt 1"


@pytest.mark.asyncio
async def test_reviewed_import_is_additive_and_idempotent(client):
    async with async_session() as session:
        category = PromptCategory(name="内部分类")
        session.add(category)
        await session.flush()
        session.add(
            PromptExample(
                category_id=category.id,
                param_type="内部",
                chinese_example="内部提示词",
                english_example="",
                source_kind="internal",
            )
        )
        await session.commit()

    rows = [
        {
            "external_id": "reviewed-v1:item-1",
            "prompt_zh": "汽车商业视觉",
            "prompt_en": "Automotive commercial visual",
            "image_url": "/uploads/prompts/reviewed-v1/item-1.webp",
            "name": "汽车素材",
            "category": "汽车视觉",
            "param_type": "汽车视觉",
            "sort_order": 1,
            "source_name": "Test source",
            "source_url": "https://example.test/source",
            "source_license": "CC0 1.0",
            "source_author": "Tester",
            "tags": ["汽车"],
        }
    ]

    first = await import_rows("reviewed-v1", rows)
    second = await import_rows("reviewed-v1", rows)

    assert first["created"] == 1
    assert second["created"] == 0
    assert second["updated"] == 1
    async with async_session() as session:
        counts = dict(
            (
                await session.execute(
                    select(PromptExample.source_kind, func.count(PromptExample.id))
                    .where(PromptExample.deleted_at.is_(None))
                    .group_by(PromptExample.source_kind)
                )
            ).all()
        )
    assert counts == {"external": 1, "internal": 1}
