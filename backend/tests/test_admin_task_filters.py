"""Admin task/resource username filter tests."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.db.session import async_session
from app.models.ai_task import AITask
from app.models.dify_run_log import DifyRunLog
from app.models.dify_task import DifyTask
from app.models.dify_workflow import DifyWorkflowConfig
from app.models.material import Material
from app.models.user import User
from tests.conftest import make_auth_headers


CST = timezone(timedelta(hours=8))


def _now_cst_naive() -> datetime:
    return datetime.now(CST).replace(tzinfo=None)


def _cst_to_ai_utc_naive(value: datetime) -> datetime:
    return value - timedelta(hours=8)


async def _seed_admin_task_data() -> None:
    now = _now_cst_naive()
    async with async_session() as db:
        db.add_all([
            User(id=1, username="admin", email="admin@test.com", hashed_password="x", role="admin"),
            User(id=2, username="alice", email="alice@test.com", hashed_password="x", role="viewer"),
            User(id=3, username="bob", email="bob@test.com", hashed_password="x", role="viewer"),
        ])
        await db.flush()

        workflow = DifyWorkflowConfig(api_key="k", base_url="http://x", app_name="WF-A", app_type="workflow", created_by=1)
        db.add(workflow)
        await db.flush()

        db.add_all([
            AITask(
                user_id=2,
                model_name="seedream",
                prompt="a",
                status="completed",
                params={"provider": {"name": "DuckCoding GPT Image 2", "provider_kind": "openai_images"}},
                created_at=now,
            ),
            AITask(user_id=3, model_name="seedream", prompt="b", status="completed", created_at=now),
            DifyTask(workflow_id=workflow.id, user_id=2, status="succeeded", created_at=now),
            DifyTask(workflow_id=workflow.id, user_id=3, status="failed", created_at=now),
            DifyRunLog(workflow_id=workflow.id, user_id=2, status="succeeded", started_at=now),
            DifyRunLog(workflow_id=workflow.id, user_id=3, status="failed", started_at=now),
            Material(name="alice-mat", type="image", url="/a.png", created_by=2, file_size=100),
            Material(name="bob-mat", type="image", url="/b.png", created_by=3, file_size=200),
        ])
        await db.commit()


@pytest.mark.asyncio
async def test_unknown_username_returns_empty_for_admin_task_endpoints(client):
    await _seed_admin_task_data()
    headers = make_auth_headers(1)

    endpoints = [
        "/api/v1/admin/resources/workflow-tasks",
        "/api/v1/admin/resources/ai-tasks",
        "/api/v1/admin/workflows/tasks",
        "/api/v1/admin/workflows/logs",
        "/api/v1/admin/materials",
    ]
    for path in endpoints:
        resp = await client.get(path, params={"username": "nobody"}, headers=headers)
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["items"] == []
        assert data["total"] == 0


@pytest.mark.asyncio
async def test_exact_username_filter_only_returns_target_user_data(client):
    await _seed_admin_task_data()
    headers = make_auth_headers(1)

    workflow_tasks = await client.get("/api/v1/admin/workflows/tasks", params={"username": "alice"}, headers=headers)
    assert workflow_tasks.status_code == 200
    workflow_items = workflow_tasks.json()["data"]["items"]
    assert len(workflow_items) == 1
    assert workflow_items[0]["user_name"] == "alice"
    assert workflow_items[0]["workflow_name"] == "WF-A"

    ai_tasks = await client.get("/api/v1/admin/resources/ai-tasks", params={"username": "alice"}, headers=headers)
    assert ai_tasks.status_code == 200
    ai_items = ai_tasks.json()["data"]["items"]
    assert len(ai_items) == 1
    assert ai_items[0]["username"] == "alice"
    assert ai_items[0]["provider_name"] == "DuckCoding GPT Image 2"
    assert ai_items[0]["provider_kind"] == "openai_images"

    logs = await client.get("/api/v1/admin/workflows/logs", params={"username": "alice"}, headers=headers)
    assert logs.status_code == 200
    log_items = logs.json()["data"]["items"]
    assert len(log_items) == 1
    assert log_items[0]["user_name"] == "alice"

    materials = await client.get("/api/v1/admin/materials", params={"username": "alice"}, headers=headers)
    assert materials.status_code == 200
    mat_items = materials.json()["data"]["items"]
    assert len(mat_items) == 1
    assert mat_items[0]["username"] == "alice"


@pytest.mark.asyncio
async def test_admin_ai_tasks_created_at_returns_utc_iso_for_local_rendering(client):
    async with async_session() as db:
        db.add_all([
            User(id=1, username="admin", email="admin@test.com", hashed_password="x", role="admin"),
            User(id=2, username="alice", email="alice@test.com", hashed_password="x", role="viewer"),
        ])
        await db.flush()

        created_at_cst = datetime(2026, 5, 18, 16, 30, 45)
        db.add(
            AITask(
                user_id=2,
                model_name="gptimage2",
                prompt="time check",
                status="completed",
                created_at=_cst_to_ai_utc_naive(created_at_cst),
            )
        )
        await db.commit()

    resp = await client.get("/api/v1/admin/resources/ai-tasks", headers=make_auth_headers(1))
    assert resp.status_code == 200
    item = resp.json()["data"]["items"][0]
    assert item["created_at"] == "2026-05-18T08:30:45Z"
