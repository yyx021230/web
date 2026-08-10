from __future__ import annotations

import asyncio
import uuid
from datetime import timedelta

import pytest
from sqlalchemy import delete, func, select, text
from sqlalchemy.dialects import postgresql, sqlite
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
    JobLeaseLost,
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
async def test_claim_next_job_records_lease_attempt_and_event(client):
    claim_time = utc_now_naive()
    async with async_session() as db:
        service = JobService(db)
        job, _ = await service.create_job(job_type="homepage_sync", priority=20)
        claimed = await service.claim_next_job(
            worker_id="worker-1",
            worker_type="server",
            lease_seconds=90,
            now=claim_time,
        )
        assert claimed is not None
        claimed_job, attempt = claimed
        await db.commit()

        assert claimed_job.id == job.id
        assert claimed_job.status == JobStatus.LEASED.value
        assert claimed_job.lease_owner == "worker-1"
        assert claimed_job.heartbeat_at == claim_time
        assert claimed_job.lease_expires_at == claim_time + timedelta(seconds=90)
        assert attempt.attempt_number == 1
        assert attempt.worker_id == "worker-1"
        assert attempt.status == JobStatus.LEASED.value
        assert attempt.heartbeat_at == claim_time
        assert attempt.lease_expires_at == claim_time + timedelta(seconds=90)

        lease_event = (
            await db.execute(
                select(JobEvent).where(
                    JobEvent.job_id == job.id,
                    JobEvent.event_type == "status_changed",
                    JobEvent.to_status == JobStatus.LEASED.value,
                )
            )
        ).scalar_one()
        assert lease_event.actor_type == "worker"
        assert lease_event.actor_id == "worker-1"
        assert lease_event.details["attempt_id"] == attempt.id
        assert lease_event.details["attempt_number"] == 1


@pytest.mark.asyncio
async def test_claim_next_job_respects_priority_due_time_filters_and_worker_type(
    client,
):
    now = utc_now_naive()
    async with async_session() as db:
        service = JobService(db)
        cancelled, _ = await service.create_job(job_type="sync", priority=0)
        cancelled.cancel_requested = True
        future, _ = await service.create_job(job_type="sync", priority=1)
        future.run_after = now + timedelta(minutes=5)
        browser_job, _ = await service.create_job(
            job_type="browser_sync", worker_type="browser", priority=2
        )
        filtered_out, _ = await service.create_job(job_type="report", priority=3)
        first, _ = await service.create_job(job_type="sync", priority=10)
        second, _ = await service.create_job(job_type="sync", priority=20)
        await db.commit()

    async with async_session() as db:
        service = JobService(db)
        first_claim = await service.claim_next_job(
            worker_id="server-1", job_types=["sync"], now=now
        )
        assert first_claim is not None
        assert first_claim[0].id == first.id
        await db.commit()

    async with async_session() as db:
        service = JobService(db)
        second_claim = await service.claim_next_job(
            worker_id="server-2", job_types="sync", now=now
        )
        assert second_claim is not None
        assert second_claim[0].id == second.id
        assert (
            await service.claim_next_job(
                worker_id="server-2", job_types=["sync"], now=now
            )
            is None
        )
        await db.commit()

    async with async_session() as db:
        browser_claim = await JobService(db).claim_next_job(
            worker_id="browser-1", worker_type="browser", now=now
        )
        assert browser_claim is not None
        assert browser_claim[0].id == browser_job.id
        await db.commit()

        untouched_ids = {
            row.id
            for row in (
                (
                    await db.execute(
                        select(Job).where(Job.status == JobStatus.QUEUED.value)
                    )
                )
                .scalars()
                .all()
            )
        }
        assert untouched_ids == {cancelled.id, future.id, filtered_out.id}


@pytest.mark.asyncio
async def test_claim_next_job_is_atomic_across_concurrent_workers(client):
    async with async_session() as db:
        job, _ = await JobService(db).create_job(job_type="single_claim")
        await db.commit()
        job_id = job.id

    async def claim(worker_id: str):
        async with async_session() as db:
            claimed = await JobService(db).claim_next_job(
                worker_id=worker_id,
                job_types=["single_claim"],
            )
            await db.commit()
            return None if claimed is None else (claimed[0].id, worker_id)

    results = await asyncio.gather(claim("worker-a"), claim("worker-b"))
    winners = [result for result in results if result is not None]
    assert len(winners) == 1
    assert winners[0][0] == job_id

    async with async_session() as db:
        stored_job = (
            await db.execute(select(Job).where(Job.id == job_id))
        ).scalar_one()
        attempts = (
            (await db.execute(select(JobAttempt).where(JobAttempt.job_id == job_id)))
            .scalars()
            .all()
        )
        lease_events = (
            (
                await db.execute(
                    select(JobEvent).where(
                        JobEvent.job_id == job_id,
                        JobEvent.to_status == JobStatus.LEASED.value,
                    )
                )
            )
            .scalars()
            .all()
        )
        assert stored_job.lease_owner == winners[0][1]
        assert len(attempts) == 1
        assert len(lease_events) == 1


