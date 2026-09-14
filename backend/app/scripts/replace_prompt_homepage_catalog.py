"""Replace the prompt homepage with a licensed, locally mirrored catalog."""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import io
import json
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Any

import requests
from PIL import Image, ImageOps
from remotezip import RemoteZip
from sqlalchemy import select, update

from app.config import settings
from app.db.session import async_session
from app.models.prompt import PromptCategory, PromptExample


MEIGEN_DATA_URL = (
    "https://raw.githubusercontent.com/jau123/nanobanana-trending-prompts/"
    "eb4e5889ac3272fe9d9ca49db90cec60e2a24a38/prompts/prompts.json"
)
DIFFUSIONDB_PART_URL = (
    "https://huggingface.co/datasets/poloclub/diffusiondb/resolve/main/"
    "images/part-000001.zip"
)
CATALOG_BATCH = "open-catalog-20260914"
MEIGEN_LICENSE = "CC BY 4.0"
DIFFUSIONDB_LICENSE = "CC0 1.0"

CATEGORY_MAP = {
    "Photography": "摄影",
    "Illustration & 3D": "插画与 3D",
    "Product & Brand": "产品与品牌",
    "Food & Drink": "美食与饮品",
    "Poster Design": "海报设计",
    "UI & Graphic": "UI 与视觉设计",
}

BLOCKED_TERMS = re.compile(
    r"\b(nsfw|nude|nudity|naked|porn|pornographic|sex|sexual|sexy|fetish|"
    r"lingerie|bikini|underwear|gore|gory|bloodbath|decapitat|suicide|"
    r"child porn|loli|lolita)\b",
    re.IGNORECASE,
)
DIFFUSION_NEGATIVE_TERMS = re.compile(
    r"\b(girl|woman|women|boy|man|men|baby|child|portrait|celebrity|"
    r"doom|zombie|monster|war|weapon|gun|anime|marvel|disney|pokemon|"
    r"batman|superman|star wars|by [a-z])\b",
    re.IGNORECASE,
)
DIFFUSION_POSITIVE_TERMS = re.compile(
    r"\b(architecture|architectural|interior|landscape|nature|forest|"
    r"mountain|ocean|city|street|product|still life|vehicle|car|sculpture|"
    r"abstract|minimalist|minimalism|macro|food|ceramic|glass|botanical|"
    r"futuristic building|space station)\b",
    re.IGNORECASE,
)


