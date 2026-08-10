from __future__ import annotations

import copy
from collections import Counter, defaultdict
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import String, cast, exists, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import noload

from app.config import settings
from app.models.job import Job, JobItem, JobStatus
from app.models.xhs_account_sync_run import (
    XHSAccountSyncRun,
    XHSAccountSyncRunItem,
)
from app.services.xhs_homepage_sync_shadow import (
    LEGACY_TERMINAL_STATUS_MAP,
    SHADOW_JOB_TYPES,
    SHADOW_SOURCE_TYPE,
    SHADOW_WORKER_TYPE,
)
from app.utils.timezone import (
    aware_or_cst_naive_to_utc_naive,
    utc_naive_to_aware_iso,
    utc_naive_to_cst_naive,
)


TERMINAL_SHADOW_STATUSES = (
    JobStatus.SUCCEEDED.value,
    JobStatus.FAILED.value,
    JobStatus.CANCELLED.value,
)
MAX_MISMATCH_DETAILS_PER_SAMPLE = 50
MAX_ORPHAN_DIAGNOSTICS = 20
MANUAL_MIGRATION_CHECKS = (
    "确认旧执行器是唯一业务执行方，没有重复抓取账号",
    "确认开启影子记录后，主页同步耗时和数据库负载没有明显增加",
    "确认失败账号重跑与取消任务的操作结果符合预期",
)
MANUAL_MIGRATION_CHECKS_BY_KIND = {
    "posts": MANUAL_MIGRATION_CHECKS,
    "engagement": (
        "确认旧执行器是唯一业务执行方，没有重复抓取账号互动数据",
        "确认开启影子记录后，互动同步耗时和数据库负载没有明显增加",
        "确认失败账号重跑与取消任务的操作结果符合预期",
    ),
    "details": (
        "确认旧执行器是唯一业务执行方，没有重复抓取帖子详情",
        "确认影子记录只在批次边界落库，没有按每条帖子增加高频写入",
        "确认失败帖子重跑与取消任务的操作结果符合预期",
    ),
}


