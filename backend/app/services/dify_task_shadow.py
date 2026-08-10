from __future__ import annotations

import copy
import logging
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.session import async_session
from app.models.dify_task import DifyTask
from app.models.job import Job, JobStatus, TERMINAL_JOB_STATUSES
from app.services.job_service import JobService
from app.utils.timezone import aware_or_cst_naive_to_utc_naive, utc_now_naive


logger = logging.getLogger(__name__)

DIFY_JOB_TYPE = "dify_workflow"
DIFY_WORKER_TYPE = "legacy_shadow"
DIFY_SOURCE_TYPE = "dify_task"
DIFY_DELETED_SOURCE_TYPE = "dify_task_deleted"
DIFY_TERMINAL_STATUSES = frozenset({"succeeded", "failed", "cancelled"})
DIFY_TO_JOB_STATUS = {
    "pending": JobStatus.QUEUED.value,
    "queued": JobStatus.QUEUED.value,
    "running": JobStatus.RUNNING.value,
    "succeeded": JobStatus.SUCCEEDED.value,
    "failed": JobStatus.FAILED.value,
    "cancelled": JobStatus.CANCELLED.value,
}


class DifyTaskShadowAdapter:
    """Mirror a legacy Dify task without executing or querying Dify."""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.jobs = JobService(db)

    async def mirror(self, task_id: int) -> Job | None:
        task = await self.db.get(DifyTask, int(task_id))
        if task is None:
            return None
        job = await self._ensure_job(task)
        await self._mirror_status(job, task)
        self._mirror_progress(job, task)
        await self.db.flush()
        return job

    async def detach_deleted(self, task_id: int) -> Job | None:
        job = await self._load_job(task_id)
        if job is None:
            return None
        if job.source_type == DIFY_DELETED_SOURCE_TYPE:
            return job
        payload = copy.deepcopy(job.payload or {})
        payload["legacy_source_deleted"] = True
        payload["legacy_source_deleted_at"] = utc_now_naive().isoformat()
        job.payload = payload
        job.source_type = DIFY_DELETED_SOURCE_TYPE
        await self.jobs.append_event(
            job,
            event_type="legacy_source_deleted",
            message="Legacy Dify task record deleted",
            details={"legacy_task_id": int(task_id)},
            actor_type="legacy_shadow",
            actor_id=str(task_id),
        )
        await self.db.flush()
        return job

    async def _ensure_job(self, task: DifyTask) -> Job:
        existing = await self._load_job(int(task.id))
        if existing is not None:
            return existing
        job, _ = await self.jobs.create_job(
            job_type=DIFY_JOB_TYPE,
            worker_type=DIFY_WORKER_TYPE,
            scope_key=f"user:{int(task.user_id)}",
            requested_by_user_id=int(task.user_id),
            idempotency_key=f"legacy-dify-task:{int(task.id)}",
            source_type=DIFY_SOURCE_TYPE,
            source_id=str(int(task.id)),
            progress_total=1,
            payload=_task_payload(task),
            actor_type="legacy_shadow",
            actor_id=str(int(task.id)),
        )
        return job

    async def _load_job(self, task_id: int) -> Job | None:
        return (
            await self.db.execute(
                select(Job).where(
                    Job.source_type.in_(
                        (DIFY_SOURCE_TYPE, DIFY_DELETED_SOURCE_TYPE)
                    ),
                    Job.source_id == str(int(task_id)),
                )
            )
        ).scalar_one_or_none()

    async def _mirror_status(self, job: Job, task: DifyTask) -> None:
        legacy_status = str(task.status or "pending").strip().lower()
        target = DIFY_TO_JOB_STATUS.get(legacy_status)
        if target is None or target == JobStatus.QUEUED.value:
            return
        if job.status in TERMINAL_JOB_STATUSES:
            return

        transition_time = _task_transition_time(task)
        if target == JobStatus.RUNNING.value:
            await self._ensure_running(job, task, now=transition_time)
            return
        if target == JobStatus.SUCCEEDED.value or (
            target == JobStatus.FAILED.value
            and (task.task_id or task.elapsed_ms is not None)
        ):
            await self._ensure_running(job, task, now=_task_started_at(task))

        await self.jobs.transition(
            job,
            target,
            message=_status_message(legacy_status),
            error_code="dify_workflow_failed"
            if target == JobStatus.FAILED.value
            else None,
            user_message=_bounded_text(task.error)
            if target == JobStatus.FAILED.value
            else None,
            internal_error=_bounded_text(task.error)
            if target == JobStatus.FAILED.value
            else None,
            result_summary=_task_result_summary(task),
            actor_type="legacy_shadow",
            actor_id=str(int(task.id)),
            now=transition_time,
        )

    async def _ensure_running(
        self,
        job: Job,
        task: DifyTask,
        *,
        now: datetime,
    ) -> None:
        if job.status == JobStatus.QUEUED.value:
            await self.jobs.transition(
                job,
                JobStatus.LEASED,
                message="Legacy Dify task accepted",
                actor_type="legacy_shadow",
                actor_id=str(int(task.id)),
                now=now,
            )
        if job.status == JobStatus.LEASED.value:
            await self.jobs.transition(
                job,
                JobStatus.RUNNING,
                message="Legacy Dify task started",
                actor_type="legacy_shadow",
                actor_id=str(int(task.id)),
                now=now,
            )

    @staticmethod
    def _mirror_progress(job: Job, task: DifyTask) -> None:
        legacy_status = str(task.status or "pending").strip().lower()
        job.progress_total = 1
        job.progress_current = 1 if legacy_status in DIFY_TERMINAL_STATUSES else 0
        job.current_step = _bounded_text(task.progress, limit=160) or _status_message(
            legacy_status
        )
        if legacy_status in DIFY_TERMINAL_STATUSES:
            job.result_summary = _task_result_summary(task)


