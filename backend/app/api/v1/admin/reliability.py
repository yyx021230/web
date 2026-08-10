from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import require_admin
from app.db.session import get_db
from app.models.user import User
from app.schemas.common import ApiResponse
from app.services.xhs_homepage_sync_parity_service import HomepageSyncParityService


router = APIRouter()


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
