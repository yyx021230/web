"""Export the active prompt homepage as a checksummed deployment manifest."""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select

from app.config import settings
from app.db.session import async_session
from app.models.prompt import PromptCategory, PromptExample


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


async def _export(output_path: Path) -> dict[str, object]:
    upload_root = Path(settings.storage_path).resolve()
    async with async_session() as session:
        records = (
            await session.execute(
                select(PromptExample, PromptCategory.name)
                .join(PromptCategory, PromptCategory.id == PromptExample.category_id)
                .where(PromptExample.deleted_at.is_(None))
                .order_by(PromptExample.sort_order.desc(), PromptExample.id.desc())
            )
        ).all()

    if len(records) != 1000:
        raise RuntimeError(f"active prompt catalog must contain exactly 1000 rows, got {len(records)}")

    items: list[dict[str, object]] = []
    for example, category_name in records:
        image_url = str(example.image_url or "")
        if not image_url.startswith("/uploads/"):
            raise ValueError(f"prompt {example.id} does not use a mirrored upload image")
        image_path = (upload_root / image_url.removeprefix("/uploads/")).resolve()
        if upload_root not in image_path.parents or not image_path.is_file():
            raise FileNotFoundError(f"prompt {example.id} image is missing: {image_url}")
        items.append(
            {
                "external_id": example.external_id,
                "prompt": example.chinese_example,
                "image_url": image_url,
                "image_size": image_path.stat().st_size,
                "image_sha256": _file_sha256(image_path),
                "name": example.name,
                "category": category_name,
                "param_type": example.param_type,
                "sort_order": example.sort_order,
                "source_kind": example.source_kind,
                "source_name": example.source_name,
                "source_url": example.source_url,
                "source_license": example.source_license,
                "source_author": example.source_author,
            }
        )

    external_ids = {str(item["external_id"] or "") for item in items}
    if "" in external_ids or len(external_ids) != len(items):
        raise RuntimeError("active prompt catalog has missing or duplicated external IDs")

    payload = {
        "schema_version": 1,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "count": len(items),
        "items": items,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
    return {
        "output": str(output_path),
        "items": len(items),
        "bytes": output_path.stat().st_size,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    print(json.dumps(asyncio.run(_export(args.output.resolve())), ensure_ascii=False))


if __name__ == "__main__":
    main()