class HomepageSyncParityService:
    """Independently compare legacy account-sync history with shadow jobs."""

    def __init__(self, db: AsyncSession, *, sync_kind: str = "posts"):
        if sync_kind not in SHADOW_JOB_TYPES:
            raise ValueError(f"unsupported sync_kind: {sync_kind}")
        self.db = db
        self.sync_kind = sync_kind
        self.shadow_job_type = SHADOW_JOB_TYPES[sync_kind]

    async def build_report(
        self,
        *,
        finished_from: datetime | None = None,
        finished_to: datetime | None = None,
        sample_limit: int = 100,
        min_samples: int = 20,
    ) -> dict[str, Any]:
        if not 1 <= sample_limit <= 500:
            raise ValueError("sample_limit must be between 1 and 500")
        if not 1 <= min_samples <= 500:
            raise ValueError("min_samples must be between 1 and 500")
        if sample_limit < min_samples:
            raise ValueError(
                "sample_limit must be greater than or equal to min_samples"
            )

        normalized_from = _normalize_utc_filter(finished_from)
        normalized_to = _normalize_utc_filter(finished_to)
        if (
            normalized_from is not None
            and normalized_to is not None
            and normalized_from > normalized_to
        ):
            raise ValueError("finished_from must not be later than finished_to")

        legacy_filters = [
            XHSAccountSyncRun.sync_kind == self.sync_kind,
            XHSAccountSyncRun.status.in_(LEGACY_TERMINAL_STATUS_MAP.keys()),
        ]
        if normalized_from is not None:
            legacy_filters.append(
                XHSAccountSyncRun.finished_at >= utc_naive_to_cst_naive(normalized_from)
            )
        if normalized_to is not None:
            legacy_filters.append(
                XHSAccountSyncRun.finished_at <= utc_naive_to_cst_naive(normalized_to)
            )

        rows = (
            await self.db.execute(
                select(
                    XHSAccountSyncRun,
                    func.count(XHSAccountSyncRun.id).over().label("total_count"),
                )
                .options(noload(XHSAccountSyncRun.items))
                .where(*legacy_filters)
                .order_by(
                    XHSAccountSyncRun.finished_at.desc(),
                    XHSAccountSyncRun.id.desc(),
                )
                .limit(sample_limit)
            )
        ).all()
        legacy_runs = [row[0] for row in rows]
        total_count = int(rows[0].total_count) if rows else 0
        run_ids = [int(run.id) for run in legacy_runs]

        legacy_items = (
            list(
                (
                    await self.db.execute(
                        select(XHSAccountSyncRunItem).where(
                            XHSAccountSyncRunItem.run_id.in_(run_ids)
                        )
                    )
                )
                .scalars()
                .all()
            )
            if run_ids
            else []
        )
        legacy_items_by_run: dict[int, list[XHSAccountSyncRunItem]] = defaultdict(list)
        for legacy_item in legacy_items:
            legacy_items_by_run[int(legacy_item.run_id)].append(legacy_item)

        jobs = (
            list(
                (
                    await self.db.execute(
                        select(Job).where(
                            Job.job_type == self.shadow_job_type,
                            Job.worker_type == SHADOW_WORKER_TYPE,
                            Job.source_type == SHADOW_SOURCE_TYPE,
                            Job.source_id.in_([str(run_id) for run_id in run_ids]),
                        )
                    )
                )
                .scalars()
                .all()
            )
            if run_ids
            else []
        )
        jobs_by_run: dict[int, list[Job]] = defaultdict(list)
        for job in jobs:
            source_id = _optional_int(job.source_id)
            if source_id is not None:
                jobs_by_run[source_id].append(job)

        job_ids = [job.id for job in jobs]
        shadow_items = (
            list(
                (
                    await self.db.execute(
                        select(JobItem).where(JobItem.job_id.in_(job_ids))
                    )
                )
                .scalars()
                .all()
            )
            if job_ids
            else []
        )
        shadow_items_by_job: dict[int, list[JobItem]] = defaultdict(list)
        for shadow_item in shadow_items:
            shadow_items_by_job[shadow_item.job_id].append(shadow_item)

        parent_job_ids = sorted(
            {int(job.parent_job_id) for job in jobs if job.parent_job_id is not None}
        )
        parent_jobs = (
            list(
                (await self.db.execute(select(Job).where(Job.id.in_(parent_job_ids))))
                .scalars()
                .all()
            )
            if parent_job_ids
            else []
        )
        parent_job_by_id = {job.id: job for job in parent_jobs}

        orphan_diagnostics = await self._load_orphan_diagnostics(
            finished_from=normalized_from,
            finished_to=normalized_to,
        )
        samples = [
            self._compare_sample(
                run,
                legacy_items_by_run.get(int(run.id), []),
                jobs_by_run.get(int(run.id), []),
                shadow_items_by_job,
                parent_job_by_id,
            )
            for run in legacy_runs
        ]
        return self._build_report_payload(
            samples=samples,
            total_count=total_count,
            orphan_diagnostics=orphan_diagnostics,
            finished_from=normalized_from,
            finished_to=normalized_to,
            sample_limit=sample_limit,
            min_samples=min_samples,
        )

    def _compare_sample(
        self,
        legacy_run: XHSAccountSyncRun,
        legacy_items: list[XHSAccountSyncRunItem],
        jobs: list[Job],
        shadow_items_by_job: dict[int, list[JobItem]],
        parent_job_by_id: dict[int, Job],
    ) -> dict[str, Any]:
        mismatches: list[dict[str, Any]] = []
        ordered_jobs = sorted(jobs, key=lambda row: row.id)
        job = ordered_jobs[0] if ordered_jobs else None
        if job is None:
            _add_mismatch(
                mismatches,
                "missing_shadow_job",
                expected="present",
                actual=None,
            )
            shadow_items: list[JobItem] = []
        else:
            shadow_items = shadow_items_by_job.get(job.id, [])
            self._compare_job_fields(job, legacy_run, parent_job_by_id, mismatches)
            self._compare_items(shadow_items, legacy_items, mismatches)
            self._compare_result_summary(job, legacy_run, legacy_items, mismatches)
        if len(ordered_jobs) > 1:
            _add_mismatch(
                mismatches,
                "duplicate_shadow_jobs",
                expected=1,
                actual=len(ordered_jobs),
            )

        mismatch_codes = sorted({row["code"] for row in mismatches})
        mismatched_item_keys = sorted(
            {
                str(row["item_key"])
                for row in mismatches
                if row.get("item_key") is not None
            }
        )
        started_at = (
            job.started_at
            if job is not None
            else _legacy_datetime_to_utc(legacy_run.started_at)
        )
        finished_at = (
            job.finished_at
            if job is not None
            else _legacy_datetime_to_utc(legacy_run.finished_at)
        )
        return {
            "job_id": job.public_id if job is not None else None,
            "legacy_run_id": int(legacy_run.id),
            "legacy_job_id": legacy_run.job_id,
            "sync_kind": legacy_run.sync_kind,
            "source": legacy_run.source,
            "job_status": job.status if job is not None else None,
            "legacy_status": legacy_run.status,
            "account_count": len(legacy_items),
            "shadow_item_count": len(shadow_items),
            "matched": not mismatches,
            "mismatch_codes": mismatch_codes,
            "mismatched_item_count": len(legacy_items)
            if job is None
            else len(mismatched_item_keys),
            "mismatches": mismatches[:MAX_MISMATCH_DETAILS_PER_SAMPLE],
            "mismatches_truncated": len(mismatches) > MAX_MISMATCH_DETAILS_PER_SAMPLE,
            "created_at": utc_naive_to_aware_iso(job.created_at)
            if job is not None
            else utc_naive_to_aware_iso(_legacy_datetime_to_utc(legacy_run.created_at)),
            "started_at": utc_naive_to_aware_iso(started_at),
            "finished_at": utc_naive_to_aware_iso(finished_at),
        }

    async def _load_orphan_diagnostics(
        self,
        *,
        finished_from: datetime | None,
        finished_to: datetime | None,
    ) -> dict[str, Any]:
        legacy_run_exists = exists(
            select(XHSAccountSyncRun.id).where(
                cast(XHSAccountSyncRun.id, String) == Job.source_id
            )
        )
        filters = [
            Job.job_type == self.shadow_job_type,
            Job.worker_type == SHADOW_WORKER_TYPE,
            Job.source_type == SHADOW_SOURCE_TYPE,
            Job.status.in_(TERMINAL_SHADOW_STATUSES),
            ~legacy_run_exists,
        ]
        if finished_from is not None:
            filters.append(Job.finished_at >= finished_from)
        if finished_to is not None:
            filters.append(Job.finished_at <= finished_to)
        rows = (
            await self.db.execute(
                select(Job, func.count(Job.id).over().label("total_count"))
                .where(*filters)
                .order_by(Job.finished_at.desc(), Job.id.desc())
                .limit(MAX_ORPHAN_DIAGNOSTICS)
            )
        ).all()
        total_count = int(rows[0].total_count) if rows else 0
        items = []
        for row in rows:
            job = row[0]
            code = (
                "invalid_source_id"
                if _optional_int(job.source_id) is None
                else "missing_legacy_run"
            )
            items.append(
                {
                    "job_id": job.public_id,
                    "source_id": job.source_id,
                    "job_status": job.status,
                    "code": code,
                    "finished_at": utc_naive_to_aware_iso(job.finished_at),
                }
            )
        return {
            "total_count": total_count,
            "items": items,
            "is_truncated": total_count > len(items),
        }

    @staticmethod
    def _compare_job_fields(
        job: Job,
        run: XHSAccountSyncRun,
        parent_job_by_id: dict[int, Job],
        mismatches: list[dict[str, Any]],
    ) -> None:
        expected_status = LEGACY_TERMINAL_STATUS_MAP.get(str(run.status or ""))
        _compare_value(
            mismatches,
            "job_status",
            expected_status,
            job.status,
        )
        _compare_value(
            mismatches,
            "requested_by_user",
            _optional_int(run.requested_by_user_id),
            job.requested_by_user_id,
        )
        payload = job.payload if isinstance(job.payload, dict) else {}
        _compare_value(
            mismatches,
            "payload_legacy_run_id",
            int(run.id),
            _optional_int(payload.get("legacy_run_id")),
        )
        _compare_value(
            mismatches,
            "payload_legacy_job_id",
            run.job_id,
            payload.get("legacy_job_id"),
        )
        _compare_value(
            mismatches,
            "payload_source",
            run.source,
            payload.get("legacy_source"),
        )
        _compare_value(
            mismatches,
            "request_config",
            copy.deepcopy(run.request_config or {}),
            copy.deepcopy(payload.get("request_config") or {}),
        )
        _compare_value(
            mismatches,
            "payload_shadow_mode",
            True,
            payload.get("shadow_mode"),
        )
        is_failed = run.status == JobStatus.FAILED.value
        expected_error = run.error if is_failed else None
        _compare_value(
            mismatches,
            "job_error_code",
            "legacy_sync_failed" if is_failed else None,
            job.error_code,
        )
        _compare_value(
            mismatches,
            "job_user_message",
            expected_error,
            job.user_message,
        )
        _compare_value(
            mismatches,
            "job_internal_error",
            expected_error,
            job.internal_error,
        )
        _compare_value(
            mismatches,
            "job_cancel_requested",
            run.status == JobStatus.CANCELLED.value,
            job.cancel_requested,
        )
        if run.started_at is not None:
            _compare_value(
                mismatches,
                "job_started_at",
                _legacy_datetime_to_utc(run.started_at),
                job.started_at,
            )
        if run.finished_at is not None:
            _compare_value(
                mismatches,
                "job_finished_at",
                _legacy_datetime_to_utc(run.finished_at),
                job.finished_at,
            )

        if run.parent_run_id is None:
            if job.parent_job_id is not None:
                _add_mismatch(
                    mismatches,
                    "unexpected_parent_job",
                    expected=None,
                    actual=job.parent_job_id,
                )
            return

        if job.parent_job_id is None:
            _add_mismatch(
                mismatches,
                "missing_parent_job",
                expected=int(run.parent_run_id),
                actual=None,
            )
            return
        parent = parent_job_by_id.get(int(job.parent_job_id))
        actual_parent_run_id = (
            _optional_int(parent.source_id)
            if parent is not None and parent.source_type == SHADOW_SOURCE_TYPE
            else None
        )
        _compare_value(
            mismatches,
            "parent_run",
            int(run.parent_run_id),
            actual_parent_run_id,
        )

    @staticmethod
    def _compare_items(
        shadow_items: list[JobItem],
        legacy_items: list[XHSAccountSyncRunItem],
        mismatches: list[dict[str, Any]],
    ) -> None:
        shadow_by_key = {item.item_key: item for item in shadow_items}
        legacy_by_key = {_legacy_item_key(item): item for item in legacy_items}
        for item_key in sorted(legacy_by_key.keys() - shadow_by_key.keys()):
            _add_mismatch(
                mismatches,
                "missing_shadow_item",
                item_key=item_key,
                expected="present",
                actual=None,
            )
        for item_key in sorted(shadow_by_key.keys() - legacy_by_key.keys()):
            _add_mismatch(
                mismatches,
                "extra_shadow_item",
                item_key=item_key,
                expected=None,
                actual="present",
            )

        for item_key in sorted(legacy_by_key.keys() & shadow_by_key.keys()):
            legacy = legacy_by_key[item_key]
            shadow = shadow_by_key[item_key]
            expected_error_code = "legacy_sync_failed" if legacy.error else None
            comparisons = (
                ("item_status", str(legacy.status or "queued"), shadow.status),
                (
                    "item_display_name",
                    (legacy.account_name or "").strip() or None,
                    shadow.display_name,
                ),
                ("item_result", copy.deepcopy(legacy.result), shadow.result),
                ("item_message", legacy.message, shadow.user_message),
                ("item_error", legacy.error, shadow.internal_error),
                ("item_error_code", expected_error_code, shadow.error_code),
                (
                    "item_attempt_count",
                    0 if str(legacy.status or "queued") == "queued" else 1,
                    shadow.attempt_count,
                ),
                (
                    "item_started_at",
                    _legacy_datetime_to_utc(legacy.started_at),
                    shadow.started_at,
                ),
                (
                    "item_finished_at",
                    _legacy_datetime_to_utc(legacy.finished_at),
                    shadow.finished_at,
                ),
            )
            for code, expected, actual in comparisons:
                _compare_value(
                    mismatches,
                    code,
                    expected,
                    actual,
                    item_key=item_key,
                )

            shadow_payload = shadow.payload if isinstance(shadow.payload, dict) else {}
            _compare_value(
                mismatches,
                "item_environment_id",
                _optional_int(legacy.environment_id),
                _optional_int(shadow_payload.get("environment_id")),
                item_key=item_key,
            )
            _compare_value(
                mismatches,
                "item_legacy_id",
                int(legacy.id),
                _optional_int(shadow_payload.get("legacy_run_item_id")),
                item_key=item_key,
            )

    @staticmethod
    def _compare_result_summary(
        job: Job,
        run: XHSAccountSyncRun,
        legacy_items: list[XHSAccountSyncRunItem],
        mismatches: list[dict[str, Any]],
    ) -> None:
        summary = job.result_summary if isinstance(job.result_summary, dict) else {}
        counts = Counter(str(item.status or "queued") for item in legacy_items)
        processed = counts["succeeded"] + counts["failed"] + counts["cancelled"]
        comparisons = (
            ("summary_shadow_mode", True, summary.get("shadow_mode")),
            (
                "summary_legacy_run_id",
                int(run.id),
                _optional_int(summary.get("legacy_run_id")),
            ),
            ("summary_legacy_job_id", run.job_id, summary.get("legacy_job_id")),
            ("summary_legacy_status", run.status, summary.get("legacy_status")),
            ("summary_history_status", run.status, summary.get("history_status")),
            (
                "summary_total_accounts",
                len(legacy_items),
                _optional_int(summary.get("total_accounts")),
            ),
            (
                "summary_succeeded_accounts",
                counts["succeeded"],
                _optional_int(summary.get("succeeded_accounts")),
            ),
            (
                "summary_failed_accounts",
                counts["failed"],
                _optional_int(summary.get("failed_accounts")),
            ),
            (
                "summary_cancelled_accounts",
                counts["cancelled"],
                _optional_int(summary.get("cancelled_accounts")),
            ),
            ("job_progress_total", len(legacy_items), job.progress_total),
            ("job_progress_current", processed, job.progress_current),
        )
        for code, expected, actual in comparisons:
            _compare_value(mismatches, code, expected, actual)

    def _build_report_payload(
        self,
        *,
        samples: list[dict[str, Any]],
        total_count: int,
        orphan_diagnostics: dict[str, Any],
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
        orphan_count = int(orphan_diagnostics.get("total_count") or 0)
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
            "feature_enabled": (
                settings.xhs_homepage_sync_shadow_enabled
                if self.sync_kind == "posts"
                else settings.xhs_engagement_detail_sync_shadow_enabled
            ),
            "sync_kind": self.sync_kind,
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
                "match_rate": round(matched_count / len(samples), 4)
                if samples
                else 0.0,
                "mismatch_reasons": dict(sorted(reason_counts.items())),
                "is_truncated": total_count > len(samples),
            },
            "diagnostics": {
                "orphan_shadow_jobs": orphan_diagnostics,
            },
            "migration_gate": {
                "decision": decision,
                "automated_checks_passed": automated_checks_passed,
                "execution_cutover_allowed": False,
                "manual_checks_required": list(
                    MANUAL_MIGRATION_CHECKS_BY_KIND[self.sync_kind]
                ),
            },
            "samples": samples,
        }


