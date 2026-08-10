from __future__ import annotations

import copy
import logging
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.ai_model.registry import model_registry
from app.db.session import async_session
from app.models.ai_task import AITask
from app.models.job import Job, JobStatus, TERMINAL_JOB_STATUSES
from app.services.ai_image_provider_service import AIImageProviderService
from app.services.ai_image_shadow import (
    AI_SHADOW_JOB_TYPE,
    AI_SHADOW_SOURCE_TYPE,
    AI_SHADOW_WORKER_TYPE,
)
from app.services.job_service import JobService
from app.utils.timezone import utc_now_naive


logger = logging.getLogger(__name__)

StatusFetcher = Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]
ImagePersister = Callable[[list[str]], Awaitable[list[str]]]
SUPPORTED_MANUAL_OUTCOMES = frozenset({"succeeded", "failed", "cancelled"})
SUPPORTED_LIST_STATUSES = frozenset(
    {
        "all",
        JobStatus.WAITING_REVIEW.value,
        JobStatus.SUCCEEDED.value,
        JobStatus.FAILED.value,
        JobStatus.CANCELLED.value,
    }
)


class AIImageReconciliationError(ValueError):
    pass


class AIImageReconciliationNotFound(AIImageReconciliationError):
    pass


class AIImageReconciliationConflict(AIImageReconciliationError):
    pass


