from __future__ import annotations

from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.deps import require_admin
from app.db.session import get_db
from app.models.user import User
from app.schemas.common import ApiResponse
from app.services.ai_image_reconciliation_service import (
    AIImageReconciliationConflict,
    AIImageReconciliationError,
    AIImageReconciliationNotFound,
    AIImageReconciliationService,
)
from app.services.job_query_service import (
    JobQueryError,
    JobQueryNotFound,
    JobQueryService,
)
from app.services.xhs_homepage_sync_parity_service import HomepageSyncParityService
from app.services.xhs_report_refresh_parity_service import (
    ReportRefreshParityService,
)
from app.services.dify_task_parity_service import DifyTaskParityService
from app.services.scheduler_leader import (
    SCHEDULER_LEASE_KEY,
    SchedulerLeaseService,
    normalized_scheduler_lease_settings,
)
from app.utils.timezone import utc_naive_to_aware_iso, utc_now_naive


router = APIRouter()


@router.get("/scheduler-leader")
async def get_scheduler_leader_status(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """Return the current database-backed scheduler leader lease."""

    lease = await SchedulerLeaseService(db).get(SCHEDULER_LEASE_KEY)
    now = utc_now_naive()
    lease_seconds, heartbeat_seconds = normalized_scheduler_lease_settings()
    is_healthy = bool(
        lease
        and lease.owner_id
        and lease.lease_expires_at
        and lease.lease_expires_at > now
    )
    return ApiResponse(
        data={
            "enabled": settings.scheduler_leader_enabled,
            "lease_key": SCHEDULER_LEASE_KEY,
            "owner_id": lease.owner_id if lease else None,
            "is_healthy": is_healthy,
            "acquired_at": utc_naive_to_aware_iso(
                lease.acquired_at if lease else None
            ),
            "heartbeat_at": utc_naive_to_aware_iso(
                lease.heartbeat_at if lease else None
            ),
            "lease_expires_at": utc_naive_to_aware_iso(
                lease.lease_expires_at if lease else None
            ),
            "lease_seconds": lease_seconds,
            "heartbeat_seconds": heartbeat_seconds,
        }
    )


class AIImageManualResolutionRequest(BaseModel):
    outcome: Literal["succeeded", "failed", "cancelled"]
    reason: str = Field(min_length=3, max_length=500)


@router.get("/xhs-homepage-shadow")
async def get_xhs_homepage_shadow_parity(
    finished_from: datetime | None = Query(default=None),
    finished_to: datetime | None = Query(default=None),
    sample_limit: int = Query(default=100, ge=1, le=500),
    min_samples: int = Query(default=20, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """Review legacy/shadow parity without changing task execution ownership."""

    try:
        report = await HomepageSyncParityService(db).build_report(
            finished_from=finished_from,
            finished_to=finished_to,
            sample_limit=sample_limit,
            min_samples=min_samples,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return ApiResponse(data=report)


@router.get("/xhs-account-data-shadow")
async def get_xhs_account_data_shadow_parity(
    sync_kind: Literal["engagement", "details"] = Query(...),
    finished_from: datetime | None = Query(default=None),
    finished_to: datetime | None = Query(default=None),
    sample_limit: int = Query(default=100, ge=1, le=500),
    min_samples: int = Query(default=20, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """Review engagement/detail sync parity without changing execution ownership."""

    try:
        report = await HomepageSyncParityService(
            db,
            sync_kind=sync_kind,
        ).build_report(
            finished_from=finished_from,
            finished_to=finished_to,
            sample_limit=sample_limit,
            min_samples=min_samples,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return ApiResponse(data=report)


@router.get("/xhs-report-refresh-shadow")
async def get_xhs_report_refresh_shadow_parity(
    finished_from: datetime | None = Query(default=None),
    finished_to: datetime | None = Query(default=None),
    sample_limit: int = Query(default=100, ge=1, le=500),
    min_samples: int = Query(default=20, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """Compare persistent legacy refresh runs with their shadow jobs."""

    try:
        report = await ReportRefreshParityService(db).build_report(
            finished_from=finished_from,
            finished_to=finished_to,
            sample_limit=sample_limit,
            min_samples=min_samples,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return ApiResponse(data=report)


@router.get("/dify-task-shadow")
async def get_dify_task_shadow_parity(
    finished_from: datetime | None = Query(default=None),
    finished_to: datetime | None = Query(default=None),
    sample_limit: int = Query(default=100, ge=1, le=500),
    min_samples: int = Query(default=20, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """Compare terminal Dify tasks with their durable shadow jobs."""

    try:
        report = await DifyTaskParityService(db).build_report(
            finished_from=finished_from,
            finished_to=finished_to,
            sample_limit=sample_limit,
            min_samples=min_samples,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return ApiResponse(data=report)


@router.get("/ai-image-shadow")
async def list_ai_image_shadow_reconciliation(
    status: str = Query(default="waiting_review"),
    limit: int = Query(default=100, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """List AI image shadow jobs without exposing prompts or Provider keys."""

    try:
        data = await AIImageReconciliationService(db).list_jobs(
            status=status,
            limit=limit,
        )
    except AIImageReconciliationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return ApiResponse(data=data)


@router.post("/ai-image-shadow/{job_id}/reconcile")
async def reconcile_ai_image_shadow_job(
    job_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """Query accepted upstream task IDs; this never submits generation work."""

    try:
        data = await AIImageReconciliationService(db).reconcile_job(
            job_id,
            actor_type="admin",
            actor_id=str(current_user.id),
        )
        await db.commit()
    except AIImageReconciliationNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except AIImageReconciliationConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except AIImageReconciliationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return ApiResponse(data=data)


@router.post("/ai-image-shadow/{job_id}/resolve")
async def resolve_ai_image_shadow_job(
    job_id: int,
    request: AIImageManualResolutionRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """Close a review manually with an explicit administrator reason."""

    try:
        data = await AIImageReconciliationService(db).manual_resolve(
            job_id,
            outcome=request.outcome,
            reason=request.reason,
            actor_id=str(current_user.id),
        )
        await db.commit()
    except AIImageReconciliationNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except AIImageReconciliationConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except AIImageReconciliationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return ApiResponse(data=data)


@router.get("/jobs")
async def list_durable_jobs(
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=20, ge=1, le=100),
    status: str | None = Query(default=None),
    job_type: str | None = Query(default=None),
    worker_type: str | None = Query(default=None),
    username: str | None = Query(default=None),
    search: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """List durable jobs for the unified admin task center."""

    try:
        data = await JobQueryService(db).list_jobs(
            page=page,
            limit=limit,
            status=status,
            job_type=job_type,
            worker_type=worker_type,
            username=username,
            search=search,
        )
    except JobQueryError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return ApiResponse(data=data)


@router.get("/jobs/{job_id}")
async def get_durable_job(
    job_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """Return sanitized job evidence, attempts, items, and event timeline."""

    try:
        data = await JobQueryService(db).get_job(job_id)
    except JobQueryNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return ApiResponse(data=data)
