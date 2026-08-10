from __future__ import annotations

import copy
import hashlib
import logging
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.session import async_session
from app.models.ai_task import AITask
from app.models.job import Job, JobStatus, TERMINAL_JOB_STATUSES
from app.services.job_service import JobService
from app.utils.timezone import utc_now_naive


logger = logging.getLogger(__name__)

AI_SHADOW_JOB_TYPE = "ai_image_generation"
AI_SHADOW_WORKER_TYPE = "legacy_shadow"
AI_SHADOW_SOURCE_TYPE = "ai_task"
AI_SHADOW_PROGRESS_TOTAL = 6
AI_SHADOW_PHASE_PROGRESS = {
    "queued": 0,
    "enqueue_failed": 0,
    "worker_recovered": 0,
    "worker_started": 1,
    "upstream_started": 1,
    "provider_selected": 2,
    "upstream_finished": 3,
    "result_stored": 4,
    "watermark_finished": 5,
    "completed": 6,
}
MAX_PHASE_HISTORY = 50


class AIImageShadowAdapter:
    """Mirror legacy AI image tasks without owning or repeating generation."""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.jobs = JobService(db)

    async def mirror(
        self,
        task_id: int,
        *,
        phase: str | None = None,
        details: dict[str, Any] | None = None,
        result_unknown: bool = False,
    ) -> Job | None:
        task = await self.db.get(AITask, int(task_id))
        if task is None:
            return None

        job = await self._ensure_shadow_job(task)
        normalized_phase = (phase or _phase_for_task(task)).strip() or "queued"
        safe_details = _sanitize_details(details or {})
        self._record_phase(
            job,
            phase=normalized_phase,
            details=safe_details,
            result_unknown=result_unknown,
        )
        await self._mirror_status(
            job,
            task,
            phase=normalized_phase,
            result_unknown=result_unknown,
        )
        self._mirror_summary(
            job,
            task,
            phase=normalized_phase,
            details=safe_details,
            result_unknown=result_unknown,
        )
        await self.db.flush()
        return job

    async def _ensure_shadow_job(self, task: AITask) -> Job:
        existing = (
            await self.db.execute(
                select(Job).where(
                    Job.job_type == AI_SHADOW_JOB_TYPE,
                    Job.worker_type == AI_SHADOW_WORKER_TYPE,
                    Job.source_type == AI_SHADOW_SOURCE_TYPE,
                    Job.source_id == str(task.id),
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            return existing

        params: dict[str, Any] = task.params if isinstance(task.params, dict) else {}
        job, _ = await self.jobs.create_job(
            job_type=AI_SHADOW_JOB_TYPE,
            worker_type=AI_SHADOW_WORKER_TYPE,
            scope_key=f"user:{int(task.user_id or 0)}",
            requested_by_user_id=int(task.user_id) if task.user_id else None,
            idempotency_key=f"legacy-ai-task:{int(task.id)}",
            source_type=AI_SHADOW_SOURCE_TYPE,
            source_id=str(task.id),
            max_retries=0,
            progress_total=AI_SHADOW_PROGRESS_TOTAL,
            payload={
                "shadow_mode": True,
                "legacy_task_id": int(task.id),
                "client_request_id": task.client_request_id,
                "model_name": task.model_name,
                "prompt_sha256": hashlib.sha256(
                    (task.prompt or "").encode("utf-8")
                ).hexdigest(),
                "prompt_length": len(task.prompt or ""),
                "request": _request_snapshot(params),
                "phase_history": [],
            },
            actor_type="legacy_shadow",
            actor_id=str(task.id),
        )
        if task.created_at is not None:
            job.created_at = task.created_at
        return job

    async def _mirror_status(
        self,
        job: Job,
        task: AITask,
        *,
        phase: str,
        result_unknown: bool,
    ) -> None:
        legacy_status = str(task.status or "queued").strip().lower()
        previously_unknown = bool(
            isinstance(job.result_summary, dict)
            and job.result_summary.get("result_certainty") == "unknown"
        )

        if result_unknown:
            if job.status in TERMINAL_JOB_STATUSES:
                return
            await self._ensure_running(job, task, allow_review_resume=False)
            if job.status == JobStatus.RUNNING.value:
                await self.jobs.transition(
                    job,
                    JobStatus.WAITING_REVIEW,
                    message="AI image result requires reconciliation",
                    error_code="upstream_result_unknown",
                    user_message="上游可能已受理，正在等待结果核验",
                    internal_error=_optional_text(task.error),
                    details={"legacy_status": legacy_status, "phase": phase},
                    actor_type="legacy_shadow",
                    actor_id=str(task.id),
                    now=_optional_datetime(task.finished_at) or utc_now_naive(),
                )
            return

        if legacy_status == "queued":
            return
        if legacy_status == "processing":
            await self._ensure_running(job, task, allow_review_resume=True)
            return
        if legacy_status == "completed":
            if job.status in TERMINAL_JOB_STATUSES:
                return
            await self._ensure_running(job, task, allow_review_resume=True)
            if job.status == JobStatus.RUNNING.value:
                await self.jobs.transition(
                    job,
                    JobStatus.SUCCEEDED,
                    message="Legacy AI image task completed",
                    result_summary=copy.deepcopy(job.result_summary or {}),
                    actor_type="legacy_shadow",
                    actor_id=str(task.id),
                    now=_optional_datetime(task.finished_at) or utc_now_naive(),
                )
            return
        if legacy_status == "failed":
            if previously_unknown or job.status == JobStatus.WAITING_REVIEW.value:
                return
            if job.status in TERMINAL_JOB_STATUSES:
                return
            if _task_started_at(task) is not None:
                await self._ensure_running(job, task, allow_review_resume=False)
            if job.status in {
                JobStatus.QUEUED.value,
                JobStatus.LEASED.value,
                JobStatus.RUNNING.value,
            }:
                if job.status == JobStatus.LEASED.value:
                    await self._ensure_running(job, task, allow_review_resume=False)
                await self.jobs.transition(
                    job,
                    JobStatus.FAILED,
                    message="Legacy AI image task failed",
                    error_code="legacy_ai_image_failed",
                    user_message=_optional_text(task.error),
                    internal_error=_optional_text(task.error),
                    actor_type="legacy_shadow",
                    actor_id=str(task.id),
                    now=_optional_datetime(task.finished_at) or utc_now_naive(),
                )
            return
        if legacy_status == "cancelled":
            if job.status in TERMINAL_JOB_STATUSES:
                return
            if job.status == JobStatus.WAITING_REVIEW.value:
                await self.jobs.transition(
                    job,
                    JobStatus.CANCELLED,
                    message="Legacy AI image task cancelled during reconciliation",
                    actor_type="legacy_shadow",
                    actor_id=str(task.id),
                    now=_optional_datetime(task.finished_at) or utc_now_naive(),
                )
                return
            if _task_started_at(task) is not None:
                await self._ensure_running(job, task, allow_review_resume=False)
            await self.jobs.transition(
                job,
                JobStatus.CANCELLED,
                message="Legacy AI image task cancelled",
                actor_type="legacy_shadow",
                actor_id=str(task.id),
                now=_optional_datetime(task.finished_at) or utc_now_naive(),
            )

    async def _ensure_running(
        self,
        job: Job,
        task: AITask,
        *,
        allow_review_resume: bool,
    ) -> None:
        started_at = _task_started_at(task) or utc_now_naive()
        if job.status == JobStatus.WAITING_REVIEW.value and allow_review_resume:
            await self.jobs.transition(
                job,
                JobStatus.QUEUED,
                message="Legacy AI image task resumed after an unknown result",
                details={"duplicate_charge_risk": True},
                actor_type="legacy_shadow",
                actor_id=str(task.id),
                now=started_at,
            )
        if job.status == JobStatus.QUEUED.value:
            await self.jobs.transition(
                job,
                JobStatus.LEASED,
                message="Legacy AI image worker accepted task",
                actor_type="legacy_shadow",
                actor_id=str(task.id),
                now=started_at,
            )
        if job.status == JobStatus.LEASED.value:
            await self.jobs.transition(
                job,
                JobStatus.RUNNING,
                message="Legacy AI image generation started",
                actor_type="legacy_shadow",
                actor_id=str(task.id),
                now=started_at,
            )

    @staticmethod
    def _record_phase(
        job: Job,
        *,
        phase: str,
        details: dict[str, Any],
        result_unknown: bool,
    ) -> None:
        payload = copy.deepcopy(job.payload or {})
        history = list(payload.get("phase_history") or [])
        comparable = {
            "phase": phase,
            "details": details,
            "result_unknown": result_unknown,
        }
        last = history[-1] if history else None
        if (
            not isinstance(last, dict)
            or {
                "phase": last.get("phase"),
                "details": last.get("details") or {},
                "result_unknown": bool(last.get("result_unknown")),
            }
            != comparable
        ):
            history.append({**comparable, "recorded_at": utc_now_naive().isoformat()})
        payload["phase_history"] = history[-MAX_PHASE_HISTORY:]
        job.payload = payload
        job.current_step = phase[:160]
        phase_progress = AI_SHADOW_PHASE_PROGRESS.get(phase)
        if phase_progress is not None:
            job.progress_current = max(int(job.progress_current or 0), phase_progress)
        job.progress_total = max(int(job.progress_total or 0), AI_SHADOW_PROGRESS_TOTAL)

    @staticmethod
    def _mirror_summary(
        job: Job,
        task: AITask,
        *,
        phase: str,
        details: dict[str, Any],
        result_unknown: bool,
    ) -> None:
        previous = copy.deepcopy(job.result_summary or {})
        previous_unknown = previous.get("result_certainty") == "unknown"
        provider = _provider_snapshot(task.params)
        upstream_task_id = details.get("upstream_task_id") or previous.get(
            "upstream_task_id"
        )
        certainty = "unknown" if result_unknown or previous_unknown else "known"
        job.result_summary = {
            **previous,
            "shadow_mode": True,
            "legacy_task_id": int(task.id),
            "legacy_status": task.status,
            "phase": phase,
            "result_certainty": certainty,
            "requires_reconciliation": certainty == "unknown",
            "provider": provider,
            "upstream_task_id": upstream_task_id,
            "image_count": len(task.result_urls or []),
            "legacy_error": _optional_text(task.error),
        }


def _phase_for_task(task: AITask) -> str:
    return {
        "queued": "queued",
        "processing": "worker_started",
        "completed": "completed",
        "failed": "failed",
        "cancelled": "cancelled",
    }.get(str(task.status or "queued").strip().lower(), "queued")


def _task_started_at(task: AITask) -> datetime | None:
    params: dict[str, Any] = task.params if isinstance(task.params, dict) else {}
    value = params.get("_processing_started_at")
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value).replace(tzinfo=None)
    except ValueError:
        return None


def _request_snapshot(params: dict[str, Any]) -> dict[str, Any]:
    snapshot = {
        key: copy.deepcopy(params.get(key))
        for key in ("width", "height", "style", "quality", "count")
        if params.get(key) is not None
    }
    snapshot["has_reference"] = bool(
        params.get("image_data") or params.get("image_url") or params.get("images_data")
    )
    return snapshot


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _optional_datetime(value: Any) -> datetime | None:
    return value if isinstance(value, datetime) else None


def _provider_snapshot(params: Any) -> dict[str, Any] | None:
    if not isinstance(params, dict) or not isinstance(params.get("provider"), dict):
        return None
    provider = params["provider"]
    return {
        key: copy.deepcopy(provider.get(key))
        for key in ("id", "name", "provider_kind", "provider_model")
        if provider.get(key) is not None
    }


def _sanitize_details(value: Any, *, depth: int = 0) -> Any:
    if depth >= 4:
        return "[truncated]"
    if isinstance(value, dict):
        sanitized: dict[str, Any] = {}
        for index, (key, item) in enumerate(value.items()):
            if index >= 30:
                break
            lowered = str(key).lower()
            if any(
                marker in lowered
                for marker in ("api_key", "secret", "authorization", "cookie", "token")
            ):
                sanitized[str(key)] = "[redacted]"
            else:
                sanitized[str(key)] = _sanitize_details(item, depth=depth + 1)
        return sanitized
    if isinstance(value, (list, tuple)):
        return [_sanitize_details(item, depth=depth + 1) for item in value[:20]]
    if isinstance(value, str):
        return value[:500]
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return str(value)[:500]


async def mirror_ai_image_shadow_safely(
    task_id: int | None,
    *,
    phase: str | None = None,
    details: dict[str, Any] | None = None,
    result_unknown: bool = False,
) -> int | None:
    """Best-effort AI shadow write that cannot fail the legacy task path."""

    if not settings.ai_image_shadow_enabled or not task_id:
        return None
    try:
        safe_details = copy.deepcopy(details or {})
        async with async_session() as db:
            job = await AIImageShadowAdapter(db).mirror(
                int(task_id),
                phase=phase,
                details=safe_details,
                result_unknown=result_unknown,
            )
            await db.commit()
            return job.id if job is not None else None
    except Exception:
        logger.exception(
            "AI image shadow mirror failed: task_id=%s phase=%s", task_id, phase
        )
        return None