class AIImageReconciliationService:
    """Resolve unknown legacy image results without submitting new work."""

    def __init__(
        self,
        db: AsyncSession,
        *,
        status_fetcher: StatusFetcher | None = None,
        image_persister: ImagePersister | None = None,
    ):
        self.db = db
        self.jobs = JobService(db)
        self._status_fetcher = status_fetcher or self._fetch_upstream_status
        self._image_persister = image_persister or self._persist_images

    async def list_jobs(
        self,
        *,
        status: str = JobStatus.WAITING_REVIEW.value,
        limit: int = 100,
    ) -> dict[str, Any]:
        normalized_status = str(status or "").strip().lower()
        if normalized_status not in SUPPORTED_LIST_STATUSES:
            raise AIImageReconciliationError("不支持的核对状态筛选")
        normalized_limit = max(1, min(int(limit), 500))
        conditions = [
            Job.job_type == AI_SHADOW_JOB_TYPE,
            Job.worker_type == AI_SHADOW_WORKER_TYPE,
            Job.source_type == AI_SHADOW_SOURCE_TYPE,
        ]
        if normalized_status != "all":
            conditions.append(Job.status == normalized_status)

        total = int(
            (
                await self.db.execute(
                    select(func.count()).select_from(Job).where(*conditions)
                )
            ).scalar_one()
        )
        jobs = list(
            (
                await self.db.execute(
                    select(Job)
                    .where(*conditions)
                    .order_by(Job.updated_at.desc(), Job.id.desc())
                    .limit(normalized_limit)
                )
            ).scalars()
        )
        task_ids = [
            int(job.source_id) for job in jobs if str(job.source_id or "").isdigit()
        ]
        tasks = (
            {
                int(task.id): task
                for task in (
                    await self.db.execute(select(AITask).where(AITask.id.in_(task_ids)))
                ).scalars()
            }
            if task_ids
            else {}
        )
        return {
            "total": total,
            "items": [
                self.serialize_job(
                    job,
                    tasks.get(int(job.source_id))
                    if str(job.source_id or "").isdigit()
                    else None,
                )
                for job in jobs
            ],
        }

    async def reconcile_job(
        self,
        job_id: int,
        *,
        actor_type: str = "system",
        actor_id: str | None = None,
        force: bool = True,
    ) -> dict[str, Any]:
        job = await self._load_job(job_id)
        task = await self._load_task(job)
        if job.status in TERMINAL_JOB_STATUSES:
            return {**self.serialize_job(job, task), "changed": False}
        if job.status != JobStatus.WAITING_REVIEW.value:
            raise AIImageReconciliationConflict("任务当前不处于待核对状态")

        summary = copy.deepcopy(job.result_summary or {})
        reconciliation = summary.get("reconciliation")
        if (
            isinstance(reconciliation, dict)
            and reconciliation.get("method") == "manual_required"
        ):
            result = {**self.serialize_job(job, task), "changed": False}
            if not force:
                result["skipped"] = True
            return result
        attempts = _normalized_attempts(summary.get("upstream_attempts"))
        if not attempts:
            await self._record_manual_required(
                job,
                summary,
                reason="missing_upstream_task_id",
                actor_type=actor_type,
                actor_id=actor_id,
            )
            return {**self.serialize_job(job, task), "changed": False}

        now = utc_now_naive()
        next_check_at = _parse_datetime(
            (summary.get("reconciliation") or {}).get("next_check_at")
            if isinstance(summary.get("reconciliation"), dict)
            else None
        )
        if not force and next_check_at is not None and next_check_at > now:
            return {**self.serialize_job(job, task), "changed": False, "skipped": True}

        query_results: dict[tuple[str, Any, Any], dict[str, Any]] = {}
        for attempt in attempts:
            if attempt.get("status") in {"completed", "failed"}:
                continue
            upstream_result = await self._status_fetcher(copy.deepcopy(attempt))
            query_results[_attempt_identity(attempt)] = _safe_status_result(
                upstream_result
            )

        completed_urls: list[str] = []
        for attempt in attempts:
            query_result = query_results.get(_attempt_identity(attempt))
            if query_result is None:
                continue
            attempt["status"] = query_result["status"]
            attempt["raw_status"] = query_result.get("raw_status")
            attempt["checked_at"] = now.isoformat()
            attempt["error"] = query_result.get("error")
            attempt["image_count"] = len(query_result.get("image_urls") or [])
            if query_result["status"] == "completed":
                completed_urls.extend(
                    str(url) for url in query_result.get("image_urls") or [] if url
                )

        completed_urls = list(dict.fromkeys(completed_urls))[:4]
        recovered_urls = list(summary.get("recovered_image_urls") or [])
        if completed_urls and not recovered_urls:
            recovered_urls = await self._image_persister(completed_urls)
            if recovered_urls and task is not None:
                task.status = "completed"
                task.result_urls = recovered_urls
                task.error = None
                task.finished_at = now

        statuses = [str(attempt.get("status") or "unknown") for attempt in attempts]
        check_count = (
            int(
                (summary.get("reconciliation") or {}).get("check_count", 0)
                if isinstance(summary.get("reconciliation"), dict)
                else 0
            )
            + 1
        )
        retry_delay = min(300, max(30, 30 * (2 ** min(check_count - 1, 3))))
        summary.update(
            {
                "upstream_attempts": attempts,
                "upstream_task_id": attempts[-1]["upstream_task_id"],
                "recovered_image_urls": recovered_urls,
                "image_count": len(recovered_urls),
                "reconciliation": {
                    "method": "automatic",
                    "check_count": check_count,
                    "last_checked_at": now.isoformat(),
                    "next_check_at": (now + timedelta(seconds=retry_delay)).isoformat(),
                    "statuses": statuses,
                },
            }
        )
        await self.jobs.append_event(
            job,
            event_type="ai_image_reconciliation_checked",
            message="Queried accepted upstream image task(s)",
            details={
                "attempt_count": len(attempts),
                "queried_count": len(query_results),
                "statuses": statuses,
                "recovered_image_count": len(recovered_urls),
            },
            actor_type=actor_type,
            actor_id=actor_id,
            created_at=now,
        )

        completed_count = statuses.count("completed")
        unresolved = any(status not in {"completed", "failed"} for status in statuses)
        if unresolved:
            summary["duplicate_charge_risk"] = len(attempts) > 1
            job.result_summary = copy.deepcopy(summary)
            await self.db.flush()
            return {**self.serialize_job(job, task), "changed": False}

        summary["result_certainty"] = "known"
        summary["requires_reconciliation"] = False
        summary["duplicate_success_count"] = completed_count
        summary["duplicate_charge_risk"] = len(attempts) > 1
        if completed_count:
            summary["resolution"] = {
                "outcome": "succeeded",
                "method": "automatic",
                "resolved_at": now.isoformat(),
                "actor_type": actor_type,
                "actor_id": actor_id,
                "result_recovered": bool(recovered_urls),
            }
            job.error_code = None
            job.user_message = None
            job.internal_error = None
            await self.jobs.transition(
                job,
                JobStatus.SUCCEEDED,
                message="Upstream AI image result reconciled as succeeded",
                result_summary=summary,
                details={
                    "attempt_count": len(attempts),
                    "duplicate_success_count": completed_count,
                    "result_recovered": bool(recovered_urls),
                },
                actor_type=actor_type,
                actor_id=actor_id,
                now=now,
            )
        else:
            error = next(
                (
                    str(attempt.get("error"))
                    for attempt in attempts
                    if attempt.get("error")
                ),
                "上游任务确认失败",
            )
            if task is not None and task.status != "completed":
                task.status = "failed"
                task.error = error
                task.finished_at = now
            summary["resolution"] = {
                "outcome": "failed",
                "method": "automatic",
                "resolved_at": now.isoformat(),
                "actor_type": actor_type,
                "actor_id": actor_id,
            }
            await self.jobs.transition(
                job,
                JobStatus.FAILED,
                message="Upstream AI image result reconciled as failed",
                error_code="upstream_confirmed_failed",
                user_message=error,
                internal_error=error,
                result_summary=summary,
                details={"attempt_count": len(attempts)},
                actor_type=actor_type,
                actor_id=actor_id,
                now=now,
            )
        await self.db.flush()
        return {**self.serialize_job(job, task), "changed": True}

    async def manual_resolve(
        self,
        job_id: int,
        *,
        outcome: str,
        reason: str,
        actor_id: str,
    ) -> dict[str, Any]:
        normalized_outcome = str(outcome or "").strip().lower()
        normalized_reason = str(reason or "").strip()
        if normalized_outcome not in SUPPORTED_MANUAL_OUTCOMES:
            raise AIImageReconciliationError("人工核对结果不合法")
        if len(normalized_reason) < 3:
            raise AIImageReconciliationError("人工核对必须填写至少 3 个字的原因")
        if len(normalized_reason) > 500:
            raise AIImageReconciliationError("人工核对原因不能超过 500 字")

        job = await self._load_job(job_id)
        task = await self._load_task(job)
        if job.status in TERMINAL_JOB_STATUSES:
            existing = (
                (job.result_summary or {}).get("resolution", {}).get("outcome")
                if isinstance((job.result_summary or {}).get("resolution"), dict)
                else None
            )
            if existing == normalized_outcome:
                return {**self.serialize_job(job, task), "changed": False}
            raise AIImageReconciliationConflict("任务已经以其他结果完成核对")
        if job.status != JobStatus.WAITING_REVIEW.value:
            raise AIImageReconciliationConflict("任务当前不处于待核对状态")

        now = utc_now_naive()
        summary = copy.deepcopy(job.result_summary or {})
        recovered_urls = list(summary.get("recovered_image_urls") or [])
        summary.update(
            {
                "result_certainty": "known",
                "requires_reconciliation": False,
                "resolution": {
                    "outcome": normalized_outcome,
                    "method": "manual",
                    "reason": normalized_reason,
                    "resolved_at": now.isoformat(),
                    "actor_type": "admin",
                    "actor_id": str(actor_id),
                    "result_recovered": bool(recovered_urls),
                },
            }
        )
        target = {
            "succeeded": JobStatus.SUCCEEDED,
            "failed": JobStatus.FAILED,
            "cancelled": JobStatus.CANCELLED,
        }[normalized_outcome]
        if task is not None:
            if normalized_outcome == "succeeded" and recovered_urls:
                task.status = "completed"
                task.result_urls = recovered_urls
                task.error = None
            elif normalized_outcome == "failed" and task.status != "completed":
                task.status = "failed"
                task.error = normalized_reason
            elif normalized_outcome == "cancelled" and task.status != "completed":
                task.status = "cancelled"
                task.error = normalized_reason
            task.finished_at = now

        if target == JobStatus.SUCCEEDED:
            job.error_code = None
            job.user_message = None
            job.internal_error = None
        await self.jobs.transition(
            job,
            target,
            message="AI image reconciliation resolved manually",
            error_code=(
                "manual_upstream_failed"
                if target == JobStatus.FAILED
                else "manual_reconciliation_cancelled"
                if target == JobStatus.CANCELLED
                else None
            ),
            user_message=normalized_reason if target != JobStatus.SUCCEEDED else None,
            internal_error=normalized_reason if target != JobStatus.SUCCEEDED else None,
            result_summary=summary,
            details={"outcome": normalized_outcome, "reason": normalized_reason},
            actor_type="admin",
            actor_id=str(actor_id),
            now=now,
        )
        await self.db.flush()
        return {**self.serialize_job(job, task), "changed": True}

    async def _record_manual_required(
        self,
        job: Job,
        summary: dict[str, Any],
        *,
        reason: str,
        actor_type: str,
        actor_id: str | None,
    ) -> None:
        now = utc_now_naive()
        summary["reconciliation"] = {
            "method": "manual_required",
            "reason": reason,
            "last_checked_at": now.isoformat(),
        }
        job.result_summary = summary
        await self.jobs.append_event(
            job,
            event_type="ai_image_reconciliation_manual_required",
            level="warning",
            message="Automatic reconciliation is not available",
            details={"reason": reason},
            actor_type=actor_type,
            actor_id=actor_id,
            created_at=now,
        )
        await self.db.flush()

    async def _load_job(self, job_id: int) -> Job:
        job = await self.db.get(Job, int(job_id))
        if (
            job is None
            or job.job_type != AI_SHADOW_JOB_TYPE
            or job.worker_type != AI_SHADOW_WORKER_TYPE
            or job.source_type != AI_SHADOW_SOURCE_TYPE
        ):
            raise AIImageReconciliationNotFound("未找到 AI 生图核对任务")
        return job

    async def _load_task(self, job: Job) -> AITask | None:
        if not str(job.source_id or "").isdigit():
            return None
        return await self.db.get(AITask, int(job.source_id))

    async def _fetch_upstream_status(self, attempt: dict[str, Any]) -> dict[str, Any]:
        capability = str(attempt.get("query_capability") or "")
        task_id = str(attempt.get("upstream_task_id") or "")
        provider_id = attempt.get("provider_id")
        if capability == "mentalout_batch" and provider_id is not None:
            return await AIImageProviderService(self.db).get_upstream_task_status(
                int(provider_id),
                task_id,
            )
        if capability == "legacy_batch_gateway":
            adapter = model_registry.get("gptimage2")
            if adapter is not None:
                return await adapter.get_task_status(task_id)
        return {
            "task_id": task_id,
            "status": "unsupported",
            "image_urls": [],
            "error": "当前上游任务无法自动查询",
        }

    async def _persist_images(self, image_urls: list[str]) -> list[str]:
        from app.services.ai_image_service import AIImageService, _store_images

        stored_urls = await _store_images(image_urls)
        if not stored_urls:
            return []
        return await AIImageService(
            model_name="gptimage2", db=self.db
        )._remove_watermarks(stored_urls)

    @staticmethod
    def serialize_job(job: Job, task: AITask | None) -> dict[str, Any]:
        summary = copy.deepcopy(job.result_summary or {})
        return {
            "job_id": int(job.id),
            "public_id": job.public_id,
            "status": job.status,
            "legacy_task_id": int(task.id) if task is not None else None,
            "legacy_status": task.status if task is not None else None,
            "user_id": task.user_id if task is not None else job.requested_by_user_id,
            "model_name": task.model_name if task is not None else None,
            "created_at": _loaded_datetime_iso(job, "created_at"),
            "updated_at": _loaded_datetime_iso(job, "updated_at"),
            "finished_at": _loaded_datetime_iso(job, "finished_at"),
            "provider": summary.get("provider"),
            "upstream_task_id": summary.get("upstream_task_id"),
            "upstream_attempts": summary.get("upstream_attempts") or [],
            "result_certainty": summary.get("result_certainty"),
            "requires_reconciliation": bool(summary.get("requires_reconciliation")),
            "duplicate_charge_risk": bool(summary.get("duplicate_charge_risk")),
            "reconciliation": summary.get("reconciliation"),
            "resolution": summary.get("resolution"),
            "image_count": int(summary.get("image_count") or 0),
            "error_code": job.error_code,
            "user_message": job.user_message,
        }


