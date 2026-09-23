"""Build a visually diverse 500-item prompt catalog for the four core use cases."""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import unquote, urlsplit

from PIL import Image, ImageOps
from sqlalchemy import select, update

from app.config import settings
from app.db.session import async_session
from app.models.ai_task import AITask
from app.models.prompt import PromptCategory, PromptExample
from app.models.xhs_post import XHSPost


BATCH = "business-curated-20260918"
QUOTA = 125
CATEGORIES = ("产品视觉", "AI短剧与漫剧", "海报营销", "汽车创意")

PRODUCT_TERMS = re.compile(
    r"\b(product|packaging|package|bottle|cosmetic|skincare|perfume|beverage|"
    r"food|jewelry|watch|shoe|fashion|brand|commercial|still life)\b",
    re.IGNORECASE,
)
NARRATIVE_TERMS = re.compile(
    r"角色|故事|分镜|漫画|漫剧|动画|短剧|"
    r"\b(character|storyboard|comic|manga|animation|animated|anime|hero|"
    r"villain|dialogue|episode|protagonist|graphic novel|visual novel|cartoon|"
    r"chibi|pokemon|pixar|avatar|expression sheet|webtoon|manhwa)\b",
    re.IGNORECASE,
)
POSTER_TERMS = re.compile(
    r"\b(poster|campaign|advertis|marketing|promotion|sale|launch|event|"
    r"festival|flyer|typography|editorial|billboard|social media|key visual)\b",
    re.IGNORECASE,
)
AUTOMOTIVE_TERMS = re.compile(
    r"汽车|车型|新能源|小红书.{0,4}封面|购车|车价|优惠|促销|行情|"
    r"\b(car|vehicle|automotive|suv|sedan)\b",
    re.IGNORECASE,
)


@dataclass
class Candidate:
    external_id: str
    category: str
    prompt: str
    image_url: str
    source_kind: str
    source_name: str
    source_url: str
    source_license: str
    source_author: str
    param_type: str
    score: int
    image_hash: int = 0
    image_sha256: str = ""


def _image_path(upload_root: Path, url: str) -> Path | None:
    if not url.startswith("/uploads/"):
        return None
    relative = unquote(urlsplit(url).path.removeprefix("/uploads/"))
    candidate = (upload_root / relative).resolve()
    if upload_root not in candidate.parents or not candidate.is_file():
        return None
    return candidate


def _dhash(path: Path) -> int:
    with Image.open(path) as source:
        image = ImageOps.exif_transpose(source).convert("L").resize((9, 8), Image.Resampling.LANCZOS)
        pixels = list(image.getdata())
    value = 0
    for row in range(8):
        offset = row * 9
        for column in range(8):
            value = (value << 1) | int(pixels[offset + column] > pixels[offset + column + 1])
    return value


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _prepare(candidate: Candidate, upload_root: Path) -> Candidate | None:
    path = _image_path(upload_root, candidate.image_url)
    if path is None:
        return None
    try:
        candidate.image_hash = _dhash(path)
        candidate.image_sha256 = _sha256(path)
    except Exception:
        return None
    return candidate


def _distance(left: int, right: int) -> int:
    return bin(left ^ right).count("1")


def _select_diverse(
    candidates: Iterable[Candidate],
    wanted: int,
    used_hashes: list[int],
    used_sha256: set[str],
) -> list[Candidate]:
    pool = sorted(candidates, key=lambda item: (item.score, item.external_id), reverse=True)
    selected: list[Candidate] = []
    selected_ids: set[str] = set()

    # Relax only when needed; exact duplicate image bytes are never accepted.
    for minimum_distance in (8, 6, 4, 2, 1, 0):
        for candidate in pool:
            if len(selected) >= wanted:
                break
            if (
                candidate.external_id in selected_ids
                or candidate.image_sha256 in used_sha256
            ):
                continue
            if minimum_distance and any(
                _distance(candidate.image_hash, existing) < minimum_distance
                for existing in (*used_hashes, *(item.image_hash for item in selected))
            ):
                continue
            selected.append(candidate)
            selected_ids.add(candidate.external_id)
            used_sha256.add(candidate.image_sha256)
        if len(selected) >= wanted:
            break

    if len(selected) != wanted:
        raise RuntimeError(f"{pool[0].category if pool else 'unknown'} only selected {len(selected)}/{wanted}")
    used_hashes.extend(item.image_hash for item in selected)
    return selected


