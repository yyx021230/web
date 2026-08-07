from __future__ import annotations

import asyncio
import uuid
from datetime import timedelta

import pytest
from sqlalchemy import delete, func, select, text
from sqlalchemy.exc import IntegrityError

from app.db.session import async_session
from app.models.job import (
    Job,
    JobAttempt,
    JobEvent,
    JobItem,
    JobStatus,
    TERMINAL_JOB_STATUSES,
)
from app.models.user import User
from app.services.job_service import (
    ALLOWED_JOB_TRANSITIONS,
    InvalidJobProgress,
    InvalidJobTransition,
    JobService,
    JobStateError,
    normalize_job_status,
)
from app.utils.timezone import utc_now_naive


@pytest.mark.asyncio
async def test_create_job_is_idempotent_within_scope_and_type(client):
    async with async_session() as db:
        service = JobService(db)
        first, first_created = await service.create_job(
            job_type="xhs_homepage_sync",
            scope_key="internal",
            idempotency_key="request-001",
            payload={"environment_ids": [1, 2]},
        )
        duplicate, duplicate_created = await service.create_job(
            job_type="xhs_homepage_sync",
            scope_key="internal",
            idempotency_key="request-001",
            payload={"environment_ids": [999]},
        )
        other_type, other_type_created = await service.create_job(
            job_type="ai_image",
            scope_key="internal",
            idempotency_key="request-001",
        )
        other_scope, other_scope_created = await service.create_job(
            job_type="xhs_homepage_sync",
            scope_key="another-scope",
            idempotency_key="request-001",
        )
        await db.commit()

        assert first_created is True
        assert duplicate_created is False
        assert duplicate.id == first.id
        assert duplicate.payload == {"environment_ids": [1, 2]}
        assert other_type_created is True
        assert other_type.id != first.id
        assert other_scope_created is True
        assert other_scope.id != first.id

        event_rows = (
            (
                await db.execute(
                    select(JobEvent)
                    .where(JobEvent.job_id == first.id)
                    .order_by(JobEvent.id)
                )
            )
            .scalars()
            .all()
        )
        assert [(event.event_type, event.to_status) for event in event_rows] == [
            ("job_created", JobStatus.QUEUED.value)
        ]


@pytest.mark.asyncio
async def test_job_creation_does_not_commit_caller_transaction(client):
    async with async_session() as db:
        service = JobService(db)
        await service.create_job(
            job_type="xhs_homepage_sync", idempotency_key="rollback-me"
        )
        await db.rollback()

    async with async_session() as db:
        job_count = (await db.execute(select(func.count(Job.id)))).scalar_one()
        event_count = (await db.execute(select(func.count(JobEvent.id)))).scalar_one()
        assert job_count == 0
        assert event_count == 0


@pytest.mark.asyncio
async def test_valid_status_transitions_record_times_and_events(client):
    async with async_session() as db:
        service = JobService(db)
        job, _ = await service.create_job(job_type="xhs_homepage_sync")

        lease_time = utc_now_naive()
        assert await service.transition(job, JobStatus.LEASED, now=lease_time) is True
        start_time = lease_time + timedelta(seconds=1)
        assert await service.transition(job, JobStatus.RUNNING, now=start_time) is True
        finish_time = start_time + timedelta(seconds=3)
        assert (
            await service.transition(
                job,
                JobStatus.SUCCEEDED,
                result_summary={"success": 2, "failed": 0},
                now=finish_time,
            )
            is True
        )
        assert await service.transition(job, JobStatus.SUCCEEDED) is False
        await db.commit()

        assert job.status == JobStatus.SUCCEEDED.value
        assert job.started_at == start_time
        assert job.finished_at == finish_time
        assert job.result_summary == {"success": 2, "failed": 0}

        transitions = (
            await db.execute(
                select(JobEvent.from_status, JobEvent.to_status)
                .where(
                    JobEvent.job_id == job.id, JobEvent.event_type == "status_changed"
                )
                .order_by(JobEvent.id)
            )
        ).all()
        assert transitions == [
            (JobStatus.QUEUED.value, JobStatus.LEASED.value),
            (JobStatus.LEASED.value, JobStatus.RUNNING.value),
            (JobStatus.RUNNING.value, JobStatus.SUCCEEDED.value),
        ]