@pytest.mark.asyncio
async def test_claim_pool_never_duplicates_jobs_across_many_workers(client):
    job_count = 6
    async with async_session() as db:
        for index in range(job_count):
            await JobService(db).create_job(
                job_type="concurrent_pool",
                idempotency_key=f"pool-{index}",
            )
        await db.commit()

    async def claim(worker_number: int):
        async with async_session() as db:
            claimed = await JobService(db).claim_next_job(
                worker_id=f"pool-worker-{worker_number}",
                job_types=["concurrent_pool"],
            )
            await db.commit()
            return None if claimed is None else claimed[0].id

    results = await asyncio.gather(*(claim(index) for index in range(job_count * 2)))
    claimed_ids = [job_id for job_id in results if job_id is not None]
    assert len(claimed_ids) == job_count
    assert len(set(claimed_ids)) == job_count

    async with async_session() as db:
        attempt_count = (
            await db.execute(
                select(func.count(JobAttempt.id))
                .join(Job)
                .where(Job.job_type == "concurrent_pool")
            )
        ).scalar_one()
        lease_event_count = (
            await db.execute(
                select(func.count(JobEvent.id))
                .join(Job)
                .where(
                    Job.job_type == "concurrent_pool",
                    JobEvent.to_status == JobStatus.LEASED.value,
                )
            )
        ).scalar_one()
        assert attempt_count == job_count
        assert lease_event_count == job_count


@pytest.mark.asyncio
async def test_claim_next_job_rollback_releases_the_job(client):
    async with async_session() as db:
        job, _ = await JobService(db).create_job(job_type="rollback_claim")
        await db.commit()
        job_id = job.id

    async with async_session() as db:
        claimed = await JobService(db).claim_next_job(worker_id="worker-rollback")
        assert claimed is not None
        await db.rollback()

    async with async_session() as db:
        stored_job = (
            await db.execute(select(Job).where(Job.id == job_id))
        ).scalar_one()
        attempt_count = (
            await db.execute(
                select(func.count(JobAttempt.id)).where(JobAttempt.job_id == job_id)
            )
        ).scalar_one()
        assert stored_job.status == JobStatus.QUEUED.value
        assert stored_job.lease_owner is None
        assert attempt_count == 0

        reclaimed = await JobService(db).claim_next_job(worker_id="worker-retry")
        assert reclaimed is not None
        assert reclaimed[0].id == job_id


@pytest.mark.asyncio
async def test_claim_next_job_validates_worker_and_lease_inputs(client):
    async with async_session() as db:
        service = JobService(db)
        with pytest.raises(ValueError, match="worker_id"):
            await service.claim_next_job(worker_id=" ")
        with pytest.raises(ValueError, match="worker_type"):
            await service.claim_next_job(worker_id="worker", worker_type=" ")
        with pytest.raises(ValueError, match="lease_seconds"):
            await service.claim_next_job(worker_id="worker", lease_seconds=0)
        with pytest.raises(ValueError, match="job_types"):
            await service.claim_next_job(worker_id="worker", job_types=[" "])


def test_claim_statement_uses_postgresql_skip_locked_and_sqlite_atomic_update():
    now = utc_now_naive()
    kwargs = {
        "worker_type": "server",
        "job_types": ("homepage_sync",),
        "claim_time": now,
        "lease_owner": "worker-1",
        "lease_expires_at": now + timedelta(seconds=60),
    }
    postgresql_sql = str(
        JobService._build_claim_statement(**kwargs, dialect_name="postgresql").compile(
            dialect=postgresql.dialect()
        )
    )
    sqlite_sql = str(
        JobService._build_claim_statement(**kwargs, dialect_name="sqlite").compile(
            dialect=sqlite.dialect()
        )
    )

    assert "FOR UPDATE SKIP LOCKED" in postgresql_sql
    assert "RETURNING jobs.id" in postgresql_sql
    assert "FOR UPDATE" not in sqlite_sql
    assert "RETURNING id" in sqlite_sql


