from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from sqlalchemy import select

from app.models.ai_image_provider import AIImageProvider
from app.db.session import async_session
from app.core.security import create_access_token
from app.models.ai_task import AITask
from app.models.user import User
from app.services.ai_image_service import AIImageService
from app.services.ai_task_queue import ai_image_task_queue
from app.scripts.ai_worker import AIImageWorker


@pytest.mark.asyncio
async def test_cleanup_stale_ai_tasks_marks_only_old_processing_tasks_failed(client):
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    stale_at = now - timedelta(minutes=45)
    fresh_at = now - timedelta(minutes=5)

    async with async_session() as db:
        db.add(User(id=1, username="stale_user", email="stale@example.com", hashed_password="x"))
        db.add_all([
            AITask(id=101, user_id=1, model_name="gptimage2", prompt="old queued", status="queued", created_at=stale_at),
            AITask(id=102, user_id=1, model_name="gptimage2", prompt="old processing", status="processing", created_at=stale_at),
            AITask(id=103, user_id=1, model_name="gptimage2", prompt="fresh", status="processing", created_at=fresh_at),
            AITask(
                id=104,
                user_id=1,
                model_name="gptimage2",
                prompt="queued long then started",
                status="processing",
                created_at=stale_at,
                params={"_processing_started_at": fresh_at.isoformat()},
            ),
        ])
        await db.commit()

        service = AIImageService(db=db)
        recovered = await service.cleanup_stale_tasks(stale_after_minutes=30)
        assert recovered == 1

        result = await db.execute(
            select(AITask).where(AITask.id.in_([101, 102, 103, 104]))
        )
        rows = {row.id: row for row in result.scalars().all()}
        assert rows[101].status == "queued"
        assert rows[102].status == "failed"
        assert rows[103].status == "processing"
        assert rows[104].status == "processing"
        assert rows[101].error is None
        assert rows[102].finished_at is not None


@pytest.mark.asyncio
async def test_generate_does_not_fallback_when_configured_provider_fails(client, monkeypatch):
    async with async_session() as db:
        db.add(User(id=2, username="fallback_user", email="fallback@example.com", hashed_password="x"))
        db.add(AIImageProvider(
            name="MentalOut GPT Image 2（旧入口）",
            model_name="gptimage2",
            provider_kind="mentalout_batch",
            provider_model="gpt-image-2",
            endpoint_url="https://image.mentalout.top",
            api_key="sk-test",
            is_enabled=True,
            is_default=True,
            supports_text_input=True,
            supports_image_input=True,
            config={"api_base_url": "https://chunfeng.mentalout.top/v1"},
        ))
        await db.commit()

        async def fake_provider_generate(
            self,
            prompt,
            params,
            user_id=None,
            model_name="gptimage2",
            on_provider_selected=None,
        ):
            return {
                "task_id": "",
                "status": "failed",
                "image_urls": [],
                "error": "provider failed",
                "provider_configured": True,
                "provider": None,
            }

        async def fake_adapter_generate(self, prompt, **params):
            return {
                "task_id": "adapter-ok",
                "status": "completed",
                "image_urls": ["/uploads/ai-images/fallback.png"],
                "error": None,
            }

        monkeypatch.setattr("app.services.ai_image_provider_service.AIImageProviderService.generate", fake_provider_generate)
        monkeypatch.setattr("app.adapters.ai_model.gptimage2.GPTImage2Adapter.generate_image", fake_adapter_generate)

        service = AIImageService(model_name="gptimage2", db=db)
        result = await service.generate("fallback prompt", {"width": 1024, "height": 1024}, user_id=2)

        assert result["status"] == "failed"
        assert result["error"] == "provider failed"
        assert result["image_urls"] == []


def test_normalize_failed_result_fills_missing_error():
    service = AIImageService(model_name="gptimage2")
    result = service._normalize_failed_result({
        "task_id": "",
        "status": "failed",
        "image_urls": [],
        "error": None,
    })
    assert result["error"] == "上游返回失败，但没有提供错误详情"