@pytest.mark.asyncio
async def test_terminal_job_rejects_late_worker_callback(client):
    async with async_session() as db:
        service = JobService(db)
        job, _ = await service.create_job(job_type="ai_image")
        await service.transition(job, JobStatus.LEASED)
        await service.transition(job, JobStatus.RUNNING)
        await service.transition(job, JobStatus.SUCCEEDED)

        with pytest.raises(InvalidJobTransition) as exc:
            await service.transition(job, JobStatus.FAILED)

        assert exc.value.current_status == JobStatus.SUCCEEDED.value
        assert exc.value.target_status == JobStatus.FAILED.value


@pytest.mark.asyncio
async def test_retry_limit_moves_job_to_dead_letter(client):
    async with async_session() as db:
        service = JobService(db)
        job, _ = await service.create_job(job_type="xhs_homepage_sync", max_retries=1)
        await service.transition(job, JobStatus.LEASED)
        await service.transition(job, JobStatus.RUNNING)

        retry_at = utc_now_naive() + timedelta(seconds=30)
        first_result = await service.schedule_retry(
            job,
            run_after=retry_at,
            error_code="upstream_timeout",
        )
        assert first_result == JobStatus.RETRY_WAIT.value
        assert job.retry_count == 1
        assert job.run_after == retry_at

        await service.transition(job, JobStatus.QUEUED)
        assert job.run_after is None
        await service.transition(job, JobStatus.LEASED)
        await service.transition(job, JobStatus.RUNNING)
        second_result = await service.schedule_retry(
            job,
            run_after=retry_at + timedelta(seconds=30),
            error_code="upstream_timeout",
        )

        assert second_result == JobStatus.DEAD_LETTER.value
        assert job.status == JobStatus.DEAD_LETTER.value
        assert job.retry_count == 2
        assert job.run_after is None
        assert job.finished_at is not None


@pytest.mark.asyncio
async def test_progress_is_monotonic_and_bounded(client):
    async with async_session() as db:
        service = JobService(db)
        job, _ = await service.create_job(
            job_type="xhs_homepage_sync", progress_total=3
        )
        await service.set_progress(job, current=1, current_step="同步第一个账号")

        assert job.progress_current == 1
        assert job.progress_total == 3
        assert job.current_step == "同步第一个账号"

        with pytest.raises(InvalidJobProgress, match="must not move backwards"):
            await service.set_progress(job, current=0)
        with pytest.raises(InvalidJobProgress, match="must not exceed"):
            await service.set_progress(job, current=4)
        with pytest.raises(
            InvalidJobProgress, match="progress_total must not move backwards"
        ):
            await service.set_progress(job, current=1, total=2)


@pytest.mark.asyncio
async def test_cancel_request_is_idempotent_and_audited(client):
    async with async_session() as db:
        service = JobService(db)
        job, _ = await service.create_job(job_type="xhs_homepage_sync")

        assert await service.request_cancel(job, actor_id="7") is True
        assert await service.request_cancel(job, actor_id="7") is False
        await db.commit()

        cancel_events = (
            (
                await db.execute(
                    select(JobEvent).where(
                        JobEvent.job_id == job.id,
                        JobEvent.event_type == "cancel_requested",
                    )
                )
            )
            .scalars()
            .all()
        )
        assert job.cancel_requested is True
        assert job.status == JobStatus.QUEUED.value
        assert len(cancel_events) == 1
        assert cancel_events[0].actor_type == "user"
        assert cancel_events[0].actor_id == "7"


@pytest.mark.asyncio
async def test_job_items_are_idempotent_per_job(client):
    async with async_session() as db:
        service = JobService(db)
        first_job, _ = await service.create_job(job_type="xhs_homepage_sync")
        second_job, _ = await service.create_job(job_type="xhs_homepage_sync")

        first_item, first_created = await service.add_item(
            first_job,
            item_key="environment:42",
            display_name="测试账号",
            payload={"environment_id": 42},
        )
        duplicate, duplicate_created = await service.add_item(
            first_job,
            item_key="environment:42",
            payload={"environment_id": 999},
        )
        second_item, second_created = await service.add_item(
            second_job,
            item_key="environment:42",
        )
        await db.commit()

        assert first_created is True
        assert duplicate_created is False
        assert duplicate.id == first_item.id
        assert duplicate.payload == {"environment_id": 42}
        assert second_created is True
        assert second_item.job_id != first_item.job_id

        item_count = (await db.execute(select(func.count(JobItem.id)))).scalar_one()
        assert item_count == 2


