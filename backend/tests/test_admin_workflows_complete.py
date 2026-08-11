from __future__ import annotations

import asyncio
from datetime import datetime, timedelta

import pytest
from app.api.v1.admin import workflows as module
from app.db.session import async_session
from app.models.dify_run_log import DifyRunLog
from app.models.dify_task import DifyTask
from app.models.dify_workflow import DifyWorkflowConfig
from app.models.user import User
from app.services.dify.workflow_service import DifyWorkflowService
from tests.conftest import make_auth_headers


async def _seed_admin_workflow(*, app_type: str = "workflow"):
    async with async_session() as db:
        admin = User(id=1, username="admin", email="admin@example.com", hashed_password="x", role="admin")
        member = User(id=2, username="member", email="member@example.com", hashed_password="x")
        db.add_all([admin, member])
        await db.flush()
        workflow = DifyWorkflowConfig(
            id=10,
            api_key="1234567890",
            base_url="https://dify.example/v1",
            app_name="内容生产",
            app_type=app_type,
            inputs_schema={"topic": {"type": "text-input"}},
            description="description",
            created_by=admin.id,
            is_enabled=True,
        )
        db.add(workflow)
        await db.commit()
    return admin, member, workflow


def test_admin_workflow_parameter_parser_and_empty_user_resolution():
    assert module._parse_dify_params({"variables": [{"text-input": {"name": "topic"}}]})["topic"]["type"] == "text-input"
    assert module._parse_dify_params({"inputs": [{"type": "select", "variable": "style"}]})["style"]["label"] == "style"


@pytest.mark.asyncio
async def test_admin_workflow_crud_search_fetch_and_validation(client, monkeypatch):
    admin, _, workflow = await _seed_admin_workflow()
    headers = make_auth_headers(admin.id)
    listed = await client.get("/api/v1/admin/workflows?search=内容&created_by=1", headers=headers)
    assert listed.status_code == 200
    item = listed.json()["data"]["items"][0]
    assert item["created_by_name"] == "admin"
    assert item["api_key_prefix"] == "12345678..."
    assert (await client.get("/api/v1/admin/workflows?search=不存在", headers=headers)).json()["data"]["total"] == 0
    assert (await client.post("/api/v1/admin/workflows/fetch-params", json={}, headers=headers)).status_code == 400

    class _Client:
        def __init__(self, base_url, api_key):
            self.base_url = base_url
            self.api_key = api_key

        async def get_app_parameters(self):
            return {"parameters": [{"type": "text-input", "variable": "name", "required": True}]}

    monkeypatch.setattr(module, "DifyClient", _Client)
    fetched = await client.post(
        "/api/v1/admin/workflows/fetch-params",
        json={"api_key": "1234567890", "base_url": "https://dify"},
        headers=headers,
    )
    assert fetched.json()["data"]["inputs_schema"]["name"]["required"] is True

    explicit = await client.post(
        "/api/v1/admin/workflows",
        json={
            "api_key": "1234567890",
            "base_url": "https://dify",
            "app_name": "手动参数",
            "app_type": "workflow",
            "inputs_schema": {"manual": {"type": "text-input"}},
        },
        headers=headers,
    )
    assert explicit.status_code == 200
    explicit_id = explicit.json()["data"]["id"]
    automatic = await client.post(
        "/api/v1/admin/workflows",
        json={"api_key": "1234567890", "base_url": "https://dify", "app_name": "自动参数", "app_type": "workflow"},
        headers=headers,
    )
    assert automatic.status_code == 200

    class _BrokenClient(_Client):
        async def get_app_parameters(self):
            raise RuntimeError("Dify offline")

    monkeypatch.setattr(module, "DifyClient", _BrokenClient)
    broken = await client.post(
        "/api/v1/admin/workflows",
        json={"api_key": "1234567890", "app_name": "失败", "app_type": "workflow"},
        headers=headers,
    )
    assert broken.status_code == 400

    updated = await client.put(
        f"/api/v1/admin/workflows/{explicit_id}",
        json={"app_name": "已更新", "is_enabled": False},
        headers=headers,
    )
    assert updated.status_code == 200
    assert (await client.put("/api/v1/admin/workflows/999", json={}, headers=headers)).status_code == 404
    assert (await client.delete("/api/v1/admin/workflows/999", headers=headers)).status_code == 404
    assert (await client.delete(f"/api/v1/admin/workflows/{explicit_id}", headers=headers)).status_code == 200
    assert workflow.id == 10


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "app_type,result,expected_status,expected_task",
    [
        ("workflow", {"workflow_run_id": "w1", "data": {"outputs": {"text": "ok"}}}, "succeeded", "w1"),
        ("chat", {"message_id": "m1", "answer": "hello"}, "succeeded", "m1"),
        ("completion", {"message_id": "c1", "data": ["value"], "error": "failed"}, "failed", "c1"),
    ],
)
async def test_admin_run_workflow_types(client, monkeypatch, app_type, result, expected_status, expected_task):
    admin, _, workflow = await _seed_admin_workflow(app_type=app_type)
    headers = make_auth_headers(admin.id)

    class _Client:
        async def run_workflow(self, **kwargs):
            return result

        async def chat(self, **kwargs):
            assert kwargs["query"] == "问题"
            return result

        async def completion(self, **kwargs):
            return result

    async def get_client(self, workflow_id):
        return _Client(), app_type

    monkeypatch.setattr(DifyWorkflowService, "get_client", get_client)
    response = await client.post(
        f"/api/v1/admin/workflows/{workflow.id}/run",
        json={"inputs": {"query": "问题"}},
        headers=headers,
    )
    assert response.status_code == 200
    assert response.json()["data"]["status"] == expected_status
    assert response.json()["data"]["task_id"] == expected_task


