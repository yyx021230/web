from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import event

from app.db.session import async_session, engine
from app.models.job import JobAttempt, JobStatus
from app.models.user import User
from app.services.job_query_service import (
    JobQueryError,
    JobQueryNotFound,
    JobQueryService,
    sanitize_job_data,
)
from app.services.job_service import JobService
from app.utils.timezone import utc_now_naive
from tests.conftest import make_auth_headers


async def _seed_jobs(db) -> dict[str, int]:
    db.add_all(
        [
            User(
                id=1,
                username="admin-account",
                display_name="平台管理员",
                email="admin-jobs@example.com",
                hashed_password="x",
                role="admin",
            ),
            User(
                id=2,
                username="operator-account",
                display_name="运营小林",
                email="operator-jobs@example.com",
                hashed_password="x",
                role="viewer",
            ),
        ]
    )
    await db.flush()
    service = JobService(db)

    review_job, _ = await service.create_job(
        job_type="ai_image_generation",
        worker_type="legacy_shadow",
        requested_by_user_id=1,
        source_type="ai_task",
        source_id="source-77",
        idempotency_key="ai-review-77",
        progress_total=6,
        payload={
            "prompt": "不得返回的提示词",
            "api_key": "provider-secret",
            "nested": {
                "authorization": "Bearer nested-secret",
                "safe": "可见字段",
            },
        },
    )
    item, _ = await service.add_item(
        review_job,
        item_key="account-1",
        item_type="xhs_account",
        display_name="账号一",
        payload={"password": "item-secret", "account_id": "10001"},
    )
    item.status = JobStatus.FAILED.value
    item.error_code = "item_failed"
    item.user_message = "分片执行失败"
    item.result = {
        "url": "https://example.com/result.png?token=url-secret&width=100",
        "image_data": "base64-secret",
    }
    await service.transition(review_job, JobStatus.LEASED)
    await service.transition(review_job, JobStatus.RUNNING)
    await service.set_progress(review_job, current=2, current_step="等待上游核验")
    review_job.user_message = "上游返回 Bearer response-secret"
    review_job.result_summary = {
        "requires_reconciliation": True,
        "client_secret": "result-secret",
    }
    await service.transition(
        review_job,
        JobStatus.WAITING_REVIEW,
        error_code="upstream_result_unknown",
        details={"cookie": "event-secret", "reason": "timeout"},
    )
    now = utc_now_naive()
    db.add(
        JobAttempt(
            job_id=review_job.id,
            attempt_number=1,
            worker_id="worker-a",
            status=JobStatus.FAILED.value,
            metrics={"api_token": "attempt-secret", "duration_ms": 123},
            error_code="worker_timeout",
            user_message="执行器超时",
            internal_error="Bearer attempt-internal-secret",
            started_at=now - timedelta(seconds=10),
            finished_at=now,
        )
    )

    completed_job, _ = await service.create_job(
        job_type="xhs_homepage_sync",
        worker_type="legacy_shadow",
        requested_by_user_id=2,
        source_type="xhs_account_sync_run",
        source_id="88",
        idempotency_key="homepage-88",
        progress_total=1,
    )
    await service.transition(completed_job, JobStatus.LEASED)
    await service.transition(completed_job, JobStatus.RUNNING)
    await service.set_progress(completed_job, current=1, current_step="同步完成")
    await service.transition(
        completed_job,
        JobStatus.SUCCEEDED,
        result_summary={"success": 1, "failed": 0},
    )

    queued_job, _ = await service.create_job(
        job_type="report_refresh",
        worker_type="server",
        requested_by_user_id=2,
        source_type="report",
        source_id="monthly-2026-08",
        idempotency_key="report-monthly",
    )
    await db.commit()
    return {
        "review": int(review_job.id),
        "completed": int(completed_job.id),
        "queued": int(queued_job.id),
    }


@pytest.mark.asyncio
async def test_job_query_list_filters_summary_and_display_name(client):
    async with async_session() as db:
        ids = await _seed_jobs(db)
        service = JobQueryService(db)

        result = await service.list_jobs(page=1, limit=2)
        assert result["total"] == 3
        assert len(result["items"]) == 2
        assert result["summary"]["total"] == 3
        assert result["summary"]["active"] == 1
        assert result["summary"]["attention"] == 1
        assert result["summary"]["status_counts"] == {
            "queued": 1,
            "leased": 0,
            "running": 0,
            "retry_wait": 0,
            "waiting_review": 1,
            "succeeded": 1,
            "failed": 0,
            "cancelled": 0,
            "dead_letter": 0,
        }
        assert result["filters"]["job_types"] == [
            "ai_image_generation",
            "report_refresh",
            "xhs_homepage_sync",
        ]

        filtered = await service.list_jobs(
            status="waiting_review",
            job_type="ai_image_generation",
            username="平台管理",
            search="source-77",
        )
        assert filtered["total"] == 1
        assert filtered["items"][0]["id"] == ids["review"]
        assert filtered["items"][0]["display_name"] == "平台管理员"
        assert "payload" not in filtered["items"][0]

        numeric_id = await service.list_jobs(search=f"#{ids['review']}")
        assert numeric_id["total"] == 1
        assert numeric_id["items"][0]["id"] == ids["review"]

        no_match = await service.list_jobs(username="不存在的用户")
        assert no_match["total"] == 0
        with pytest.raises(JobQueryError):
            await service.list_jobs(status="processing")