def _normalized_prompt(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").replace("\x00", " ")).strip()


def _load_json(source: str) -> Any:
    path = Path(source)
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    response = requests.get(source, timeout=60)
    response.raise_for_status()
    return response.json()


def _is_safe_prompt(prompt: str) -> bool:
    return bool(prompt) and not BLOCKED_TERMS.search(prompt)


def _select_meigen(source: str, wanted: int) -> list[dict[str, Any]]:
    rows = _load_json(source)
    if not isinstance(rows, list):
        raise ValueError("MeiGen prompt source must be a JSON array")

    selected: list[dict[str, Any]] = []
    seen_prompts: set[str] = set()
    seen_images: set[str] = set()
    ranked = sorted(
        rows,
        key=lambda row: (
            float(row.get("score") or 0),
            int(row.get("likes") or 0),
            int(row.get("views") or 0),
        ),
        reverse=True,
    )
    for row in ranked:
        prompt = _normalized_prompt(row.get("prompt"))
        image_url = str(row.get("image") or "").strip()
        fingerprint = hashlib.sha256(prompt.lower().encode("utf-8")).hexdigest()
        if not _is_safe_prompt(prompt) or not image_url:
            continue
        if fingerprint in seen_prompts or image_url in seen_images:
            continue
        categories = row.get("categories") if isinstance(row.get("categories"), list) else []
        source_category = next((str(value) for value in categories if str(value) in CATEGORY_MAP), "")
        category = CATEGORY_MAP.get(source_category, "创意灵感")
        selected.append(
            {
                "source_kind": "external",
                "source_name": "MeiGen Trending Prompts",
                "source_url": str(row.get("source_url") or "https://www.meigen.ai/").strip(),
                "source_license": MEIGEN_LICENSE,
                "source_author": str(row.get("author_name") or row.get("author") or "MeiGen").strip(),
                "external_id": f"meigen:{row.get('id')}",
                "prompt": prompt,
                "image_source": image_url,
                "category": category,
                "param_type": "GPT Image" if row.get("model") == "gptimage" else "Nano Banana",
                "name": f"{category} · 灵感 {int(row.get('rank') or len(selected) + 1):04d}",
                "sort_order": int(round(float(row.get("score") or 0) * 100)),
            }
        )
        seen_prompts.add(fingerprint)
        seen_images.add(image_url)
        if len(selected) >= wanted:
            break
    if len(selected) < wanted:
        raise RuntimeError(f"MeiGen safe candidates are insufficient: {len(selected)} < {wanted}")
    return selected


def _diffusion_category(prompt: str) -> str:
    value = prompt.lower()
    if any(word in value for word in ("product", "still life", "ceramic", "glass")):
        return "产品与品牌"
    if any(word in value for word in ("architecture", "interior", "building", "city")):
        return "空间与建筑"
    if any(word in value for word in ("landscape", "nature", "forest", "mountain", "ocean", "botanical")):
        return "自然与风景"
    if any(word in value for word in ("car", "vehicle")):
        return "汽车创意"
    return "插画与 3D"


def _select_diffusiondb(remote_zip: RemoteZip, wanted: int) -> list[dict[str, Any]]:
    metadata = json.loads(remote_zip.read("part-000001.json"))
    candidates: list[dict[str, Any]] = []
    seen_prompts: set[str] = set()
    for image_name, raw in metadata.items():
        prompt = _normalized_prompt((raw or {}).get("p"))
        if not _is_safe_prompt(prompt):
            continue
        if DIFFUSION_NEGATIVE_TERMS.search(prompt) or not DIFFUSION_POSITIVE_TERMS.search(prompt):
            continue
        fingerprint = hashlib.sha256(prompt.lower().encode("utf-8")).hexdigest()
        if fingerprint in seen_prompts:
            continue
        category = _diffusion_category(prompt)
        candidates.append(
            {
                "source_kind": "external",
                "source_name": "DiffusionDB",
                "source_url": "https://github.com/poloclub/diffusiondb",
                "source_license": DIFFUSIONDB_LICENSE,
                "source_author": "DiffusionDB",
                "external_id": f"diffusiondb:{image_name}",
                "prompt": prompt,
                "zip_image_name": image_name,
                "category": category,
                "param_type": "Stable Diffusion",
                "name": f"{category} · 开放灵感 {len(candidates) + 1:03d}",
                "sort_order": 0,
            }
        )
        seen_prompts.add(fingerprint)
    candidates.sort(key=lambda row: hashlib.sha256(row["external_id"].encode("utf-8")).hexdigest())
    if len(candidates) < wanted:
        raise RuntimeError(f"DiffusionDB safe candidates are insufficient: {len(candidates)} < {wanted}")
    return candidates[:wanted]


def _encode_webp(content: bytes, destination: Path) -> None:
    with Image.open(io.BytesIO(content)) as source:
        image = ImageOps.exif_transpose(source)
        if image.mode not in {"RGB", "RGBA"}:
            image = image.convert("RGB")
        image.thumbnail((1600, 2000), Image.Resampling.LANCZOS)
        destination.parent.mkdir(parents=True, exist_ok=True)
        image.save(destination, "WEBP", quality=84, method=6)


def _local_image_target(root: Path, row: dict[str, Any]) -> tuple[Path, str]:
    source_slug, external_key = row["external_id"].split(":", 1)
    safe_key = re.sub(r"[^a-zA-Z0-9_-]+", "-", external_key).strip("-")
    relative = Path("prompts") / "catalog" / CATALOG_BATCH / source_slug / f"{safe_key}.webp"
    return root / relative, f"/uploads/{relative.as_posix()}"


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_manifest(path: Path, upload_root: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    rows = payload.get("items") if isinstance(payload, dict) else None
    if not isinstance(rows, list) or len(rows) != 1000:
        raise ValueError("catalog manifest must contain exactly 1000 items")

    normalized: list[dict[str, Any]] = []
    external_ids: set[str] = set()
    image_urls: set[str] = set()
    prompt_fingerprints: set[str] = set()
    for index, raw in enumerate(rows, start=1):
        if not isinstance(raw, dict):
            raise ValueError(f"catalog manifest item {index} must be an object")
        row = dict(raw)
        external_id = str(row.get("external_id") or "").strip()
        prompt = _normalized_prompt(row.get("prompt"))
        image_url = str(row.get("image_url") or "").strip()
        if not external_id or not prompt or not image_url.startswith("/uploads/"):
            raise ValueError(f"catalog manifest item {index} is incomplete")
        fingerprint = hashlib.sha256(prompt.lower().encode("utf-8")).hexdigest()
        if (
            external_id in external_ids
            or image_url in image_urls
            or fingerprint in prompt_fingerprints
        ):
            raise ValueError(f"catalog manifest item {index} is duplicated")

        relative = Path(image_url.removeprefix("/uploads/") or ".")
        image_path = (upload_root / relative).resolve()
        if upload_root not in image_path.parents or not image_path.is_file():
            raise FileNotFoundError(f"catalog image is missing: {image_url}")
        expected_sha256 = str(row.get("image_sha256") or "").strip().lower()
        if expected_sha256 and _file_sha256(image_path) != expected_sha256:
            raise ValueError(f"catalog image checksum mismatch: {image_url}")

        row.update(
            {
                "external_id": external_id,
                "prompt": prompt,
                "image_url": image_url,
                "name": str(row.get("name") or f"创意灵感 {index:04d}"),
                "category": str(row.get("category") or "创意灵感"),
                "param_type": str(row.get("param_type") or "AI Image"),
                "sort_order": int(row.get("sort_order") or 0),
                "source_kind": str(row.get("source_kind") or "external"),
                "source_name": str(row.get("source_name") or "Open catalog"),
                "source_url": str(row.get("source_url") or ""),
                "source_license": str(row.get("source_license") or ""),
                "source_author": str(row.get("source_author") or ""),
            }
        )
        normalized.append(row)
        external_ids.add(external_id)
        image_urls.add(image_url)
        prompt_fingerprints.add(fingerprint)
    return normalized


def _download_meigen_images(rows: list[dict[str, Any]], root: Path, workers: int) -> list[dict[str, Any]]:
    def download(row: dict[str, Any]) -> dict[str, Any]:
        destination, public_url = _local_image_target(root, row)
        if not destination.exists():
            response = requests.get(row["image_source"], timeout=40)
            response.raise_for_status()
            _encode_webp(response.content, destination)
        return {**row, "image_url": public_url}

    completed: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=max(1, workers)) as executor:
        future_map = {executor.submit(download, row): row for row in rows}
        for future in as_completed(future_map):
            row = future_map[future]
            try:
                completed.append(future.result())
            except Exception as exc:
                print(f"skip {row['external_id']}: {exc}")
    completed.sort(key=lambda row: row["sort_order"], reverse=True)
    return completed


def _download_diffusiondb_images(
    rows: list[dict[str, Any]],
    root: Path,
    workers: int,
) -> list[dict[str, Any]]:
    worker_count = max(1, min(workers, len(rows)))
    chunks = [rows[index::worker_count] for index in range(worker_count)]

    def download_chunk(chunk: list[dict[str, Any]]) -> list[dict[str, Any]]:
        chunk_results: list[dict[str, Any]] = []
        with RemoteZip(DIFFUSIONDB_PART_URL) as remote_zip:
            for row in chunk:
                destination, public_url = _local_image_target(root, row)
                try:
                    if not destination.exists():
                        _encode_webp(remote_zip.read(row["zip_image_name"]), destination)
                    chunk_results.append({**row, "image_url": public_url})
                except Exception as exc:
                    print(f"skip {row['external_id']}: {exc}", flush=True)
        return chunk_results

    completed: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=worker_count) as executor:
        for future in as_completed(executor.submit(download_chunk, chunk) for chunk in chunks):
            completed.extend(future.result())
            print(f"DiffusionDB images: {len(completed)}/{len(rows)}", flush=True)
    return completed