def _normalize_utc_filter(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value
    return value.astimezone(timezone.utc).replace(tzinfo=None)


def _legacy_item_key(item: XHSAccountSyncRunItem) -> str:
    if item.environment_id:
        return f"environment:{int(item.environment_id)}"
    return f"legacy-item:{int(item.id)}"


def _optional_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _legacy_datetime_to_utc(value: Any) -> datetime | None:
    if not isinstance(value, datetime):
        return None
    return aware_or_cst_naive_to_utc_naive(value)


def _compare_value(
    mismatches: list[dict[str, Any]],
    code: str,
    expected: Any,
    actual: Any,
    *,
    item_key: str | None = None,
) -> None:
    if expected == actual:
        return
    _add_mismatch(
        mismatches,
        code,
        item_key=item_key,
        expected=expected,
        actual=actual,
    )


def _add_mismatch(
    mismatches: list[dict[str, Any]],
    code: str,
    *,
    expected: Any,
    actual: Any,
    item_key: str | None = None,
) -> None:
    row = {
        "code": code,
        "expected": _json_safe_value(expected),
        "actual": _json_safe_value(actual),
    }
    if item_key is not None:
        row["item_key"] = item_key
    mismatches.append(row)


def _json_safe_value(value: Any) -> Any:
    if isinstance(value, datetime):
        return utc_naive_to_aware_iso(value)
    return copy.deepcopy(value)