async def _external_candidates(upload_root: Path) -> dict[str, list[Candidate]]:
    async with async_session() as session:
        rows = (
            await session.execute(
                select(PromptExample, PromptCategory.name)
                .join(PromptCategory, PromptCategory.id == PromptExample.category_id)
                .where(
                    PromptExample.source_kind == "external",
                    PromptExample.is_public.is_(True),
                )
            )
        ).all()

    groups: dict[str, list[Candidate]] = {category: [] for category in CATEGORIES}
    for example, old_category in rows:
        prompt = str(example.chinese_example or example.english_example or "").strip()
        image_url = str(example.image_url or "").strip()
        base = {
            "external_id": str(example.external_id or f"legacy-prompt:{example.id}"),
            "prompt": prompt,
            "image_url": image_url,
            "source_kind": "external",
            "source_name": str(example.source_name or "开放素材"),
            "source_url": str(example.source_url or ""),
            "source_license": str(example.source_license or ""),
            "source_author": str(example.source_author or ""),
            "param_type": str(example.param_type or "AI Image"),
            "score": int(example.sort_order or 0),
        }
        targets: list[str] = []
        if old_category in {"产品与品牌", "产品视觉"} or PRODUCT_TERMS.search(prompt):
            targets.append("产品视觉")
        if NARRATIVE_TERMS.search(prompt):
            targets.append("AI短剧与漫剧")
        if old_category in {"海报设计", "海报营销"} or POSTER_TERMS.search(prompt):
            targets.append("海报营销")
        if old_category == "汽车创意" or AUTOMOTIVE_TERMS.search(prompt):
            targets.append("汽车创意")
        for category in targets:
            prepared = _prepare(Candidate(category=category, **base), upload_root)
            if prepared is not None:
                groups[category].append(prepared)
    return groups


async def _automotive_candidates(upload_root: Path) -> list[Candidate]:
    async with async_session() as session:
        tasks = (
            await session.execute(
                select(AITask)
                .where(AITask.status == "completed")
                .order_by(AITask.created_at.desc(), AITask.id.desc())
            )
        ).scalars().all()

    candidates: list[Candidate] = []
    for task in tasks:
        prompt = str(task.prompt or "").strip()
        if not AUTOMOTIVE_TERMS.search(prompt):
            continue
        for index, image_url in enumerate(task.result_urls or []):
            candidate = Candidate(
                external_id=f"business-ai:{task.id}:{index}",
                category="汽车创意",
                prompt=prompt,
                image_url=str(image_url or "").strip(),
                source_kind="internal",
                source_name="AI 生图精选",
                source_url="",
                source_license="内部素材",
                source_author="Creative Studio",
                param_type=str(
                    (task.params or {}).get("provider", {}).get("name")
                    or task.model_name
                    or "AI Image"
                ),
                score=int(task.id or 0),
            )
            prepared = _prepare(candidate, upload_root)
            if prepared is not None:
                candidates.append(prepared)
    return candidates


async def _performance_automotive_candidates(upload_root: Path) -> list[Candidate]:
    async with async_session() as session:
        posts = (
            await session.execute(
                select(XHSPost)
                .where(XHSPost.image_urls.is_not(None))
                .order_by(
                    XHSPost.view_count.desc(),
                    XHSPost.like_count.desc(),
                    XHSPost.id.desc(),
                )
            )
        ).scalars().all()

    candidates: list[Candidate] = []
    for post in posts:
        title = str(post.title or "汽车内容封面").strip()
        prompt = (
            "参考这张小红书汽车封面的构图和信息层级，围绕"
            f"「{title}」创作 3:4 竖版汽车营销封面；保留清晰车型主体、强标题和价格/优惠信息区，"
            "不复制原账号标识或水印。"
        )
        engagement = sum(
            int(value or 0)
            for value in (post.like_count, post.comment_count, post.collect_count, post.share_count)
        )
        score = int(post.view_count or 0) + engagement * 20
        for index, image_url in enumerate(post.image_urls or []):
            candidate = Candidate(
                external_id=f"business-xhs:{post.id}:{index}",
                category="汽车创意",
                prompt=prompt,
                image_url=str(image_url or "").strip(),
                source_kind="performance",
                source_name="优质帖子封面",
                source_url=str(post.post_url or ""),
                source_license="内部运营数据",
                source_author="小红书运营样本",
                param_type="小红书汽车封面",
                score=score,
            )
            prepared = _prepare(candidate, upload_root)
            if prepared is not None:
                candidates.append(prepared)
    return candidates


