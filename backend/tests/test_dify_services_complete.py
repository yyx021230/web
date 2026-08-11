from __future__ import annotations

from datetime import datetime

import pytest

from app.db.session import async_session
from app.services.dify.dify_client import DifyClient
from app.services.dify.workflow_service import DifyWorkflowService


class _Response:
    def __init__(self, payload=None, *, status=200, text="", lines=None, json_error=False):
        self.payload = payload
        self.status_code = status
        self.text = text
        self.lines = lines or []
        self.json_error = json_error
        self.is_success = status < 400

    def json(self):
        if self.json_error:
            raise ValueError("bad json")
        return self.payload

    def raise_for_status(self):
        if not self.is_success:
            raise RuntimeError(f"HTTP {self.status_code}")

    async def aiter_lines(self):
        for line in self.lines:
            yield line


class _StreamContext:
    def __init__(self, response):
        self.response = response

    async def __aenter__(self):
        return self.response

    async def __aexit__(self, *args):
        return False


class _HTTPClient:
    responses = []
    calls = []

    def __init__(self, *args, **kwargs):
        self.timeout = kwargs.get("timeout")

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    @classmethod
    def reset(cls, *responses):
        cls.responses = list(responses)
        cls.calls = []

    def _next(self, method, url, kwargs):
        self.calls.append((method, url, kwargs))
        return self.responses.pop(0)

    async def post(self, url, **kwargs):
        return self._next("POST", url, kwargs)

    async def get(self, url, **kwargs):
        return self._next("GET", url, kwargs)

    def stream(self, method, url, **kwargs):
        return _StreamContext(self._next(method, url, kwargs))


@pytest.fixture
def mocked_http(monkeypatch):
    monkeypatch.setattr("app.services.dify.dify_client.httpx.AsyncClient", _HTTPClient)
    return _HTTPClient


@pytest.mark.asyncio
async def test_dify_client_blocking_streaming_and_errors(mocked_http):
    client = DifyClient("https://dify.example/v1/", "secret")
    assert client.base_url == "https://dify.example"
    assert client.headers["Authorization"] == "Bearer secret"

    mocked_http.reset(_Response({"data": {"outputs": {"answer": "ok"}}}))
    result = await client.run_workflow({"topic": "car"}, files=[{"id": "f1"}])
    assert result["data"]["outputs"]["answer"] == "ok"
    assert mocked_http.calls[0][1].endswith("/v1/workflows/run")
    assert mocked_http.calls[0][2]["json"]["response_mode"] == "blocking"

    mocked_http.reset(_Response(lines=["event: ping", "data: first", "data: second"]))
    stream = await client.run_workflow({}, streaming=True)
    assert [item async for item in stream] == ["first", "second"]

    mocked_http.reset(_Response({"message": "bad input"}, status=400))
    with pytest.raises(RuntimeError, match="bad input"):
        await client.chat("hello")
    mocked_http.reset(_Response(status=502, text="gateway failed", json_error=True))
    with pytest.raises(RuntimeError, match="gateway failed"):
        await client.completion({"prompt": "x"})


@pytest.mark.asyncio
async def test_dify_client_all_endpoint_helpers(mocked_http):
    client = DifyClient("https://dify.example", "key")
    mocked_http.reset(
        _Response({"answer": "chat"}),
        _Response(lines=["data: chat-stream"]),
        _Response({"text": "done"}),
        _Response(lines=["data: completion-stream"]),
        _Response({"parameters": []}),
        _Response({"name": "app"}),
        _Response({"id": "file-1"}),
        _Response({"result": "success"}),
        _Response({"data": []}),
    )
    assert (await client.chat("hi", conversation_id="conv"))["answer"] == "chat"
    chat_stream = await client.chat("hi", streaming=True)
    assert [item async for item in chat_stream] == ["chat-stream"]
    assert (await client.completion({"q": "x"}))["text"] == "done"
    completion_stream = await client.completion({}, streaming=True)
    assert [item async for item in completion_stream] == ["completion-stream"]
    assert await client.get_app_parameters() == {"parameters": []}
    assert await client.get_app_info() == {"name": "app"}
    assert (await client.upload_file(b"data", "a.png", "image/png"))["id"] == "file-1"
    assert (await client.stop_task("task-1"))["result"] == "success"
    assert await client.get_workflow_logs(page=2, limit=5, status="succeeded") == {"data": []}
    assert mocked_http.calls[-1][2]["params"] == {
        "page": 2,
        "limit": 5,
        "status": "succeeded",
    }


@pytest.mark.asyncio
async def test_dify_workflow_service_lifecycle_and_logs(client):
    async with async_session() as db:
        service = DifyWorkflowService(db)
        workflow = await service.create_workflow({
            "api_key": "key",
            "base_url": "https://dify.example/v1",
            "app_name": "内容工作流",
            "app_type": "workflow",
            "inputs_schema": {"topic": "string"},
            "created_by": 1,
        })
        listed = await service.list_workflows()
        assert [item.id for item in listed] == [workflow.id]
        dify_client, app_type = await service.get_client(workflow.id)
        assert dify_client.base_url == "https://dify.example"
        assert app_type == "workflow"
        with pytest.raises(ValueError, match="not found"):
            await service.get_client(99999)

        await service.save_run_log({
            "workflow_id": workflow.id,
            "user_id": 1,
            "inputs": {"topic": "汽车"},
            "outputs": {"text": "结果"},
            "status": "succeeded",
            "started_at": datetime(2026, 8, 11, 10, 0),
        })
        await service.save_run_log({
            "workflow_id": workflow.id,
            "user_id": 2,
            "status": "failed",
            "started_at": datetime(2026, 8, 11, 11, 0),
        })
        logs, total = await service.get_run_logs(workflow.id, page=1, limit=1)
        assert total == 2
        assert len(logs) == 1
        assert logs[0].status == "failed"
        assert await service.delete_workflow(99999) is False
        assert await service.delete_workflow(workflow.id) is True