@pytest.mark.asyncio
async def test_submit_enqueues_task_in_redis_queue(client, monkeypatch):
    queued_task_ids: list[int] = []

    async def fake_enqueue_task(task_id: int) -> bool:
        queued_task_ids.append(task_id)
        return True

    monkeypatch.setattr(ai_image_task_queue, "enqueue_task", fake_enqueue_task)

    async with async_session() as db:
        db.add(User(id=3, username="queue_user", email="queue@example.com", hashed_password="x"))
        await db.commit()

        service = AIImageService(model_name="gptimage2", db=db)
        result = await service.submit("queued prompt", {"width": 1024, "height": 1024}, user_id=3)

        assert result["status"] == "queued"
        assert result["task_id"].isdigit()
        assert queued_task_ids == [int(result["task_id"])]

        stored = await db.execute(select(AITask).where(AITask.id == int(result["task_id"])))
        task = stored.scalar_one_or_none()
        assert task is not None
        assert task.status == "queued"
        assert task.prompt == "queued prompt"


@pytest.mark.asyncio
async def test_submit_with_client_request_id_is_idempotent_for_same_user(client, monkeypatch):
    queued_task_ids: list[int] = []

    async def fake_enqueue_task(task_id: int) -> bool:
        queued_task_ids.append(task_id)
        return True

    monkeypatch.setattr(ai_image_task_queue, "enqueue_task", fake_enqueue_task)

    async with async_session() as db:
        db.add(User(id=4, username="idempotent_user", email="idempotent@example.com", hashed_password="x"))
        await db.commit()

        service = AIImageService(model_name="gptimage2", db=db)
        first = await service.submit(
            "idempotent prompt",
            {"width": 1024, "height": 1024},
            user_id=4,
            client_request_id="client-req-1",
        )
        second = await service.submit(
            "idempotent prompt retry",
            {"width": 2048, "height": 2048},
            user_id=4,
            client_request_id="client-req-1",
        )

        assert first["task_id"] == second["task_id"]
        assert first["client_request_id"] == "client-req-1"
        assert queued_task_ids == [int(first["task_id"])]

        stored = await db.execute(select(AITask).where(AITask.user_id == 4))
        tasks = list(stored.scalars().all())
        assert len(tasks) == 1
        assert tasks[0].prompt == "idempotent prompt"


@pytest.mark.asyncio
async def test_submit_with_same_client_request_id_allows_different_users(client, monkeypatch):
    queued_task_ids: list[int] = []

    async def fake_enqueue_task(task_id: int) -> bool:
        queued_task_ids.append(task_id)
        return True

    monkeypatch.setattr(ai_image_task_queue, "enqueue_task", fake_enqueue_task)

    async with async_session() as db:
        db.add_all([
            User(id=41, username="idempotent_a", email="idempotent-a@example.com", hashed_password="x"),
            User(id=42, username="idempotent_b", email="idempotent-b@example.com", hashed_password="x"),
        ])
        await db.commit()

        service = AIImageService(model_name="gptimage2", db=db)
        first = await service.submit(
            "user a prompt",
            {"width": 1024, "height": 1024},
            user_id=41,
            client_request_id="shared-client-req",
        )
        second = await service.submit(
            "user b prompt",
            {"width": 1024, "height": 1024},
            user_id=42,
            client_request_id="shared-client-req",
        )

        assert first["task_id"] != second["task_id"]
        assert len(queued_task_ids) == 2