async def _build(upload_root: Path) -> list[Candidate]:
    groups = await _external_candidates(upload_root)
    groups["汽车创意"] = (
        await _automotive_candidates(upload_root)
        + await _performance_automotive_candidates(upload_root)
        + groups["汽车创意"]
    )
    used_hashes: list[int] = []
    used_sha256: set[str] = set()
    selected: list[Candidate] = []
    for category in CATEGORIES:
        selected.extend(
            _select_diverse(
                groups[category],
                QUOTA,
                used_hashes,
                used_sha256,
            )
        )
    return selected


async def _apply(rows: list[Candidate]) -> dict[str, int]:
    now = datetime.utcnow()
    async with async_session() as session:
        await session.execute(
            update(PromptExample)
            .where(
                PromptExample.deleted_at.is_(None),
                (
                    (PromptExample.source_kind == "external")
                    | (PromptExample.external_id.like("business-ai:%"))
                ),
            )
            .values(deleted_at=now)
        )

        categories: dict[str, PromptCategory] = {}
        existing_categories = (
            await session.execute(
                select(PromptCategory).where(PromptCategory.name.in_(CATEGORIES))
            )
        ).scalars().all()
        for category in existing_categories:
            category.deleted_at = None
            categories[category.name] = category
        for order, name in enumerate(CATEGORIES, start=1):
            if name not in categories:
                category = PromptCategory(name=name, sort_order=100 - order)
                session.add(category)
                await session.flush()
                categories[name] = category

        external_ids = [row.external_id for row in rows]
        existing_rows = (
            await session.execute(select(PromptExample).where(PromptExample.external_id.in_(external_ids)))
        ).scalars().all()
        by_external_id = {str(row.external_id): row for row in existing_rows if row.external_id}

        created = 0
        for index, row in enumerate(rows):
            example = by_external_id.get(row.external_id)
            if example is None:
                example = PromptExample(external_id=row.external_id)
                session.add(example)
                created += 1
            category_index = CATEGORIES.index(row.category)
            item_index = index - category_index * QUOTA + 1
            example.category_id = categories[row.category].id
            example.param_type = row.param_type
            example.image_num = 1
            example.image_url = row.image_url
            example.name = f"{row.category} · {item_index:03d}"
            example.chinese_example = row.prompt
            example.english_example = row.prompt if row.prompt.isascii() else ""
            example.ul_list = []
            example.sort_order = 500 - index
            example.is_public = True
            example.source_kind = row.source_kind
            example.source_name = row.source_name
            example.source_url = row.source_url
            example.source_license = row.source_license
            example.source_author = row.source_author
            example.deleted_at = None

        await session.commit()
        return {"selected": len(rows), "created": created, "reused": len(rows) - created}


def _write_manifest(rows: list[Candidate], destination: Path) -> None:
    payload: dict[str, Any] = {
        "batch": BATCH,
        "created_at": datetime.utcnow().isoformat() + "Z",
        "total": len(rows),
        "categories": {category: sum(row.category == category for row in rows) for category in CATEGORIES},
        "items": [
            {
                "external_id": row.external_id,
                "category": row.category,
                "prompt": row.prompt,
                "image_url": row.image_url,
                "image_sha256": row.image_sha256,
                "image_dhash": f"{row.image_hash:016x}",
                "source_kind": row.source_kind,
                "source_name": row.source_name,
                "source_url": row.source_url,
                "source_license": row.source_license,
                "source_author": row.source_author,
                "param_type": row.param_type,
            }
            for row in rows
        ],
    }
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="replace the visible external catalog")
    parser.add_argument(
        "--manifest",
        type=Path,
        default=Path(settings.storage_path) / "prompts" / "catalog" / BATCH / "catalog.json",
    )
    args = parser.parse_args()

    upload_root = Path(settings.storage_path).resolve()
    rows = await _build(upload_root)
    _write_manifest(rows, args.manifest)
    result = await _apply(rows) if args.apply else {"selected": len(rows), "dry_run": 1}
    print(json.dumps({**result, "manifest": str(args.manifest)}, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(main())