@pytest.mark.asyncio
async def test_admin_run_workflow_maps_value_and_server_errors(client, monkeypatch):
    admin, _, workflow = await _seed_admin_workflow()
    headers = make_auth_headers(admin.id)

    async def not_found(self, workflow_id):
        raise ValueError("工作流不存在")

    monkeypatch.setattr(DifyWorkflowService, "get_client", not_found)
    assert (
        await client.post(f"/api/v1/admin/workflows/{workflow.id}/run", json={"inputs": {}}, headers=headers)
    ).status_code == 404

    async def offline(self, workflow_id):
        raise RuntimeError("offline")

    monkeypatch.setattr(DifyWorkflowService, "get_client", offline)
    assert (
        await client.post(f"/api/v1/admin/workflows/{workflow.id}/run", json={"inputs": {}}, headers=headers)
    ).status_code == 500

    class _Client:
        async def run_workflow(self, **kwargs):
            return {"task_id": "plain", "outputs": "plain-output"}

    async def unsupported(self, workflow_id):
        return _Client(), "unsupported"

    monkeypatch.setattr(DifyWorkflowService, "get_client", unsupported)
    assert (
        await client.post(f"/api/v1/admin/workflows/{workflow.id}/run", json={"inputs": {}}, headers=headers)
    ).status_code == 404


@pytest.mark.asyncio
async def test_admin_background_task_runs_for_requested_user(client, monkeypatch):
    admin, member, workflow = await _seed_admin_workflow()
    headers = make_auth_headers(admin.id)
    mirrored = []

    async def mirror(task_id):
        mirrored.append(task_id)

    class _Client:
        def __init__(self, base_url, api_key):
            self.base_url = base_url
            self.api_key = api_key

        async def run_workflow(self, **kwargs):
            return {"workflow_run_id": "remote-1", "data": {"outputs": {"text": "done"}}}

    monkeypatch.setattr(module, "mirror_dify_task_safely", mirror)
    monkeypatch.setattr("app.services.dify.dify_client.DifyClient", _Client)
    assert (
        await client.post(
            f"/api/v1/admin/workflows/{workflow.id}/tasks",
            json={"user_id": "bad", "inputs": {}},
            headers=headers,
        )
    ).status_code == 400
    assert (
        await client.post(
            f"/api/v1/admin/workflows/{workflow.id}/tasks",
            json={"user_id": 999, "inputs": {}},
            headers=headers,
        )
    ).status_code == 400
    created = await client.post(
        f"/api/v1/admin/workflows/{workflow.id}/tasks",
        json={"user_id": member.id, "inputs": {"topic": "汽车"}},
        headers=headers,
    )
    assert created.status_code == 200
    task_id = created.json()["data"]["task_id"]
    for _ in range(50):
        await asyncio.sleep(0.01)
        async with async_session() as db:
            task = await db.get(DifyTask, task_id)
            if task and task.status == "succeeded":
                break
    assert task.user_id == member.id
    assert task.task_id == "remote-1"
    assert task.outputs == {"text": "done"}
    assert len(mirrored) >= 3


