"""End-to-end API contracts for materials and the copywriting library."""

from __future__ import annotations

from datetime import date, datetime
from io import BytesIO
from unittest.mock import AsyncMock

import openpyxl
import pytest
from fastapi import HTTPException

from app.db.session import async_session
from app.models.scrape_review import ScrapeCandidate, ScrapeTask, ScrapeTaskReviewer
from app.models.user import User
from app.services.scrape_review_service import ScrapeReviewService
from tests.conftest import make_auth_headers


async def _seed_user(user_id: int = 1, username: str = "content-user") -> dict[str, str]:
    async with async_session() as db:
        db.add(
            User(
                id=user_id,
                username=username,
                email=f"{username}@content.test",
                hashed_password="x",
                role="viewer",
            )
        )
        await db.commit()
    return make_auth_headers(user_id)


@pytest.mark.asyncio
async def test_material_api_full_lifecycle_and_validation(client, monkeypatch):
    headers = await _seed_user()
    save = AsyncMock(side_effect=lambda content, filename, content_type, subdir: f"/uploads/{subdir}/{filename}")
    monkeypatch.setattr("app.api.v1.materials.storage.save", save)

    image = await client.post(
        "/api/v1/materials/upload",
        data={"target": "templates"},
        files={"file": ("cover.png", b"png", "image/png")},
        headers=headers,
    )
    assert image.status_code == 200
    assert image.json()["data"]["type"] == "image"
    assert image.json()["data"]["url"] == "/uploads/templates/cover.png"

    video = await client.post(
        "/api/v1/materials/upload",
        files={"file": ("clip.mp4", b"video", "video/mp4")},
        headers=headers,
    )
    assert video.status_code == 200
    assert video.json()["data"]["type"] == "video"

    generic = await client.post(
        "/api/v1/materials/upload",
        files={"file": ("blob.bin", b"blob", "")},
        headers=headers,
    )
    assert generic.status_code == 200
    assert generic.json()["data"]["type"] == "file"

    invalid = await client.post(
        "/api/v1/materials/upload",
        files={"file": ("notes.txt", b"text", "text/plain")},
        headers=headers,
    )
    assert invalid.status_code == 400
    assert "不支持" in invalid.json()["detail"]

    oversized = await client.post(
        "/api/v1/materials/upload",
        files={"file": ("large.png", b"x" * (10 * 1024 * 1024 + 1), "image/png")},
        headers=headers,
    )
    assert oversized.status_code == 400
    assert "文件大小" in oversized.json()["detail"]

    design = await client.post(
        "/api/v1/materials/design",
        json={
            "name": "设计稿",
            "design_json": {"objects": []},
            "thumbnail": "/thumb.png",
            "width": 1080,
            "height": 1440,
        },
        headers=headers,
    )
    assert design.status_code == 200
    design_id = design.json()["data"]["id"]

    updated = await client.put(
        f"/api/v1/materials/{design_id}",
        json={"name": "新版设计稿", "width": 1200, "tags": ["汽车"]},
        headers=headers,
    )
    assert updated.status_code == 200
    assert updated.json()["data"]["name"] == "新版设计稿"
    assert updated.json()["data"]["tags"] == ["汽车"]
    assert (await client.put("/api/v1/materials/99999", json={"name": "missing"}, headers=headers)).status_code == 404

    usage = (await client.get("/api/v1/materials/storage-usage", headers=headers)).json()["data"]
    assert usage["file_count"] == 4
    assert usage["total_items"] == 4
    assert usage["limit_mb"] == 5120

    listed = (
        await client.get(
            "/api/v1/materials",
            params={"owner": False, "exclude_category": "ai-template"},
            headers=headers,
        )
    ).json()["data"]
    assert listed["total"] == 3

    assert (await client.delete("/api/v1/materials/99999", headers=headers)).status_code == 404
    assert (await client.delete(f"/api/v1/materials/{design_id}", headers=headers)).status_code == 200
    deleted = await client.delete("/api/v1/materials/all", headers=headers)
    assert deleted.status_code == 200
    assert deleted.json()["data"]["count"] == 3