@pytest.mark.asyncio
async def test_idempotency_is_atomic_across_concurrent_sessions(client):
    async def create_once():
        async with async_session() as db:
            job, created = await JobService(db).create_job(
                job_type="concurrent_smoke",
                idempotency_key="same-concurrent-request",
            )
            await db.commit()
            return job.id, created

    first, second = await asyncio.gather(create_once(), create_once())
    assert first[0] == second[0]
    assert sorted([first[1], second[1]]) == [False, True]

    async with async_session() as db:
        job_count = (
            await db.execute(
                select(func.count(Job.id)).where(Job.job_type == "concurrent_smoke")
            )
        ).scalar_one()
        event_count = (
            await db.execute(
                select(func.count(JobEvent.id)).where(JobEvent.job_id == first[0])
            )
        ).scalar_one()
        assert job_count == 1
        assert event_count == 1


def test_state_machine_covers_every_declared_status():
    declared = {status.value for status in JobStatus}
    assert set(ALLOWED_JOB_TRANSITIONS) == declared
    assert TERMINAL_JOB_STATUSES == {
        JobStatus.SUCCEEDED.value,
        JobStatus.FAILED.value,
        JobStatus.CANCELLED.value,
        JobStatus.DEAD_LETTER.value,
    }
    for terminal_status in TERMINAL_JOB_STATUSES:
        assert ALLOWED_JOB_TRANSITIONS[terminal_status] == frozenset()
    with pytest.raises(JobStateError, match="unknown job status"):
        normalize_job_status("invented")


@pytest.mark.asyncio
async def test_sqlite_foreign_keys_are_enabled(client):
    async with async_session() as db:
        enabled = (await db.execute(text("PRAGMA foreign_keys"))).scalar_one()
        assert enabled == 1


@pytest.mark.asyncio
async def test_review_branch_and_failure_details_are_persisted(client):
    async with async_session() as db:
        service = JobService(db)
        review_job, _ = await service.create_job(job_type="content_review")
        await service.transition(review_job, JobStatus.LEASED)
        await service.transition(review_job, JobStatus.RUNNING)
        await service.transition(
            review_job, JobStatus.WAITING_REVIEW, message="等待人工审核"
        )
        await service.transition(
            review_job,
            JobStatus.SUCCEEDED,
            result_summary={"review": "approved"},
        )

        failed_job, _ = await service.create_job(job_type="content_review")
        await service.transition(
            failed_job,
            JobStatus.FAILED,
            error_code="invalid_config",
            user_message="配置无效",
            internal_error="missing workflow id",
            details={"field": "workflow_id"},
            actor_type="operator",
            actor_id="9",
        )
        await db.commit()

        assert review_job.status == JobStatus.SUCCEEDED.value
        assert review_job.result_summary == {"review": "approved"}
        assert failed_job.status == JobStatus.FAILED.value
        assert failed_job.error_code == "invalid_config"
        assert failed_job.user_message == "配置无效"
        assert failed_job.internal_error == "missing workflow id"

        failure_event = (
            await db.execute(
                select(JobEvent).where(
                    JobEvent.job_id == failed_job.id,
                    JobEvent.to_status == JobStatus.FAILED.value,
                )
            )
        ).scalar_one()
        assert failure_event.details == {"field": "workflow_id"}
        assert failure_event.actor_type == "operator"
        assert failure_event.actor_id == "9"


@pytest.mark.asyncio
async def test_retry_rejects_non_running_job_without_mutating_count(client):
    async with async_session() as db:
        job, _ = await JobService(db).create_job(job_type="retry_guard", max_retries=2)
        with pytest.raises(InvalidJobTransition):
            await JobService(db).schedule_retry(
                job,
                run_after=utc_now_naive() + timedelta(seconds=10),
            )
        assert job.retry_count == 0
        assert job.status == JobStatus.QUEUED.value


@pytest.mark.asyncio
async def test_transition_clears_lease_metadata(client):
    async with async_session() as db:
        service = JobService(db)
        job, _ = await service.create_job(job_type="lease_cleanup")
        await service.transition(job, JobStatus.LEASED)
        job.lease_owner = "worker-1"
        job.lease_expires_at = utc_now_naive() + timedelta(minutes=1)
        job.heartbeat_at = utc_now_naive()
        await service.transition(job, JobStatus.RUNNING)
        assert job.lease_owner == "worker-1"

        await service.transition(job, JobStatus.FAILED)
        assert job.lease_owner is None
        assert job.lease_expires_at is None
        assert job.heartbeat_at is None