@pytest.mark.asyncio
async def test_get_task_by_client_request_id_is_scoped_to_user(client):
    async with async_session() as db:
        db.add_all([
            User(id=51, username="recover_a", email="recover-a@example.com", hashed_password="x"),
            User(id=52, username="recover_b", email="recover-b@example.com", hashed_password="x"),
        ])
        db.add(AITask(
            id=351,
            user_id=51,
            client_request_id="recover-req",
            model_name="gptimage2",
            prompt="recover prompt",
            status="completed",
            result_urls=["/uploads/ai-images/recovered.png"],
        ))
        await db.commit()

        service = AIImageService(model_name="gptimage2", db=db)
        found = await service.get_task_by_client_request_id(51, "recover-req")
        missing = await service.get_task_by_client_request_id(52, "recover-req")

        assert found is not None
        assert found["task_id"] == "351"
        assert found["status"] == "completed"
        assert found["image_urls"] == ["/uploads/ai-images/recovered.png"]
        assert missing is None


@pytest.mark.asyncio
async def test_submit_rejects_seventh_active_user_task(client):
    async with async_session() as db:
        db.add(User(id=6, username="limit_user", email="limit@example.com", hashed_password="x"))
        db.add_all([
            AITask(id=301, user_id=6, model_name="gptimage2", prompt="queued 1", status="queued"),
            AITask(id=302, user_id=6, model_name="gptimage2", prompt="queued 2", status="queued"),
            AITask(id=303, user_id=6, model_name="gptimage2", prompt="processing", status="processing"),
            AITask(id=304, user_id=6, model_name="gptimage2", prompt="queued 4", status="queued"),
            AITask(id=305, user_id=6, model_name="gptimage2", prompt="queued 5", status="queued"),
            AITask(id=306, user_id=6, model_name="gptimage2", prompt="processing 6", status="processing"),
        ])
        await db.commit()

        service = AIImageService(model_name="gptimage2", db=db)
        with pytest.raises(ValueError, match="最多同时提交 6 个生图任务"):
            await service.submit("seventh prompt", {"width": 1024, "height": 1024}, user_id=6)


@pytest.mark.asyncio
async def test_get_active_tasks_returns_user_active_count(client):
    async with async_session() as db:
        db.add(User(id=8, username="active_user", email="active@example.com", hashed_password="x"))
        db.add_all([
            AITask(id=321, user_id=8, model_name="gptimage2", prompt="queued", status="queued"),
            AITask(id=322, user_id=8, model_name="gptimage2", prompt="processing", status="processing"),
            AITask(id=323, user_id=8, model_name="gptimage2", prompt="done", status="completed"),
            AITask(id=324, user_id=99, model_name="gptimage2", prompt="other user", status="processing"),
        ])
        await db.commit()

        service = AIImageService(model_name="gptimage2", db=db)
        result = await service.get_active_tasks(8)

        assert result["active_count"] == 2
        assert result["max_active"] == 6
        assert result["can_submit"] is True
        assert [item["id"] for item in result["items"]] == [321, 322]


