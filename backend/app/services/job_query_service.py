from __future__ import annotations

import re
from datetime import datetime
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.job import Job, JobAttempt, JobEvent, JobItem, JobStatus
from app.models.user import User
from app.utils.timezone import utc_naive_to_aware_iso


SUPPORTED_JOB_STATUSES = frozenset(status.value for status in JobStatus)
_SECRET_KEY_MARKERS = (
    "api_key",
    "apikey",
    "authorization",
    "cookie",
    "password",
    "secret",
    "access_key",
    "private_key",
    "credential",
    "token",
)
_CONTENT_KEY_MARKERS = (
    "prompt",
    "negative_prompt",
    "image_data",
    "images_data",
    "base64",
    "b64_json",
)
_SENSITIVE_QUERY_KEYS = frozenset(
    {
        "token",
        "signature",
        "x-oss-signature",
        "ossaccesskeyid",
        "access_key",
        "api_key",
        "x-amz-credential",
        "x-amz-signature",
        "x-amz-security-token",
    }
)
_BEARER_PATTERN = re.compile(r"(?i)bearer\s+[a-z0-9._~+/=-]+")
_INLINE_SECRET_PATTERN = re.compile(
    r"(?i)(\b(?:api[_-]?key|access[_-]?key|authorization|password|secret|token)\b\s*[:=]\s*)([^\s,;&]+)"
)


class JobQueryError(ValueError):
    pass


class JobQueryNotFound(JobQueryError):
    pass


