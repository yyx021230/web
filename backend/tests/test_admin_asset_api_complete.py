"""Administrative material and AI provider API lifecycle coverage."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from app.db.session import async_session
from app.models.ai_task import AITask
from app.models.material import Material
from app.models.user import User
from app.services.ai_image_provider_service import AIImageProviderService
from tests.conftest import make_auth_headers


async def _seed_admin_and_user() -> dict[str, str]:
    async with async_session() as db:
        db.add_all(
            [
                User(id=1, username="asset-admin", email="asset-admin@test.local", hashed_password="x", role="admin"),
                User(id=2, username="asset-user", email="asset-user@test.local", hashed_password="x", role="viewer"),
            ]
        )
        await db.commit()
    return make_auth_headers(1)


@pytest.mark.asyncio
async def test_admin_material_filters_templates_and_delete_paths(client):
    headers = await _seed_admin_and_user()
    async with async_session() as db:
        db.add_all(
            [
                Material(
                    id=10,
                    name="用户图片",
                    type="image",
                    url="/a.png",
                    width=768,
                    height=1024,
                    category="draft",
                    tags=["汽车"],
                    file_size=100,
                    created_by=2,
                ),
                Material(
                    id=11,
                    name="AI 模板",
                    type="image",
                    url="/template.png",
                    width=768,
                    height=1024,
                    category="ai-template",
                    ai_meta={"prompt": "模板"},
                    file_size=200,
                    created_by=2,
                ),
                Material(id=12, name="视频", type="video", url="/v.mp4", category="draft", created_by=2),
            ]
        )
        await db.commit()

    missing = await client.get(
        "/api/v1/admin/materials",
        params={"username": "missing"},
        headers=headers,
    )
    assert missing.status_code == 200
    assert missing.json()["data"]["total"] == 0

    filtered = await client.get(
        "/api/v1/admin/materials",
        params={"username": "asset-user", "category": "draft", "type": "image"},
        headers=headers,
    )
    assert filtered.status_code == 200
    assert [item["id"] for item in filtered.json()["data"]["items"]] == [10]
    assert filtered.json()["data"]["items"][0]["username"] == "asset-user"

    templates = await client.get("/api/v1/admin/materials/templates", headers=headers)
    assert templates.status_code == 200
    assert templates.json()["data"]["items"][0]["ai_meta"] == {"prompt": "模板"}

    assert (await client.post("/api/v1/admin/materials/batch-delete", json={}, headers=headers)).status_code == 400
    batch = await client.post(
        "/api/v1/admin/materials/batch-delete",
        json={"material_ids": [10, 99999]},
        headers=headers,
    )
    assert batch.status_code == 200
    assert batch.json()["data"]["deleted"] == 1
    assert (await client.delete("/api/v1/admin/materials/99999", headers=headers)).status_code == 404
    assert (await client.delete("/api/v1/admin/materials/12", headers=headers)).status_code == 200


@pytest.mark.asyncio
async def test_admin_ai_provider_update_health_test_and_missing_paths(client, monkeypatch):
    headers = await _seed_admin_and_user()
    create = await client.post(
        "/api/v1/admin/ai-image/providers",
        headers=headers,
        json={
            "name": "测试生图入口",
            "model_name": "gptimage2",
            "provider_kind": "openai_images",
            "provider_model": "gpt-image-2",
            "endpoint_url": "https://provider.test/v1",
            "api_key": "sk-provider-test",
            "is_enabled": True,
            "is_default": False,
            "priority": 20,
            "weight": 1,
            "supports_text_input": True,
            "supports_image_input": True,
            "config": {},
        },
    )
    assert create.status_code == 200
    provider_id = create.json()["data"]["id"]
    assert create.json()["data"]["api_key_prefix"] == "sk-provi..."

    updated = await client.put(
        f"/api/v1/admin/ai-image/providers/{provider_id}",
        headers=headers,
        json={"name": "新版入口", "priority": 5, "weight": 2},
    )
    assert updated.status_code == 200
    assert updated.json()["data"]["name"] == "新版入口"
    assert (await client.put("/api/v1/admin/ai-image/providers/99999", headers=headers, json={"name": "x"})).status_code == 404
    assert (await client.post("/api/v1/admin/ai-image/providers/99999/default", headers=headers)).status_code == 404
    assert (await client.post("/api/v1/admin/ai-image/providers/99999/enable", headers=headers, json={})).status_code == 404
    assert (await client.delete("/api/v1/admin/ai-image/providers/99999", headers=headers)).status_code == 404

    async def fake_health(self, item_id):
        return {
            "id": item_id,
            "healthy": item_id == provider_id,
            "status": "healthy" if item_id == provider_id else "failed",
            "error": None,
            "checked_at": "2026-08-11T12:00:00",
        }

    monkeypatch.setattr(AIImageProviderService, "health_check", fake_health)
    single = await client.post(
        f"/api/v1/admin/ai-image/providers/{provider_id}/health-check",
        headers=headers,
    )
    assert single.status_code == 200
    assert single.json()["data"]["healthy"] is True
    all_health = await client.post(
        "/api/v1/admin/ai-image/providers/health-check",
        params={"model_name": "gptimage2"},
        headers=headers,
    )
    assert all_health.status_code == 200
    assert any(item["id"] == provider_id for item in all_health.json()["data"])

    monkeypatch.setattr("app.api.v1.admin.ai_image._run_provider_test_task", AsyncMock())
    submitted = await client.post(
        f"/api/v1/admin/ai-image/providers/{provider_id}/test",
        headers=headers,
        json={
            "prompt": "测试汽车图片",
            "width": 768,
            "height": 1024,
            "count": 1,
            "quality": "high",
            "image_data": "data:image/png;base64,aGVsbG8=",
        },
    )
    assert submitted.status_code == 200
    task_id = submitted.json()["data"]["task_id"]
    async with async_session() as db:
        task = await db.get(AITask, int(task_id))
        assert task is not None
        assert task.params["image_data"].startswith("data:image/png;base64,")
        assert task.params["_provider_test_force_image_edit"] is True
    status = await client.get(
        f"/api/v1/admin/ai-image/providers/test-tasks/{task_id}",
        headers=headers,
    )
    assert status.status_code == 200
    assert status.json()["data"]["task_id"] == task_id
    assert (await client.get("/api/v1/admin/ai-image/providers/test-tasks/99999", headers=headers)).status_code == 404
    assert (
        await client.post(
            "/api/v1/admin/ai-image/providers/99999/test",
            headers=headers,
            json={"prompt": "missing", "width": 768, "height": 1024, "count": 1},
        )
    ).status_code == 404
