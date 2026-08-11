from __future__ import annotations

import pytest

from app.db.session import async_session
from app.models.ai_task import AITask
from app.models.copywriting import Copywriting
from app.models.dify_run_log import DifyRunLog
from app.models.dify_task import DifyTask
from app.models.dify_workflow import DifyWorkflowConfig
from app.models.project import Project
from app.models.user import User
from tests.conftest import make_auth_headers


@pytest.mark.asyncio
async def test_admin_resource_lists_details_fail_and_delete(client):
    async with async_session() as db:
        admin = User(id=1, username="admin", email="admin@example.com", hashed_password="x", role="admin")
        member = User(id=2, username="member", email="member@example.com", hashed_password="x", role="viewer")
        db.add_all([admin, member])
        workflow = DifyWorkflowConfig(
            id=10,
            api_key="key",
            app_name="工作流",
            app_type="workflow",
            created_by=admin.id,
        )
        db.add(workflow)
        project1 = Project(id=20, user_id=member.id, name="项目一", status="draft")
        project2 = Project(id=21, user_id=member.id, name="项目二", status="published")
        dify_task = DifyTask(
            id=30,
            workflow_id=workflow.id,
            user_id=member.id,
            task_id="upstream-30",
            status="failed",
            inputs={"topic": "汽车"},
            outputs={},
            error="failed",
            progress="80%",
        )
        ai_task = AITask(
            id=40,
            user_id=member.id,
            model_name="gptimage2",
            prompt="p" * 120,
            negative_prompt="bad",
            status="processing",
            result_urls=["https://img/1.png"],
            error="warning",
            params={
                "provider": {"name": "MentalOut", "provider_kind": "openai_images"},
                "upstream_debug": {
                    "captured_at": "2026-08-11T10:00:00",
                    "request": {"method": "POST", "url": "https://upstream/images"},
                    "response": {"status_code": 524},
                },
            },
        )
        completed_task = AITask(
            id=41,
            user_id=member.id,
            model_name="seedream",
            prompt="done",
            status="completed",
        )
        copy = Copywriting(id=50, title="零跑优惠", content="正文" * 120, category="零跑", created_by=member.id)
        db.add_all([project1, project2, dify_task, ai_task, completed_task, copy])
        await db.flush()
        db.add(DifyRunLog(
            workflow_id=workflow.id,
            user_id=member.id,
            task_id="upstream-30",
            status="failed",
            error="upstream error",
            inputs={"topic": "汽车"},
        ))
        await db.commit()
    headers = make_auth_headers(1)

    for path in (
        "/api/v1/admin/resources/workflow-tasks?username=missing",
        "/api/v1/admin/resources/projects?username=missing",
        "/api/v1/admin/resources/ai-tasks?username=missing",
        "/api/v1/admin/resources/copywritings?username=missing",
    ):
        response = await client.get(path, headers=headers)
        assert response.status_code == 200
        assert response.json()["data"]["total"] == 0

    workflow_list = await client.get(
        "/api/v1/admin/resources/workflow-tasks",
        params={"username": "member", "status": "failed", "workflow_id": 10},
        headers=headers,
    )
    assert workflow_list.json()["data"]["total"] == 1
    workflow_detail = await client.get("/api/v1/admin/resources/workflow-tasks/30", headers=headers)
    assert workflow_detail.status_code == 200
    assert workflow_detail.json()["data"]["logs"][0]["level"] == "error"
    assert (await client.get("/api/v1/admin/resources/workflow-tasks/99999", headers=headers)).status_code == 404

    projects = await client.get(
        "/api/v1/admin/resources/projects",
        params={"username": "member", "status": "published"},
        headers=headers,
    )
    assert projects.json()["data"]["total"] == 1
    assert (await client.delete("/api/v1/admin/resources/projects/99999", headers=headers)).status_code == 404
    assert (
        await client.post("/api/v1/admin/resources/projects/batch-delete", json={}, headers=headers)
    ).status_code == 400
    batch = await client.post(
        "/api/v1/admin/resources/projects/batch-delete",
        json={"project_ids": [20, 99999]},
        headers=headers,
    )
    assert batch.json()["data"]["deleted"] == 1
    assert (await client.delete("/api/v1/admin/resources/projects/21", headers=headers)).status_code == 200

    ai_list = await client.get(
        "/api/v1/admin/resources/ai-tasks",
        params={"username": "member", "status": "processing", "model_name": "gptimage2"},
        headers=headers,
    )
    assert ai_list.json()["data"]["total"] == 1
    ai_detail = await client.get("/api/v1/admin/resources/ai-tasks/40", headers=headers)
    logs = ai_detail.json()["data"]["logs"]
    assert {item["title"] for item in logs} == {
        "任务已创建",
        "任务处理中",
        "生成完成",
        "任务异常",
        "上游响应快照",
    }
    assert (await client.get("/api/v1/admin/resources/ai-tasks/99999", headers=headers)).status_code == 404
    assert (
        await client.post("/api/v1/admin/resources/ai-tasks/99999/fail", json={}, headers=headers)
    ).status_code == 404
    assert (
        await client.post("/api/v1/admin/resources/ai-tasks/41/fail", json={}, headers=headers)
    ).status_code == 400
    failed = await client.post(
        "/api/v1/admin/resources/ai-tasks/40/fail",
        json={"reason": "  管理员终止  "},
        headers=headers,
    )
    assert failed.status_code == 200
    assert failed.json()["data"]["status"] == "failed"

    copies = await client.get(
        "/api/v1/admin/resources/copywritings",
        params={"username": "member", "category": "零跑", "search": "优惠"},
        headers=headers,
    )
    assert copies.json()["data"]["total"] == 1
    assert len(copies.json()["data"]["items"][0]["content"]) == 200
    assert (await client.delete("/api/v1/admin/resources/copywritings/99999", headers=headers)).status_code == 404
    assert (await client.delete("/api/v1/admin/resources/copywritings/50", headers=headers)).status_code == 200
    assert (await client.delete("/api/v1/admin/resources/workflow-tasks/30", headers=headers)).status_code == 200
    assert (await client.delete("/api/v1/admin/resources/workflow-tasks/99999", headers=headers)).status_code == 404