async def reconcile_ai_image_shadow_jobs_once(limit: int = 20) -> dict[str, int]:
    """Best-effort worker tick; each job commits independently."""

    normalized_limit = max(1, min(int(limit), 100))
    async with async_session() as db:
        candidate_ids = list(
            (
                await db.execute(
                    select(Job.id)
                    .where(
                        Job.job_type == AI_SHADOW_JOB_TYPE,
                        Job.worker_type == AI_SHADOW_WORKER_TYPE,
                        Job.source_type == AI_SHADOW_SOURCE_TYPE,
                        Job.status == JobStatus.WAITING_REVIEW.value,
                    )
                    .order_by(Job.updated_at.asc(), Job.id.asc())
                    .limit(normalized_limit * 5)
                )
            ).scalars()
        )

    checked = resolved = skipped = errors = 0
    for job_id in candidate_ids:
        if checked >= normalized_limit:
            break
        try:
            async with async_session() as db:
                result = await AIImageReconciliationService(db).reconcile_job(
                    int(job_id),
                    actor_type="reconciliation_worker",
                    actor_id="ai-worker",
                    force=False,
                )
                await db.commit()
            if result.get("skipped"):
                skipped += 1
                continue
            checked += 1
            if result.get("changed"):
                resolved += 1
        except Exception:
            errors += 1
            logger.exception("AI image reconciliation tick failed: job_id=%s", job_id)
    return {
        "candidates": len(candidate_ids),
        "checked": checked,
        "resolved": resolved,
        "skipped": skipped,
        "errors": errors,
    }


