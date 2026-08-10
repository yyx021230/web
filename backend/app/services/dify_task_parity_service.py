from __future__ import annotations

import copy
from collections import Counter, defaultdict
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import String, cast, exists, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.dify_task import DifyTask
from app.models.job import Job
from app.services.dify_task_shadow import (
    DIFY_DELETED_SOURCE_TYPE,
    DIFY_JOB_TYPE,
    DIFY_SOURCE_TYPE,
    DIFY_TERMINAL_STATUSES,
    DIFY_TO_JOB_STATUS,
    DIFY_WORKER_TYPE,
    _bounded_text,
    _status_message,
    _task_payload,
    _task_result_summary,
)
from app.utils.timezone import (
    aware_or_cst_naive_to_utc_naive,
    utc_naive_to_aware_iso,
    utc_naive_to_cst_naive,
)


MAX_MISMATCH_DETAILS = 100
MAX_ORPHAN_DETAILS = 100
MANUAL_MIGRATION_CHECKS = (
    "verify each legacy task calls the Dify create/run endpoint exactly once",
    "restart the Web process with queued and running tasks and review stuck outcomes",
    "verify cancellation does not hide a later upstream success or charge",
)


class DifyTaskParityService:
    """Independently compare terminal Dify tasks with durable shadow jobs."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def build_report(
        self,
        *,
        finished_from: datetime | None = None,
        finished_to: datetime | None = None,
        sample_limit: int = 100,
        min_samples: int = 20,
    ) -> dict[str, Any]:
        normalized_from = _normalize_utc_filter(finished_from)
        normalized_to = _normalize_utc_filter(finished_to)
        if normalized_from and normalized_to and normalized_from > normalized_to:
            raise ValueError("finished_from must not be after finished_to")
        normalized_limit = max(1, min(int(sample_limit), 500))
        normalized_min = max(1, min(int(min_samples), 500))
        if normalized_min > normalized_limit:
            raise ValueError("min_samples must not exceed sample_limit")

        filters = [DifyTask.status.in_(DIFY_TERMINAL_STATUSES)]
        if normalized_from:
            filters.append(
                DifyTask.finished_at >= utc_naive_to_cst_naive(normalized_from)
            )
        if normalized_to:
            filters.append(
                DifyTask.finished_at <= utc_naive_to_cst_naive(normalized_to)
            )

        task_rows = (
            await self.db.execute(
                select(
                    DifyTask,
                    func.count(DifyTask.id).over().label("total_count"),
                )
                .where(*filters)
                .order_by(DifyTask.finished_at.desc(), DifyTask.id.desc())
                .limit(normalized_limit)
            )
        ).all()
        tasks = [row[0] for row in task_rows]
        total_count = int(task_rows[0][1]) if task_rows else 0
        task_ids = [int(task.id) for task in tasks]

        jobs_by_task: dict[int, list[Job]] = defaultdict(list)
        if task_ids:
            jobs = list(
                (
                    await self.db.execute(
                        select(Job).where(
                            Job.source_type == DIFY_SOURCE_TYPE,
                            Job.source_id.in_([str(task_id) for task_id in task_ids]),
                        )
                    )
                ).scalars()
            )
            for job in jobs:
                task_id = _optional_int(job.source_id)
                if task_id is not None:
                    jobs_by_task[task_id].append(job)

        diagnostics = await self._load_diagnostics()
        samples = [
            self._compare_task(task, jobs_by_task.get(int(task.id), []))
            for task in tasks
        ]
        return self._build_payload(
            samples=samples,
            total_count=total_count,
            diagnostics=diagnostics,
            finished_from=normalized_from,
            finished_to=normalized_to,
            sample_limit=normalized_limit,
            min_samples=normalized_min,
        )

    async def _load_diagnostics(self) -> dict[str, Any]:
        valid_source = exists(
            select(DifyTask.id).where(cast(DifyTask.id, String) == Job.source_id)
        )
        orphan_filter = (
            Job.source_type == DIFY_SOURCE_TYPE,
            ~valid_source,
        )
        orphan_count = int(
            (
                await self.db.execute(
                    select(func.count(Job.id)).where(*orphan_filter)
                )
            ).scalar_one()
        )
        orphan_rows = list(
            (
                await self.db.execute(
                    select(Job)
                    .where(*orphan_filter)
                    .order_by(Job.id.desc())
                    .limit(MAX_ORPHAN_DETAILS)
                )
            ).scalars()
        )
        deleted_count = int(
            (
                await self.db.execute(
                    select(func.count(Job.id)).where(
                        Job.source_type == DIFY_DELETED_SOURCE_TYPE
                    )
                )
            ).scalar_one()
        )
        return {
            "orphan_shadow_jobs": {
                "total_count": orphan_count,
                "items": [
                    {
                        "job_id": int(job.id),
                        "public_id": job.public_id,
                        "source_id": job.source_id,
                        "status": job.status,
                    }
                    for job in orphan_rows
                ],
                "is_truncated": orphan_count > len(orphan_rows),
            },
            "deleted_source_snapshot_count": deleted_count,
        }

    def _compare_task(self, task: DifyTask, jobs: list[Job]) -> dict[str, Any]:
        mismatches: list[dict[str, Any]] = []
        if not jobs:
            _add_mismatch(
                mismatches,
                "missing_shadow_job",
                expected=1,
                actual=0,
            )
            return self._sample(task, None, mismatches)
        if len(jobs) > 1:
            _add_mismatch(
                mismatches,
                "duplicate_shadow_job",
                expected=1,
                actual=len(jobs),
            )

        job = sorted(jobs, key=lambda row: int(row.id))[0]
        legacy_status = str(task.status or "").strip().lower()
        expected_status = DIFY_TO_JOB_STATUS.get(legacy_status)
        expected_payload = _task_payload(task)
        expected_result = _task_result_summary(task)
        comparisons: tuple[tuple[str, Any, Any], ...] = (
            ("job_type", DIFY_JOB_TYPE, job.job_type),
            ("worker_type", DIFY_WORKER_TYPE, job.worker_type),
            ("job_status", expected_status, job.status),
            ("requested_by_user_id", int(task.user_id), job.requested_by_user_id),
            ("source_id", str(int(task.id)), job.source_id),
            (
                "idempotency_key",
                f"legacy-dify-task:{int(task.id)}",
                job.idempotency_key,
            ),
            ("payload", expected_payload, job.payload or {}),
            ("progress_total", 1, job.progress_total),
            ("progress_current", 1, job.progress_current),
            (
                "current_step",
                _bounded_text(task.progress, limit=160)
                or _status_message(legacy_status),
                job.current_step,
            ),
            (
                "finished_at",
                aware_or_cst_naive_to_utc_naive(task.finished_at),
                job.finished_at,
            ),
            ("result_summary", expected_result, job.result_summary or {}),
            (
                "error_code",
                "dify_workflow_failed" if legacy_status == "failed" else None,
                job.error_code,
            ),
            (
                "internal_error",
                _bounded_text(task.error) if legacy_status == "failed" else None,
                job.internal_error,
            ),
        )
        for code, expected, actual in comparisons:
            _compare_value(mismatches, code, expected, actual)
        return self._sample(task, job, mismatches)

    @staticmethod
    def _sample(
        task: DifyTask,
        job: Job | None,
        mismatches: list[dict[str, Any]],
    ) -> dict[str, Any]:
        codes = [str(item["code"]) for item in mismatches]
        finished_at = aware_or_cst_naive_to_utc_naive(task.finished_at)
        return {
            "legacy_task_id": int(task.id),
            "workflow_id": int(task.workflow_id),
            "user_id": int(task.user_id),
            "legacy_status": str(task.status or ""),
            "job_id": job.public_id if job else None,
            "durable_status": job.status if job else None,
            "upstream_task_id": _bounded_text(task.task_id, limit=100),
            "elapsed_ms": _safe_float(task.elapsed_ms),
            "finished_at": utc_naive_to_aware_iso(finished_at),
            "matched": not mismatches,
            "mismatch_codes": sorted(set(codes)),
            "mismatch_count": len(mismatches),
            "mismatches": copy.deepcopy(mismatches[:MAX_MISMATCH_DETAILS]),
            "mismatches_truncated": len(mismatches) > MAX_MISMATCH_DETAILS,
        }

    @staticmethod
    def _build_payload(
        *,
        samples: list[dict[str, Any]],
        total_count: int,
        diagnostics: dict[str, Any],
        finished_from: datetime | None,
        finished_to: datetime | None,
        sample_limit: int,
        min_samples: int,
    ) -> dict[str, Any]:
        matched_count = sum(bool(sample["matched"]) for sample in samples)
        mismatch_count = len(samples) - matched_count
        reason_counts = Counter(
            code for sample in samples for code in sample["mismatch_codes"]
        )
        orphan_count = _safe_int(
            diagnostics.get("orphan_shadow_jobs", {}).get("total_count")
        )
        if orphan_count:
            reason_counts["orphan_shadow_job"] += orphan_count
        automated_checks_passed = (
            len(samples) >= min_samples and mismatch_count == 0 and orphan_count == 0
        )
        if mismatch_count or orphan_count:
            decision = "blocked_by_mismatch"
        elif len(samples) < min_samples:
            decision = "insufficient_samples"
        else:
            decision = "manual_validation_required"
        return {
            "feature_enabled": settings.dify_task_shadow_enabled,
            "scope": {
                "finished_from": utc_naive_to_aware_iso(finished_from),
                "finished_to": utc_naive_to_aware_iso(finished_to),
                "sample_limit": sample_limit,
                "min_samples": min_samples,
            },
            "summary": {
                "total_terminal_count": total_count,
                "evaluated_count": len(samples),
                "matched_count": matched_count,
                "mismatch_count": mismatch_count,
                "orphan_shadow_count": orphan_count,
                "deleted_source_snapshot_count": _safe_int(
                    diagnostics.get("deleted_source_snapshot_count")
                ),
                "match_rate": round(matched_count / len(samples), 4)
                if samples
                else 0.0,
                "mismatch_reasons": dict(sorted(reason_counts.items())),
                "is_truncated": total_count > len(samples),
            },
            "diagnostics": diagnostics,
            "migration_gate": {
                "decision": decision,
                "automated_checks_passed": automated_checks_passed,
                "execution_cutover_allowed": False,
                "manual_checks_required": list(MANUAL_MIGRATION_CHECKS),
            },
            "samples": samples,
        }


def _normalize_utc_filter(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value
    return value.astimezone(timezone.utc).replace(tzinfo=None)


def _compare_value(
    mismatches: list[dict[str, Any]],
    code: str,
    expected: Any,
    actual: Any,
) -> None:
    if expected == actual:
        return
    _add_mismatch(mismatches, code, expected=expected, actual=actual)


def _add_mismatch(
    mismatches: list[dict[str, Any]],
    code: str,
    *,
    expected: Any,
    actual: Any,
) -> None:
    mismatches.append(
        {
            "code": code,
            "expected": _json_safe(expected),
            "actual": _json_safe(actual),
        }
    )


def _json_safe(value: Any) -> Any:
    if isinstance(value, datetime):
        return utc_naive_to_aware_iso(value)
    return copy.deepcopy(value)


def _optional_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _safe_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _safe_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return round(float(value), 3)
    except (TypeError, ValueError):
        return None
