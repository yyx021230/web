from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.vehicle_catalog import VehicleCatalog


_SEED_CSV_FILE = Path(__file__).resolve().parents[1] / "data" / "cars_data.csv"
_SEED_REFRESHED = False


class VehicleCatalogService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def ensure_seeded(self) -> int:
        global _SEED_REFRESHED
        count = await self.db.scalar(select(func.count(VehicleCatalog.id)))
        # Older databases may have been seeded from an earlier, incomplete CSV.
        # Refresh once per process so newly added models are upserted as well.
        if _SEED_REFRESHED and int(count or 0) > 0:
            return int(count or 0)
        refreshed = await self.import_seed_csv(replace=False)
        _SEED_REFRESHED = True
        return refreshed

    async def import_seed_csv(self, *, replace: bool = False) -> int:
        if not _SEED_CSV_FILE.exists():
            return 0

        rows: list[dict[str, Any]] = []
        seen: set[tuple[str, str]] = set()
        with _SEED_CSV_FILE.open("r", encoding="utf-8-sig", newline="") as handle:
            for item in csv.DictReader(handle):
                brand = str(item.get("汽车品牌") or "").strip()
                model = str(item.get("详细车型") or "").strip()
                if not brand or not model:
                    continue
                key = (brand, model)
                if key in seen:
                    continue
                seen.add(key)
                rows.append({
                    "mid": str(item.get("mid") or "").strip() or None,
                    "brand": brand,
                    "model": model,
                    "model_id": str(item.get("车型ID") or "").strip() or None,
                    "source": "seed_csv",
                })

        if not rows:
            return 0
        if replace:
            await self.db.execute(delete(VehicleCatalog))

        bind = self.db.get_bind()
        insert_factory = sqlite_insert if bind is not None and bind.dialect.name == "sqlite" else insert
        stmt = insert_factory(VehicleCatalog).values(rows)
        stmt = stmt.on_conflict_do_nothing(index_elements=["brand", "model"])
        await self.db.execute(stmt)
        await self.db.commit()
        count = await self.db.scalar(select(func.count(VehicleCatalog.id)))
        return int(count or 0)

    async def rows(self) -> list[dict[str, str | None]]:
        await self.ensure_seeded()
        result = await self.db.execute(
            select(VehicleCatalog.mid, VehicleCatalog.brand, VehicleCatalog.model, VehicleCatalog.model_id)
            .order_by(VehicleCatalog.brand.asc(), VehicleCatalog.model.asc())
        )
        return [
            {
                "mid": mid,
                "brand": brand,
                "model": model,
                "model_id": model_id,
            }
            for mid, brand, model, model_id in result.all()
        ]

    async def brands(self) -> tuple[str, ...]:
        await self.ensure_seeded()
        result = await self.db.execute(select(VehicleCatalog.brand).distinct().order_by(VehicleCatalog.brand.asc()))
        return tuple(str(row[0]) for row in result.all() if row[0])

    async def match_entries(self) -> list[dict[str, str]]:
        await self.ensure_seeded()
        result = await self.db.execute(
            select(VehicleCatalog.brand, VehicleCatalog.model)
            .order_by(VehicleCatalog.brand.asc(), VehicleCatalog.model.asc())
        )
        return [
            {"brand": brand, "model": model}
            for brand, model in result.all()
            if brand and model
        ]
