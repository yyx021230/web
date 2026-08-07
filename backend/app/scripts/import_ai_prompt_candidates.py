"""Import curated AI image tasks into the prompt library without duplicates."""
from __future__ import annotations

import argparse
import asyncio
import json
import re
from pathlib import Path

from sqlalchemy import select

from app.db.session import async_session
from app.models.prompt import PromptCategory, PromptExample


def _normalize_prompt(value: str | None) -> str:
    return re.sub(r"\s+", " ", (value or "").strip())


async def import_candidates(manifest_path: Path, *, dry_run: bool) -> dict[str, int]:
    candidates = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(candidates, list):
        raise ValueError("manifest must be a JSON array")

    async with async_session() as session:
        category = (
            await session.execute(
                select(PromptCategory).where(
                    PromptCategory.name == "AI生图分享",
                    PromptCategory.deleted_at.is_(None),
                )
            )
        ).scalar_one_or_none()
        if category is None:
            category = PromptCategory(name="AI生图分享", sort_order=0)
            session.add(category)
            await session.flush()

        existing_rows = (
            await session.execute(
                select(PromptExample.chinese_example, PromptExample.image_url).where(
                    PromptExample.deleted_at.is_(None)
                )
            )
        ).all()
        existing_prompts = {_normalize_prompt(prompt) for prompt, _ in existing_rows if prompt}
        existing_images = {url.strip() for _, url in existing_rows if url and url.strip()}

        imported = 0
        duplicate_prompt = 0
        duplicate_image = 0
        invalid = 0
        batch_prompts: set[str] = set()
        batch_images: set[str] = set()

        for item in candidates:
            prompt = _normalize_prompt(str(item.get("prompt") or ""))
            image_url = str(item.get("url") or "").strip()
            if not prompt or not image_url:
                invalid += 1
                continue

            if prompt in existing_prompts or prompt in batch_prompts:
                duplicate_prompt += 1
                continue
            if image_url in existing_images or image_url in batch_images:
                duplicate_image += 1
                continue

            if not dry_run:
                index = int(item.get("index") or imported + 1)
                bucket = str(item.get("bucket") or "精选")
                task_id = item.get("id")
                session.add(
                    PromptExample(
                        category_id=category.id,
                        param_type=f"精选 · {bucket}",
                        image_url=image_url,
                        name=f"精选 {index:03d} · {bucket}",
                        chinese_example=prompt,
                        english_example="",
                        ul_list=["线上生图精选", f"来源任务 #{task_id}"],
                        sort_order=0,
                        is_public=True,
                        created_by=1,
                        updated_by=1,
                    )
                )

            imported += 1
            batch_prompts.add(prompt)
            batch_images.add(image_url)

        if dry_run:
            await session.rollback()
        else:
            await session.commit()

    return {
        "source_count": len(candidates),
        "imported": imported,
        "duplicate_prompt": duplicate_prompt,
        "duplicate_image": duplicate_image,
        "invalid": invalid,
        "dry_run": dry_run,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    print(json.dumps(asyncio.run(import_candidates(args.manifest, dry_run=args.dry_run)), ensure_ascii=False))


if __name__ == "__main__":
    main()