async def mirror_dify_task_safely(task_id: int | None) -> None:
    if not settings.dify_task_shadow_enabled or not task_id:
        return
    try:
        async with async_session() as db:
            await DifyTaskShadowAdapter(db).mirror(int(task_id))
            await db.commit()
    except Exception:
        logger.exception("Dify task shadow mirror failed: task_id=%s", task_id)


async def detach_deleted_dify_task_safely(task_id: int | None) -> None:
    if not settings.dify_task_shadow_enabled or not task_id:
        return
    try:
        async with async_session() as db:
            await DifyTaskShadowAdapter(db).detach_deleted(int(task_id))
            await db.commit()
    except Exception:
        logger.exception("Dify task shadow detach failed: task_id=%s", task_id)


def _task_payload(task: DifyTask) -> dict[str, Any]:
    return {
        "shadow_mode": True,
        "legacy_task_id": int(task.id),
        "workflow_id": int(task.workflow_id),
        "user_id": int(task.user_id),
        "inputs": _data_shape(task.inputs),
    }


def _task_result_summary(task: DifyTask) -> dict[str, Any]:
    return {
        "shadow_mode": True,
        "legacy_task_id": int(task.id),
        "legacy_status": str(task.status or ""),
        "workflow_id": int(task.workflow_id),
        "upstream_task_id": _bounded_text(task.task_id, limit=100),
        "elapsed_ms": _safe_float(task.elapsed_ms),
        "outputs": _data_shape(task.outputs),
    }


def _data_shape(value: Any) -> dict[str, Any]:
    source = value if isinstance(value, dict) else {}
    normalized = {str(key)[:80]: item for key, item in source.items()}
    keys = sorted(normalized)
    visible_keys = keys[:50]
    return {
        "field_count": len(source),
        "field_names": visible_keys,
        "field_types": {
            key: _value_type(normalized.get(key)) for key in visible_keys
        },
        "is_truncated": len(source) > len(visible_keys),
    }


def _value_type(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, (int, float)):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, dict):
        return "object"
    if isinstance(value, (list, tuple)):
        return "array"
    return "other"


def _task_transition_time(task: DifyTask) -> datetime:
    if task.finished_at is not None:
        converted = aware_or_cst_naive_to_utc_naive(task.finished_at)
        if converted is not None:
            return converted
    return utc_now_naive()


def _task_started_at(task: DifyTask) -> datetime:
    finished = aware_or_cst_naive_to_utc_naive(task.finished_at)
    elapsed_ms = _safe_float(task.elapsed_ms)
    if finished is not None and elapsed_ms is not None and elapsed_ms >= 0:
        return finished - timedelta(milliseconds=elapsed_ms)
    created = aware_or_cst_naive_to_utc_naive(task.created_at)
    return created or utc_now_naive()


def _status_message(status: str) -> str:
    return {
        "pending": "Dify 工作流等待执行",
        "queued": "Dify 工作流排队中",
        "running": "Dify 工作流执行中",
        "succeeded": "Dify 工作流执行完成",
        "failed": "Dify 工作流执行失败",
        "cancelled": "Dify 工作流已取消",
    }.get(status, f"Dify 工作流状态：{status or 'unknown'}")


def _bounded_text(value: Any, *, limit: int = 1000) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text[:limit] or None


def _safe_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return round(float(value), 3)
    except (TypeError, ValueError):
        return None
