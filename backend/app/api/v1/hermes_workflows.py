from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.deps import get_current_user
from app.core.roles import has_role
from app.db.session import get_db
from app.models.hermes_workflow import HermesWorkerState
from app.models.user import User
from app.schemas.common import ApiResponse
from app.schemas.hermes_workflow import (
    HermesBatchRunCreate,
    HermesPublishPlanRequest,
    HermesReviewRequest,
    HermesRunCreate,
    HermesWorkerClaim,
    HermesWorkerComplete,
    HermesWorkerFail,
    HermesPostEdit,
)
from app.services.hermes_workflow_service import HermesWorkflowService, aggregate_status, post_counts, serialize_post, serialize_run
from app.services.hermes_policy_service import policy_summaries
from app.services.vehicle_catalog_service import VehicleCatalogService
from app.services.hermes_reference_service import reference_catalog
from app.utils.timezone import cst_now_naive


router = APIRouter()


@router.get('/reference-types')
async def get_reference_types(db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)):
    return ApiResponse(data=await reference_catalog(db, current_user))


def _require_worker_token(x_xhs_worker_token: str | None = Header(default=None)) -> None:
    expected = str(getattr(settings, "xhs_worker_internal_token", "") or "").strip()
    if not expected:
        raise HTTPException(status_code=503, detail="Hermes Worker 内部令牌未配置")
    if x_xhs_worker_token != expected:
        raise HTTPException(status_code=403, detail="Hermes Worker 内部令牌无效")


def _user_run_payload(run: Any, user_id: int) -> dict[str, Any]:
    payload = serialize_run(run)
    posts = [post for post in run.posts if post.owner_user_id == user_id or run.requested_by == user_id]
    visible_environments = {post.environment_id for post in posts}
    payload['parameters']['accounts'] = [a for a in payload['parameters'].get('accounts', []) if a.get('environment_id') in visible_environments]
    counts = post_counts(posts)
    assigned_status = aggregate_status(posts, run.status)
    payload.update({
        "assigned_status": assigned_status,
        "assigned_posts": len(posts),
        "assigned_generated": counts['generated'],
        "assigned_failed": counts['failed'],
        "assigned_pending_review": counts['pending_review'],
        "assigned_approved": sum(post.status in {"approved", "publish_ready", "published"} for post in posts),
        "assigned_rejected": sum(post.status == "rejected" for post in posts),
        "accounts": sorted({post.account_name for post in posts}),
        "vehicles": sorted({post.vehicle_model for post in posts}),
    })
    return payload


