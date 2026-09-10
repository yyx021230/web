from __future__ import annotations

from datetime import date, timedelta
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import require_admin
from app.db.session import get_db
from app.models.hermes_workflow import HermesWorkerState, HermesWorkflowRun
from app.models.user import User
from app.models.user_xhs_env import UserXHSEnvironment
from app.models.xhs_environment import XHSEnvironment
from app.schemas.common import ApiResponse
from app.schemas.hermes_workflow import (
    HermesAdminRunCreate,
    HermesReviewRequest,
    HermesScheduleUpdate,
    HermesPublishPlanRequest,
)
from app.services.hermes_workflow_service import (
    HermesWorkflowService,
    serialize_run,
    serialize_schedule,
    serialize_post,
)
from app.utils.timezone import cst_now_naive
from app.services.hermes_policy_service import policy_summaries


router = APIRouter()


@router.get("/bootstrap")
async def bootstrap(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """Return schedule, account inventory, queue counters and worker state."""
    service = HermesWorkflowService(db)
    schedule = await service.get_or_create_schedule(created_by=current_user.id)
    await db.commit()
    environment_rows = list((await db.execute(
        select(XHSEnvironment, User.id, User.display_name, User.username)
        .outerjoin(UserXHSEnvironment, UserXHSEnvironment.environment_id == XHSEnvironment.id)
        .outerjoin(User, User.id == UserXHSEnvironment.user_id)
        .where(XHSEnvironment.status == "active", XHSEnvironment.department == "xhs")
        .order_by(XHSEnvironment.account_name.asc())
    )).all())
    cutoff = cst_now_naive() - timedelta(seconds=90)
    workers = list((await db.execute(
        select(HermesWorkerState).order_by(HermesWorkerState.last_seen_at.desc())
    )).scalars().all())
    status_rows = await db.execute(
        select(HermesWorkflowRun.status, func.count(HermesWorkflowRun.id)).group_by(HermesWorkflowRun.status)
    )
    return ApiResponse(data={
        "schedule": serialize_schedule(schedule),
        "policies": policy_summaries(),
        "accounts": [
            {
                "id": environment.id,
                "name": environment.account_name,
                "group": environment.group_name,
                "labels": environment.labels,
                "owner_user_id": owner_user_id,
                "owner_name": owner_display_name or owner_username,
            }
            for environment, owner_user_id, owner_display_name, owner_username in environment_rows
        ],
        "status_counts": {str(status): int(count) for status, count in status_rows.all()},
        "workers": [{
            "worker_id": row.worker_id,
            "status": row.status,
            "current_run_id": row.current_run_id,
            "online": row.last_seen_at >= cutoff,
            "last_seen_at": row.last_seen_at.isoformat(),
            "capabilities": row.capabilities or {},
        } for row in workers],
    })


@router.put("/schedule")
async def update_schedule(
    request: HermesScheduleUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """Replace the single official 8-account/40-post daily schedule."""
    service = HermesWorkflowService(db)
    schedule = await service.get_or_create_schedule(created_by=current_user.id)
    accounts = await service.validate_accounts([item.model_dump() for item in request.accounts]) if request.accounts else []
    schedule = await service.update_schedule(
        schedule=schedule,
        enabled=request.enabled,
        run_time=request.run_time,
        posts_per_account=request.posts_per_account,
        accounts=accounts,
        instruction=request.instruction,
    )
    return ApiResponse(data=serialize_schedule(schedule), message="定时生产配置已保存")


@router.post("/schedule/run-now")
async def run_schedule_now(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """Queue the configured 8×5 schedule immediately without waiting for its clock."""
    service = HermesWorkflowService(db)
    schedule = await service.get_or_create_schedule(created_by=current_user.id)
    accounts = await service.validate_accounts(list(schedule.accounts or []))
    if len(accounts) != 8 or int(schedule.posts_per_account or 0) != 5:
        raise HTTPException(status_code=409, detail="请先保存完整的8账号×5篇配置")
    if any(not account.get("owner_user_id") for account in accounts):
        raise HTTPException(status_code=409, detail="8个账号都需要先分配负责人")
    run = await service.create_run(
        source="admin_manual",
        requested_by=current_user.id,
        accounts=accounts,
        posts_per_account=int(schedule.posts_per_account or 5),
        instruction=schedule.instruction,
    )
    return ApiResponse(data=serialize_run(run, include_posts=True), message="40篇任务已进入 Hermes 队列")


@router.post("/runs")
async def create_run(
    request: HermesAdminRunCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """Queue an administrator-created custom Hermes production run."""
    service = HermesWorkflowService(db)
    accounts = await service.validate_accounts([item.model_dump() for item in request.accounts])
    run = await service.create_run(
        source="admin_manual",
        requested_by=current_user.id,
        accounts=accounts,
        posts_per_account=request.posts_per_account,
        instruction=request.instruction,
    )
    return ApiResponse(data=serialize_run(run, include_posts=True), message="任务已下发")


@router.get("/runs")
async def list_runs(
    status: str | None = Query(default=None),
    search: str | None = Query(default=None, max_length=100),
    source: str | None = Query(default=None, max_length=30),
    workflow_mode: Literal['batch', 'single'] | None = Query(default=None),
    environment_id: int | None = Query(default=None, gt=0),
    date_from: date | None = Query(default=None),
    date_to: date | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=30, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """List all Hermes production runs for administrator oversight."""
    rows, total = await HermesWorkflowService(db).list_runs(
        user_id=None,
        status=status,
        page=page,
        limit=limit,
        search=search, source=source, workflow_mode=workflow_mode, environment_id=environment_id, date_from=date_from, date_to=date_to,
    )
    return ApiResponse(data={
        "items": [serialize_run(row) for row in rows],
        "total": total,
        "page": page,
        "limit": limit,
    })


@router.get("/runs/{run_id}")
async def get_run(
    run_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """Return a complete 40-post run including provenance and review state."""
    run = await HermesWorkflowService(db).get_run(run_id)
    return ApiResponse(data=serialize_run(run, include_posts=True))


@router.post("/posts/{post_id}/review")
async def review_post(
    post_id: int,
    request: HermesReviewRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """Allow an administrator to approve or reject any generated post."""
    run = await HermesWorkflowService(db).review_post(
        post_id=post_id,
        reviewer=current_user,
        action=request.action,
        comment=request.comment,
        is_admin=True,
        expected_version=request.expected_version,
        regenerate=request.regenerate,
    )
    payload = serialize_run(run, include_posts=True)
    if request.regenerate:
        post = next(p for p in run.posts if p.id == post_id)
        payload['regenerated_run_id'] = post.source_detail['latest_regeneration']['run_id']
    return ApiResponse(data=payload, message="审核结果已保存；重生任务已入队" if request.regenerate else "审核结果已保存")


@router.get('/publish-candidates')
async def publish_candidates(
    page: int = Query(1, ge=1), limit: int = Query(40, ge=1, le=100),
    search: str | None = Query(None, max_length=100), environment_id: int | None = None,
    planned: bool | None = None,
    db: AsyncSession = Depends(get_db), current_user: User = Depends(require_admin),
):
    rows, total = await HermesWorkflowService(db).publish_candidates(None, page=page, limit=limit, search=search, environment_id=environment_id, planned=planned)
    return ApiResponse(data={'items': [serialize_post(p) for p in rows], 'total': total})


@router.post('/publish-plan')
async def save_publish_plan(request: HermesPublishPlanRequest, db: AsyncSession = Depends(get_db), current_user: User = Depends(require_admin)):
    rows = await HermesWorkflowService(db).save_publish_plan(user=current_user, items=[p.model_dump() for p in request.items], is_admin=True)
    return ApiResponse(data={'items': [serialize_post(p) for p in rows]}, message='排期已保存，未执行发布')


@router.post("/runs/{run_id}/publish")
async def prepare_publish(
    run_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """Build the future one-click-publish manifest without calling an external publisher."""
    run, manifest = await HermesWorkflowService(db).prepare_publish(run_id)
    return ApiResponse(
        data={"run": serialize_run(run, include_posts=True), "publish_manifest": manifest},
        message="发布清单已生成，外部发布接口待接入",
    )
