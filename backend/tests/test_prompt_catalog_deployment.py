from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from sqlalchemy import func, select

from app.db.session import async_session
from app.models.prompt import PromptCategory, PromptExample
from app.scripts.replace_prompt_homepage_catalog import (
    _load_manifest,
    _replace_database,
)


def _catalog_row(index: int, image_url: str, checksum: str) -> dict[str, object]:
    return {
        "external_id": f"catalog:{index}",
        "prompt": f"Unique prompt {index}",
        "image_url": image_url,
        "image_sha256": checksum,
        "name": f"Catalog item {index}",
        "category": "产品与品牌",
        "param_type": "GPT Image",
        "sort_order": 1000 - index,
        "source_kind": "external",
        "source_name": "Test catalog",
        "source_url": "https://example.com/catalog",
        "source_license": "CC0",
        "source_author": "Test author",
    }


def test_manifest_requires_1000_unique_checksummed_local_images(tmp_path):
    checksum = hashlib.sha256(b"image").hexdigest()
    items = []
    for index in range(1000):
        relative = f"prompts/catalog/test/{index}.webp"
        image_path = tmp_path / relative
        image_path.parent.mkdir(parents=True, exist_ok=True)
        image_path.write_bytes(b"image")
        items.append(_catalog_row(index, f"/uploads/{relative}", checksum))

    manifest = tmp_path / "catalog.json"
    manifest.write_text(json.dumps({"items": items}), encoding="utf-8")

    rows = _load_manifest(manifest, tmp_path.resolve())

    assert len(rows) == 1000
    assert len({row["external_id"] for row in rows}) == 1000
    assert len({row["image_url"] for row in rows}) == 1000


def test_manifest_rejects_a_checksum_mismatch(tmp_path):
    image_path = tmp_path / "prompts/catalog/test/item.webp"
    image_path.parent.mkdir(parents=True)
    image_path.write_bytes(b"image")
    row = _catalog_row(0, "/uploads/prompts/catalog/test/item.webp", "0" * 64)
    manifest = tmp_path / "catalog.json"
    manifest.write_text(json.dumps({"items": [row] * 1000}), encoding="utf-8")

    with pytest.raises(ValueError, match="checksum mismatch|duplicated"):
        _load_manifest(manifest, tmp_path.resolve())


@pytest.mark.asyncio
async def test_catalog_database_replace_is_atomic_and_idempotent(client):
    async with async_session() as session:
        legacy_category = PromptCategory(name="旧分类")
        session.add(legacy_category)
        await session.flush()
        session.add(
            PromptExample(
                category_id=legacy_category.id,
                param_type="旧类型",
                chinese_example="旧提示词",
                english_example="",
                image_url="/uploads/legacy.webp",
                source_kind="internal",
            )
        )
        await session.commit()

    rows = [
        _catalog_row(index, f"/uploads/catalog/{index}.webp", "")
        for index in range(2)
    ]
    first = await _replace_database(rows, replace=True)
    second = await _replace_database(rows, replace=True)

    assert first == {
        "active_before": 1,
        "active_after": 2,
        "imported": 2,
        "created": 2,
        "reused": 0,
    }
    assert second == {
        "active_before": 2,
        "active_after": 2,
        "imported": 2,
        "created": 0,
        "reused": 2,
    }
    async with async_session() as session:
        active_count = await session.scalar(
            select(func.count(PromptExample.id)).where(PromptExample.deleted_at.is_(None))
        )
        total_count = await session.scalar(select(func.count(PromptExample.id)))
    assert active_count == 2
    assert total_count == 3


@pytest.mark.asyncio
async def test_catalog_database_add_is_idempotent_and_preserves_internal_content(client):
    async with async_session() as session:
        internal_category = PromptCategory(name="内部分类")
        session.add(internal_category)
        await session.flush()
        internal = PromptExample(
            category_id=internal_category.id,
            param_type="内部类型",
            chinese_example="现有内部提示词",
            english_example="",
            image_url="/uploads/internal.webp",
            source_kind="internal",
        )
        session.add(internal)
        await session.commit()
        internal_id = internal.id

    rows = [
        _catalog_row(index, f"/uploads/catalog/{index}.webp", "")
        for index in range(2)
    ]
    first = await _replace_database(rows, replace=False)
    second = await _replace_database(rows, replace=False)

    assert first == {
        "active_before": 1,
        "active_after": 3,
        "imported": 2,
        "created": 2,
        "reused": 0,
    }
    assert second == {
        "active_before": 3,
        "active_after": 3,
        "imported": 2,
        "created": 0,
        "reused": 2,
    }
    async with async_session() as session:
        preserved = await session.get(PromptExample, internal_id)
        source_counts = dict(
            (
                await session.execute(
                    select(PromptExample.source_kind, func.count(PromptExample.id))
                    .where(PromptExample.deleted_at.is_(None))
                    .group_by(PromptExample.source_kind)
                )
            ).all()
        )
    assert preserved is not None
    assert preserved.deleted_at is None
    assert preserved.chinese_example == "现有内部提示词"
    assert source_counts == {"external": 2, "internal": 1}


def test_windows_catalog_installer_uses_additive_mode():
    installer = (
        Path(__file__).resolve().parents[2]
        / "scripts"
        / "windows"
        / "Install-PromptHomepageCatalog.ps1"
    ).read_text(encoding="utf-8")

    install_command = installer.split("python -m app.scripts.replace_prompt_homepage_catalog", 1)[1]
    install_command = install_command.split("} 'Prompt catalog database installation failed'", 1)[0]
    assert "--replace" not in install_command
    assert "source_kind = 'internal'" in installer
    assert "source_kind = 'external'" in installer
    assert "Prompt catalog installation changed internal content" in installer
