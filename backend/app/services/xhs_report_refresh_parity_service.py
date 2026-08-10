from __future__ import annotations

import copy
from collections import Counter, defaultdict
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import String, cast, exists, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.job import Job, JobItem
from app.models.xhs_report_refresh_run import XHSReportRefreshRun
from app.services.xhs_report_refresh_shadow import (
    REPORT_REFRESH_JOB_TYPE,
    REPORT_REFRESH_SOURCE_TYPE,
    REPORT_REFRESH_WORKER_TYPE,
    RUN_TO_JOB_STATUS,
    TERMINAL_RUN_STATUSES,
    _reports_by_type,
    _report_types,
)
from app.utils.timezone import utc_naive_to_aware_iso


MAX_MISMATCH_DETAILS = 100
MAX_ORPHAN_DETAILS = 100
MANUAL_MIGRATION_CHECKS = (
    "verify the legacy report API is called exactly once per report type",
    "compare refreshed row/account totals with the legacy dashboard cache",
    "measure refresh duration and database load before execution cutover",
)


class ReportRefreshParityService:
    """Independently compare legacy refresh history with durable shadow jobs."""

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

        run_filters = [XHSReportRefreshRun.status.in_(TERMINAL_RUN_STATUSES)]
        if normalized_from:
            run_filters.append(XHSReportRefreshRun.finished_at >= normalized_from)
        if normalized_to:
            run_filters.append(XHSReportRefreshRun.finished_at <= normalized_to)

        run_rows = (
            await self.db.execute(
                select(
                    XHSReportRefreshRun,
                    func.count(XHSReportRefreshRun.id).over().label("total_count"),
                )
                .where(*run_filters)
                .order_by(
                    XHSReportRefreshRun.finished_at.desc(),
                    XHSReportRefreshRun.id.desc(),
                )
                .limit(normalized_limit)
            )
        ).all()
        runs = [row[0] for row in run_rows]
        total_count = int(run_rows[0][1]) if run_rows else 0
        run_ids = [int(run.id) for run in runs]

        jobs_by_run: dict[int, list[Job]] = defaultdict(list)
        items_by_job: dict[int, list[JobItem]] = defaultdict(list)
        if run_ids:
            jobs = list(
                (
                    await self.db.execute(
                        select(Job).where(
                            Job.source_type == REPORT_REFRESH_SOURCE_TYPE,
                            Job.source_id.in_([str(run_id) for run_id in run_ids]),
                        )
                    )
                ).scalars()
            )
            for job in jobs:
                run_id = _optional_int(job.source_id)
                if run_id is not None:
                    jobs_by_run[run_id].append(job)
            job_ids = [int(job.id) for job in jobs]
            if job_ids:
                items = list(
                    (
                        await self.db.execute(
                            select(JobItem)
                            .where(JobItem.job_id.in_(job_ids))
                            .order_by(JobItem.job_id.asc(), JobItem.id.asc())
                        )
                    ).scalars()
                )
                for item in items:
                    items_by_job[int(item.job_id)].append(item)

        orphan_diagnostics = await self._load_orphan_diagnostics()
        samples = [
            self._compare_run(
                run,
                jobs_by_run.get(int(run.id), []),
                items_by_job,
            )
            for run in runs
        ]
        return self._build_payload(
            samples=samples,
            total_count=total_count,
            orphan_diagnostics=orphan_diagnostics,
            finished_from=normalized_from,
            finished_to=normalized_to,
            sample_limit=normalized_limit,
            min_samples=normalized_min,
        )

    async def _load_orphan_diagnostics(self) -> dict[str, Any]:
        valid_source = exists(
            select(XHSReportRefreshRun.id).where(
                cast(XHSReportRefreshRun.id, String) == Job.source_id
            )
        )
        orphan_filter = (
            Job.source_type == REPORT_REFRESH_SOURCE_TYPE,
            ~valid_source,
        )
        total = int(
            (
                await self.db.execute(
                    select(func.count(Job.id)).where(*orphan_filter)
                )
            ).scalar_one()
        )
        rows = list(
            (
                await self.db.execute(
                    select(Job)
                    .where(*orphan_filter)
                    .order_by(Job.id.desc())
                    .limit(MAX_ORPHAN_DETAILS)
                )
            ).scalars()
        )
        return {
            "total_count": total,
            "items": [
                {
                    "job_id": int(job.id),
                    "public_id": job.public_id,
                    "source_id": job.source_id,
                    "status": job.status,
                }
                for job in rows
            ],
            "is_truncated": total > len(rows),
        }

    def _compare_run(
        self,
        run: XHSReportRefreshRun,
        jobs: list[Job],
        items_by_job: dict[int, list[JobItem]],
    ) -> dict[str, Any]:
        mismatches: list[dict[str, Any]] = []
        if not jobs:
            _add_mismatch(
                mismatches,
                "missing_shadow_job",
                expected=1,
                actual=0,
            )
            return self._sample(run, None, mismatches)
        if len(jobs) > 1:
            _add_mismatch(
                mismatches,
                "duplicate_shadow_job",
                expected=1,
                actual=len(jobs),
            )

        job = sorted(jobs, key=lambda row: int(row.id))[0]
        report_types = _report_types(run.request_config)
        reports = _reports_by_type(run.result_summary)
        expected_status = RUN_TO_JOB_STATUS.get(str(run.status or ""))
        expected_progress = len([name for name in report_types if name in reports])
        payload = job.payload if isinstance(job.payload, dict) else {}
        comparisons = (
            ("job_type", REPORT_REFRESH_JOB_TYPE, job.job_type),
            ("worker_type", REPORT_REFRESH_WORKER_TYPE, job.worker_type),
            ("job_status", expected_status, job.status),
            ("requested_by_user_id", run.requested_by_user_id, job.requested_by_user_id),
            ("source_id", str(run.id), job.source_id),
            (
                "idempotency_key",
                f"legacy-report-refresh:{run.job_id}",
                job.idempotency_key,
            ),
            ("payload_shadow_mode", True, payload.get("shadow_mode")),
            ("payload_legacy_run_id", int(run.id), _optional_int(payload.get("legacy_run_id"))),
            ("payload_legacy_job_id", run.job_id, payload.get("legacy_job_id")),
            ("payload_legacy_source", run.source, payload.get("legacy_source")),
            ("payload_request_config", run.request_config or {}, payload.get("request_config") or {}),
            ("progress_total", len(report_types), job.progress_total),
            ("progress_current", expected_progress, job.progress_current),
            ("started_at", run.started_at, job.started_at),
            ("finished_at", run.finished_at, job.finished_at),
        )
        for code, expected, actual in comparisons:
            _compare_value(mismatches, code, expected, actual)

        self._compare_items(
            run,
            report_types,
            reports,
            items_by_job.get(int(job.id), []),
            mismatches,
        )
        self._compare_summary(run, job, reports, mismatches)
        return self._sample(run, job, mismatches)

    @staticmethod
    def _compare_items(
        run: XHSReportRefreshRun,
        report_types: list[str],
        reports: dict[str, dict[str, Any]],
        items: list[JobItem],
        mismatches: list[dict[str, Any]],
    ) -> None:
        items_by_key = {item.item_key: item for item in items}
        expected_keys = {f"report:{name}" for name in report_types}
        actual_keys = set(items_by_key)
        for key in sorted(expected_keys - actual_keys):
            _add_mismatch(
                mismatches,
                "missing_report_item",
                item_key=key,
                expected="present",
                actual="missing",
            )
        for key in sorted(actual_keys - expected_keys):
            _add_mismatch(
                mismatches,
                "extra_report_item",
                item_key=key,
                expected="absent",
                actual="present",
            )
        for report_type in report_types:
            key = f"report:{report_type}"
            item = items_by_key.get(key)
            if item is None:
                continue
            entry = reports.get(report_type)
            expected_item_status = (
                str(entry.get("status"))
                if entry is not None
                else ("running" if run.status == "running" else "queued")
            )
            _compare_value(
                mismatches,
                "item_status",
                expected_item_status,
                item.status,
                item_key=key,
            )
            payload = item.payload if isinstance(item.payload, dict) else {}
            _compare_value(
                mismatches,
                "item_report_type",
                report_type,
                payload.get("report_type"),
                item_key=key,
            )
            if entry is None:
                continue
            result = item.result if isinstance(item.result, dict) else {}
            for field in ("updated_accounts", "updated_rows", "error_count"):
                _compare_value(
                    mismatches,
                    f"item_{field}",
                    _safe_int(entry.get(field)),
                    _safe_int(result.get(field)),
                    item_key=key,
                )

    @staticmethod
    def _compare_summary(
        run: XHSReportRefreshRun,
        job: Job,
        reports: dict[str, dict[str, Any]],
        mismatches: list[dict[str, Any]],
    ) -> None:
        summary = job.result_summary if isinstance(job.result_summary, dict) else {}
        legacy = run.result_summary if isinstance(run.result_summary, dict) else {}
        comparisons = (
            ("summary_shadow_mode", True, summary.get("shadow_mode")),
            ("summary_legacy_run_id", int(run.id), _optional_int(summary.get("legacy_run_id"))),
            ("summary_legacy_job_id", run.job_id, summary.get("legacy_job_id")),
            ("summary_legacy_status", run.status, summary.get("legacy_status")),
            (
                "summary_updated_accounts",
                _safe_int(legacy.get("updated_accounts")),
                _safe_int(summary.get("updated_accounts")),
            ),
            (
                "summary_updated_rows",
                _safe_int(legacy.get("updated_rows")),
                _safe_int(summary.get("updated_rows")),
            ),
            (
                "summary_error_count",
                _safe_int(legacy.get("error_count")),
                _safe_int(summary.get("error_count")),
            ),
            ("summary_reports", list(reports.values()), summary.get("reports") or []),
        )
        for code, expected, actual in comparisons:
            _compare_value(mismatches, code, expected, actual)

    @staticmethod
    def _sample(
        run: XHSReportRefreshRun,
        job: Job | None,
        mismatches: list[dict[str, Any]],
    ) -> dict[str, Any]:
        all_codes = [str(item["code"]) for item in mismatches]
        return {
            "legacy_run_id": int(run.id),
            "legacy_job_id": run.job_id,
            "source": run.source,
            "legacy_status": run.status,
            "job_id": job.public_id if job else None,
            "durable_status": job.status if job else None,
            "report_types": _report_types(run.request_config),
            "updated_accounts": _safe_int(
                (run.result_summary or {}).get("updated_accounts")
            ),
            "updated_rows": _safe_int((run.result_summary or {}).get("updated_rows")),
            "error_count": _safe_int((run.result_summary or {}).get("error_count")),
            "finished_at": utc_naive_to_aware_iso(run.finished_at),
            "matched": not mismatches,
            "mismatch_codes": sorted(set(all_codes)),
            "mismatch_count": len(mismatches),
            "mismatches": copy.deepcopy(mismatches[:MAX_MISMATCH_DETAILS]),
            "mismatches_truncated": len(mismatches) > MAX_MISMATCH_DETAILS,
        }

    @staticmethod
    def _build_payload(
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
        orphan_count = _safe_int(orphan_diagnostics.get("total_count"))
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
            "feature_enabled": settings.xhs_report_refresh_shadow_enabled,
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
            "diagnostics": {"orphan_shadow_jobs": orphan_diagnostics},
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
    *,
    item_key: str | None = None,
) -> None:
    if expected == actual:
        return
    _add_mismatch(
        mismatches,
        code,
        expected=expected,
        actual=actual,
        item_key=item_key,
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
        "expected": _json_safe(expected),
        "actual": _json_safe(actual),
    }
    if item_key is not None:
        row["item_key"] = item_key
    mismatches.append(row)


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
