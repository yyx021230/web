from __future__ import annotations

import asyncio
import pytest

from app.api.v1 import workflows as module
from app.db.session import async_session
from app.models.dify_run_log import DifyRunLog
from app.models.dify_task import DifyTask
from app.models.dify_workflow import DifyWorkflowConfig
from app.models.user import User
from app.models.user_workflow import user_workflow_access
from app.services.dify.workflow_service import DifyWorkflowService
from tests.conftest import make_auth_headers


async def _seed_users_and_workflows():
    async with async_session() as db:
        admin = User(id=1, username="admin", email="admin@example.com", hashed_password="x", role="admin")
        member = User(id=2, username="member", email="member@example.com", hashed_password="x", role="viewer")
        other = User(id=3, username="other", email="other@example.com", hashed_password="x", role="viewer")
        db.add_all([admin, member, other])
        await db.flush()
        workflow = DifyWorkflowConfig(
            id=10,
            api_key="1234567890",
            base_url="https://dify.example/v1",
            app_name="内容工作流",
            app_type="workflow",
            description="desc",
            inputs_schema={"topic": {"type": "text-input"}},
            is_enabled=True,
            created_by=admin.id,
        )
        disabled = DifyWorkflowConfig(
            id=11,
            api_key="1234567890",
            base_url="https://dify.example/v1",
            app_name="停用",
            app_type="chat",
            is_enabled=False,
            created_by=admin.id,
        )
        db.add_all([workflow, disabled])
        await db.flush()
        await db.execute(user_workflow_access.insert().values([
            {"user_id": member.id, "workflow_id": workflow.id},
            {"user_id": member.id, "workflow_id": disabled.id},
        ]))
        await db.commit()
        return admin, member, other, workflow


def test_parse_dify_params_old_flat_and_invalid_items():
    parsed = module._parse_dify_params({
        "user_input_form": [
            {"text-input": {"variable": "topic", "label": "主题", "required": True}},
            {"type": "select", "name": "style", "options": ["A", "B"], "default": "A"},
            {"text-input": "invalid"},
            "invalid",
            {"type": "ignored"},
        ]
    })
    assert parsed["topic"]["label"] == "主题"
    assert parsed["style"]["options"] == ["A", "B"]
    assert module._parse_dify_params({"parameters": []}) == {}
    assert module._get_workflow_lock(99) is module._get_workflow_lock(99)


@pytest.mark.asyncio
async def test_workflow_config_list_fetch_create_update_delete(client, monkeypatch):
    admin, member, _, workflow = await _seed_users_and_workflows()
    admin_headers = make_auth_headers(admin.id)
    member_headers = make_auth_headers(member.id)

    admin_list = await client.get("/api/v1/workflows", headers=admin_headers)
    assert [item["id"] for item in admin_list.json()["data"]] == [workflow.id]
    member_list = await client.get("/api/v1/workflows", headers=member_headers)
    assert [item["id"] for item in member_list.json()["data"]] == [workflow.id]

    assert (
        await client.post("/api/v1/workflows/fetch-params", json={}, headers=admin_headers)
    ).status_code == 400

    class _Client:
        def __init__(self, base_url, api_key):
            self.base_url = base_url
            self.api_key = api_key

        async def get_app_parameters(self):
            return {"parameters": [{"type": "text-input", "variable": "name", "required": True}]}

    monkeypatch.setattr(module, "DifyClient", _Client)
    fetched = await client.post(
        "/api/v1/workflows/fetch-params",
        json={"base_url": "https://dify", "api_key": "1234567890"},
        headers=admin_headers,
    )
    assert fetched.json()["data"]["inputs_schema"]["name"]["required"] is True

    created = await client.post(
        "/api/v1/workflows",
        json={
            "api_key": "1234567890",
            "base_url": "https://dify",
            "app_name": "新工作流",
            "app_type": "workflow",
            "inputs_schema": {"manual": {"type": "text-input"}},
        },
        headers=admin_headers,
    )
    assert created.status_code == 200
    created_id = created.json()["data"]["id"]
    auto_created = await client.post(
        "/api/v1/workflows",
        json={
            "api_key": "1234567890",
            "base_url": "https://dify",
            "app_name": "自动参数",
            "app_type": "workflow",
        },
        headers=admin_headers,
    )
    assert auto_created.status_code == 200

    updated = await client.put(
        f"/api/v1/workflows/{created_id}",
        json={"app_name": "已更新", "is_enabled": False},
        headers=admin_headers,
    )
    assert updated.status_code == 200
    assert (await client.put("/api/v1/workflows/99999", json={}, headers=admin_headers)).status_code == 404
    assert (await client.delete("/api/v1/workflows/99999", headers=admin_headers)).status_code == 404
    assert (await client.delete(f"/api/v1/workflows/{created_id}", headers=admin_headers)).status_code == 200