@pytest.mark.asyncio
async def test_ai_material_remote_download_folder_and_error_paths(client, monkeypatch):
    headers = await _seed_user()
    save = AsyncMock(side_effect=lambda content, filename, content_type, subdir: f"/local/{subdir}/{filename}")
    download = AsyncMock(return_value=(b"image", "remote.webp", "image/webp"))
    monkeypatch.setattr("app.api.v1.materials.storage.save", save)
    monkeypatch.setattr("app.api.v1.materials._download_remote_image", download)

    template = await client.post(
        "/api/v1/materials/template",
        json={
            "name": "远程模板",
            "url": "https://images.test/remote.webp",
            "ai_meta": {"prompt": "汽车海报"},
            "width": 768,
            "height": 1024,
            "tags": ["待归档"],
        },
        headers=headers,
    )
    assert template.status_code == 200
    template_data = template.json()["data"]
    assert template_data["url"] == "/local/templates/remote.webp"
    assert template_data["ai_meta"]["prompt"] == "汽车海报"
    template_id = template_data["id"]

    local = await client.post(
        f"/api/v1/materials/{template_id}/download",
        json={"url": "/local/templates/remote.webp"},
        headers=headers,
    )
    assert local.status_code == 200
    assert "无需" in local.json()["message"]

    remote = await client.post(
        f"/api/v1/materials/{template_id}/download",
        json={"url": "https://images.test/new.webp"},
        headers=headers,
    )
    assert remote.status_code == 200
    assert remote.json()["data"]["url"] == "/local/templates/remote.webp"
    assert (await client.post("/api/v1/materials/99999/download", json={}, headers=headers)).status_code == 404

    renamed = await client.put(
        "/api/v1/materials/folders/%E5%BE%85%E5%BD%92%E6%A1%A3",
        json={"new_name": "已归档"},
        headers=headers,
    )
    assert renamed.status_code == 200
    assert renamed.json()["data"]["count"] == 1
    assert (
        await client.put(
            "/api/v1/materials/folders/%E5%B7%B2%E5%BD%92%E6%A1%A3",
            json={"new_name": "  "},
            headers=headers,
        )
    ).status_code == 400
    removed = await client.delete("/api/v1/materials/folders/%E5%B7%B2%E5%BD%92%E6%A1%A3", headers=headers)
    assert removed.status_code == 200
    assert removed.json()["data"]["affected_count"] == 1

    draft = await client.post(
        "/api/v1/materials/draft-ai",
        json={"url": "https://images.test/draft.webp", "ai_meta": {"prompt": "draft"}},
        headers=headers,
    )
    assert draft.status_code == 200
    assert draft.json()["data"]["url"] == "/local/drafts/remote.webp"

    download.side_effect = HTTPException(status_code=400, detail="blocked")
    blocked = await client.post(
        "/api/v1/materials/template",
        json={"url": "https://blocked.test/image.png"},
        headers=headers,
    )
    assert blocked.status_code == 400

    download.side_effect = RuntimeError("network down")
    failed_template = await client.post(
        "/api/v1/materials/template",
        json={"url": "https://broken.test/image.png"},
        headers=headers,
    )
    assert failed_template.status_code == 500
    assert "network down" in failed_template.json()["detail"]
    failed_draft = await client.post(
        "/api/v1/materials/draft-ai",
        json={"url": "https://broken.test/image.png"},
        headers=headers,
    )
    assert failed_draft.status_code == 500


