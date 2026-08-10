from __future__ import annotations

import copy
import logging
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import settings
from app.db.session import async_session
from app.models.job import Job, JobItem, JobStatus, TERMINAL_JOB_STATUSES
from app.models.xhs_account_sync_run import XHSAccountSyncRun, XHSAccountSyncRunItem
from app.services.job_service import JobService
from app.utils.timezone import aware_or_cst_naive_to_utc_naive, utc_now_naive


logger = logging.getLogger(__name__)

SHADOW_JOB_TYPE = "xhs_homepage_sync"
SHADOW_WORKER_TYPE = "legacy_shadow"
SHADOW_SOURCE_TYPE = "xhs_account_sync_run"
SHADOW_PROGRESS_PHASES = frozenset(
    {
        "fetching_account_posts",
        "account_posts_completed",
        "account_posts_failed",
    }
)

LEGACY_TERMINAL_STATUS_MAP = {
    "succeeded": JobStatus.SUCCEEDED.value,
    "failed": JobStatus.FAILED.value,
    "cancelled": JobStatus.CANCELLED.value,
}


class HomepageSyncShadowAdapter:
    """Mirror legacy homepage-sync records without executing business work."""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.jobs = JobService(db)

    async def mirror(
        self,
        history_run_id: int,
        *,
        legacy_job: dict[str, Any] | None = None,
    ) -> Job | None:
        run = await self._load_run(history_run_id)
        if run is None or run.sync_kind != "posts":
            return None

        legacy_snapshot = copy.deepcopy(legacy_job or {})
        job = await self._ensure_shadow_job(run, legacy_snapshot)
        legacy_items = list(run.items or [])
        await self._mirror_items(
            job,
            self._items_for_snapshot(legacy_items, legacy_snapshot),
        )
        await self._mirror_status(job, run, legacy_snapshot)
        self._mirror_progress_and_result(job, run, legacy_snapshot)
        await self.db.flush()
        return job

    async def _load_run(self, history_run_id: int) -> XHSAccountSyncRun | None:
        return (
            await self.db.execute(
                select(XHSAccountSyncRun)
                .options(selectinload(XHSAccountSyncRun.items))
                .where(XHSAccountSyncRun.id == history_run_id)
            )
        ).scalar_one_or_none()

    async def _ensure_shadow_job(
        self,
        run: XHSAccountSyncRun,
        legacy_job: dict[str, Any],
    ) -> Job:
        existing = (
            await self.db.execute(
                select(Job).where(
                    Job.source_type == SHADOW_SOURCE_TYPE,
                    Job.source_id == str(run.id),
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            return existing

        parent_job_id = None
        if run.parent_run_id:
            parent_job_id = (
                await self.db.execute(
                    select(Job.id).where(
                        Job.source_type == SHADOW_SOURCE_TYPE,
                        Job.source_id == str(run.parent_run_id),
                    )
                )
            ).scalar_one_or_none()

        job, _ = await self.jobs.create_job(
            job_type=SHADOW_JOB_TYPE,
            scope_key="internal",
            worker_type=SHADOW_WORKER_TYPE,
            requested_by_user_id=_legacy_optional_int(run.requested_by_user_id),
            parent_job_id=parent_job_id,
            idempotency_key=f"legacy-homepage-sync:{run.job_id}",
            source_type=SHADOW_SOURCE_TYPE,
            source_id=str(run.id),
            progress_total=len(run.items or []),
            payload={
                "shadow_mode": True,
                "legacy_run_id": run.id,
                "legacy_job_id": run.job_id,
                "legacy_source": run.source,
                "legacy_parent_run_id": run.parent_run_id,
                "request_config": copy.deepcopy(run.request_config or {}),
                "initial_legacy_status": str(
                    legacy_job.get("status") or run.status or "queued"
                ),
            },
            actor_type="legacy_shadow",
            actor_id=str(run.id),
        )
        return job

    async def _mirror_items(
        self,
        job: Job,
        legacy_items: list[XHSAccountSyncRunItem],
    ) -> None:
        for legacy_item in legacy_items:
            item_key = self._legacy_item_key(legacy_item)
            item, _ = await self.jobs.add_item(
                job,
                item_key=item_key,
                item_type="xhs_environment",
                display_name=(legacy_item.account_name or "").strip() or None,
                payload={
                    "legacy_run_item_id": legacy_item.id,
                    "environment_id": legacy_item.environment_id,
                },
            )
            self._apply_legacy_item(item, legacy_item)

    @staticmethod
    def _items_for_snapshot(
        items: list[XHSAccountSyncRunItem],
        legacy_job: dict[str, Any],
    ) -> list[XHSAccountSyncRunItem]:
        legacy_status = str(legacy_job.get("status") or "queued").strip().lower()
        if legacy_status in LEGACY_TERMINAL_STATUS_MAP:
            return items

        progress = legacy_job.get("progress")
        if not isinstance(progress, dict):
            return items
        phase = str(progress.get("phase") or "").strip()
        account_name = str(progress.get("account_name") or "").strip()
        if phase not in SHADOW_PROGRESS_PHASES or not account_name:
            return items

        # Legacy history updates the first exact-name match, so mirror that same row.
        matched = [
            item for item in items if (item.account_name or "").strip() == account_name
        ]
        return matched[:1]

    @staticmethod
    def _legacy_item_key(item: XHSAccountSyncRunItem) -> str:
        if item.environment_id:
            return f"environment:{int(item.environment_id)}"
        return f"legacy-item:{int(item.id)}"

    @staticmethod
    def _apply_legacy_item(item: JobItem, legacy: XHSAccountSyncRunItem) -> None:
        legacy_status = str(legacy.status or "queued").strip().lower()
        item.status = (
            legacy_status
            if legacy_status
            in {
                JobStatus.QUEUED.value,
                JobStatus.RUNNING.value,
                JobStatus.SUCCEEDED.value,
                JobStatus.FAILED.value,
                JobStatus.CANCELLED.value,
            }
            else JobStatus.QUEUED.value
        )
        item.display_name = (legacy.account_name or "").strip() or item.display_name
        item.attempt_count = max(
            int(item.attempt_count or 0),
            1 if item.status != JobStatus.QUEUED.value else 0,
        )
        item.result = (
            copy.deepcopy(legacy.result) if legacy.result is not None else None
        )
        item.user_message = legacy.message
        item.internal_error = legacy.error
        item.error_code = "legacy_sync_failed" if legacy.error else None
        item.started_at = _legacy_datetime_to_utc(legacy.started_at)
        item.finished_at = _legacy_datetime_to_utc(legacy.finished_at)

    async def _mirror_status(
        self,
        job: Job,
        run: XHSAccountSyncRun,
        legacy_job: dict[str, Any],
    ) -> None:
        legacy_status = str(legacy_job.get("status") or run.status or "queued").lower()
        cancel_requested = bool(
            legacy_job.get("cancel_requested")
        ) or legacy_status in {
            "cancelling",
            "cancelled",
        }
        if cancel_requested and job.status not in TERMINAL_JOB_STATUSES:
            await self.jobs.request_cancel(
                job,
                actor_type="legacy_shadow",
                actor_id=str(run.id),
                message="Legacy homepage sync requested cancellation",
            )

        if legacy_status in {"running", "cancelling"}:
            await self._ensure_running(job, run)
            return

        target_status = LEGACY_TERMINAL_STATUS_MAP.get(legacy_status)
        if target_status is None or job.status in TERMINAL_JOB_STATUSES:
            return
        if (
            target_status == JobStatus.CANCELLED.value
            and job.status == JobStatus.QUEUED.value
        ):
            await self.jobs.transition(
                job,
                target_status,
                message="Legacy homepage sync cancelled",
                actor_type="legacy_shadow",
                actor_id=str(run.id),
                now=_legacy_datetime_to_utc(run.finished_at) or utc_now_naive(),
            )
            return

        await self._ensure_running(job, run)
        await self.jobs.transition(
            job,
            target_status,
            message=_legacy_text(run.message)
            or f"Legacy homepage sync {legacy_status}",
            error_code="legacy_sync_failed"
            if target_status == JobStatus.FAILED.value
            else None,
            user_message=(
                _legacy_text(run.error)
                if target_status == JobStatus.FAILED.value
                else None
            ),
            internal_error=(
                _legacy_text(run.error)
                if target_status == JobStatus.FAILED.value
                else None
            ),
            actor_type="legacy_shadow",
            actor_id=str(run.id),
            now=_legacy_datetime_to_utc(run.finished_at) or utc_now_naive(),
        )

    async def _ensure_running(self, job: Job, run: XHSAccountSyncRun) -> None:
        if job.status == JobStatus.QUEUED.value:
            await self.jobs.transition(
                job,
                JobStatus.LEASED,
                message="Legacy homepage sync accepted",
                actor_type="legacy_shadow",
                actor_id=str(run.id),
                now=_legacy_datetime_to_utc(run.started_at) or utc_now_naive(),
            )
        if job.status == JobStatus.LEASED.value:
            await self.jobs.transition(
                job,
                JobStatus.RUNNING,
                message="Legacy homepage sync started",
                actor_type="legacy_shadow",
                actor_id=str(run.id),
                now=_legacy_datetime_to_utc(run.started_at) or utc_now_naive(),
            )

    @staticmethod
    def _mirror_progress_and_result(
        job: Job,
        run: XHSAccountSyncRun,
        legacy_job: dict[str, Any],
    ) -> None:
        items = list(run.items or [])
        succeeded = sum(item.status == "succeeded" for item in items)
        failed = sum(item.status == "failed" for item in items)
        cancelled = sum(item.status == "cancelled" for item in items)
        processed = succeeded + failed + cancelled
        job.progress_total = max(int(job.progress_total or 0), len(items))
        job.progress_current = max(int(job.progress_current or 0), processed)
        current_step = (run.message or "").strip()
        job.current_step = current_step[:160] or None

        legacy_status = str(legacy_job.get("status") or run.status or "queued").lower()
        if legacy_status not in LEGACY_TERMINAL_STATUS_MAP:
            return

        legacy_metrics = _legacy_result_metrics(legacy_job)
        expected_job_status = LEGACY_TERMINAL_STATUS_MAP[legacy_status]
        checks: dict[str, bool] = {
            "legacy_history_status": legacy_status == str(run.status or ""),
            "durable_job_status": job.status == expected_job_status,
        }
        if "synced_accounts" in legacy_metrics:
            checks["synced_accounts"] = (
                int(legacy_metrics["synced_accounts"]) == succeeded
            )
        mismatches = [name for name, matched in checks.items() if not matched]
        job.result_summary = {
            "shadow_mode": True,
            "legacy_run_id": run.id,
            "legacy_job_id": run.job_id,
            "legacy_status": legacy_status,
            "history_status": run.status,
            "total_accounts": len(items),
            "succeeded_accounts": succeeded,
            "failed_accounts": failed,
            "cancelled_accounts": cancelled,
            "legacy_metrics": legacy_metrics,
            "parity": {
                "status": "matched" if not mismatches else "mismatch",
                "checks": checks,
                "mismatches": mismatches,
            },
        }


def _legacy_result_metrics(legacy_job: dict[str, Any]) -> dict[str, int]:
    result = legacy_job.get("result")
    source = result if isinstance(result, dict) else legacy_job.get("progress")
    if not isinstance(source, dict):
        return {}
    keys = (
        "synced_accounts",
        "created_notes",
        "updated_notes",
        "metric_synced_notes",
        "total_notes",
    )
    return {
        key: _legacy_int(source.get(key)) for key in keys if source.get(key) is not None
    }


def _legacy_datetime_to_utc(value: Any) -> datetime | None:
    if not isinstance(value, datetime):
        return None
    return aware_or_cst_naive_to_utc_naive(value)


def _legacy_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _legacy_optional_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _legacy_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


async def mirror_homepage_sync_shadow_safely(
    history_run_id: int | None,
    *,
    legacy_job: dict[str, Any] | None = None,
) -> int | None:
    """Best-effort shadow write that cannot fail the legacy executor."""

    if not settings.xhs_homepage_sync_shadow_enabled or not history_run_id:
        return None
    legacy_snapshot = copy.deepcopy(legacy_job or {})
    try:
        async with async_session() as db:
            job = await HomepageSyncShadowAdapter(db).mirror(
                history_run_id,
                legacy_job=legacy_snapshot,
            )
            await db.commit()
            return job.id if job is not None else None
    except Exception:
        logger.exception(
            "homepage sync shadow mirror failed: history_run_id=%s",
            history_run_id,
        )
        return None