@router.get("/bootstrap")
async def bootstrap(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return the current user's assigned accounts and available Leapmotor models."""
    service = HermesWorkflowService(db)
    environments = await service.assigned_environments(current_user.id)
    vehicle_rows = await VehicleCatalogService(db).rows()
    policies = policy_summaries()
    leapmotor_models = sorted({
        str(row["model"])
        for row in vehicle_rows
        if "零跑" in str(row.get("brand") or "") or "零跑" in str(row.get("model") or "")
    } | {str(row["vehicle_model"]) for row in policies})
    if not leapmotor_models:
        leapmotor_models = ["零跑A05", "零跑A10", "零跑B01", "零跑B10", "零跑C10", "零跑C11", "零跑C16"]
    return ApiResponse(data={
        "accounts": [
            {"id": row.id, "name": row.account_name, "group": row.group_name, "labels": row.labels}
            for row in environments
        ],
        "vehicle_models": leapmotor_models,
        "policies": policies,
        "limits": {"max_posts_per_run": 5},
    })


@router.post("/runs")
async def create_run(
    request: HermesRunCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Queue one manual Hermes production run for an account owned by the user."""
    service = HermesWorkflowService(db)
    accounts = await service.validate_accounts([
        {
            "environment_id": request.account_id,
            "vehicle_model": request.vehicle_model,
            "case_id": request.case_id,
        }
    ], owner_user_id=current_user.id)
    precision = [
        value for value in (
            f"指定文案类型：{request.copy_type}" if request.copy_type else "",
            f"指定图片类型：{request.image_type}" if request.image_type else "",
            (request.instruction or "").strip(),
        ) if value
    ]
    run = await service.create_run(
        source="manual",
        requested_by=current_user.id,
        accounts=accounts,
        posts_per_account=request.post_count,
        instruction="\n".join(precision),
        name=request.name,
        copy_type=request.copy_type,
        image_type=request.image_type,
    )
    return ApiResponse(data=_user_run_payload(run, current_user.id), message="任务已进入 Hermes 队列")


@router.post("/runs/batch")
async def create_batch_run(
    request: HermesBatchRunCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Queue one mixed-vehicle batch with a per-account post count."""
    service = HermesWorkflowService(db)
    first_model = request.vehicle_models[0]
    normalized = await service.validate_accounts([
        {"environment_id": item.environment_id, "vehicle_model": first_model}
        for item in request.accounts
    ], owner_user_id=current_user.id)
    cursor = 0
    for account, requested in zip(normalized, request.accounts):
        count = requested.post_count
        account["post_count"] = count
        account["vehicle_models"] = [
            request.vehicle_models[(cursor + index) % len(request.vehicle_models)]
            for index in range(count)
        ]
        cursor += count
    run = await service.create_run(
        source="manual_batch",
        requested_by=current_user.id,
        accounts=normalized,
        posts_per_account=1,
        instruction=request.instruction,
        name=request.name,
    )
    return ApiResponse(data=_user_run_payload(run, current_user.id), message="批量任务已进入 Hermes 队列")


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
    limit: int = Query(default=30, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List manual and scheduled runs visible to the current account owner."""
    rows, total = await HermesWorkflowService(db).list_runs(
        user_id=current_user.id,
        status=status,
        page=page,
        limit=limit,
        search=search, source=source, workflow_mode=workflow_mode, environment_id=environment_id, date_from=date_from, date_to=date_to,
    )
    return ApiResponse(data={
        "items": [_user_run_payload(row, current_user.id) for row in rows],
        "total": total,
        "page": page,
        "limit": limit,
    })


@router.get("/runs/{run_id}")
async def get_run(
    run_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return the posts from a run that belong to the current user."""
    run = await HermesWorkflowService(db).user_run(run_id, current_user.id)
    payload = _user_run_payload(run, current_user.id)
    payload["posts"] = [
        serialize_post(post)
        for post in sorted(run.posts, key=lambda row: (row.environment_id, row.slot))
        if post.owner_user_id == current_user.id or run.requested_by == current_user.id
    ]
    return ApiResponse(data=payload)


@router.post("/posts/{post_id}/review")
async def review_post(
    post_id: int,
    request: HermesReviewRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Approve or reject one generated post assigned to the current user."""
    run = await HermesWorkflowService(db).review_post(
        post_id=post_id,
        reviewer=current_user,
        action=request.action,
        comment=request.comment,
        is_admin=has_role(current_user, "admin"),
        expected_version=request.expected_version,
        regenerate=request.regenerate,
    )
    payload = _user_run_payload(run, current_user.id)
    if request.regenerate:
        post = next(p for p in run.posts if p.id == post_id)
        payload['regenerated_run_id'] = post.source_detail['latest_regeneration']['run_id']
    return ApiResponse(data=payload, message="审核结果已保存；重生任务已入队" if request.regenerate else "审核结果已保存")


@router.patch('/posts/{post_id}')
async def edit_post(post_id: int, request: HermesPostEdit, db: AsyncSession = Depends(get_db),
                    current_user: User = Depends(get_current_user)):
    post = await HermesWorkflowService(db).edit_post(
        post_id, current_user, **request.model_dump(), is_admin=has_role(current_user, 'admin'),
    )
    return ApiResponse(data=serialize_post(post), message='新版本已保存，需重新审核；原文与图片不变')


@router.post('/runs/{run_id}/cancel')
async def cancel_run(run_id: int, db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)):
    run = await HermesWorkflowService(db).cancel_queued(run_id, current_user, is_admin=has_role(current_user, 'admin'))
    return ApiResponse(data=_user_run_payload(run, current_user.id), message='已取消尚未开始的任务')


@router.get("/publish-candidates")
async def publish_candidates(
    page: int = Query(1, ge=1), limit: int = Query(40, ge=1, le=100),
    search: str | None = Query(None, max_length=100), environment_id: int | None = None,
    planned: bool | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    rows, total = await HermesWorkflowService(db).publish_candidates(current_user.id, page=page, limit=limit, search=search, environment_id=environment_id, planned=planned)
    return ApiResponse(data={"items": [serialize_post(post) for post in rows], "total": total})


@router.post("/publish-plan")
async def save_publish_plan(
    request: HermesPublishPlanRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    rows = await HermesWorkflowService(db).save_publish_plan(
        user=current_user,
        items=[item.model_dump() for item in request.items],
    )
    return ApiResponse(
        data={"items": [serialize_post(post) for post in rows]},
        message="发布计划已保存；发布接口尚未接入，不会实际发布",
    )


@router.post("/worker/heartbeat", dependencies=[Depends(_require_worker_token)])
async def worker_heartbeat(
    request: HermesWorkerClaim,
    db: AsyncSession = Depends(get_db),
):
    """Update external Hermes worker liveness without claiming a run."""
    worker = await HermesWorkflowService(db).heartbeat_worker(
        worker_id=request.worker_id,
        status=request.status,
        current_run_id=request.current_run_id,
        capabilities=request.capabilities,
    )
    return ApiResponse(data={"worker_id": worker.worker_id, "last_seen_at": worker.last_seen_at.isoformat()})


@router.post("/worker/claim", dependencies=[Depends(_require_worker_token)])
async def worker_claim(
    request: HermesWorkerClaim,
    db: AsyncSession = Depends(get_db),
):
    """Claim the oldest queued Hermes run for one external worker."""
    service = HermesWorkflowService(db)
    run = await service.claim_next(request.worker_id)
    await service.heartbeat_worker(
        worker_id=request.worker_id,
        status="running" if run else "idle",
        current_run_id=run.id if run else None,
        capabilities=request.capabilities,
    )
    return ApiResponse(data=serialize_run(run, include_posts=True) if run else None)


@router.post("/worker/runs/{run_id}/progress", dependencies=[Depends(_require_worker_token)])
async def worker_progress(
    run_id: int,
    request: HermesWorkerComplete,
    db: AsyncSession = Depends(get_db),
):
    """Expose each complete, checked post without terminating its sibling jobs."""
    run = await HermesWorkflowService(db).progress_run(run_id, request.delivery, worker_id=request.worker_id)
    return ApiResponse(data=serialize_run(run, include_posts=True))


@router.post("/worker/runs/{run_id}/complete", dependencies=[Depends(_require_worker_token)])
async def worker_complete(
    run_id: int,
    request: HermesWorkerComplete,
    db: AsyncSession = Depends(get_db),
):
    """Ingest the auditable delivery manifest produced by the Hermes worker."""
    run = await HermesWorkflowService(db).complete_run(run_id, request.delivery, worker_id=request.worker_id)
    if run.worker_id:
        await HermesWorkflowService(db).heartbeat_worker(
            worker_id=run.worker_id,
            status="idle",
            current_run_id=None,
        )
    return ApiResponse(data=serialize_run(run, include_posts=True))


@router.post("/worker/runs/{run_id}/fail", dependencies=[Depends(_require_worker_token)])
async def worker_fail(
    run_id: int,
    request: HermesWorkerFail,
    db: AsyncSession = Depends(get_db),
):
    """Persist a terminal Hermes worker failure for operator review."""
    run = await HermesWorkflowService(db).fail_run(run_id, request.error, worker_id=request.worker_id)
    if run.worker_id:
        await HermesWorkflowService(db).heartbeat_worker(
            worker_id=run.worker_id,
            status="idle",
            current_run_id=None,
        )
    return ApiResponse(data=serialize_run(run, include_posts=True))


@router.get("/worker/status", dependencies=[Depends(_require_worker_token)])
async def worker_status(db: AsyncSession = Depends(get_db)):
    """Return worker heartbeat records for command-line diagnostics."""
    cutoff = cst_now_naive() - timedelta(seconds=90)
    workers = list((await db.execute(select(HermesWorkerState).order_by(HermesWorkerState.last_seen_at.desc()))).scalars().all())
    return ApiResponse(data=[{
        "worker_id": row.worker_id,
        "status": row.status,
        "current_run_id": row.current_run_id,
        "online": row.last_seen_at >= cutoff,
        "last_seen_at": row.last_seen_at.isoformat(),
        "capabilities": row.capabilities or {},
    } for row in workers])
