from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.vehicle_catalog import VehicleModelImage


_SEED_JSON_FILE = Path(__file__).resolve().parents[1] / "data" / "car_models.json"


class VehicleModelImageService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def ensure_seeded(self) -> int:
        count = await self.db.scalar(select(func.count(VehicleModelImage.id)))
        if int(count or 0) > 0:
            return int(count or 0)
        return await self.import_seed_json(replace=False)

    async def import_seed_json(self, *, replace: bool = False) -> int:
        if not _SEED_JSON_FILE.exists():
            return 0
        with _SEED_JSON_FILE.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
        return await self.replace_data(data) if replace else await self._insert_data_if_empty(data, source="seed_json")

    async def _insert_data_if_empty(self, data: dict[str, Any], *, source: str) -> int:
        count = await self.db.scalar(select(func.count(VehicleModelImage.id)))
        if int(count or 0) > 0:
            return int(count or 0)
        self._add_data_rows(data, source=source)
        await self.db.commit()
        count = await self.db.scalar(select(func.count(VehicleModelImage.id)))
        return int(count or 0)

    def _add_data_rows(self, data: dict[str, Any], *, source: str) -> None:
        for brand, models in data.items():
            if not isinstance(models, dict):
                continue
            for model, images in models.items():
                if not isinstance(images, list):
                    continue
                for index, image in enumerate(images):
                    label = str((image or {}).get("label") or "").strip()
                    url = str((image or {}).get("url") or "").strip()
                    if not brand or not model or not label or not url:
                        continue
                    self.db.add(VehicleModelImage(
                        brand=str(brand).strip(),
                        model=str(model).strip(),
                        label=label,
                        url=url,
                        sort_order=index,
                        source=source,
                    ))

    async def replace_data(self, data: dict[str, Any]) -> int:
        await self.db.execute(delete(VehicleModelImage))
        self._add_data_rows(data, source="json_replace")
        await self.db.commit()
        count = await self.db.scalar(select(func.count(VehicleModelImage.id)))
        return int(count or 0)

    async def all_data(self) -> dict[str, dict[str, list[dict[str, str]]]]:
        await self.ensure_seeded()
        result = await self.db.execute(
            select(
                VehicleModelImage.brand,
                VehicleModelImage.model,
                VehicleModelImage.label,
                VehicleModelImage.url,
            )
            .order_by(
                VehicleModelImage.brand.asc(),
                VehicleModelImage.model.asc(),
                VehicleModelImage.sort_order.asc(),
                VehicleModelImage.id.asc(),
            )
        )
        data: dict[str, dict[str, list[dict[str, str]]]] = {}
        for brand, model, label, url in result.all():
            data.setdefault(str(brand), {}).setdefault(str(model), []).append({
                "label": str(label),
                "url": str(url),
            })
        return data

    async def brands(self) -> list[str]:
        data = await self.all_data()
        return sorted(data.keys())

    async def models(self, brand: str | None = None) -> dict[str, list[str]]:
        data = await self.all_data()
        if brand:
            if brand not in data:
                return {}
            return {brand: sorted(data[brand].keys())}
        return {item_brand: sorted(models.keys()) for item_brand, models in data.items()}

    async def images(self, brand: str, model: str | None = None) -> list[dict[str, str]]:
        data = await self.all_data()
        if brand not in data:
            return []
        if not model or model == "all":
            images: list[dict[str, str]] = []
            for model_name, items in data[brand].items():
                for item in items:
                    images.append({**item, "model": model_name})
            return images
        return list(data[brand].get(model, []))

    async def find_existing_model_name(self, brand: str, model_name: str) -> str | None:
        data = await self.all_data()
        models = data.get(brand) or {}
        target = model_name.casefold()
        for existing in models.keys():
            if existing.casefold() == target:
                return existing
        return None

    async def update_model_images(self, brand: str, model: str, images: list[dict[str, str]], *, source: str = "manual") -> None:
        await self.ensure_seeded()
        existing = await self.find_existing_model_name(brand, model)
        if not existing:
            raise KeyError("model_not_found")
        await self.db.execute(delete(VehicleModelImage).where(
            VehicleModelImage.brand == brand,
            VehicleModelImage.model == existing,
        ))
        for index, image in enumerate(images):
            self.db.add(VehicleModelImage(
                brand=brand,
                model=existing,
                label=str(image.get("label") or "").strip(),
                url=str(image.get("url") or "").strip(),
                sort_order=index,
                source=source,
            ))
        await self.db.commit()

    async def delete_model(self, brand: str, model: str) -> tuple[str, list[dict[str, str]]]:
        data = await self.all_data()
        if brand not in data:
            raise KeyError("brand_not_found")
        existing = await self.find_existing_model_name(brand, model)
        if not existing:
            raise KeyError("model_not_found")
        images = list(data[brand].get(existing, []))
        await self.db.execute(delete(VehicleModelImage).where(
            VehicleModelImage.brand == brand,
            VehicleModelImage.model == existing,
        ))
        await self.db.commit()
        return existing, images

    async def delete_image(self, brand: str, model: str, label: str, url: str) -> list[dict[str, str]]:
        data = await self.all_data()
        if brand not in data:
            raise KeyError("brand_not_found")
        existing = await self.find_existing_model_name(brand, model)
        if not existing:
            raise KeyError("model_not_found")
        images = list(data[brand].get(existing, []))
        if len(images) <= 1:
            raise ValueError("last_image")

        remaining: list[dict[str, str]] = []
        deleted = False
        for item in images:
            if not deleted and item.get("label") == label and item.get("url") == url:
                deleted = True
                continue
            remaining.append(item)
        if not deleted:
            raise KeyError("image_not_found")
        await self.update_model_images(brand, existing, remaining, source="delete_image")
        return remaining

    async def upsert_model_images(self, brand: str, model: str, images: list[dict[str, str]], *, source: str = "import_folder") -> None:
        await self.ensure_seeded()
        existing = await self.find_existing_model_name(brand, model)
        target = existing or model
        await self.db.execute(delete(VehicleModelImage).where(
            VehicleModelImage.brand == brand,
            VehicleModelImage.model == target,
        ))
        for index, image in enumerate(images):
            self.db.add(VehicleModelImage(
                brand=brand,
                model=target,
                label=str(image.get("label") or "").strip(),
                url=str(image.get("url") or "").strip(),
                sort_order=index,
                source=source,
            ))
        await self.db.commit()