@pytest.mark.asyncio
async def test_copywriting_crud_import_and_review_api(client, monkeypatch):
    headers = await _seed_user()

    created = await client.post(
        "/api/v1/copywritings",
        json={"title": "零跑 C10", "content": "#零跑# 购车建议"},
        headers=headers,
    )
    assert created.status_code == 200
    copy_id = created.json()["data"]["id"]

    category_filtered = await client.get(
        "/api/v1/copywritings",
        params={"owner": True, "keyword": "零跑", "category": "汽车"},
        headers=headers,
    )
    assert category_filtered.status_code == 200
    assert category_filtered.json()["data"]["total"] == 0
    listed = await client.get(
        "/api/v1/copywritings",
        params={"owner": True, "keyword": "零跑"},
        headers=headers,
    )
    assert listed.status_code == 200
    assert listed.json()["data"]["total"] == 1
    assert (await client.get("/api/v1/copywritings/categories")).status_code == 200
    assert (await client.get(f"/api/v1/copywritings/{copy_id}")).status_code == 200
    assert (await client.get("/api/v1/copywritings/99999")).status_code == 404

    updated = await client.put(
        f"/api/v1/copywritings/{copy_id}",
        json={"title": "零跑 C10 新版", "content": "更新内容"},
        headers=headers,
    )
    assert updated.status_code == 200
    assert updated.json()["data"]["title"] == "零跑 C10 新版"
    assert (await client.put("/api/v1/copywritings/99999", json={"title": "x"}, headers=headers)).status_code == 404

    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.append(["文案"])
    sheet.append(["标题：第一条\n正文一"])
    sheet.append(["标题: 第二条\n正文二"])
    sheet.append(["第三条\n正文三"])
    sheet.append([""])
    payload = BytesIO()
    workbook.save(payload)
    imported = await client.post(
        "/api/v1/copywritings/import",
        files={"file": ("copy.xlsx", payload.getvalue(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        headers=headers,
    )
    assert imported.status_code == 200
    assert imported.json()["data"]["count"] == 3

    async with async_session() as db:
        task = ScrapeTask(
            id=50,
            name="审核任务",
            source="keyword",
            status="completed",
            created_by=1,
            candidate_count=1,
            pending_count=1,
            finished_at=datetime(2026, 6, 1),
        )
        db.add(task)
        await db.flush()
        db.add(ScrapeTaskReviewer(task_id=50, user_id=1))
        db.add(
            ScrapeCandidate(
                id=60,
                task_id=50,
                external_id="candidate-60",
                title="待审核文案",
                content="候选正文",
                author="作者",
                source="keyword",
                source_keyword="零跑",
                publish_date=date(2026, 6, 1),
                copy_type="测评",
                brand="零跑",
                likes=10,
                comments=2,
                collects=3,
                shares=1,
                views=100,
                review_status="pending",
            )
        )
        await db.commit()

    tasks = await client.get("/api/v1/copywritings/review/tasks", headers=headers)
    assert tasks.status_code == 200
    assert tasks.json()["data"]["items"][0]["finished_at"] is not None
    candidates = await client.get(
        "/api/v1/copywritings/review/candidates",
        params={"task_id": 50},
        headers=headers,
    )
    assert candidates.status_code == 200
    assert candidates.json()["data"]["items"][0]["publish_date"] == "2026-06-01"
    assert (
        await client.get(
            "/api/v1/copywritings/review/candidates",
            params={"status": "approved"},
            headers=headers,
        )
    ).status_code == 200

    approved = await client.post(
        "/api/v1/copywritings/review/candidates/60/action",
        json={"action": "approved", "note": "通过"},
        headers=headers,
    )
    assert approved.status_code == 200
    assert approved.json()["data"]["review_status"] == "approved"
    assert (await client.post("/api/v1/copywritings/review/candidates/999/action", json={"action": "approved"}, headers=headers)).status_code == 404

    monkeypatch.setattr(
        ScrapeReviewService,
        "review_candidate",
        AsyncMock(side_effect=PermissionError("not assigned")),
    )
    assert (
        await client.post(
            "/api/v1/copywritings/review/candidates/60/action",
            json={"action": "reject"},
            headers=headers,
        )
    ).status_code == 403
    monkeypatch.setattr(
        ScrapeReviewService,
        "review_candidate",
        AsyncMock(side_effect=ValueError("bad action")),
    )
    assert (
        await client.post(
            "/api/v1/copywritings/review/candidates/60/action",
            json={"action": "bad"},
            headers=headers,
        )
    ).status_code == 400

    assert (await client.delete("/api/v1/copywritings/99999", headers=headers)).status_code == 404
    assert (await client.delete(f"/api/v1/copywritings/{copy_id}", headers=headers)).status_code == 200
