"""Import a checksummed reviewed catalog without replacing existing prompts."""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlsplit

from sqlalchemy import func, select

from app.config import settings
from app.db.session import async_session
from app.models.prompt import PromptCategory, PromptExample


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _local_image_path(upload_root: Path, image_url: str) -> Path:
    relative = unquote(urlsplit(image_url).path.removeprefix("/uploads/"))
    candidate = (upload_root / relative).resolve()
    root_text = str(upload_root)
    candidate_text = str(candidate)
    if not (
        candidate_text == root_text
        or candidate_text.startswith(root_text + os.sep)
    ):
        raise ValueError(f"catalog image escapes upload root: {image_url}")
    return candidate


def load_manifest(path: Path, upload_root: Path) -> tuple[str, list[dict[str, Any]]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("catalog manifest must be an object")
    batch = str(payload.get("batch") or "").strip()
    rows = payload.get("items")
    if not batch or not isinstance(rows, list) or not rows:
        raise ValueError("catalog manifest requires a batch and non-empty items")
    if int(payload.get("count") or 0) != len(rows):
        raise ValueError("catalog manifest count does not match items")

    normalized: list[dict[str, Any]] = []
    external_ids: set[str] = set()
    image_urls: set[str] = set()
    for index, raw in enumerate(rows, start=1):
        if not isinstance(raw, dict):
            raise ValueError(f"catalog item {index} must be an object")
        external_id = str(raw.get("external_id") or "").strip()
        prompt_zh = str(raw.get("prompt_zh") or "").strip()
        image_url = str(raw.get("image_url") or "").strip()
        category = str(raw.get("category") or "").strip()
        source_name = str(raw.get("source_name") or "").strip()
        if not all((external_id, prompt_zh, category, source_name)):
            raise ValueError(f"catalog item {index} is incomplete")
        if not image_url.startswith("/uploads/"):
            raise ValueError(f"catalog item {index} does not use mirrored storage")
        if external_id in external_ids or image_url in image_urls:
            raise ValueError(f"catalog item {index} is duplicated")
        if not external_id.startswith(f"{batch}:"):
            raise ValueError(f"catalog item {index} is outside batch namespace")

        image_path = _local_image_path(upload_root, image_url)
        if not image_path.is_file():
            raise FileNotFoundError(f"catalog image is missing: {image_url}")
        expected_sha256 = str(raw.get("image_sha256") or "").strip().lower()
        if not expected_sha256 or _file_sha256(image_path) != expected_sha256:
            raise ValueError(f"catalog image checksum mismatch: {image_url}")

        normalized.append(
            {
                "external_id": external_id,
                "prompt_zh": prompt_zh,
                "prompt_en": str(raw.get("prompt_en") or "").strip(),
                "image_url": image_url,
                "name": str(raw.get("name") or f"外部素材 {index:04d}").strip(),
                "category": category,
                "param_type": str(raw.get("param_type") or "AI Image").strip(),
                "sort_order": int(raw.get("sort_order") or 0),
                "source_name": source_name,
                "source_url": str(raw.get("source_url") or "").strip(),
                "source_license": str(raw.get("source_license") or "授权待复核").strip(),
                "source_author": str(raw.get("source_author") or source_name).strip(),
                "tags": [str(value).strip() for value in raw.get("tags", []) if str(value).strip()],
            }
        )
        external_ids.add(external_id)
        image_urls.add(image_url)
    return batch, normalized


async def import_rows(batch: str, rows: list[dict[str, Any]]) -> dict[str, int | str]:
    async with async_session() as session:
        internal_before = int(
            await session.scalar(
                select(func.count(PromptExample.id)).where(
                    PromptExample.deleted_at.is_(None),
                    PromptExample.source_kind == "internal",
                )
            )
            or 0
        )
        external_before = int(
            await session.scalar(
                select(func.count(PromptExample.id)).where(
                    PromptExample.deleted_at.is_(None),
                    PromptExample.source_kind == "external",
                )
            )
            or 0
        )

        category_names = sorted({row["category"] for row in rows})
        category_records = list(
            (
                await session.execute(
                    select(PromptCategory).where(
                        PromptCategory.name.in_(category_names),
                        PromptCategory.deleted_at.is_(None),
                    )
                )
            ).scalars()
        )
        categories = {record.name: record for record in category_records}
        for category_name in category_names:
            if category_name in categories:
                continue
            category = PromptCategory(name=category_name, sort_order=0)
            session.add(category)
            await session.flush()
            categories[category_name] = category

        external_ids = [row["external_id"] for row in rows]
        existing_records = list(
            (
                await session.execute(
                    select(PromptExample)
                    .where(PromptExample.external_id.in_(external_ids))
                    .order_by(PromptExample.id.desc())
                )
            ).scalars()
        )
        existing: dict[str, PromptExample] = {}
        for record in existing_records:
            if record.external_id and record.external_id not in existing:
                existing[record.external_id] = record

        created = 0
        updated = 0
        for row in rows:
            prompt = existing.get(row["external_id"])
            if prompt is None:
                prompt = PromptExample(external_id=row["external_id"])
                session.add(prompt)
                existing[row["external_id"]] = prompt
                created += 1
            else:
                updated += 1
            prompt.category_id = categories[row["category"]].id
            prompt.param_type = row["param_type"]
            prompt.image_num = 1
            prompt.image_url = row["image_url"]
            prompt.name = row["name"]
            prompt.chinese_example = row["prompt_zh"]
            prompt.english_example = row["prompt_en"]
            prompt.ul_list = row["tags"]
            prompt.sort_order = row["sort_order"]
            prompt.is_public = True
            prompt.source_kind = "external"
            prompt.source_name = row["source_name"]
            prompt.source_url = row["source_url"]
            prompt.source_license = row["source_license"]
            prompt.source_author = row["source_author"]
            prompt.deleted_at = None

        await session.flush()
        batch_count = int(
            await session.scalar(
                select(func.count(PromptExample.id)).where(
                    PromptExample.deleted_at.is_(None),
                    PromptExample.external_id.like(f"{batch}:%"),
                )
            )
            or 0
        )
        internal_after = int(
            await session.scalar(
                select(func.count(PromptExample.id)).where(
                    PromptExample.deleted_at.is_(None),
                    PromptExample.source_kind == "internal",
                )
            )
            or 0
        )
        external_after = int(
            await session.scalar(
                select(func.count(PromptExample.id)).where(
                    PromptExample.deleted_at.is_(None),
                    PromptExample.source_kind == "external",
                )
            )
            or 0
        )
        if batch_count != len(rows):
            raise RuntimeError(f"batch verification failed: expected={len(rows)} actual={batch_count}")
        if internal_after != internal_before:
            raise RuntimeError(
                f"internal catalog changed: before={internal_before} after={internal_after}"
            )
        await session.commit()
        return {
            "batch": batch,
            "items": len(rows),
            "created": created,
            "updated": updated,
            "internal_before": internal_before,
            "internal_after": internal_after,
            "external_before": external_before,
            "external_after": external_after,
        }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--upload-root", type=Path, default=Path(settings.storage_path))
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    batch, rows = load_manifest(args.manifest.resolve(), args.upload_root.resolve())
    if args.dry_run:
        print(json.dumps({"batch": batch, "items": len(rows), "valid": True}, ensure_ascii=False))
        return
    print(json.dumps(asyncio.run(import_rows(batch, rows)), ensure_ascii=False))


if __name__ == "__main__":
    main()