async def _replace_database(rows: list[dict[str, Any]], replace: bool) -> dict[str, int]:
    async with async_session() as session:
        active_before = len(
            (
                await session.execute(
                    select(PromptExample.id).where(PromptExample.deleted_at.is_(None))
                )
            ).scalars().all()
        )
        if replace:
            await session.execute(
                update(PromptExample)
                .where(PromptExample.deleted_at.is_(None))
                .values(deleted_at=datetime.utcnow())
            )

        category_names = sorted({row["category"] for row in rows})
        existing = (
            await session.execute(
                select(PromptCategory).where(
                    PromptCategory.name.in_(category_names),
                    PromptCategory.deleted_at.is_(None),
                )
            )
        ).scalars().all()
        categories = {category.name: category for category in existing}
        for category_name in category_names:
            if category_name not in categories:
                category = PromptCategory(name=category_name, sort_order=0)
                session.add(category)
                await session.flush()
                categories[category_name] = category

        external_ids = [row["external_id"] for row in rows]
        existing_rows = (
            await session.execute(
                select(PromptExample)
                .where(PromptExample.external_id.in_(external_ids))
                .order_by(PromptExample.id.desc())
            )
        ).scalars().all()
        existing_by_external_id: dict[str, PromptExample] = {}
        for example in existing_rows:
            if example.external_id and example.external_id not in existing_by_external_id:
                existing_by_external_id[example.external_id] = example

        created = 0
        reused = 0
        for row in rows:
            example = existing_by_external_id.get(row["external_id"])
            if example is None:
                example = PromptExample(external_id=row["external_id"])
                session.add(example)
                created += 1
            else:
                reused += 1
            example.category_id = categories[row["category"]].id
            example.param_type = row["param_type"]
            example.image_num = 1
            example.image_url = row["image_url"]
            example.name = row["name"]
            example.chinese_example = row["prompt"]
            example.english_example = ""
            example.ul_list = []
            example.sort_order = row["sort_order"]
            example.is_public = True
            example.source_kind = row["source_kind"]
            example.source_name = row["source_name"]
            example.source_url = row["source_url"]
            example.source_license = row["source_license"]
            example.source_author = row["source_author"]
            example.deleted_at = None

        active_after = len(
            (
                await session.execute(
                    select(PromptExample.id).where(PromptExample.deleted_at.is_(None))
                )
            ).scalars().all()
        )
        if replace and active_after != len(rows):
            raise RuntimeError(
                f"catalog transaction produced {active_after} active rows, expected {len(rows)}"
            )
        await session.commit()
        return {
            "active_before": active_before,
            "active_after": active_after,
            "imported": len(rows),
            "created": created,
            "reused": reused,
        }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--meigen-source", default=MEIGEN_DATA_URL)
    parser.add_argument("--meigen-count", type=int, default=900)
    parser.add_argument("--diffusiondb-count", type=int, default=100)
    parser.add_argument("--workers", type=int, default=12)
    parser.add_argument("--replace", action="store_true", help="soft-delete the current homepage catalog")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--manifest",
        type=Path,
        help="install a pre-mirrored catalog manifest instead of downloading remote sources",
    )
    args = parser.parse_args()

    if args.meigen_count < 0 or args.diffusiondb_count < 0:
        raise ValueError("source counts must be non-negative")
    expected = args.meigen_count + args.diffusiondb_count
    if expected != 1000:
        raise ValueError(f"catalog must contain exactly 1000 items, got {expected}")

    upload_root = Path(settings.storage_path).resolve()
    if args.manifest:
        rows = _load_manifest(args.manifest.resolve(), upload_root)
        if args.dry_run:
            print(json.dumps({"manifest": str(args.manifest), "items": len(rows)}, ensure_ascii=False))
            return
        result = asyncio.run(_replace_database(rows, args.replace))
        result.update({"manifest": str(args.manifest)})
        print(json.dumps(result, ensure_ascii=False))
        return

    meigen_rows = _select_meigen(args.meigen_source, args.meigen_count + 20)
    with RemoteZip(DIFFUSIONDB_PART_URL) as remote_zip:
        diffusion_rows = _select_diffusiondb(remote_zip, args.diffusiondb_count + 20)
    if args.dry_run:
        print(json.dumps({"meigen": args.meigen_count, "diffusiondb": args.diffusiondb_count}, ensure_ascii=False))
        return

    mirrored_meigen = _download_meigen_images(meigen_rows, upload_root, args.workers)
    mirrored_diffusion = _download_diffusiondb_images(diffusion_rows, upload_root, min(args.workers, 8))

    rows = mirrored_meigen[: args.meigen_count] + mirrored_diffusion[: args.diffusiondb_count]
    if len(rows) != expected:
        raise RuntimeError(f"only {len(rows)} of {expected} images were mirrored; database was not changed")
    result = asyncio.run(_replace_database(rows, args.replace))
    result.update({"meigen": len(mirrored_meigen), "diffusiondb": len(mirrored_diffusion)})
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
