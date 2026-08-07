from __future__ import annotations

import copy
import uuid
from collections.abc import Collection
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.dml import Update

from app.models.job import (
    Job,
    JobAttempt,
    JobEvent,
    JobItem,
    JobStatus,
    TERMINAL_JOB_STATUSES,
)
from app.utils.timezone import utc_now_naive


ALLOWED_JOB_TRANSITIONS: dict[str, frozenset[str]] = {
    JobStatus.QUEUED.value: frozenset(
        {JobStatus.LEASED.value, JobStatus.CANCELLED.value, JobStatus.FAILED.value}
    ),
    JobStatus.LEASED.value: frozenset(
        {
            JobStatus.RUNNING.value,
            JobStatus.QUEUED.value,
            JobStatus.RETRY_WAIT.value,
            JobStatus.FAILED.value,
            JobStatus.CANCELLED.value,
            JobStatus.DEAD_LETTER.value,
        }
    ),
    JobStatus.RUNNING.value: frozenset(
        {
            JobStatus.SUCCEEDED.value,
            JobStatus.RETRY_WAIT.value,
            JobStatus.WAITING_REVIEW.value,
            JobStatus.FAILED.value,
            JobStatus.CANCELLED.value,
            JobStatus.DEAD_LETTER.value,
        }
    ),
    JobStatus.RETRY_WAIT.value: frozenset(
        {
            JobStatus.QUEUED.value,
            JobStatus.FAILED.value,
            JobStatus.CANCELLED.value,
            JobStatus.DEAD_LETTER.value,
        }
    ),
    JobStatus.WAITING_REVIEW.value: frozenset(
        {
            JobStatus.QUEUED.value,
            JobStatus.SUCCEEDED.value,
            JobStatus.FAILED.value,
            JobStatus.CANCELLED.value,
        }
    ),
    JobStatus.SUCCEEDED.value: frozenset(),
    JobStatus.FAILED.value: frozenset(),
    JobStatus.CANCELLED.value: frozenset(),
    JobStatus.DEAD_LETTER.value: frozenset(),
}


class JobStateError(ValueError):
    pass


class InvalidJobTransition(JobStateError):
    def __init__(self, current_status: str, target_status: str):
        super().__init__(f"invalid job transition: {current_status} -> {target_status}")
        self.current_status = current_status
        self.target_status = target_status


class InvalidJobProgress(JobStateError):
    pass


def normalize_job_status(status: JobStatus | str) -> str:
    value = status.value if isinstance(status, JobStatus) else str(status).strip()
    if value not in ALLOWED_JOB_TRANSITIONS:
        raise JobStateError(f"unknown job status: {value}")
    return value


