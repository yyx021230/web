from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import func, select

from app.db.session import async_session
from app.models.job import Job, JobEvent, JobItem, JobStatus
from app.services.job_service import InvalidJobProgress, InvalidJobTransition, JobService
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
        await db.commit()

        assert first_created is True
        assert duplicate_created is False
        assert duplicate.id == first.id
        assert duplicate.payload == {"environment_ids": [1, 2]}
        assert other_type_created is True
        assert other_type.id != first.id

        event_rows = (
            await db.execute(
                select(JobEvent).where(JobEvent.job_id == first.id).order_by(JobEvent.id)
            )
        ).scalars().all()
        assert [(event.event_type, event.to_status) for event in event_rows] == [
            ("job_created", JobStatus.QUEUED.value)
        ]


@pytest.mark.asyncio
async def test_job_creation_does_not_commit_caller_transaction(client):
    async with async_session() as db:
        service = JobService(db)
        await service.create_job(job_type="xhs_homepage_sync", idempotency_key="rollback-me")
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
        assert await service.transition(
            job,
            JobStatus.SUCCEEDED,
            result_summary={"success": 2, "failed": 0},
            now=finish_time,
        ) is True
        assert await service.transition(job, JobStatus.SUCCEEDED) is False
        await db.commit()

        assert job.status == JobStatus.SUCCEEDED.value
        assert job.started_at == start_time
        assert job.finished_at == finish_time
        assert job.result_summary == {"success": 2, "failed": 0}

        transitions = (
            await db.execute(
                select(JobEvent.from_status, JobEvent.to_status)
                .where(JobEvent.job_id == job.id, JobEvent.event_type == "status_changed")
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
        job, _ = await service.create_job(job_type="xhs_homepage_sync", progress_total=3)
        await service.set_progress(job, current=1, current_step="同步第一个账号")

        assert job.progress_current == 1
        assert job.progress_total == 3
        assert job.current_step == "同步第一个账号"

        with pytest.raises(InvalidJobProgress, match="must not move backwards"):
            await service.set_progress(job, current=0)
        with pytest.raises(InvalidJobProgress, match="must not exceed"):
            await service.set_progress(job, current=4)
        with pytest.raises(InvalidJobProgress, match="progress_total must not move backwards"):
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
            await db.execute(
                select(JobEvent).where(
                    JobEvent.job_id == job.id,
                    JobEvent.event_type == "cancel_requested",
                )
            )
        ).scalars().all()
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