@pytest.mark.asyncio
async def test_payload_and_result_inputs_are_defensively_copied(client):
    async with async_session() as db:
        payload = {"environment_ids": [1]}
        result = {"success_ids": [1]}
        service = JobService(db)
        job, _ = await service.create_job(job_type="copy_guard", payload=payload)
        payload["environment_ids"].append(2)
        await service.transition(job, JobStatus.LEASED)
        await service.transition(job, JobStatus.RUNNING)
        await service.transition(job, JobStatus.SUCCEEDED, result_summary=result)
        result["success_ids"].append(2)

        assert job.payload == {"environment_ids": [1]}
        assert job.result_summary == {"success_ids": [1]}


@pytest.mark.asyncio
async def test_attempt_uniqueness_and_job_delete_cascade(client):
    async with async_session() as db:
        service = JobService(db)
        job, _ = await service.create_job(job_type="cascade_check")
        await service.add_item(job, item_key="account:1")
        db.add(
            JobAttempt(
                job_id=job.id,
                attempt_number=1,
                worker_id="worker-1",
                status=JobStatus.RUNNING.value,
                metrics={"duration_ms": 12},
                started_at=utc_now_naive(),
            )
        )
        await db.commit()
        job_id = job.id

    async with async_session() as db:
        db.add(
            JobAttempt(
                job_id=job_id,
                attempt_number=1,
                worker_id="worker-2",
                status=JobStatus.RUNNING.value,
                metrics={},
                started_at=utc_now_naive(),
            )
        )
        with pytest.raises(IntegrityError):
            await db.flush()
        await db.rollback()

    async with async_session() as db:
        await db.execute(delete(Job).where(Job.id == job_id))
        await db.commit()
        counts = {
            "items": (await db.execute(select(func.count(JobItem.id)))).scalar_one(),
            "attempts": (
                await db.execute(select(func.count(JobAttempt.id)))
            ).scalar_one(),
            "events": (await db.execute(select(func.count(JobEvent.id)))).scalar_one(),
        }
        assert counts == {"items": 0, "attempts": 0, "events": 0}


@pytest.mark.asyncio
async def test_parent_and_requester_foreign_keys_are_set_null(client):
    async with async_session() as db:
        user = User(
            username="job-owner",
            email="job-owner@invalid.local",
            hashed_password="not-used",
            is_active=True,
            role="viewer",
        )
        db.add(user)
        await db.flush()
        service = JobService(db)
        parent, _ = await service.create_job(
            job_type="parent", requested_by_user_id=user.id
        )
        child, _ = await service.create_job(
            job_type="child",
            requested_by_user_id=user.id,
            parent_job_id=parent.id,
        )
        await db.commit()
        parent_id = parent.id
        child_id = child.id
        user_id = user.id

    async with async_session() as db:
        await db.execute(delete(Job).where(Job.id == parent_id))
        await db.execute(delete(User).where(User.id == user_id))
        await db.commit()
        child = (await db.execute(select(Job).where(Job.id == child_id))).scalar_one()
        assert child.parent_job_id is None
        assert child.requested_by_user_id is None


@pytest.mark.asyncio
async def test_database_rejects_invalid_job_numbers(client):
    async with async_session() as db:
        invalid_job = Job(
            public_id=str(uuid.uuid4()),
            job_type="invalid-priority",
            priority=-1,
            payload={},
        )
        db.add(invalid_job)
        with pytest.raises(IntegrityError):
            await db.flush()
        await db.rollback()

    async with async_session() as db:
        job, _ = await JobService(db).create_job(job_type="invalid-children")
        await db.commit()
        job_id = job.id

    async with async_session() as db:
        db.add(
            JobItem(
                job_id=job_id,
                item_key="negative-attempts",
                status=JobStatus.QUEUED.value,
                payload={},
                attempt_count=-1,
            )
        )
        with pytest.raises(IntegrityError):
            await db.flush()
        await db.rollback()

    async with async_session() as db:
        db.add(
            JobAttempt(
                job_id=job_id,
                attempt_number=0,
                status=JobStatus.RUNNING.value,
                metrics={},
                started_at=utc_now_naive(),
            )
        )
        with pytest.raises(IntegrityError):
            await db.flush()
        await db.rollback()