def _attempt_identity(attempt: dict[str, Any]) -> tuple[str, Any, Any]:
    return (
        str(attempt.get("upstream_task_id") or ""),
        attempt.get("provider_id"),
        attempt.get("provider_kind"),
    )


def _normalized_attempts(value: Any) -> list[dict[str, Any]]:
    attempts: list[dict[str, Any]] = []
    for item in value if isinstance(value, list) else []:
        if not isinstance(item, dict):
            continue
        task_id = str(item.get("upstream_task_id") or "").strip()
        if not task_id:
            continue
        normalized = {
            key: copy.deepcopy(item.get(key))
            for key in (
                "provider_id",
                "provider_kind",
                "provider_model",
                "query_capability",
                "accepted_at",
                "status",
                "raw_status",
                "checked_at",
                "error",
                "image_count",
            )
            if item.get(key) is not None
        }
        normalized["upstream_task_id"] = task_id[:160]
        if _attempt_identity(normalized) not in {
            _attempt_identity(existing) for existing in attempts
        }:
            attempts.append(normalized)
    return attempts[-20:]


def _safe_status_result(value: Any) -> dict[str, Any]:
    result = value if isinstance(value, dict) else {}
    status = str(result.get("status") or "unknown").strip().lower()
    if status not in {"completed", "failed", "generating", "unknown", "unsupported"}:
        status = "unknown"
    return {
        "status": status,
        "raw_status": str(result.get("raw_status") or "")[:80] or None,
        "image_urls": [str(url) for url in (result.get("image_urls") or [])[:4] if url],
        "error": str(result.get("error") or "")[:500] or None,
    }


def _parse_datetime(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value).replace(tzinfo=None)
    except ValueError:
        return None


def _loaded_datetime_iso(instance: Any, attribute: str) -> str | None:
    value = instance.__dict__.get(attribute)
    return value.isoformat() if isinstance(value, datetime) else None