class JobService:
    """Transaction-scoped operations for the durable job kernel.

    Methods flush but never commit. The API or worker owns the surrounding
    transaction so a business write and its job event can commit atomically.
    """

    def __init__(self, db: AsyncSession):
        self.db = db

    async def create_job(
        self,
        *,
        job_type: str,
        payload: dict[str, Any] | None = None,
        scope_key: str = "internal",
        worker_type: str = "server",
        requested_by_user_id: int | None = None,
        parent_job_id: int | None = None,
        idempotency_key: str | None = None,
        source_type: str | None = None,
        source_id: str | None = None,
        priority: int = 100,
        max_retries: int = 3,
        progress_total: int = 0,
        actor_type: str = "system",
        actor_id: str | None = None,
    ) -> tuple[Job, bool]:
        normalized_type = job_type.strip()
        normalized_scope = scope_key.strip() or "internal"
        normalized_key = (idempotency_key or "").strip() or None
        if not normalized_type:
            raise ValueError("job_type must not be empty")
        if priority < 0:
            raise ValueError("priority must be non-negative")
        if max_retries < 0:
            raise ValueError("max_retries must be non-negative")
        if progress_total < 0:
            raise InvalidJobProgress("progress_total must be non-negative")

        if normalized_key:
            existing = await self._find_idempotent_job(
                scope_key=normalized_scope,
                job_type=normalized_type,
                idempotency_key=normalized_key,
            )
            if existing is not None:
                return existing, False

        values = {
            "public_id": str(uuid.uuid4()),
            "scope_key": normalized_scope,
            "requested_by_user_id": requested_by_user_id,
            "parent_job_id": parent_job_id,
            "job_type": normalized_type,
            "worker_type": worker_type.strip() or "server",
            "status": JobStatus.QUEUED.value,
            "priority": priority,
            "idempotency_key": normalized_key,
            "source_type": (source_type or "").strip() or None,
            "source_id": (source_id or "").strip() or None,
            "payload": copy.deepcopy(payload or {}),
            "progress_current": 0,
            "progress_total": progress_total,
            "retry_count": 0,
            "max_retries": max_retries,
            "cancel_requested": False,
        }

        if normalized_key:
            inserted_id = await self._insert_job_idempotently(values)
            if inserted_id is None:
                existing = await self._find_idempotent_job(
                    scope_key=normalized_scope,
                    job_type=normalized_type,
                    idempotency_key=normalized_key,
                )
                if existing is None:
                    raise RuntimeError("idempotent job insert lost its conflict row")
                return existing, False
            job = await self.db.get(Job, inserted_id)
            if job is None:
                raise RuntimeError("created job could not be loaded")
        else:
            job = Job(**values)
            self.db.add(job)
            await self.db.flush()

        await self._append_event(
            job=job,
            event_type="job_created",
            to_status=JobStatus.QUEUED.value,
            message="Job created",
            details={"worker_type": job.worker_type},
            actor_type=actor_type,
            actor_id=actor_id,
        )
        await self.db.flush()
        return job, True

    async def add_item(
        self,
        job: Job,
        *,
        item_key: str,
        item_type: str | None = None,
        display_name: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> tuple[JobItem, bool]:
        normalized_key = item_key.strip()
        if not normalized_key:
            raise ValueError("item_key must not be empty")
        if job.id is None:
            await self.db.flush()

        existing = (
            await self.db.execute(
                select(JobItem).where(
                    JobItem.job_id == job.id,
                    JobItem.item_key == normalized_key,
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            return existing, False

        values = {
            "job_id": job.id,
            "item_key": normalized_key,
            "item_type": (item_type or "").strip() or None,
            "display_name": (display_name or "").strip() or None,
            "status": JobStatus.QUEUED.value,
            "payload": copy.deepcopy(payload or {}),
            "attempt_count": 0,
        }
        inserted_id = await self._insert_item_idempotently(values)
        if inserted_id is None:
            existing = (
                await self.db.execute(
                    select(JobItem).where(
                        JobItem.job_id == job.id,
                        JobItem.item_key == normalized_key,
                    )
                )
            ).scalar_one_or_none()
            if existing is None:
                raise RuntimeError("idempotent job item insert lost its conflict row")
            return existing, False
        item = await self.db.get(JobItem, inserted_id)
        if item is None:
            raise RuntimeError("created job item could not be loaded")
        return item, True

    async def claim_next_job(
        self,
        *,
        worker_id: str,
        worker_type: str = "server",
        lease_seconds: int = 60,
        job_types: Collection[str] | None = None,
        now: datetime | None = None,
    ) -> tuple[Job, JobAttempt] | None:
        """Atomically lease the next eligible job for a worker.

        Lower priority numbers run first. The caller owns the transaction and
        must commit the returned lease before executing external side effects.
        """

        normalized_worker_id = worker_id.strip()
        normalized_worker_type = worker_type.strip()
        if not normalized_worker_id:
            raise ValueError("worker_id must not be empty")
        if not normalized_worker_type:
            raise ValueError("worker_type must not be empty")
        if lease_seconds <= 0:
            raise ValueError("lease_seconds must be positive")

        normalized_job_types: tuple[str, ...] | None = None
        if job_types is not None:
            raw_job_types = (job_types,) if isinstance(job_types, str) else job_types
            normalized_job_types = tuple(
                sorted({value.strip() for value in raw_job_types if value.strip()})
            )
            if not normalized_job_types:
                raise ValueError("job_types must contain at least one non-empty value")

        claim_time = now or utc_now_naive()
        lease_expires_at = claim_time + timedelta(seconds=lease_seconds)
        bind = self.db.get_bind()
        dialect_name = bind.dialect.name if bind is not None else ""
        claim_statement = self._build_claim_statement(
            worker_type=normalized_worker_type,
            job_types=normalized_job_types,
            claim_time=claim_time,
            lease_owner=normalized_worker_id,
            lease_expires_at=lease_expires_at,
            dialect_name=dialect_name,
        )
        claimed_id = (await self.db.execute(claim_statement)).scalar_one_or_none()
        if claimed_id is None:
            return None

        job = await self.db.get(Job, claimed_id)
        if job is None:
            raise RuntimeError("claimed job could not be loaded")
        await self.db.refresh(job)

        attempt_number = int(
            (
                await self.db.execute(
                    select(
                        func.coalesce(func.max(JobAttempt.attempt_number), 0) + 1
                    ).where(JobAttempt.job_id == job.id)
                )
            ).scalar_one()
        )
        attempt = JobAttempt(
            job_id=job.id,
            attempt_number=attempt_number,
            worker_id=normalized_worker_id,
            status=JobStatus.LEASED.value,
            lease_expires_at=lease_expires_at,
            heartbeat_at=claim_time,
            metrics={},
            started_at=claim_time,
        )
        self.db.add(attempt)
        await self.db.flush()
        await self._append_event(
            job=job,
            event_type="status_changed",
            from_status=JobStatus.QUEUED.value,
            to_status=JobStatus.LEASED.value,
            message="Job leased",
            details={
                "attempt_id": attempt.id,
                "attempt_number": attempt.attempt_number,
                "lease_expires_at": lease_expires_at.isoformat(),
            },
            actor_type="worker",
            actor_id=normalized_worker_id,
            created_at=claim_time,
        )
        await self.db.flush()
        return job, attempt

    @staticmethod
    def _build_claim_statement(
        *,
        worker_type: str,
        job_types: tuple[str, ...] | None,
        claim_time: datetime,
        lease_owner: str,
        lease_expires_at: datetime,
        dialect_name: str,
    ) -> Update:
        eligible_conditions = [
            Job.status == JobStatus.QUEUED.value,
            Job.cancel_requested.is_(False),
            Job.worker_type == worker_type,
            or_(Job.run_after.is_(None), Job.run_after <= claim_time),
        ]
        if job_types is not None:
            eligible_conditions.append(Job.job_type.in_(job_types))

        candidate = (
            select(Job.id)
            .where(and_(*eligible_conditions))
            .order_by(Job.priority.asc(), Job.created_at.asc(), Job.id.asc())
            .limit(1)
        )
        if dialect_name == "postgresql":
            candidate = candidate.with_for_update(skip_locked=True)
        elif dialect_name != "sqlite":
            raise RuntimeError(
                f"durable jobs do not support database dialect: {dialect_name or 'unknown'}"
            )

        return (
            update(Job)
            .where(
                Job.id == candidate.scalar_subquery(),
                and_(*eligible_conditions),
            )
            .values(
                status=JobStatus.LEASED.value,
                lease_owner=lease_owner,
                lease_expires_at=lease_expires_at,
                heartbeat_at=claim_time,
                run_after=None,
            )
            .returning(Job.id)
            .execution_options(synchronize_session=False)
        )

    async def transition(
        self,
        job: Job,
        target_status: JobStatus | str,
        *,
        message: str | None = None,
        error_code: str | None = None,
        user_message: str | None = None,
        internal_error: str | None = None,
        result_summary: dict[str, Any] | None = None,
        run_after: datetime | None = None,
        details: dict[str, Any] | None = None,
        actor_type: str = "system",
        actor_id: str | None = None,
        now: datetime | None = None,
    ) -> bool:
        current_status = normalize_job_status(job.status)
        normalized_target = normalize_job_status(target_status)
        if current_status == normalized_target:
            return False
        if normalized_target not in ALLOWED_JOB_TRANSITIONS[current_status]:
            raise InvalidJobTransition(current_status, normalized_target)

        transition_time = now or utc_now_naive()
        job.status = normalized_target
        if normalized_target == JobStatus.RUNNING.value and job.started_at is None:
            job.started_at = transition_time
        if normalized_target in TERMINAL_JOB_STATUSES:
            job.finished_at = transition_time
        if normalized_target in {
            JobStatus.QUEUED.value,
            JobStatus.RETRY_WAIT.value,
            *TERMINAL_JOB_STATUSES,
        }:
            job.lease_owner = None
            job.lease_expires_at = None
            job.heartbeat_at = None
        if normalized_target == JobStatus.RETRY_WAIT.value:
            job.run_after = run_after
        else:
            job.run_after = None

        if error_code is not None:
            job.error_code = error_code
        if user_message is not None:
            job.user_message = user_message
        if internal_error is not None:
            job.internal_error = internal_error
        if result_summary is not None:
            job.result_summary = copy.deepcopy(result_summary)

        await self._append_event(
            job=job,
            event_type="status_changed",
            from_status=current_status,
            to_status=normalized_target,
            message=message,
            details=details,
            actor_type=actor_type,
            actor_id=actor_id,
            created_at=transition_time,
        )
        await self.db.flush()
        return True

    async def schedule_retry(
        self,
        job: Job,
        *,
        run_after: datetime,
        error_code: str | None = None,
        user_message: str | None = None,
        internal_error: str | None = None,
        actor_type: str = "worker",
        actor_id: str | None = None,
        now: datetime | None = None,
    ) -> str:
        current_status = normalize_job_status(job.status)
        if current_status not in {JobStatus.LEASED.value, JobStatus.RUNNING.value}:
            raise InvalidJobTransition(current_status, JobStatus.RETRY_WAIT.value)

        next_retry_count = int(job.retry_count or 0) + 1
        job.retry_count = next_retry_count
        if next_retry_count > int(job.max_retries or 0):
            target = JobStatus.DEAD_LETTER.value
            retry_at = None
        else:
            target = JobStatus.RETRY_WAIT.value
            retry_at = run_after

        await self.transition(
            job,
            target,
            message="Retry scheduled" if retry_at else "Retry limit exhausted",
            error_code=error_code,
            user_message=user_message,
            internal_error=internal_error,
            run_after=retry_at,
            details={
                "retry_count": next_retry_count,
                "max_retries": int(job.max_retries or 0),
            },
            actor_type=actor_type,
            actor_id=actor_id,
            now=now,
        )
        return target

    async def set_progress(
        self,
        job: Job,
        *,
        current: int,
        total: int | None = None,
        current_step: str | None = None,
    ) -> None:
        existing_current = int(job.progress_current or 0)
        existing_total = int(job.progress_total or 0)
        next_total = existing_total if total is None else total
        if current < 0 or next_total < 0:
            raise InvalidJobProgress("progress values must be non-negative")
        if current < existing_current:
            raise InvalidJobProgress("progress_current must not move backwards")
        if total is not None and next_total < existing_total:
            raise InvalidJobProgress("progress_total must not move backwards")
        if next_total > 0 and current > next_total:
            raise InvalidJobProgress("progress_current must not exceed progress_total")

        job.progress_current = current
        job.progress_total = next_total
        if current_step is not None:
            job.current_step = current_step.strip() or None
        await self.db.flush()

    async def request_cancel(
        self,
        job: Job,
        *,
        actor_type: str = "user",
        actor_id: str | None = None,
        message: str = "Cancellation requested",
    ) -> bool:
        current_status = normalize_job_status(job.status)
        if current_status in TERMINAL_JOB_STATUSES or job.cancel_requested:
            return False
        job.cancel_requested = True
        await self._append_event(
            job=job,
            event_type="cancel_requested",
            from_status=current_status,
            to_status=current_status,
            message=message,
            actor_type=actor_type,
            actor_id=actor_id,
        )
        await self.db.flush()
        return True

    async def _find_idempotent_job(
        self,
        *,
        scope_key: str,
        job_type: str,
        idempotency_key: str,
    ) -> Job | None:
        return (
            await self.db.execute(
                select(Job).where(
                    Job.scope_key == scope_key,
                    Job.job_type == job_type,
                    Job.idempotency_key == idempotency_key,
                )
            )
        ).scalar_one_or_none()

    def _dialect_insert(self, model):
        bind = self.db.get_bind()
        dialect_name = bind.dialect.name if bind is not None else ""
        if dialect_name == "postgresql":
            return postgresql_insert(model)
        if dialect_name == "sqlite":
            return sqlite_insert(model)
        raise RuntimeError(
            f"durable jobs do not support database dialect: {dialect_name or 'unknown'}"
        )

    async def _insert_job_idempotently(self, values: dict[str, Any]) -> int | None:
        statement = self._dialect_insert(Job).values(**values)
        statement = statement.on_conflict_do_nothing(
            index_elements=[Job.scope_key, Job.job_type, Job.idempotency_key]
        ).returning(Job.id)
        return (await self.db.execute(statement)).scalar_one_or_none()

    async def _insert_item_idempotently(self, values: dict[str, Any]) -> int | None:
        statement = self._dialect_insert(JobItem).values(**values)
        statement = statement.on_conflict_do_nothing(
            index_elements=[JobItem.job_id, JobItem.item_key]
        ).returning(JobItem.id)
        return (await self.db.execute(statement)).scalar_one_or_none()

    async def _append_event(
        self,
        *,
        job: Job,
        event_type: str,
        from_status: str | None = None,
        to_status: str | None = None,
        level: str = "info",
        message: str | None = None,
        details: dict[str, Any] | None = None,
        actor_type: str = "system",
        actor_id: str | None = None,
        created_at: datetime | None = None,
    ) -> JobEvent:
        if job.id is None:
            await self.db.flush()
        event = JobEvent(
            job_id=job.id,
            event_type=event_type,
            from_status=from_status,
            to_status=to_status,
            level=level,
            message=message,
            details=copy.deepcopy(details or {}),
            actor_type=actor_type,
            actor_id=actor_id,
            created_at=created_at or utc_now_naive(),
        )
        self.db.add(event)
        return event