class JobQueryService:
    """Read-only task-center queries with bounded, sanitized output."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def list_jobs(
        self,
        *,
        page: int = 1,
        limit: int = 20,
        status: str | None = None,
        job_type: str | None = None,
        worker_type: str | None = None,
        username: str | None = None,
        search: str | None = None,
    ) -> dict[str, Any]:
        normalized_page = max(1, int(page))
        normalized_limit = max(1, min(int(limit), 100))
        normalized_status = str(status or "").strip().lower() or None
        if normalized_status and normalized_status not in SUPPORTED_JOB_STATUSES:
            raise JobQueryError("不支持的任务状态")

        conditions = self._build_conditions(
            job_type=job_type,
            worker_type=worker_type,
            username=username,
            search=search,
        )
        filtered_conditions = list(conditions)
        if normalized_status:
            filtered_conditions.append(Job.status == normalized_status)

        total = int(
            (
                await self.db.execute(
                    select(func.count(Job.id))
                    .select_from(Job)
                    .outerjoin(User, Job.requested_by_user_id == User.id)
                    .where(*filtered_conditions)
                )
            ).scalar_one()
        )
        rows = (
            await self.db.execute(
                select(Job, User.username, User.display_name)
                .outerjoin(User, Job.requested_by_user_id == User.id)
                .where(*filtered_conditions)
                .order_by(Job.created_at.desc(), Job.id.desc())
                .offset((normalized_page - 1) * normalized_limit)
                .limit(normalized_limit)
            )
        ).all()

        status_rows = (
            await self.db.execute(
                select(Job.status, func.count(Job.id))
                .select_from(Job)
                .outerjoin(User, Job.requested_by_user_id == User.id)
                .where(*conditions)
                .group_by(Job.status)
            )
        ).all()
        status_counts = {status.value: 0 for status in JobStatus}
        for row_status, count in status_rows:
            status_counts[str(row_status)] = int(count or 0)

        job_types = list(
            (
                await self.db.execute(
                    select(Job.job_type)
                    .distinct()
                    .order_by(Job.job_type.asc())
                    .limit(100)
                )
            ).scalars()
        )
        worker_types = list(
            (
                await self.db.execute(
                    select(Job.worker_type)
                    .distinct()
                    .order_by(Job.worker_type.asc())
                    .limit(100)
                )
            ).scalars()
        )
        return {
            "items": [
                self._serialize_list_item(job, username_value, display_name)
                for job, username_value, display_name in rows
            ],
            "total": total,
            "page": normalized_page,
            "limit": normalized_limit,
            "summary": {
                "total": sum(status_counts.values()),
                "active": sum(
                    status_counts[name]
                    for name in (
                        JobStatus.QUEUED.value,
                        JobStatus.LEASED.value,
                        JobStatus.RUNNING.value,
                        JobStatus.RETRY_WAIT.value,
                    )
                ),
                "attention": status_counts[JobStatus.WAITING_REVIEW.value]
                + status_counts[JobStatus.DEAD_LETTER.value],
                "status_counts": status_counts,
            },
            "filters": {
                "job_types": [str(value) for value in job_types if value],
                "worker_types": [str(value) for value in worker_types if value],
            },
        }

    async def get_job(self, job_id: int) -> dict[str, Any]:
        row = (
            await self.db.execute(
                select(Job, User.username, User.display_name)
                .outerjoin(User, Job.requested_by_user_id == User.id)
                .where(Job.id == int(job_id))
            )
        ).first()
        if row is None:
            raise JobQueryNotFound("未找到统一任务")
        job, username, display_name = row

        items_with_sentinel = list(
            (
                await self.db.execute(
                    select(JobItem)
                    .where(JobItem.job_id == job.id)
                    .order_by(JobItem.id.asc())
                    .limit(1001)
                )
            ).scalars()
        )
        attempts_with_sentinel = list(
            (
                await self.db.execute(
                    select(JobAttempt)
                    .where(JobAttempt.job_id == job.id)
                    .order_by(JobAttempt.attempt_number.asc(), JobAttempt.id.asc())
                    .limit(201)
                )
            ).scalars()
        )
        events_with_sentinel = list(
            (
                await self.db.execute(
                    select(JobEvent)
                    .where(JobEvent.job_id == job.id)
                    .order_by(JobEvent.created_at.asc(), JobEvent.id.asc())
                    .limit(1001)
                )
            ).scalars()
        )
        children = list(
            (
                await self.db.execute(
                    select(Job)
                    .where(Job.parent_job_id == job.id)
                    .order_by(Job.created_at.asc(), Job.id.asc())
                    .limit(200)
                )
            ).scalars()
        )
        parent = await self.db.get(Job, job.parent_job_id) if job.parent_job_id else None
        items = items_with_sentinel[:1000]
        attempts = attempts_with_sentinel[:200]
        events = events_with_sentinel[:1000]

        data = self._serialize_list_item(job, username, display_name)
        data.update(
            {
                "scope_key": job.scope_key,
                "idempotency_key": job.idempotency_key,
                "parent": self._serialize_relation(parent),
                "children": [self._serialize_relation(child) for child in children],
                "payload": sanitize_job_data(job.payload),
                "result_summary": sanitize_job_data(job.result_summary),
                "items": [self._serialize_item(item) for item in items],
                "attempts": [self._serialize_attempt(attempt) for attempt in attempts],
                "events": [self._serialize_event(event) for event in events],
                "diagnostics": {
                    "item_count": len(items),
                    "attempt_count": len(attempts),
                    "event_count": len(events),
                    "items_truncated": len(items_with_sentinel) > 1000,
                    "attempts_truncated": len(attempts_with_sentinel) > 200,
                    "events_truncated": len(events_with_sentinel) > 1000,
                },
            }
        )
        return data

    @staticmethod
    def _build_conditions(
        *,
        job_type: str | None,
        worker_type: str | None,
        username: str | None,
        search: str | None,
    ) -> list[Any]:
        conditions: list[Any] = []
        normalized_job_type = str(job_type or "").strip()
        normalized_worker_type = str(worker_type or "").strip()
        normalized_username = str(username or "").strip()
        normalized_search = str(search or "").strip()
        if normalized_job_type:
            conditions.append(Job.job_type == normalized_job_type)
        if normalized_worker_type:
            conditions.append(Job.worker_type == normalized_worker_type)
        if normalized_username:
            pattern = f"%{normalized_username}%"
            conditions.append(
                or_(User.username.ilike(pattern), User.display_name.ilike(pattern))
            )
        if normalized_search:
            pattern = f"%{normalized_search}%"
            search_conditions = [
                Job.public_id.ilike(pattern),
                Job.source_id.ilike(pattern),
                Job.current_step.ilike(pattern),
                Job.error_code.ilike(pattern),
                Job.user_message.ilike(pattern),
            ]
            numeric_search = normalized_search.removeprefix("#")
            if numeric_search.isdigit():
                search_conditions.append(Job.id == int(numeric_search))
            conditions.append(or_(*search_conditions))
        return conditions

    @staticmethod
    def _serialize_list_item(
        job: Job,
        username: str | None,
        display_name: str | None,
    ) -> dict[str, Any]:
        return {
            "id": int(job.id),
            "public_id": job.public_id,
            "job_type": job.job_type,
            "worker_type": job.worker_type,
            "status": job.status,
            "priority": int(job.priority or 0),
            "requested_by_user_id": job.requested_by_user_id,
            "username": username,
            "display_name": display_name,
            "source_type": job.source_type,
            "source_id": job.source_id,
            "progress_current": int(job.progress_current or 0),
            "progress_total": int(job.progress_total or 0),
            "current_step": job.current_step,
            "retry_count": int(job.retry_count or 0),
            "max_retries": int(job.max_retries or 0),
            "cancel_requested": bool(job.cancel_requested),
            "error_code": job.error_code,
            "user_message": sanitize_job_text(job.user_message),
            "lease_owner": job.lease_owner,
            "run_after": _iso(job.run_after),
            "lease_expires_at": _iso(job.lease_expires_at),
            "heartbeat_at": _iso(job.heartbeat_at),
            "started_at": _iso(job.started_at),
            "finished_at": _iso(job.finished_at),
            "created_at": _iso(job.created_at),
            "updated_at": _iso(job.updated_at),
        }

    @staticmethod
    def _serialize_relation(job: Job | None) -> dict[str, Any] | None:
        if job is None:
            return None
        return {
            "id": int(job.id),
            "public_id": job.public_id,
            "job_type": job.job_type,
            "status": job.status,
        }

    @staticmethod
    def _serialize_item(item: JobItem) -> dict[str, Any]:
        return {
            "id": int(item.id),
            "item_key": item.item_key,
            "item_type": item.item_type,
            "display_name": item.display_name,
            "status": item.status,
            "attempt_count": int(item.attempt_count or 0),
            "payload": sanitize_job_data(item.payload),
            "result": sanitize_job_data(item.result),
            "error_code": item.error_code,
            "user_message": sanitize_job_text(item.user_message),
            "started_at": _iso(item.started_at),
            "finished_at": _iso(item.finished_at),
            "created_at": _iso(item.created_at),
            "updated_at": _iso(item.updated_at),
        }

    @staticmethod
    def _serialize_attempt(attempt: JobAttempt) -> dict[str, Any]:
        return {
            "id": int(attempt.id),
            "attempt_number": int(attempt.attempt_number),
            "worker_id": attempt.worker_id,
            "status": attempt.status,
            "lease_expires_at": _iso(attempt.lease_expires_at),
            "heartbeat_at": _iso(attempt.heartbeat_at),
            "metrics": sanitize_job_data(attempt.metrics),
            "error_code": attempt.error_code,
            "user_message": sanitize_job_text(attempt.user_message),
            "started_at": _iso(attempt.started_at),
            "finished_at": _iso(attempt.finished_at),
            "created_at": _iso(attempt.created_at),
        }

    @staticmethod
    def _serialize_event(event: JobEvent) -> dict[str, Any]:
        return {
            "id": int(event.id),
            "event_type": event.event_type,
            "from_status": event.from_status,
            "to_status": event.to_status,
            "level": event.level,
            "message": sanitize_job_text(event.message),
            "details": sanitize_job_data(event.details),
            "actor_type": event.actor_type,
            "actor_id": event.actor_id,
            "created_at": _iso(event.created_at),
        }


def sanitize_job_data(value: Any, *, depth: int = 0) -> Any:
    if depth >= 6:
        return "[truncated]"
    if isinstance(value, dict):
        sanitized: dict[str, Any] = {}
        for index, (key, item) in enumerate(value.items()):
            if index >= 100:
                sanitized["_truncated"] = True
                break
            normalized_key = str(key)
            lowered = normalized_key.lower()
            if any(marker in lowered for marker in _SECRET_KEY_MARKERS):
                sanitized[normalized_key] = "[redacted]"
            elif any(marker in lowered for marker in _CONTENT_KEY_MARKERS):
                sanitized[normalized_key] = "[omitted]"
            else:
                sanitized[normalized_key] = sanitize_job_data(item, depth=depth + 1)
        return sanitized
    if isinstance(value, (list, tuple)):
        items = [sanitize_job_data(item, depth=depth + 1) for item in value[:100]]
        if len(value) > 100:
            items.append("[truncated]")
        return items
    if isinstance(value, str):
        return sanitize_job_text(value)
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return sanitize_job_text(str(value))


def sanitize_job_text(value: Any) -> str | None:
    if value is None:
        return None
    text = _BEARER_PATTERN.sub("Bearer [redacted]", str(value))
    text = _INLINE_SECRET_PATTERN.sub(r"\1[redacted]", text)
    if len(text) > 2000:
        text = f"{text[:2000]}...[truncated]"
    if text.startswith(("http://", "https://")):
        text = _sanitize_url(text)
    return text


def _sanitize_url(value: str) -> str:
    try:
        parts = urlsplit(value)
        query = [
            (key, "[redacted]" if key.lower() in _SENSITIVE_QUERY_KEYS else item)
            for key, item in parse_qsl(parts.query, keep_blank_values=True)
        ]
        return urlunsplit(
            (parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment)
        )
    except ValueError:
        return value


def _iso(value: datetime | None) -> str | None:
    return utc_naive_to_aware_iso(value) if isinstance(value, datetime) else None