@pytest.mark.asyncio
async def test_workflow_tasks_queue_stop_view_delete_and_logs(client, monkeypatch):
    admin, member, other, workflow = await _seed_users_and_workflows()
    member_headers = make_auth_headers(member.id)
    admin_headers = make_auth_headers(admin.id)

    queued_tasks = []

    async def execute_task(workflow_id, task_id, inputs, user_id):
        queued_tasks.append((workflow_id, task_id, inputs, user_id))

    async def mirror(_task_id):
        return None

    monkeypatch.setattr(module, "_execute_queued_task", execute_task)
    monkeypatch.setattr(module, "mirror_dify_task_safely", mirror)
    monkeypatch.setattr(module, "detach_deleted_dify_task_safely", mirror)
    created = await client.post(
        f"/api/v1/workflows/{workflow.id}/tasks",
        json={"inputs": {"topic": "汽车"}},
        headers=member_headers,
    )
    assert created.status_code == 200
    queued_id = created.json()["data"]["task_id"]
    await asyncio.sleep(0)
    assert queued_tasks == [(workflow.id, queued_id, {"topic": "汽车"}, member.id)]

    async with async_session() as db:
        db.add_all([
            DifyTask(id=101, workflow_id=workflow.id, user_id=member.id, status="queued", inputs={}),
            DifyTask(id=102, workflow_id=workflow.id, user_id=member.id, status="running", inputs={}),
            DifyTask(id=103, workflow_id=workflow.id, user_id=member.id, status="succeeded", inputs={}),
            DifyTask(id=104, workflow_id=workflow.id, user_id=other.id, status="queued", inputs={}),
            DifyRunLog(workflow_id=workflow.id, user_id=member.id, status="succeeded", task_id="up-1"),
            DifyRunLog(workflow_id=workflow.id, user_id=other.id, status="failed", task_id="up-2"),
        ])
        await db.commit()

    tasks = await client.get("/api/v1/workflows/tasks", headers=member_headers)
    assert tasks.status_code == 200
    own_items = tasks.json()["data"]["items"]
    assert any(item["id"] == queued_id and item["queue_position"] is not None for item in own_items)

    assert (await client.post("/api/v1/workflows/tasks/99999/stop", headers=member_headers)).status_code == 404
    assert (await client.post("/api/v1/workflows/tasks/104/stop", headers=member_headers)).status_code == 403
    stopped = await client.post("/api/v1/workflows/tasks/101/stop", headers=member_headers)
    assert stopped.status_code == 200
    done_stop = await client.post("/api/v1/workflows/tasks/103/stop", headers=member_headers)
    assert "无法停止" in done_stop.json()["message"]

    assert (await client.patch("/api/v1/workflows/tasks/99999/view", headers=member_headers)).status_code == 404
    assert (await client.patch("/api/v1/workflows/tasks/104/view", headers=member_headers)).status_code == 403
    assert (await client.patch("/api/v1/workflows/tasks/104/view", headers=admin_headers)).status_code == 200
    assert (await client.patch("/api/v1/workflows/tasks/103/view", headers=member_headers)).status_code == 200

    assert (await client.delete("/api/v1/workflows/tasks/99999", headers=member_headers)).status_code == 404
    assert (await client.delete("/api/v1/workflows/tasks/104", headers=member_headers)).status_code == 403
    assert (await client.delete("/api/v1/workflows/tasks/102", headers=member_headers)).status_code == 400
    assert (await client.delete(f"/api/v1/workflows/tasks/{queued_id}", headers=member_headers)).status_code == 200
    assert (await client.delete("/api/v1/workflows/tasks/103", headers=member_headers)).status_code == 200

    own_logs = await client.get("/api/v1/workflows/logs", headers=member_headers)
    assert own_logs.json()["data"]["total"] == 1
    all_logs = await client.get("/api/v1/workflows/logs", headers=admin_headers)
    assert all_logs.json()["data"]["total"] == 2
    workflow_logs = await client.get(f"/api/v1/workflows/{workflow.id}/logs", headers=member_headers)
    assert workflow_logs.json()["data"]["total"] == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "app_type,result,expected",
    [
        ("workflow", {"workflow_run_id": "w1", "status": "succeeded", "data": {"outputs": {"text": "ok"}}}, "w1"),
        ("chat", {"message_id": "m1", "answer": "hello"}, "m1"),
        ("completion", {"message_id": "c1", "data": {"text": "done"}}, "c1"),
    ],
)
async def test_run_workflow_blocking_types(client, monkeypatch, app_type, result, expected):
    _, member, _, workflow = await _seed_users_and_workflows()
    headers = make_auth_headers(member.id)

    class _Dify:
        async def run_workflow(self, **kwargs):
            return result

        async def chat(self, **kwargs):
            return result

        async def completion(self, **kwargs):
            return result

    async def get_client(self, workflow_id):
        return _Dify(), app_type

    monkeypatch.setattr(DifyWorkflowService, "get_client", get_client)
    response = await client.post(
        f"/api/v1/workflows/{workflow.id}/run",
        json={"inputs": {"query": "hello"}, "response_mode": "blocking"},
        headers=headers,
    )
    assert response.status_code == 200
    assert response.json()["data"]["task_id"] == expected