@pytest.mark.asyncio
async def test_job_query_detail_returns_evidence_and_redacts_sensitive_data(client):
    async with async_session() as db:
        ids = await _seed_jobs(db)
        detail = await JobQueryService(db).get_job(ids["review"])

        assert detail["status"] == JobStatus.WAITING_REVIEW.value
        assert detail["progress_current"] == 2
        assert detail["payload"] == {
            "prompt": "[omitted]",
            "api_key": "[redacted]",
            "nested": {
                "authorization": "[redacted]",
                "safe": "可见字段",
            },
        }
        assert detail["result_summary"]["client_secret"] == "[redacted]"
        assert detail["user_message"] == "上游返回 Bearer [redacted]"
        assert detail["diagnostics"] == {
            "item_count": 1,
            "attempt_count": 1,
            "event_count": 4,
            "items_truncated": False,
            "attempts_truncated": False,
            "events_truncated": False,
        }
        assert detail["items"][0]["payload"]["password"] == "[redacted]"
        assert detail["items"][0]["result"] == {
            "url": "https://example.com/result.png?token=%5Bredacted%5D&width=100",
            "image_data": "[omitted]",
        }
        assert detail["attempts"][0]["metrics"]["api_token"] == "[redacted]"
        assert "internal_error" not in detail["attempts"][0]
        assert detail["events"][-1]["details"]["cookie"] == "[redacted]"
        assert detail["events"][-1]["details"]["reason"] == "timeout"
        assert detail["events"][0]["event_type"] == "job_created"

        response_text = str(detail)
        for secret in (
            "不得返回的提示词",
            "provider-secret",
            "nested-secret",
            "item-secret",
            "base64-secret",
            "attempt-secret",
            "event-secret",
        ):
            assert secret not in response_text

        with pytest.raises(JobQueryNotFound):
            await JobQueryService(db).get_job(999999)


def test_job_data_sanitizer_is_bounded_and_redacts_signed_urls():
    value = {
        "items": list(range(105)),
        "url": "https://example.com/a.png?signature=abc&name=visible",
        "oss_url": "https://example.com/a.png?OSSAccessKeyId=id&x-oss-signature=sig",
        "authorization_text": "secret",
        "message": "Bearer raw-token",
        "inline": "request failed api_key=raw-secret, retry later",
    }
    result = sanitize_job_data(value)
    assert len(result["items"]) == 101
    assert result["items"][-1] == "[truncated]"
    assert result["url"] == (
        "https://example.com/a.png?signature=%5Bredacted%5D&name=visible"
    )
    assert result["authorization_text"] == "[redacted]"
    assert result["message"] == "Bearer [redacted]"
    assert result["inline"] == "request failed api_key=[redacted], retry later"
    assert result["oss_url"] == (
        "https://example.com/a.png?OSSAccessKeyId=%5Bredacted%5D"
        "&x-oss-signature=%5Bredacted%5D"
    )


@pytest.mark.asyncio
async def test_job_query_uses_fixed_batch_queries(client):
    async with async_session() as db:
        ids = await _seed_jobs(db)
        selects: list[str] = []

        def record_selects(_conn, _cursor, statement, _parameters, _context, _many):
            if statement.lstrip().upper().startswith("SELECT"):
                selects.append(statement)

        event.listen(engine.sync_engine, "before_cursor_execute", record_selects)
        try:
            listing = await JobQueryService(db).list_jobs(limit=100)
            detail = await JobQueryService(db).get_job(ids["review"])
        finally:
            event.remove(engine.sync_engine, "before_cursor_execute", record_selects)

    assert listing["total"] == 3
    assert detail["diagnostics"]["item_count"] == 1
    assert len(selects) == 10


@pytest.mark.asyncio
async def test_durable_job_admin_api_authorization_filters_and_detail(client):
    async with async_session() as db:
        ids = await _seed_jobs(db)

    list_path = "/api/v1/admin/reliability/jobs"
    assert (await client.get(list_path)).status_code == 401
    assert (
        await client.get(list_path, headers=make_auth_headers(2))
    ).status_code == 403

    response = await client.get(
        list_path,
        headers=make_auth_headers(1),
        params={
            "status": "waiting_review",
            "job_type": "ai_image_generation",
            "username": "平台管理员",
        },
    )
    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["total"] == 1
    assert payload["items"][0]["id"] == ids["review"]

    invalid = await client.get(
        list_path,
        headers=make_auth_headers(1),
        params={"status": "processing"},
    )
    assert invalid.status_code == 400

    detail = await client.get(
        f"{list_path}/{ids['review']}",
        headers=make_auth_headers(1),
    )
    assert detail.status_code == 200
    assert detail.json()["data"]["items"][0]["display_name"] == "账号一"
    assert "provider-secret" not in detail.text
    assert "不得返回的提示词" not in detail.text

    missing = await client.get(
        f"{list_path}/999999",
        headers=make_auth_headers(1),
    )
    assert missing.status_code == 404