@pytest.mark.asyncio
async def test_active_tasks_endpoint_returns_current_user_active_tasks(client):
    async with async_session() as db:
        db.add(User(id=9, username="active_api_user", email="active-api@example.com", hashed_password="x"))
        db.add_all([
            AITask(id=331, user_id=9, model_name="gptimage2", prompt="queued", status="queued"),
            AITask(id=332, user_id=9, model_name="seedream", prompt="processing", status="processing"),
            AITask(id=333, user_id=9, model_name="gptimage2", prompt="failed", status="failed"),
        ])
        await db.commit()

    token = create_access_token(subject="9")
    resp = await client.get(
        "/api/v1/ai-image/active",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["active_count"] == 2
    assert data["max_active"] == 6
    assert data["can_submit"] is True
    assert [item["task_id"] for item in data["items"]] == ["331", "332"]


@pytest.mark.asyncio
async def test_request_recovery_endpoint_returns_only_current_user_task(client):
    async with async_session() as db:
        db.add_all([
            User(id=91, username="request_owner", email="request-owner@example.com", hashed_password="x"),
            User(id=92, username="request_other", email="request-other@example.com", hashed_password="x"),
        ])
        db.add(AITask(
            id=391,
            user_id=91,
            client_request_id="frontend-req-1",
            model_name="gptimage2",
            prompt="recover by api",
            status="completed",
            result_urls=["/uploads/ai-images/api-recovered.png"],
        ))
        await db.commit()

    owner_resp = await client.get(
        "/api/v1/ai-image/requests/frontend-req-1",
        headers={"Authorization": f"Bearer {create_access_token(subject='91')}"},
    )
    assert owner_resp.status_code == 200
    assert owner_resp.json()["data"]["task_id"] == "391"
    assert owner_resp.json()["data"]["client_request_id"] == "frontend-req-1"

    other_resp = await client.get(
        "/api/v1/ai-image/requests/frontend-req-1",
        headers={"Authorization": f"Bearer {create_access_token(subject='92')}"},
    )
    assert other_resp.status_code == 404


@pytest.mark.asyncio
async def test_runtime_config_endpoint_returns_backend_timeout(client):
    resp = await client.get("/api/v1/ai-image/runtime-config")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["task_timeout_seconds"] >= 60
    assert data["poll_interval_seconds"] == 2


@pytest.mark.asyncio
async def test_execute_submitted_task_persists_provider_when_selected(client, monkeypatch):
    async with async_session() as db:
        db.add(User(id=10, username="provider_user", email="provider@example.com", hashed_password="x"))
        db.add(AIImageProvider(
            id=401,
            name="GPT Image 2 直连 A",
            model_name="gptimage2",
            provider_kind="openai_images",
            provider_model="gpt-image-2",
            endpoint_url="https://api.example.com/v1",
            api_key="sk-test",
            is_enabled=True,
            is_default=True,
            supports_text_input=True,
            supports_image_input=True,
        ))
        db.add(AITask(
            id=341,
            user_id=10,
            model_name="gptimage2",
            prompt="provider prompt",
            params={"width": 1024, "height": 1024},
            status="queued",
        ))
        await db.commit()

        async def fake_call_provider(self, provider, prompt, params):
            result = await db.execute(select(AITask).where(AITask.id == 341))
            task = result.scalar_one()
            assert task.status == "processing"
            assert task.params["provider"] == {
                "id": 401,
                "name": "GPT Image 2 直连 A",
                "provider_kind": "openai_images",
                "provider_model": "gpt-image-2",
            }
            return {
                "task_id": "provider-task",
                "status": "completed",
                "image_urls": ["/uploads/ai-images/generated.png"],
                "error": None,
            }

        monkeypatch.setattr(
            "app.services.ai_image_provider_service.AIImageProviderService._call_provider",
            fake_call_provider,
        )

        service = AIImageService(model_name="gptimage2", db=db)
        status = await service.execute_submitted_task(341)

        assert status == "completed"
        result = await db.execute(select(AITask).where(AITask.id == 341))
        task = result.scalar_one()
        assert task.params["provider"]["name"] == "GPT Image 2 直连 A"
        assert task.status == "completed"


@pytest.mark.asyncio
async def test_submit_active_limit_ignores_finished_tasks(client, monkeypatch):
    queued_task_ids: list[int] = []

    async def fake_enqueue_task(task_id: int) -> bool:
        queued_task_ids.append(task_id)
        return True

    monkeypatch.setattr(ai_image_task_queue, "enqueue_task", fake_enqueue_task)

    async with async_session() as db:
        db.add(User(id=7, username="finished_user", email="finished@example.com", hashed_password="x"))
        db.add_all([
            AITask(id=311, user_id=7, model_name="gptimage2", prompt="queued", status="queued"),
            AITask(id=312, user_id=7, model_name="gptimage2", prompt="processing", status="processing"),
            AITask(id=313, user_id=7, model_name="gptimage2", prompt="completed", status="completed"),
            AITask(id=314, user_id=7, model_name="gptimage2", prompt="failed", status="failed"),
        ])
        await db.commit()

        service = AIImageService(model_name="gptimage2", db=db)
        result = await service.submit("third active prompt", {"width": 1024, "height": 1024}, user_id=7)

        assert result["status"] == "queued"
        assert queued_task_ids == [int(result["task_id"])]


@pytest.mark.asyncio
async def test_recover_incomplete_tasks_resets_processing_and_requeues_missing(client, monkeypatch):
    requeued_processing: list[int] = []
    discarded_processing: list[int] = []
    enqueued_missing_inputs: list[int] = []

    async def fake_drain_processing_tasks() -> list[int]:
        return [201, 203, 999]

    async def fake_requeue_drained_tasks(task_ids) -> int:
        values = [int(task_id) for task_id in task_ids]
        requeued_processing.extend(values)
        return len(values)

    async def fake_discard_tasks(task_ids) -> int:
        values = [int(task_id) for task_id in task_ids]
        discarded_processing.extend(values)
        return len(values)

    async def fake_enqueue_missing_tasks(task_ids) -> int:
        values = [int(task_id) for task_id in task_ids]
        enqueued_missing_inputs.extend(values)
        return len(values)

    monkeypatch.setattr(ai_image_task_queue, "drain_processing_tasks", fake_drain_processing_tasks)
    monkeypatch.setattr(ai_image_task_queue, "requeue_drained_tasks", fake_requeue_drained_tasks)
    monkeypatch.setattr(ai_image_task_queue, "discard_tasks", fake_discard_tasks)
    monkeypatch.setattr(ai_image_task_queue, "enqueue_missing_tasks", fake_enqueue_missing_tasks)

    async with async_session() as db:
        db.add(User(id=4, username="recover_user", email="recover@example.com", hashed_password="x"))
        db.add_all([
            AITask(id=201, user_id=4, model_name="gptimage2", prompt="processing", status="processing"),
            AITask(id=202, user_id=4, model_name="gptimage2", prompt="queued", status="queued"),
            AITask(id=203, user_id=4, model_name="gptimage2", prompt="done", status="completed"),
        ])
        await db.commit()

        service = AIImageService(db=db)
        recovery = await service.recover_incomplete_tasks()

        assert recovery["reset_processing"] == 1
        assert recovery["requeued_processing"] == 1
        assert recovery["discarded_processing"] == 2
        assert requeued_processing == [201]
        assert sorted(discarded_processing) == [203, 999]
        assert sorted(enqueued_missing_inputs) == [201, 202]

        result = await db.execute(select(AITask).where(AITask.id.in_([201, 202, 203])))
        tasks = {task.id: task for task in result.scalars().all()}
        assert tasks[201].status == "queued"
        assert tasks[201].error is None
        assert tasks[201].finished_at is None
        assert tasks[202].status == "queued"
        assert tasks[203].status == "completed"


@pytest.mark.asyncio
async def test_ai_worker_processes_submitted_task_across_backend_restart_simulation(client, monkeypatch):
    class FakeRedisQueue:
        def __init__(self):
            self.pending: list[int] = []
            self.processing: list[int] = []
            self.membership: set[int] = set()

        async def enqueue_task(self, task_id: int) -> bool:
            task_id = int(task_id)
            if task_id in self.membership:
                return False
            self.membership.add(task_id)
            self.pending.append(task_id)
            return True

        async def reserve_task(self, timeout: int = 5) -> int | None:
            if not self.pending:
                return None
            task_id = self.pending.pop(0)
            self.processing.append(task_id)
            return task_id

        async def ack_task(self, task_id: int) -> None:
            task_id = int(task_id)
            if task_id in self.processing:
                self.processing.remove(task_id)
            self.membership.discard(task_id)

        async def requeue_reserved_task(self, task_id: int) -> bool:
            task_id = int(task_id)
            if task_id in self.processing:
                self.processing.remove(task_id)
                self.pending.append(task_id)
                return True
            return False

        async def drain_processing_tasks(self) -> list[int]:
            drained = list(self.processing)
            self.processing.clear()
            return drained

        async def requeue_drained_tasks(self, task_ids) -> int:
            count = 0
            for task_id in task_ids:
                task_id = int(task_id)
                self.pending.append(task_id)
                self.membership.add(task_id)
                count += 1
            return count

        async def discard_tasks(self, task_ids) -> int:
            count = 0
            for task_id in task_ids:
                task_id = int(task_id)
                if task_id in self.membership:
                    self.membership.discard(task_id)
                    count += 1
            return count

        async def enqueue_missing_tasks(self, task_ids) -> int:
            count = 0
            for task_id in task_ids:
                task_id = int(task_id)
                if task_id in self.membership:
                    continue
                self.membership.add(task_id)
                self.pending.append(task_id)
                count += 1
            return count

        async def remove_pending_task(self, task_id: int) -> bool:
            task_id = int(task_id)
            if task_id in self.pending:
                self.pending.remove(task_id)
                self.membership.discard(task_id)
                return True
            return False

        async def get_status(self) -> dict:
            return {
                "pending": len(self.pending),
                "processing": len(self.processing),
                "tracked": len(self.membership),
            }

        async def close(self) -> None:
            return None

    fake_queue = FakeRedisQueue()

    for name in (
        "enqueue_task",
        "reserve_task",
        "ack_task",
        "requeue_reserved_task",
        "drain_processing_tasks",
        "requeue_drained_tasks",
        "discard_tasks",
        "enqueue_missing_tasks",
        "remove_pending_task",
        "get_status",
        "close",
    ):
        monkeypatch.setattr(ai_image_task_queue, name, getattr(fake_queue, name))

    async def fake_run_generation_pipeline(
        self,
        prompt: str,
        params: dict,
        user_id: int | None = None,
        task_id: int | None = None,
    ):
        return (
            {"task_id": "provider-1", "status": "completed", "image_urls": ["/uploads/ai-images/generated.png"], "error": None},
            ["/uploads/ai-images/generated.png"],
            ["/uploads/ai-images/generated.png"],
        )

    monkeypatch.setattr(AIImageService, "_run_generation_pipeline", fake_run_generation_pipeline)

    async with async_session() as db:
        db.add(User(id=5, username="worker_user", email="worker@example.com", hashed_password="x"))
        await db.commit()

        backend_service = AIImageService(model_name="gptimage2", db=db)
        submit_result = await backend_service.submit(
            "restart-safe prompt",
            {"width": 1024, "height": 1024},
            user_id=5,
        )

    assert submit_result["status"] == "queued"
    task_id = int(submit_result["task_id"])
    assert fake_queue.pending == [task_id]
    assert fake_queue.processing == []

    worker = AIImageWorker()
    worker.request_stop()
    reserved_task_id = await fake_queue.reserve_task()
    assert reserved_task_id == task_id

    # Simulate backend restart: new worker/session recovers the already-reserved task.
    async with async_session() as db:
        recovering_service = AIImageService(db=db)
        recovery = await recovering_service.recover_incomplete_tasks()
        assert recovery["requeued_processing"] == 1

    assert fake_queue.pending == [task_id]
    assert fake_queue.processing == []

    next_task_id = await fake_queue.reserve_task()
    assert next_task_id == task_id
    await worker._process_reserved_task(next_task_id)

    async with async_session() as db:
        result = await db.execute(select(AITask).where(AITask.id == task_id))
        task = result.scalar_one_or_none()
        assert task is not None
        assert task.status == "completed"
        assert task.result_urls == ["/uploads/ai-images/generated.png"]
        assert task.error is None

    assert fake_queue.pending == []
    assert fake_queue.processing == []
