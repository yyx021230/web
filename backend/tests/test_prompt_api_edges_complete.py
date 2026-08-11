"""Spreadsheet, image upload and moderation edge paths for prompt APIs."""

from __future__ import annotations

from io import BytesIO
from unittest.mock import AsyncMock

import openpyxl
import pytest

from app.db.session import async_session
from app.models.prompt import PromptCategory, PromptExample
from app.models.user import User
from tests.conftest import make_auth_headers


async def _seed_users() -> tuple[dict[str, str], dict[str, str]]:
    async with async_session() as db:
        db.add_all(
            [
                User(id=1, username="edge-admin", email="edge-admin@prompt.test", hashed_password="x", role="admin"),
                User(id=2, username="edge-user", email="edge-user@prompt.test", hashed_password="x", role="viewer"),
            ]
        )
        await db.commit()
    return make_auth_headers(1), make_auth_headers(2)


def _xlsx(rows: list[list[object]]) -> bytes:
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    for row in rows:
        sheet.append(row)
    output = BytesIO()
    workbook.save(output)
    return output.getvalue()


@pytest.mark.asyncio
async def test_prompt_xlsx_import_all_failed_empty_and_success(client):
    _, user = await _seed_users()
    headers = ["Title", "Chinese", "English", "Category", "ParamType", "ImageURL"]
    payload = _xlsx(
        [
            headers,
            ["成功", "中文内容", "English", "汽车", "海报", "/prompt.png"],
            ["缺图", "有正文", "", "汽车", "海报", ""],
            ["空正文", "", "", "汽车", "海报", "/empty.png"],
        ]
    )
    imported = await client.post(
        "/api/v1/prompts/import",
        files={"file": ("prompts.xlsx", payload, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        headers=user,
    )
    assert imported.status_code == 200
    result = imported.json()["data"]
    assert result["imported_count"] == 1
    assert result["failed_count"] == 1
    assert result["created_categories"] == ["汽车"]

    all_failed = await client.post(
        "/api/v1/prompts/import",
        files={
            "file": (
                "failed.xlsx",
                _xlsx([headers, ["只有缺图", "正文", "", "默认", "通用", ""]]),
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        },
        headers=user,
    )
    assert all_failed.status_code == 200
    assert all_failed.json()["data"]["imported_count"] == 0
    assert all_failed.json()["data"]["failed_count"] == 1

    empty = await client.post(
        "/api/v1/prompts/import",
        files={
            "file": (
                "empty.xlsx",
                _xlsx([headers, ["空", "", "", "", "", ""]]),
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        },
        headers=user,
    )
    assert empty.status_code == 400
    assert "未找到有效数据" in empty.json()["detail"]


@pytest.mark.asyncio
async def test_prompt_image_upload_and_admin_edit_visibility(client, monkeypatch):
    admin, user = await _seed_users()
    save = AsyncMock(return_value="/uploads/prompts/example.webp")
    monkeypatch.setattr("app.api.v1.prompts.storage.save", save)

    uploaded = await client.post(
        "/api/v1/prompts/upload-image",
        files={"file": ("example.webp", b"image", "image/webp")},
        headers=user,
    )
    assert uploaded.status_code == 200
    assert uploaded.json()["data"]["url"] == "/uploads/prompts/example.webp"
    save.assert_awaited_once()

    svg = await client.post(
        "/api/v1/prompts/upload-image",
        files={"file": ("bad.svg", b"svg", "image/svg+xml")},
        headers=user,
    )
    assert svg.status_code == 400
    invalid = await client.post(
        "/api/v1/prompts/upload-image",
        files={"file": ("bad.txt", b"text", "text/plain")},
        headers=user,
    )
    assert invalid.status_code == 400
    oversized = await client.post(
        "/api/v1/prompts/upload-image",
        files={"file": ("large.png", b"x" * (10 * 1024 * 1024 + 1), "image/png")},
        headers=user,
    )
    assert oversized.status_code == 400

    async with async_session() as db:
        category = PromptCategory(name="系统分类")
        db.add(category)
        await db.flush()
        db.add(
            PromptExample(
                id=100,
                category_id=category.id,
                name=None,
                param_type="",
                chinese_example="系统提示词",
                english_example="",
                image_url="/system.png",
                created_by=None,
                is_public=False,
            )
        )
        await db.commit()

    listing = await client.get("/api/v1/prompts", headers=admin)
    system_item = next(item for item in listing.json()["data"]["items"] if item["id"] == 100)
    assert system_item["title"] == "系统分类 - 通用"
    assert system_item["created_by_name"] == "系统"
    assert system_item["can_edit"] is True

    edited = await client.put(
        "/api/v1/prompts/100",
        headers=admin,
        json={
            "category": "新系统分类",
            "chinese": "新中文",
            "english": "new english",
            "image_url": "/new.png",
            "param_type": "",
            "title": "管理员标题",
            "is_public": True,
        },
    )
    assert edited.status_code == 200
    assert edited.json()["data"]["category"] == "新系统分类"
    assert edited.json()["data"]["param_type"] == "通用"
    assert edited.json()["data"]["is_public"] is True
    assert edited.json()["data"]["is_mine"] is False
    assert (await client.put("/api/v1/prompts/99999", headers=admin, json={})).status_code == 404
    assert (await client.delete("/api/v1/prompts/100", headers=admin)).status_code == 200


@pytest.mark.asyncio
async def test_prompt_duplicate_report_and_admin_report_error_branches(client):
    admin, user = await _seed_users()
    created = await client.post(
        "/api/v1/prompts",
        headers=admin,
        json={"chinese": "待举报", "image_url": "/report.png", "category": "举报"},
    )
    prompt_id = created.json()["data"]["id"]
    first = await client.post(
        f"/api/v1/prompts/{prompt_id}/report",
        headers=user,
        json={"reason": "其他", "details": "详情"},
    )
    assert first.status_code == 200
    duplicate = await client.post(
        f"/api/v1/prompts/{prompt_id}/report",
        headers=user,
        json={"reason": "其他"},
    )
    assert duplicate.status_code == 400
    reports = await client.get("/api/v1/prompts/my-reports", headers=user)
    assert reports.status_code == 200
    assert reports.json()["data"]["items"][0]["prompt_name"].startswith("#")
    report_id = reports.json()["data"]["items"][0]["id"]

    assert (
        await client.post(
            "/api/v1/admin/prompts/reports/99999/resolve",
            headers=admin,
            json={"action": "hide"},
        )
    ).status_code == 404
    assert (
        await client.post(
            "/api/v1/admin/prompts/reports/batch-resolve",
            headers=admin,
            json={"report_ids": [99999], "action": "hide"},
        )
    ).status_code == 404
    assert (
        await client.post(
            "/api/v1/admin/prompts/reports/batch-resolve",
            headers=admin,
            json={"report_ids": [report_id], "action": "invalid"},
        )
    ).status_code == 400
    resolved = await client.post(
        f"/api/v1/admin/prompts/reports/{report_id}/resolve",
        headers=admin,
        json={"action": "reject"},
    )
    assert resolved.status_code == 200
    assert (
        await client.post(
            "/api/v1/admin/prompts/reports/batch-resolve",
            headers=admin,
            json={"report_ids": [report_id], "action": "hide"},
        )
    ).json()["data"]["processed"] == 0
