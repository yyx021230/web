from __future__ import annotations

import json
from datetime import datetime, timedelta

import pytest
from sqlalchemy import select

from app.db.session import async_session
from app.models.dashboard_snapshot import DashboardSnapshot
from app.models.vehicle_catalog import VehicleCatalog
from app.schemas.template import TemplateCreate, TemplateUpdate
from app.services.copywriting_service import CopywritingService
from app.services.dashboard_snapshot_service import (
    DashboardSnapshotService,
    stable_dashboard_cache_key,
)
from app.services.project_service import ProjectService
from app.services.template_service import TemplateService
from app.services.vehicle_catalog_service import VehicleCatalogService


@pytest.mark.asyncio
async def test_project_service_full_lifecycle(client):
    async with async_session() as db:
        service = ProjectService(db)
        first = await service.create(7, "首个项目", status=None)
        second = await service.create(7, "第二项目", fabric_json="{}", status="published")
        await service.create(8, "其他用户项目")

        assert first.status == "draft"
        assert second.status == "published"
        items, total = await service.get_list(7, page=1, limit=1)
        assert total == 2
        assert len(items) == 1
        assert await service.get_by_id(first.id, 8) is None

        updated = await service.update(
            first.id,
            7,
            name="已更新",
            fabric_json='{"objects": []}',
            thumbnail="cover.png",
            status="published",
        )
        assert updated is not None
        assert (updated.name, updated.thumbnail, updated.status) == (
            "已更新",
            "cover.png",
            "published",
        )
        assert await service.update(99999, 7, name="missing") is None
        assert await service.delete(99999, 7) is False
        assert await service.delete(first.id, 7) is True
        assert await service.get_by_id(first.id, 7) is None


@pytest.mark.asyncio
async def test_template_service_crud_and_owner_rules(client):
    async with async_session() as db:
        service = TemplateService(db)
        created = await service.create(
            TemplateCreate(
                name="海报模板",
                description="描述",
                fabric_json="{}",
                category="汽车",
                tags=["封面"],
            ),
            user_id=11,
        )
        other = await service.create(
            TemplateCreate(name="其他", fabric_json="{}", category="生活"),
            user_id=None,
        )
        other.is_public = False
        await db.commit()

        items, total = await service.get_list(category="汽车")
        assert total == 1
        assert [item.id for item in items] == [created.id]
        assert await service.get_by_id(created.id) is not None
        assert await service.update(created.id, TemplateUpdate(name="越权"), user_id=12) is None

        updated = await service.update(
            created.id,
            TemplateUpdate(name="新模板", tags=["新版"]),
            user_id=11,
        )
        assert updated is not None
        assert updated.name == "新模板"
        assert updated.tags == ["新版"]
        assert await service.update(99999, TemplateUpdate(name="无"), user_id=11) is None
        assert await service.delete(created.id, user_id=12) is False
        assert await service.delete(99999, user_id=11) is False
        assert await service.delete(created.id, user_id=11) is True
        assert await service.get_by_id(created.id) is None


@pytest.mark.asyncio
async def test_copywriting_service_crud_import_and_categories(client):
    assert set(CopywritingService._extract_tags("正文 #零跑 #优惠 #零跑")) == {"零跑", "优惠"}
    assert CopywritingService._extract_category("新车", "比亚迪价格") == "比亚迪"
    assert CopywritingService._extract_category("无品牌", "普通内容") is None

    async with async_session() as db:
        service = CopywritingService(db)
        created = await service.create("零跑 C10", "正文 #购车 #优惠", user_id=21)
        await service.create("普通帖子", "没有品牌", user_id=22)
        assert created.category == "零跑"
        assert set(created.tags) == {"购车", "优惠"}

        items, total = await service.get_list(category="零跑", keyword="C10", user_id=21)
        assert total == 1
        assert items[0].id == created.id
        assert await service.get_by_id(created.id) is not None
        assert await service.update(created.id, title="越权", user_id=22) is None
        updated = await service.update(
            created.id,
            title="比亚迪海报",
            content="新正文 #价格",
            user_id=21,
        )
        assert updated is not None
        assert updated.category == "比亚迪"
        assert updated.tags == ["价格"]
        assert await service.update(99999, title="无") is None

        imported = await service.bulk_import(
            [
                {"title": "大众行情", "content": "正文 #行情"},
                {"title": "", "content": "跳过"},
                {"title": "缺正文", "content": ""},
            ],
            user_id=21,
        )
        assert imported == 1
        categories = {row["name"]: row["count"] for row in await service.get_categories()}
        assert categories["比亚迪"] == 1
        assert categories["大众"] == 1
        assert await service.delete(created.id, user_id=22) is False
        assert await service.delete(99999, user_id=21) is False
        assert await service.delete(created.id, user_id=21) is True