@pytest.mark.asyncio
async def test_start_claimed_job_updates_job_attempt_and_event_once(client):
    claim_time = utc_now_naive()
    start_time = claim_time + timedelta(seconds=5)
    async with async_session() as db:
        service = JobService(db)
        job, _ = await service.create_job(job_type="start_job")
        claimed = await service.claim_next_job(
            worker_id="worker-1", lease_seconds=60, now=claim_time
        )
        assert claimed is not None
        attempt = claimed[1]
        await db.commit()
        job_id = job.id
        attempt_id = attempt.id

    async with async_session() as db:
        service = JobService(db)
        started_job, started_attempt = await service.start_claimed_job(
            job_id=job_id,
            attempt_id=attempt_id,
            worker_id="worker-1",
            now=start_time,
        )
        duplicate_job, duplicate_attempt = await service.start_claimed_job(
            job_id=job_id,
            attempt_id=attempt_id,
            worker_id="worker-1",
            now=start_time + timedelta(seconds=1),
        )
        await db.commit()

        assert started_job.status == JobStatus.RUNNING.value
        assert started_job.started_at == start_time
        assert started_job.heartbeat_at == start_time
        assert started_attempt.status == JobStatus.RUNNING.value
        assert started_attempt.heartbeat_at == start_time
        assert duplicate_job.id == started_job.id
        assert duplicate_attempt.id == started_attempt.id

        start_events = (
            (
                await db.execute(
                    select(JobEvent).where(
                        JobEvent.job_id == job_id,
                        JobEvent.from_status == JobStatus.LEASED.value,
                        JobEvent.to_status == JobStatus.RUNNING.value,
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(start_events) == 1
        assert start_events[0].details["attempt_id"] == attempt_id


@pytest.mark.asyncio
async def test_concurrent_duplicate_start_records_one_transition(client):
    claim_time = utc_now_naive()
    async with async_session() as db:
        service = JobService(db)
        job, _ = await service.create_job(job_type="concurrent_start")
        claimed = await service.claim_next_job(
            worker_id="same-worker", lease_seconds=60, now=claim_time
        )
        assert claimed is not None
        await db.commit()
        job_id = job.id
        attempt_id = claimed[1].id

    async def start_once():
        async with async_session() as db:
            result = await JobService(db).start_claimed_job(
                job_id=job_id,
                attempt_id=attempt_id,
                worker_id="same-worker",
                now=claim_time + timedelta(seconds=1),
            )
            await db.commit()
            return result[0].id, result[1].id

    first, second = await asyncio.gather(start_once(), start_once())
    assert first == second == (job_id, attempt_id)

    async with async_session() as db:
        transition_count = (
            await db.execute(
                select(func.count(JobEvent.id)).where(
                    JobEvent.job_id == job_id,
                    JobEvent.from_status == JobStatus.LEASED.value,
                    JobEvent.to_status == JobStatus.RUNNING.value,
                )
            )
        ).scalar_one()
        assert transition_count == 1


@pytest.mark.asyncio
async def test_start_claimed_job_rejects_wrong_owner_attempt_and_expired_lease(client):
    claim_time = utc_now_naive()
    async with async_session() as db:
        service = JobService(db)
        job, _ = await service.create_job(job_type="guard_start")
        claimed = await service.claim_next_job(
            worker_id="owner", lease_seconds=30, now=claim_time
        )
        assert claimed is not None
        await db.commit()
        job_id = job.id
        attempt_id = claimed[1].id

    async with async_session() as db:
        service = JobService(db)
        with pytest.raises(JobLeaseLost):
            await service.start_claimed_job(
                job_id=job_id,
                attempt_id=attempt_id,
                worker_id="other-worker",
                now=claim_time + timedelta(seconds=1),
            )
        with pytest.raises(JobLeaseLost):
            await service.start_claimed_job(
                job_id=job_id,
                attempt_id=attempt_id + 999,
                worker_id="owner",
                now=claim_time + timedelta(seconds=1),
            )
        with pytest.raises(JobLeaseLost):
            await service.start_claimed_job(
                job_id=job_id,
                attempt_id=attempt_id,
                worker_id="owner",
                now=claim_time + timedelta(seconds=30),
            )
        await db.commit()

    async with async_session() as db:
        stored_job = (
            await db.execute(select(Job).where(Job.id == job_id))
        ).scalar_one()
        stored_attempt = (
            await db.execute(select(JobAttempt).where(JobAttempt.id == attempt_id))
        ).scalar_one()
        running_events = (
            await db.execute(
                select(func.count(JobEvent.id)).where(
                    JobEvent.job_id == job_id,
                    JobEvent.to_status == JobStatus.RUNNING.value,
                )
            )
        ).scalar_one()
        assert stored_job.status == JobStatus.LEASED.value
        assert stored_attempt.status == JobStatus.LEASED.value
        assert running_events == 0


@pytest.mark.asyncio
async def test_renew_job_lease_updates_leased_and_running_heartbeats_without_events(
    client,
):
    claim_time = utc_now_naive()
    async with async_session() as db:
        service = JobService(db)
        job, _ = await service.create_job(job_type="heartbeat")
        claimed = await service.claim_next_job(
            worker_id="worker-heartbeat", lease_seconds=30, now=claim_time
        )
        assert claimed is not None
        await db.commit()
        job_id = job.id
        attempt_id = claimed[1].id

    first_heartbeat = claim_time + timedelta(seconds=10)
    async with async_session() as db:
        service = JobService(db)
        leased_job, leased_attempt = await service.renew_job_lease(
            job_id=job_id,
            attempt_id=attempt_id,
            worker_id="worker-heartbeat",
            lease_seconds=60,
            now=first_heartbeat,
        )
        assert leased_job.lease_expires_at == first_heartbeat + timedelta(seconds=60)
        assert leased_attempt.lease_expires_at == leased_job.lease_expires_at
        first_expiry = leased_job.lease_expires_at
        shorter_job, shorter_attempt = await service.renew_job_lease(
            job_id=job_id,
            attempt_id=attempt_id,
            worker_id="worker-heartbeat",
            lease_seconds=5,
            now=first_heartbeat + timedelta(seconds=1),
        )
        assert shorter_job.lease_expires_at == first_expiry
        assert shorter_attempt.lease_expires_at == first_expiry
        await service.start_claimed_job(
            job_id=job_id,
            attempt_id=attempt_id,
            worker_id="worker-heartbeat",
            now=first_heartbeat + timedelta(seconds=1),
        )
        second_heartbeat = first_heartbeat + timedelta(seconds=20)
        running_job, running_attempt = await service.renew_job_lease(
            job_id=job_id,
            attempt_id=attempt_id,
            worker_id="worker-heartbeat",
            lease_seconds=90,
            now=second_heartbeat,
        )
        await db.commit()

        assert running_job.status == JobStatus.RUNNING.value
        assert running_attempt.status == JobStatus.RUNNING.value
        assert running_job.heartbeat_at == second_heartbeat
        assert running_attempt.heartbeat_at == second_heartbeat
        assert running_job.lease_expires_at == second_heartbeat + timedelta(seconds=90)
        assert running_attempt.lease_expires_at == running_job.lease_expires_at

        event_count = (
            await db.execute(
                select(func.count(JobEvent.id)).where(JobEvent.job_id == job_id)
            )
        ).scalar_one()
        assert event_count == 3


@pytest.mark.asyncio
async def test_concurrent_heartbeats_keep_the_latest_lease(client):
    claim_time = utc_now_naive()
    async with async_session() as db:
        service = JobService(db)
        job, _ = await service.create_job(job_type="concurrent_heartbeat")
        claimed = await service.claim_next_job(
            worker_id="heartbeat-worker", lease_seconds=30, now=claim_time
        )
        assert claimed is not None
        await db.commit()
        job_id = job.id
        attempt_id = claimed[1].id

    async def heartbeat_at(offset_seconds: int):
        async with async_session() as db:
            result = await JobService(db).renew_job_lease(
                job_id=job_id,
                attempt_id=attempt_id,
                worker_id="heartbeat-worker",
                lease_seconds=60,
                now=claim_time + timedelta(seconds=offset_seconds),
            )
            await db.commit()
            return result[0].id, result[1].id

    results = await asyncio.gather(heartbeat_at(5), heartbeat_at(10))
    assert results == [(job_id, attempt_id), (job_id, attempt_id)]

    async with async_session() as db:
        stored_job = await db.get(Job, job_id)
        stored_attempt = await db.get(JobAttempt, attempt_id)
        assert stored_job is not None
        assert stored_attempt is not None
        expected_heartbeat = claim_time + timedelta(seconds=10)
        expected_expiry = expected_heartbeat + timedelta(seconds=60)
        assert stored_job.heartbeat_at == expected_heartbeat
        assert stored_attempt.heartbeat_at == expected_heartbeat
        assert stored_job.lease_expires_at == expected_expiry
        assert stored_attempt.lease_expires_at == expected_expiry


@pytest.mark.asyncio
async def test_out_of_order_heartbeat_is_a_noop_and_never_moves_time_backwards(client):
    claim_time = utc_now_naive()
    async with async_session() as db:
        service = JobService(db)
        job, _ = await service.create_job(job_type="ordered_heartbeat")
        claimed = await service.claim_next_job(
            worker_id="ordered-worker", lease_seconds=30, now=claim_time
        )
        assert claimed is not None
        await db.commit()
        job_id = job.id
        attempt_id = claimed[1].id

    latest_heartbeat = claim_time + timedelta(seconds=15)
    async with async_session() as db:
        service = JobService(db)
        latest_job, latest_attempt = await service.renew_job_lease(
            job_id=job_id,
            attempt_id=attempt_id,
            worker_id="ordered-worker",
            lease_seconds=60,
            now=latest_heartbeat,
        )
        latest_expiry = latest_job.lease_expires_at
        latest_attempt_expiry = latest_attempt.lease_expires_at
        stale_job, stale_attempt = await service.renew_job_lease(
            job_id=job_id,
            attempt_id=attempt_id,
            worker_id="ordered-worker",
            lease_seconds=10,
            now=claim_time + timedelta(seconds=5),
        )
        await db.commit()

        assert stale_job.heartbeat_at == latest_heartbeat
        assert stale_attempt.heartbeat_at == latest_heartbeat
        assert stale_job.lease_expires_at == latest_expiry
        assert stale_attempt.lease_expires_at == latest_attempt_expiry


@pytest.mark.asyncio
async def test_renew_job_lease_rejects_wrong_or_expired_lease_without_partial_update(
    client,
):
    claim_time = utc_now_naive()
    async with async_session() as db:
        service = JobService(db)
        job, _ = await service.create_job(job_type="heartbeat_guard")
        claimed = await service.claim_next_job(
            worker_id="lease-owner", lease_seconds=20, now=claim_time
        )
        assert claimed is not None
        await db.commit()
        job_id = job.id
        attempt_id = claimed[1].id
        original_expiry = claimed[0].lease_expires_at

    async with async_session() as db:
        service = JobService(db)
        with pytest.raises(JobLeaseLost):
            await service.renew_job_lease(
                job_id=job_id,
                attempt_id=attempt_id,
                worker_id="stale-worker",
                now=claim_time + timedelta(seconds=1),
            )
        with pytest.raises(JobLeaseLost):
            await service.renew_job_lease(
                job_id=job_id,
                attempt_id=attempt_id + 1,
                worker_id="lease-owner",
                now=claim_time + timedelta(seconds=1),
            )
        with pytest.raises(JobLeaseLost):
            await service.renew_job_lease(
                job_id=job_id,
                attempt_id=attempt_id,
                worker_id="lease-owner",
                now=claim_time + timedelta(seconds=20),
            )
        await db.commit()

    async with async_session() as db:
        stored_job = (
            await db.execute(select(Job).where(Job.id == job_id))
        ).scalar_one()
        stored_attempt = (
            await db.execute(select(JobAttempt).where(JobAttempt.id == attempt_id))
        ).scalar_one()
        assert stored_job.lease_expires_at == original_expiry
        assert stored_attempt.lease_expires_at == original_expiry


@pytest.mark.asyncio
async def test_start_and_heartbeat_changes_follow_caller_transaction(client):
    claim_time = utc_now_naive()
    async with async_session() as db:
        service = JobService(db)
        job, _ = await service.create_job(job_type="lease_rollback")
        claimed = await service.claim_next_job(
            worker_id="rollback-worker", lease_seconds=60, now=claim_time
        )
        assert claimed is not None
        await db.commit()
        job_id = job.id
        attempt_id = claimed[1].id
        original_expiry = claimed[0].lease_expires_at

    async with async_session() as db:
        service = JobService(db)
        await service.start_claimed_job(
            job_id=job_id,
            attempt_id=attempt_id,
            worker_id="rollback-worker",
            now=claim_time + timedelta(seconds=1),
        )
        await service.renew_job_lease(
            job_id=job_id,
            attempt_id=attempt_id,
            worker_id="rollback-worker",
            lease_seconds=120,
            now=claim_time + timedelta(seconds=2),
        )
        await db.rollback()

    async with async_session() as db:
        stored_job = (
            await db.execute(select(Job).where(Job.id == job_id))
        ).scalar_one()
        stored_attempt = (
            await db.execute(select(JobAttempt).where(JobAttempt.id == attempt_id))
        ).scalar_one()
        running_events = (
            await db.execute(
                select(func.count(JobEvent.id)).where(
                    JobEvent.job_id == job_id,
                    JobEvent.to_status == JobStatus.RUNNING.value,
                )
            )
        ).scalar_one()
        assert stored_job.status == JobStatus.LEASED.value
        assert stored_attempt.status == JobStatus.LEASED.value
        assert stored_job.lease_expires_at == original_expiry
        assert stored_attempt.lease_expires_at == original_expiry
        assert running_events == 0


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