@pytest.mark.asyncio
async def test_admin_task_and_log_lifecycle_filters(client, monkeypatch):
    admin, member, workflow = await _seed_admin_workflow()
    headers = make_auth_headers(admin.id)
    now = datetime(2026, 8, 1, 12)
    async with async_session() as db:
        db.add_all(
            [
                DifyTask(
                    id=101,
                    workflow_id=workflow.id,
                    user_id=member.id,
                    status="pending",
                    created_at=now + timedelta(days=1),
                ),
                DifyTask(id=102, workflow_id=workflow.id, user_id=member.id, status="running", created_at=now),
                DifyTask(id=103, workflow_id=workflow.id, user_id=member.id, status="succeeded", created_at=now),
                DifyTask(
                    id=104,
                    workflow_id=workflow.id,
                    user_id=member.id,
                    task_id="remote-running",
                    status="running",
                    created_at=now,
                ),
                DifyRunLog(
                    id=201,
                    workflow_id=workflow.id,
                    user_id=member.id,
                    task_id="remote-running",
                    status="running",
                    started_at=now,
                ),
                DifyRunLog(
                    id=202,
                    workflow_id=workflow.id,
                    user_id=member.id,
                    task_id="done",
                    status="succeeded",
                    started_at=now,
                    finished_at=now,
                ),
            ]
        )
        await db.commit()

    async def noop(_task_id):
        return None

    monkeypatch.setattr(module, "mirror_dify_task_safely", noop)
    monkeypatch.setattr(module, "detach_deleted_dify_task_safely", noop)
    listed = await client.get(
        f"/api/v1/admin/workflows/tasks?username=member&workflow_id={workflow.id}&status=running",
        headers=headers,
    )
    assert listed.status_code == 200
    assert len(listed.json()["data"]["items"]) == 2
    assert (await client.get("/api/v1/admin/workflows/tasks?username=unknown", headers=headers)).json()["data"]["total"] == 0

    assert (await client.patch("/api/v1/admin/workflows/tasks/999/view", headers=headers)).status_code == 404
    assert (await client.patch("/api/v1/admin/workflows/tasks/103/view", headers=headers)).status_code == 200
    assert (await client.delete("/api/v1/admin/workflows/tasks/999", headers=headers)).status_code == 404
    assert (await client.delete("/api/v1/admin/workflows/tasks/101", headers=headers)).status_code == 400
    assert (await client.delete("/api/v1/admin/workflows/tasks/103", headers=headers)).status_code == 200

    assert (await client.post("/api/v1/admin/workflows/tasks/999/fail", headers=headers)).status_code == 404
    already_done = await client.post("/api/v1/admin/workflows/tasks/101/fail", headers=headers)
    assert already_done.status_code == 200
    assert already_done.json()["data"]["status"] == "failed"
    assert (await client.post("/api/v1/admin/workflows/tasks/101/fail", headers=headers)).status_code == 400
    failed = await client.post(
        "/api/v1/admin/workflows/tasks/104/fail",
        json={"reason": "人工终止"},
        headers=headers,
    )
    assert failed.status_code == 200
    async with async_session() as db:
        run_log = await db.get(DifyRunLog, 201)
        assert run_log.status == "failed"
        assert run_log.error == "人工终止"

    logs = await client.get(
        f"/api/v1/admin/workflows/logs?username=member&workflow_id={workflow.id}&status=succeeded",
        headers=headers,
    )
    assert logs.status_code == 200
    assert logs.json()["data"]["items"][0]["user_name"] == "member"
    assert (await client.get("/api/v1/admin/workflows/logs?username=unknown", headers=headers)).json()["data"]["total"] == 0