@pytest.mark.asyncio
async def test_run_workflow_stream_chat_and_upload(client, monkeypatch):
    _, member, _, workflow = await _seed_users_and_workflows()
    headers = make_auth_headers(member.id)

    async def chunks():
        yield '{"event":"one"}'
        yield '{"event":"two"}'

    class _Dify:
        async def run_workflow(self, **kwargs):
            return chunks()

        async def chat(self, **kwargs):
            if kwargs.get("streaming"):
                return chunks()
            return {"answer": "chat-ok"}

        async def upload_file(self, **kwargs):
            return {"id": "file-1", "name": kwargs["filename"]}

    async def get_client(self, workflow_id):
        return _Dify(), "workflow"

    monkeypatch.setattr(DifyWorkflowService, "get_client", get_client)
    stream = await client.post(
        f"/api/v1/workflows/{workflow.id}/run",
        json={"inputs": {}, "response_mode": "streaming"},
        headers=headers,
    )
    assert stream.status_code == 200
    assert "event" in stream.text

    monkeypatch.setattr(module, "DifyClient", lambda **kwargs: _Dify())
    chat = await client.post(
        f"/api/v1/workflows/{workflow.id}/chat",
        json={"query": "hello", "inputs": {}},
        headers=headers,
    )
    assert chat.json()["data"]["answer"] == "chat-ok"
    stream_chat = await client.post(
        f"/api/v1/workflows/{workflow.id}/chat",
        json={"query": "hello", "response_mode": "streaming"},
        headers=headers,
    )
    assert "event" in stream_chat.text
    uploaded = await client.post(
        "/api/v1/workflows/files/upload",
        files={"file": ("data.txt", b"content", "text/plain")},
        headers=headers,
    )
    assert uploaded.json()["data"]["id"] == "file-1"


@pytest.mark.asyncio
async def test_run_workflow_errors_and_upload_without_config(client, monkeypatch):
    admin = User(id=1, username="admin", email="admin@example.com", hashed_password="x", role="admin")
    async with async_session() as db:
        db.add(admin)
        await db.commit()
    headers = make_auth_headers(1)
    no_upload = await client.post(
        "/api/v1/workflows/files/upload",
        files={"file": ("data.txt", b"content", "text/plain")},
        headers=headers,
    )
    assert no_upload.status_code == 400

    async def missing(self, workflow_id):
        raise ValueError("not found")

    monkeypatch.setattr(DifyWorkflowService, "get_client", missing)
    response = await client.post(
        "/api/v1/workflows/999/run",
        json={"inputs": {}, "response_mode": "blocking"},
        headers=headers,
    )
    assert response.status_code == 404

    async def broken(self, workflow_id):
        raise RuntimeError("network")

    monkeypatch.setattr(DifyWorkflowService, "get_client", broken)
    response = await client.post(
        "/api/v1/workflows/999/run",
        json={"inputs": {}, "response_mode": "blocking"},
        headers=headers,
    )
    assert response.status_code == 500
