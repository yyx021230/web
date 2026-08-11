from __future__ import annotations

import pytest

from app.db.session import async_session
from app.models.ai_task import AITask
from app.models.copywriting import Copywriting
from app.models.dify_run_log import DifyRunLog
from app.models.dify_task import DifyTask
from app.models.dify_workflow import DifyWorkflowConfig
from app.models.material import Material
from app.models.project import Project
from app.models.user import User
from tests.conftest import make_auth_headers


async def _seed_admin() -> User:
    async with async_session() as db:
        admin = User(
            username="admin",
            display_name="管理员",
            email="admin@example.com",
            hashed_password="hashed",
            role="admin",
        )
        db.add(admin)
        await db.commit()
        await db.refresh(admin)
        return admin


@pytest.mark.asyncio
async def test_admin_user_creation_validation_and_profile_roles(client):
    admin = await _seed_admin()
    headers = make_auth_headers(admin.id)

    assert (await client.post("/api/v1/admin/users", json={}, headers=headers)).status_code == 400
    assert (
        await client.post(
            "/api/v1/admin/users",
            json={
                "username": "invalid",
                "email": "invalid@example.com",
                "password": "password123",
                "roles": ["not-a-role"],
            },
            headers=headers,
        )
    ).status_code == 400

    created = await client.post(
        "/api/v1/admin/users",
        json={
            "username": "operator",
            "display_name": "运营一号",
            "email": "OPERATOR@EXAMPLE.COM",
            "password": "password123",
            "roles": ["xhs_ops", "xhs_buyer"],
        },
        headers=headers,
    )
    assert created.status_code == 200
    user_id = created.json()["data"]["id"]
    assert created.json()["data"]["roles"] == ["xhs_ops", "buyer"]
    assert created.json()["data"]["email"] == "operator@example.com"

    duplicate_username = await client.post(
        "/api/v1/admin/users",
        json={"username": "operator", "email": "other@example.com", "password": "password123"},
        headers=headers,
    )
    assert duplicate_username.status_code == 400
    duplicate_email = await client.post(
        "/api/v1/admin/users",
        json={"username": "other", "email": "operator@example.com", "password": "password123"},
        headers=headers,
    )
    assert duplicate_email.status_code == 400

    listed = await client.get("/api/v1/admin/users?page=1&limit=10", headers=headers)
    assert listed.status_code == 200
    assert listed.json()["data"]["total"] == 2

    assert (
        await client.patch(f"/api/v1/admin/users/{user_id}/profile", json={"display_name": "x" * 81}, headers=headers)
    ).status_code == 400
    profile = await client.patch(
        f"/api/v1/admin/users/{user_id}/profile",
        json={"display_name": "  新展示名  "},
        headers=headers,
    )
    assert profile.json()["data"]["display_name"] == "新展示名"
    cleared = await client.patch(
        f"/api/v1/admin/users/{user_id}/profile",
        json={"display_name": ""},
        headers=headers,
    )
    assert cleared.json()["data"]["display_name"] is None

    assert (
        await client.patch(f"/api/v1/admin/users/{user_id}/role", json={"role": "invalid"}, headers=headers)
    ).status_code == 400
    role = await client.patch(
        f"/api/v1/admin/users/{user_id}/role",
        json={"role": "viewer"},
        headers=headers,
    )
    assert role.json()["data"]["roles"] == ["viewer"]
    roles = await client.patch(
        f"/api/v1/admin/users/{user_id}/roles",
        json={"roles": ["xhs_ops", "xhs_buyer", "xhs_ops"]},
        headers=headers,
    )
    assert roles.status_code == 200
    assert set(roles.json()["data"]["roles"]) == {"xhs_ops", "buyer"}
    assert (
        await client.patch(f"/api/v1/admin/users/{user_id}/roles", json={"roles": ["bad"]}, headers=headers)
    ).status_code == 400

    for endpoint in ("role", "profile", "roles", "active"):
        response = await client.patch(
            f"/api/v1/admin/users/99999/{endpoint}",
            json={"role": "viewer", "roles": ["viewer"], "is_active": True},
            headers=headers,
        )
        assert response.status_code == 404


