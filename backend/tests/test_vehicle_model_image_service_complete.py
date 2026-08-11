from __future__ import annotations

import json

import pytest

from app.db.session import async_session
from app.services.vehicle_model_image_service import VehicleModelImageService


@pytest.mark.asyncio
async def test_vehicle_image_catalog_queries_and_mutations(client, monkeypatch, tmp_path):
    missing = tmp_path / "missing.json"
    monkeypatch.setattr("app.services.vehicle_model_image_service._SEED_JSON_FILE", missing)

    async with async_session() as db:
        service = VehicleModelImageService(db)
        assert await service.import_seed_json() == 0
        assert await service.replace_data({
            "零跑": {
                "C10": [
                    {"label": "正面", "url": "https://img/1.jpg"},
                    {"label": "侧面", "url": "https://img/2.jpg"},
                ],
                "T03": [{"label": "前侧", "url": "https://img/3.jpg"}],
            },
            "无效品牌": ["not-a-dict"],
            "比亚迪": {"无效车型": "not-a-list"},
        }) == 3
        assert await service.ensure_seeded() == 3
        assert await service.brands() == ["零跑"]
        assert await service.models() == {"零跑": ["C10", "T03"]}
        assert await service.models("零跑") == {"零跑": ["C10", "T03"]}
        assert await service.models("不存在") == {}
        assert len(await service.images("零跑")) == 3
        assert len(await service.images("零跑", "all")) == 3
        assert len(await service.images("零跑", "C10")) == 2
        assert await service.images("不存在") == []
        assert await service.find_existing_model_name("零跑", "c10") == "C10"
        assert await service.find_existing_model_name("零跑", "C11") is None

        await service.update_model_images(
            "零跑",
            "c10",
            [{"label": "新正面", "url": "https://img/new.jpg"}],
        )
        assert await service.images("零跑", "C10") == [
            {"label": "新正面", "url": "https://img/new.jpg"}
        ]
        with pytest.raises(KeyError, match="model_not_found"):
            await service.update_model_images("零跑", "C99", [])

        await service.upsert_model_images(
            "零跑",
            "C11",
            [
                {"label": "A", "url": "a.jpg"},
                {"label": "B", "url": "b.jpg"},
            ],
        )
        assert len(await service.images("零跑", "C11")) == 2
        await service.upsert_model_images("零跑", "c11", [{"label": "C", "url": "c.jpg"}])
        assert await service.images("零跑", "C11") == [{"label": "C", "url": "c.jpg"}]

        with pytest.raises(ValueError, match="last_image"):
            await service.delete_image("零跑", "C11", "C", "c.jpg")
        with pytest.raises(KeyError, match="brand_not_found"):
            await service.delete_image("不存在", "C11", "C", "c.jpg")
        with pytest.raises(KeyError, match="model_not_found"):
            await service.delete_image("零跑", "C99", "C", "c.jpg")

        await service.update_model_images(
            "零跑",
            "C11",
            [{"label": "C", "url": "c.jpg"}, {"label": "D", "url": "d.jpg"}],
        )
        with pytest.raises(KeyError, match="image_not_found"):
            await service.delete_image("零跑", "C11", "X", "x.jpg")
        assert await service.delete_image("零跑", "C11", "C", "c.jpg") == [
            {"label": "D", "url": "d.jpg"}
        ]

        with pytest.raises(KeyError, match="brand_not_found"):
            await service.delete_model("不存在", "C10")
        with pytest.raises(KeyError, match="model_not_found"):
            await service.delete_model("零跑", "C99")
        deleted_name, deleted_images = await service.delete_model("零跑", "c10")
        assert deleted_name == "C10"
        assert deleted_images == [{"label": "新正面", "url": "https://img/new.jpg"}]


@pytest.mark.asyncio
async def test_vehicle_image_seed_file_and_invalid_rows(client, monkeypatch, tmp_path):
    seed = tmp_path / "images.json"
    seed.write_text(json.dumps({
        "零跑": {
            "C10": [
                {"label": "正面", "url": "1.jpg"},
                {"label": "", "url": "skip.jpg"},
                None,
            ]
        }
    }, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr("app.services.vehicle_model_image_service._SEED_JSON_FILE", seed)

    async with async_session() as db:
        service = VehicleModelImageService(db)
        assert await service.import_seed_json(replace=False) == 1
        assert await service.import_seed_json(replace=False) == 1
        assert await service.import_seed_json(replace=True) == 1