@pytest.mark.asyncio
async def test_dashboard_snapshot_cache_miss_hit_expiry_and_update(client):
    params = {"owner": "全部", "date": datetime(2026, 8, 11)}
    assert stable_dashboard_cache_key(params) == stable_dashboard_cache_key(dict(reversed(params.items())))

    async with async_session() as db:
        service = DashboardSnapshotService(db)
        storage_params = {"owner": "全部", "days": 30}
        assert await service.get_payload("xhs", storage_params) is None
        payload = {"kpis": {"views": 10}, "_snapshot": {"hit": False}}
        await service.save_payload("xhs", storage_params, payload, ttl_seconds=1)
        assert payload["_snapshot"]["hit"] is False

        hit = await service.get_payload("xhs", storage_params)
        assert hit is not None
        assert hit["kpis"]["views"] == 10
        assert hit["_snapshot"]["hit"] is True
        assert hit["_snapshot"]["namespace"] == "xhs"

        await service.save_payload("xhs", storage_params, {"kpis": {"views": 20}})
        updated = await service.get_payload("xhs", storage_params)
        assert updated is not None
        assert updated["kpis"]["views"] == 20

        row = (
            await db.execute(select(DashboardSnapshot).where(DashboardSnapshot.namespace == "xhs"))
        ).scalar_one()
        assert row.payload_bytes == len(json.dumps(row.payload, ensure_ascii=False, separators=(",", ":")).encode())
        row.expires_at = datetime.utcnow() - timedelta(seconds=1)
        await db.commit()
        assert await service.get_payload("xhs", storage_params) is None

        row.expires_at = None
        row.payload = ["invalid"]
        await db.commit()
        assert await service.get_payload("xhs", storage_params) is None


@pytest.mark.asyncio
async def test_vehicle_catalog_seed_import_and_queries(client, monkeypatch, tmp_path):
    csv_path = tmp_path / "cars.csv"
    csv_path.write_text(
        "mid,汽车品牌,详细车型,车型ID\n"
        "1,零跑,C10,100\n"
        "1,零跑,C10,100\n"
        "2,比亚迪,海豹,200\n"
        "3,,无品牌,300\n",
        encoding="utf-8",
    )
    monkeypatch.setattr("app.services.vehicle_catalog_service._SEED_CSV_FILE", csv_path)

    async with async_session() as db:
        service = VehicleCatalogService(db)
        assert await service.ensure_seeded() == 2
        assert await service.ensure_seeded() == 2
        assert await service.import_seed_csv(replace=False) == 2
        assert await service.brands() == ("比亚迪", "零跑")
        rows = await service.rows()
        assert len(rows) == 2
        assert {item["model"] for item in rows} == {"C10", "海豹"}
        assert await service.match_entries() == [
            {"brand": "比亚迪", "model": "海豹"},
            {"brand": "零跑", "model": "C10"},
        ]
        assert (await db.scalar(select(VehicleCatalog.id).limit(1))) is not None

        csv_path.write_text("mid,汽车品牌,详细车型,车型ID\n", encoding="utf-8")
        assert await service.import_seed_csv(replace=True) == 0
        missing = tmp_path / "missing.csv"
        monkeypatch.setattr("app.services.vehicle_catalog_service._SEED_CSV_FILE", missing)
        assert await service.import_seed_csv() == 0