@pytest.mark.asyncio
async def test_admin_user_workflows_stats_detail_activation_and_deletion(client):
    admin = await _seed_admin()
    headers = make_auth_headers(admin.id)

    async with async_session() as db:
        user = User(
            username="member",
            email="member@example.com",
            hashed_password="hashed",
            role="viewer",
        )
        db.add(user)
        await db.flush()
        workflow = DifyWorkflowConfig(
            api_key="key",
            base_url="https://dify.example",
            app_name="工作流",
            app_type="workflow",
            description="desc",
            created_by=user.id,
        )
        db.add(workflow)
        await db.flush()
        db.add_all([
            Project(user_id=user.id, name="项目"),
            Material(name="素材", type="image", created_by=user.id, file_size=2 * 1024 * 1024),
            AITask(user_id=user.id, model_name="seedream", prompt="prompt", status="completed"),
            DifyTask(workflow_id=workflow.id, user_id=user.id, status="succeeded"),
            DifyRunLog(workflow_id=workflow.id, user_id=user.id, status="succeeded"),
            Copywriting(title="文案", content="内容", created_by=user.id),
        ])
        await db.commit()
        user_id = user.id
        workflow_id = workflow.id

    missing_workflows = await client.get("/api/v1/admin/users/99999/workflows", headers=headers)
    assert missing_workflows.status_code == 404
    assert (
        await client.post("/api/v1/admin/users/99999/workflows", json={"workflow_ids": []}, headers=headers)
    ).status_code == 404
    assigned = await client.post(
        f"/api/v1/admin/users/{user_id}/workflows",
        json={"workflow_ids": [workflow_id, 99999]},
        headers=headers,
    )
    assert assigned.json()["data"]["workflows"] == [workflow_id]
    workflows = await client.get(f"/api/v1/admin/users/{user_id}/workflows", headers=headers)
    assert workflows.json()["data"][0]["app_name"] == "工作流"

    stats = await client.get(f"/api/v1/admin/users/{user_id}/stats", headers=headers)
    assert stats.json()["data"] == {
        "ai_tasks": 1,
        "wf_tasks": 1,
        "projects": 1,
        "storage_mb": 2.0,
    }
    detail = await client.get(f"/api/v1/admin/users/{user_id}/detail", headers=headers)
    assert detail.status_code == 200
    assert detail.json()["data"]["stats"]["copywriting_count"] == 1
    assert len(detail.json()["data"]["recent_ai_tasks"]) == 1
    assert len(detail.json()["data"]["recent_dify_tasks"]) == 1
    assert (await client.get("/api/v1/admin/users/99999/detail", headers=headers)).status_code == 404

    assert (
        await client.post("/api/v1/admin/users/batch-delete-tasks", json={}, headers=headers)
    ).status_code == 400
    assert (
        await client.post(
            "/api/v1/admin/users/batch-delete-tasks",
            json={"user_id": user_id, "type": "invalid"},
            headers=headers,
        )
    ).status_code == 400
    assert (
        await client.post(
            "/api/v1/admin/users/batch-delete-tasks",
            json={"user_id": user_id, "type": "ai"},
            headers=headers,
        )
    ).status_code == 200
    assert (
        await client.post(
            "/api/v1/admin/users/batch-delete-tasks",
            json={"user_id": user_id, "type": "workflow"},
            headers=headers,
        )
    ).status_code == 200

    assert (
        await client.patch(f"/api/v1/admin/users/{admin.id}/active", json={"is_active": False}, headers=headers)
    ).status_code == 400
    active = await client.patch(
        f"/api/v1/admin/users/{user_id}/active",
        json={"is_active": False},
        headers=headers,
    )
    assert active.json()["data"]["is_active"] is False

    assert (await client.delete("/api/v1/admin/users/99999", headers=headers)).status_code == 404
    assert (await client.delete(f"/api/v1/admin/users/{admin.id}", headers=headers)).status_code == 400
    deleted = await client.delete(f"/api/v1/admin/users/{user_id}", headers=headers)
    assert deleted.status_code == 200
