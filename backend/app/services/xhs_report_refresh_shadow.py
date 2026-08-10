from __future__ import annotations

import copy
import logging
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.session import async_session
from app.models.job import Job, JobItem, JobStatus, TERMINAL_JOB_STATUSES
from app.models.xhs_report_refresh_run import XHSReportRefreshRun
from app.services.job_service import JobService
from app.utils.timezone import utc_now_naive


logger = logging.getLogger(__name__)

REPORT_REFRESH_JOB_TYPE = "xhs_report_refresh"
REPORT_REFRESH_WORKER_TYPE = "legacy_shadow"
REPORT_REFRESH_SOURCE_TYPE = "xhs_report_refresh_run"
SUPPORTED_REPORT_TYPES = (
    "simple",
    "standard",
    "creative",
    "simple_note",
    "standard_note",
)
TERMINAL_RUN_STATUSES = frozenset({"succeeded", "failed", "cancelled"})
RUN_TO_JOB_STATUS = {
    "succeeded": JobStatus.SUCCEEDED.value,
    "failed": JobStatus.FAILED.value,
    "cancelled": JobStatus.CANCELLED.value,
}


class ReportRefreshRunService:
    """Persist bounded legacy report-refresh evidence in the caller transaction."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def create_run(
        self,
        *,
        job_id: str,
        source: str,
        request_config: dict[str, Any],
        requested_by_user_id: int | None = None,
        schedule_run_id: int | None = None,
    ) -> tuple[XHSReportRefreshRun, bool]:
        normalized_job_id = str(job_id or "").strip()
        if not normalized_job_id:
            raise ValueError("job_id must not be empty")
        existing = (
            await self.db.execute(
                select(XHSReportRefreshRun).where(
                    XHSReportRefreshRun.job_id == normalized_job_id
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            return existing, False

        normalized_config = _normalize_request_config(request_config)
        run = XHSReportRefreshRun(
            job_id=normalized_job_id,
            source=str(source or "manual").strip() or "manual",
            status="queued",
            requested_by_user_id=requested_by_user_id,
            schedule_run_id=schedule_run_id,
            request_config=normalized_config,
            result_summary=_empty_result_summary(),
            message="报表刷新任务排队中",
        )
        self.db.add(run)
        await self.db.flush()
        return run, True

    async def mark_running(
        self,
        run: XHSReportRefreshRun,
        *,
        message: str = "报表刷新任务执行中",
        now: datetime | None = None,
    ) -> bool:
        if run.status in TERMINAL_RUN_STATUSES or run.status == "running":
            return False
        run.status = "running"
        run.started_at = run.started_at or now or utc_now_naive()
        run.message = _bounded_text(message)
        run.error = None
        await self.db.flush()
        return True

    async def record_report_result(
        self,
        run: XHSReportRefreshRun,
        *,
        report_type: str,
        status: str,
        result: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> dict[str, Any]:
        normalized_type = str(report_type or "").strip()
        if normalized_type not in _report_types(run.request_config):
            raise ValueError("report_type is not part of this refresh run")
        normalized_status = str(status or "").strip().lower()
        if normalized_status not in TERMINAL_RUN_STATUSES:
            raise ValueError("report result status must be terminal")
        existing = _reports_by_type(run.result_summary).get(normalized_type)
        if run.status in TERMINAL_RUN_STATUSES:
            if existing is not None:
                return existing
            raise ValueError("cannot append a report result to a terminal run")

        payload = result if isinstance(result, dict) else {}
        raw_errors = payload.get("errors")
        errors: list[Any] = raw_errors if isinstance(raw_errors, list) else []
        entry = {
            "report_type": normalized_type,
            "status": normalized_status,
            "updated_accounts": _safe_int(payload.get("updated_accounts")),
            "updated_rows": _safe_int(payload.get("updated_rows")),
            "error_count": len(errors)
            + (1 if payload.get("aggregate_error") else 0)
            + (1 if normalized_status == "failed" else 0),
            "error_code": "legacy_report_refresh_failed"
            if normalized_status == "failed"
            else None,
            "message": _bounded_text(error)
            if error
            else _report_result_message(normalized_type, payload),
        }
        summary = _summary_with_entry(run.result_summary, entry)
        run.result_summary = summary
        run.message = entry["message"]
        if normalized_status == "failed":
            run.error = _bounded_text(error) or "报表刷新失败"
        await self.db.flush()
        return entry

    async def finish(
        self,
        run: XHSReportRefreshRun,
        *,
        status: str,
        message: str,
        error: str | None = None,
        now: datetime | None = None,
    ) -> bool:
        normalized_status = str(status or "").strip().lower()
        if normalized_status not in TERMINAL_RUN_STATUSES:
            raise ValueError("run status must be terminal")
        if run.status in TERMINAL_RUN_STATUSES:
            return False

        finished_at = now or utc_now_naive()
        reports = _reports_by_type(run.result_summary)
        missing_status = "failed" if normalized_status == "succeeded" else "cancelled"
        for report_type in _report_types(run.request_config):
            if report_type in reports:
                continue
            reports[report_type] = {
                "report_type": report_type,
                "status": missing_status,
                "updated_accounts": 0,
                "updated_rows": 0,
                "error_count": 1,
                "error_code": "missing_report_result",
                "message": "任务结束前未记录该报表结果",
            }
        run.result_summary = _build_result_summary(reports)
        run.status = normalized_status
        run.message = _bounded_text(message)
        run.error = _bounded_text(error) if error else None
        run.started_at = run.started_at or finished_at
        run.finished_at = finished_at
        await self.db.flush()
        return True


class ReportRefreshShadowAdapter:
    """Mirror report-refresh history without calling any report API."""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.jobs = JobService(db)

    async def mirror(self, run_id: int) -> Job | None:
        run = await self.db.get(XHSReportRefreshRun, int(run_id))
        if run is None:
            return None
        job = await self._ensure_job(run)
        await self._mirror_items(job, run)
        await self._mirror_status(job, run)
        self._mirror_progress(job, run)
        await self.db.flush()
        return job

    async def _ensure_job(self, run: XHSReportRefreshRun) -> Job:
        existing = (
            await self.db.execute(
                select(Job).where(
                    Job.source_type == REPORT_REFRESH_SOURCE_TYPE,
                    Job.source_id == str(run.id),
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            return existing
        report_types = _report_types(run.request_config)
        job, _ = await self.jobs.create_job(
            job_type=REPORT_REFRESH_JOB_TYPE,
            worker_type=REPORT_REFRESH_WORKER_TYPE,
            scope_key="internal",
            requested_by_user_id=_optional_int(run.requested_by_user_id),
            idempotency_key=f"legacy-report-refresh:{run.job_id}",
            source_type=REPORT_REFRESH_SOURCE_TYPE,
            source_id=str(run.id),
            progress_total=len(report_types),
            payload={
                "shadow_mode": True,
                "legacy_run_id": int(run.id),
                "legacy_job_id": run.job_id,
                "legacy_source": run.source,
                "schedule_run_id": run.schedule_run_id,
                "request_config": copy.deepcopy(run.request_config or {}),
            },
            actor_type="legacy_shadow",
            actor_id=str(run.id),
        )
        return job

    async def _mirror_items(self, job: Job, run: XHSReportRefreshRun) -> None:
        reports = _reports_by_type(run.result_summary)
        for report_type in _report_types(run.request_config):
            item, _ = await self.jobs.add_item(
                job,
                item_key=f"report:{report_type}",
                item_type="xhs_report_type",
                display_name=report_type,
                payload={"report_type": report_type},
            )
            self._apply_report_item(item, reports.get(report_type), run)

    @staticmethod
    def _apply_report_item(
        item: JobItem,
        entry: dict[str, Any] | None,
        run: XHSReportRefreshRun,
    ) -> None:
        if entry is None:
            item.status = (
                JobStatus.RUNNING.value
                if run.status == "running"
                else JobStatus.QUEUED.value
            )
            item.attempt_count = 1 if run.status == "running" else 0
            item.started_at = run.started_at if run.status == "running" else None
            return
        status = str(entry.get("status") or "failed")
        item.status = (
            status
            if status
            in {
                JobStatus.SUCCEEDED.value,
                JobStatus.FAILED.value,
                JobStatus.CANCELLED.value,
            }
            else JobStatus.FAILED.value
        )
        item.attempt_count = 1
        item.result = {
            key: copy.deepcopy(entry.get(key))
            for key in ("updated_accounts", "updated_rows", "error_count")
        }
        item.error_code = entry.get("error_code")
        item.user_message = _bounded_text(entry.get("message"))
        item.internal_error = (
            item.user_message if item.status == JobStatus.FAILED.value else None
        )
        item.started_at = run.started_at
        item.finished_at = run.finished_at or utc_now_naive()

    async def _mirror_status(self, job: Job, run: XHSReportRefreshRun) -> None:
        if run.status == "running":
            await self._ensure_running(job, run)
            return
        target = RUN_TO_JOB_STATUS.get(str(run.status or ""))
        if target is None or job.status in TERMINAL_JOB_STATUSES:
            return
        await self._ensure_running(job, run)
        await self.jobs.transition(
            job,
            target,
            message=run.message or f"Legacy report refresh {run.status}",
            error_code="legacy_report_refresh_failed"
            if target == JobStatus.FAILED.value
            else None,
            user_message=run.error if target == JobStatus.FAILED.value else None,
            internal_error=run.error if target == JobStatus.FAILED.value else None,
            actor_type="legacy_shadow",
            actor_id=str(run.id),
            now=run.finished_at or utc_now_naive(),
        )

    async def _ensure_running(self, job: Job, run: XHSReportRefreshRun) -> None:
        if job.status == JobStatus.QUEUED.value:
            await self.jobs.transition(
                job,
                JobStatus.LEASED,
                message="Legacy report refresh accepted",
                actor_type="legacy_shadow",
                actor_id=str(run.id),
                now=run.started_at or utc_now_naive(),
            )
        if job.status == JobStatus.LEASED.value:
            await self.jobs.transition(
                job,
                JobStatus.RUNNING,
                message="Legacy report refresh started",
                actor_type="legacy_shadow",
                actor_id=str(run.id),
                now=run.started_at or utc_now_naive(),
            )

    @staticmethod
    def _mirror_progress(job: Job, run: XHSReportRefreshRun) -> None:
        reports = _reports_by_type(run.result_summary)
        report_types = _report_types(run.request_config)
        job.progress_total = len(report_types)
        job.progress_current = len(
            [name for name in report_types if name in reports]
        )
        job.current_step = _bounded_text(run.message, limit=160)
        if run.status in TERMINAL_RUN_STATUSES:
            summary = _build_result_summary(reports)
            job.result_summary = {
                "shadow_mode": True,
                "legacy_run_id": int(run.id),
                "legacy_job_id": run.job_id,
                "legacy_status": run.status,
                **summary,
            }


async def create_report_refresh_run_safely(
    *,
    job_id: str,
    source: str,
    request_config: dict[str, Any],
    requested_by_user_id: int | None = None,
    schedule_run_id: int | None = None,
) -> int | None:
    if not settings.xhs_report_refresh_shadow_enabled:
        return None
    try:
        async with async_session() as db:
            run, _ = await ReportRefreshRunService(db).create_run(
                job_id=job_id,
                source=source,
                request_config=request_config,
                requested_by_user_id=requested_by_user_id,
                schedule_run_id=schedule_run_id,
            )
            await ReportRefreshShadowAdapter(db).mirror(int(run.id))
            await db.commit()
            return int(run.id)
    except Exception:
        logger.exception("report refresh history creation failed: job_id=%s", job_id)
        return None


async def mark_report_refresh_running_safely(run_id: int | None) -> None:
    await _mutate_run_safely(run_id, "mark_running")


async def record_report_refresh_result_safely(
    run_id: int | None,
    *,
    report_type: str,
    status: str,
    result: dict[str, Any] | None = None,
    error: str | None = None,
) -> None:
    await _mutate_run_safely(
        run_id,
        "record_report_result",
        report_type=report_type,
        status=status,
        result=result,
        error=error,
    )


async def finish_report_refresh_run_safely(
    run_id: int | None,
    *,
    status: str,
    message: str,
    error: str | None = None,
) -> None:
    await _mutate_run_safely(
        run_id,
        "finish",
        status=status,
        message=message,
        error=error,
    )


async def _mutate_run_safely(
    run_id: int | None,
    method_name: str,
    **kwargs: Any,
) -> None:
    if not settings.xhs_report_refresh_shadow_enabled or not run_id:
        return
    try:
        async with async_session() as db:
            run = await db.get(XHSReportRefreshRun, int(run_id))
            if run is None:
                return
            method = getattr(ReportRefreshRunService(db), method_name)
            await method(run, **kwargs)
            await ReportRefreshShadowAdapter(db).mirror(int(run.id))
            await db.commit()
    except Exception:
        logger.exception(
            "report refresh history update failed: run_id=%s method=%s",
            run_id,
            method_name,
        )


def _normalize_request_config(value: dict[str, Any]) -> dict[str, Any]:
    source = value if isinstance(value, dict) else {}
    report_types = _report_types(source)
    if not report_types:
        raise ValueError("at least one supported report_type is required")
    return {
        "report_types": report_types,
        "account_id": _bounded_text(source.get("account_id"), limit=64),
        "account_name": _bounded_text(source.get("account_name"), limit=255),
        "start_date": _bounded_text(source.get("start_date"), limit=10),
        "end_date": _bounded_text(source.get("end_date"), limit=10),
        "days": max(1, min(_safe_int(source.get("days"), default=30), 366)),
    }


def _report_types(value: Any) -> list[str]:
    source = value if isinstance(value, dict) else {}
    raw = source.get("report_types")
    if raw is None and source.get("report_type") is not None:
        raw = [source.get("report_type")]
    if not isinstance(raw, (list, tuple)):
        raw = []
    result: list[str] = []
    for item in raw:
        report_type = str(item or "").strip()
        if report_type in SUPPORTED_REPORT_TYPES and report_type not in result:
            result.append(report_type)
    return result


def _empty_result_summary() -> dict[str, Any]:
    return {
        "reports": [],
        "updated_accounts": 0,
        "updated_rows": 0,
        "error_count": 0,
    }


def _reports_by_type(value: Any) -> dict[str, dict[str, Any]]:
    source = value if isinstance(value, dict) else {}
    raw_rows = source.get("reports")
    rows: list[Any] = raw_rows if isinstance(raw_rows, list) else []
    result: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        report_type = str(row.get("report_type") or "").strip()
        if report_type in SUPPORTED_REPORT_TYPES:
            result[report_type] = copy.deepcopy(row)
    return result


def _summary_with_entry(value: Any, entry: dict[str, Any]) -> dict[str, Any]:
    reports = _reports_by_type(value)
    reports[str(entry["report_type"])] = copy.deepcopy(entry)
    return _build_result_summary(reports)


def _build_result_summary(
    reports: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    ordered = [
        reports[report_type]
        for report_type in SUPPORTED_REPORT_TYPES
        if report_type in reports
    ]
    return {
        "reports": ordered,
        "updated_accounts": sum(
            _safe_int(item.get("updated_accounts")) for item in ordered
        ),
        "updated_rows": sum(_safe_int(item.get("updated_rows")) for item in ordered),
        "error_count": sum(_safe_int(item.get("error_count")) for item in ordered),
    }


def _report_result_message(report_type: str, result: dict[str, Any]) -> str:
    error_count = len(result.get("errors") or []) + (
        1 if result.get("aggregate_error") else 0
    )
    return (
        f"{report_type} 更新 {_safe_int(result.get('updated_accounts'))} 个账户、"
        f"{_safe_int(result.get('updated_rows'))} 行，异常 {error_count} 条"
    )


def _bounded_text(value: Any, *, limit: int = 1000) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text[:limit] or None


def _safe_int(value: Any, *, default: int = 0) -> int:
    try:
        return int(value if value is not None else default)
    except (TypeError, ValueError):
        return default


def _optional_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
