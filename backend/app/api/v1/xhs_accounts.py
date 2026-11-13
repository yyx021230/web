"""Independent account directory and explicit master-sheet review endpoints."""

from datetime import date

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import IntegrityError, OperationalError

from app.core.deps import get_current_user, require_admin
from app.db.session import get_db
from app.models.user import User
from app.models.xhs_account import XHSAccount, XHSAccountHistoryLink
from app.schemas.common import ApiResponse
from app.schemas.xhs_account_master import (
    ApplyMasterRequest,
    HistoryReviewRequest,
    CloudImportRequest,
    ProfileLocatorRequest,
    MasterSyncRequest,
    MasterHomepageWorkerRequest,
    MasterDetailWorkerRequest,
)
from app.services.xhs_account_master_service import (
    MasterError,
    XHSAccountMasterService,
)
from app.api.v1.xhs import require_xhs_worker_token

router = APIRouter(prefix="/xhs/accounts", tags=["小红书账号主数据"])
admin_router = APIRouter(prefix="/xhs/account-master", tags=["管理-账号主名单"])


async def run_master_job(job_id: str, run_id: int):
    from app.api.v1.xhs import (
        XHS_BACKGROUND_JOBS,
        XHS_BACKGROUND_JOB_TASKS,
        _update_job_progress,
        _now_iso,
    )
    from app.db import session as db_session
    from app.services.xhs_master_sync import XHSMasterSync

    job = XHS_BACKGROUND_JOBS[job_id]
    job.update(status="running", started_at=_now_iso())

    async def progress(patch):
        _update_job_progress(job, **patch)

    try:
        async with db_session.async_session() as session:
            sync = XHSMasterSync(session)
            try:
                result = await sync.execute(
                    run_id,
                    cancel_check=lambda: bool(job.get("cancel_requested")),
                    progress_callback=progress,
                )
            except Exception:
                await session.rollback()
                result = await sync.finalize(
                    run_id, cancelled=bool(job.get("cancel_requested"))
                )
        job.update(
            status="failed"
            if result["status"] == "partial_failed"
            else result["status"],
            message=result["message"],
            result=result,
            finished_at=_now_iso(),
        )
    finally:
        XHS_BACKGROUND_JOB_TASKS.pop(job_id, None)


async def start_master_job(db, body: MasterSyncRequest, user_id, *, parent_run_id=None):
    import asyncio
    from app.api.v1.xhs import _new_job, XHS_BACKGROUND_JOB_TASKS
    from app.services.xhs_master_sync import XHSMasterSync

    try:
        run = await XHSMasterSync(db).prepare(
            body,
            user_id=user_id,
            source="retry_failed" if parent_run_id else "manual",
            parent_run_id=parent_run_id,
        )
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None
    job = _new_job(
        {
            "posts": "account_notes_sync",
            "engagement": "account_note_engagement_sync",
            "details": "account_note_details_sync",
        }[body.kind],
        environment_id=None,
    )
    # The durable job ID must be the same one returned to polling clients.
    run.job_id = job["job_id"]
    await db.commit()
    job.update(
        history_run_id=run.id,
        identity_source="feishu",
        master_account_ids=run.request_config["account_ids"],
    )
    XHS_BACKGROUND_JOB_TASKS[job["job_id"]] = asyncio.create_task(
        run_master_job(job["job_id"], run.id)
    )
    return job


@router.post("/sync")
async def sync_master_accounts(
    body: MasterSyncRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_admin),
):
    """Submit canonical-account work, keeping runner IDs in their own namespace."""
    return ApiResponse(data=await start_master_job(db, body, user.id))


@router.post("/internal/homepage", dependencies=[Depends(require_xhs_worker_token)])
async def master_homepage_worker(
    body: MasterHomepageWorkerRequest, db: AsyncSession = Depends(get_db)
):
    """Worker contract: native account plus revision, separately validated browser runner."""
    from app.services.xhs_master_data import master_enabled
    from app.services.xhs_master_sync import XHSMasterSync

    if not master_enabled():
        raise HTTPException(409, "飞书主名单模式未启用")
    try:
        data = await XHSMasterSync(db).homepage_local(
            body.account_id,
            body.expected_revision,
            body.runner_id,
            body.limit,
            body.homepage_sync_mode,
        )
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None
    return ApiResponse(data=data)


@router.get("/mode")
async def account_mode(
    db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)
):
    """Expose identity namespace and browser execution resources separately, with no fallback."""
    from app.core.roles import has_role, ROLE_ADMIN
    from app.services.xhs_master_data import master_enabled, master_ready
    from app.services.xhs_service import XHSService

    enabled = master_enabled()
    accounts = await XHSAccountMasterService(db).accounts(user) if enabled else []
    runners = (
        await XHSService(db).list_sync_runner_environments()
        if enabled and has_role(user, ROLE_ADMIN)
        else []
    )
    return ApiResponse(
        data={
            "mode": "feishu" if enabled else "legacy",
            "ready": await master_ready(db) if enabled else True,
            "accounts": [a for a in accounts if a["status"] != "archived"],
            "runners": [
                {"id": r.id, "account_name": r.account_name, "is_sync_runner": True}
                for r in runners
            ],
        }
    )


@router.post("/internal/details", dependencies=[Depends(require_xhs_worker_token)])
async def master_detail_worker(
    body: MasterDetailWorkerRequest, db: AsyncSession = Depends(get_db)
):
    """Enrich exact native note IDs; reject old or cross-account worker requests."""
    from app.services.xhs_master_data import master_enabled
    from app.services.xhs_master_sync import XHSMasterSync

    if not master_enabled():
        raise HTTPException(409, "飞书主名单模式未启用")
    try:
        return ApiResponse(data=await XHSMasterSync(db).details_local(body))
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None


@admin_router.patch("/accounts/{account_id}/profile")
async def update_profile(
    account_id: int,
    body: ProfileLocatorRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_admin),
):
    """Set an independent profile locator; never update identity, ownership or browser bindings."""
    try:
        data = await XHSAccountMasterService(db).update_profile(
            account_id, body.profile_url, body.expected_revision
        )
    except MasterError as exc:
        await db.rollback()
        raise HTTPException(
            422 if str(exc) == "master_profile_invalid" else 409, str(exc)
        ) from None
    return ApiResponse(data=data)


@router.get("")
async def list_accounts(
    db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)
):
    """List accounts by current master ownership and department, never by browser presence."""
    return ApiResponse(data=await XHSAccountMasterService(db).accounts(user))


@router.get("/notes")
async def list_notes(
    account_id: int | None = Query(default=None, gt=0),
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Read only explicitly attributed notes; unresolved legacy data is retained separately."""
    notes, count = await XHSAccountMasterService(db).notes(
        user, account_id=account_id, skip=skip, limit=limit
    )
    return ApiResponse(
        data={
            "total": count,
            "items": [
                {
                    "id": n.id,
                    "account_id": n.account_id,
                    "legacy_environment_id": n.environment_id,
                    "title": n.title,
                    "published_at": n.published_at,
                    "feed_id": n.feed_id,
                    "view_count": n.view_count,
                    "liked_count": n.liked_count,
                    "comment_count": n.comment_count,
                    "collected_count": n.collected_count,
                    "content": n.content,
                    "cover_image_url": n.cover_image_url,
                }
                for n in notes
            ],
        }
    )


@router.get("/insights")
async def account_insights(
    start_date: date | None = None,
    end_date: date | None = None,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Compute note statistics with canonical account identity and current owner permissions."""
    if (
        start_date
        and end_date
        and (end_date < start_date or (end_date - start_date).days > 366)
    ):
        raise HTTPException(422, "invalid_account_date_range")
    return ApiResponse(
        data=await XHSAccountMasterService(db).insights(user, start_date, end_date)
    )


@admin_router.post("/previews")
async def preview_master(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_admin),
):
    """Preview an exported master CSV without applying account, owner or history changes."""
    content = await file.read(2_000_001)
    try:
        return ApiResponse(
            data=await XHSAccountMasterService(db).preview(content, user)
        )
    except MasterError as exc:
        await db.rollback()
        raise HTTPException(422, str(exc)) from None


@admin_router.post("/previews/{preview_id}/apply")
async def apply_master(
    preview_id: str,
    body: ApplyMasterRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_admin),
):
    """Apply explicitly selected preview rows; stale previews and changed replay scopes fail closed."""
    try:
        return ApiResponse(
            data=await XHSAccountMasterService(db).apply(
                preview_id,
                body.source_hash,
                body.rows,
                user,
                include_history=body.include_history,
                replace_all=body.replace_all,
            )
        )
    except MasterError as exc:
        await db.rollback()
        raise HTTPException(409, str(exc)) from None
    except (IntegrityError, OperationalError):
        await db.rollback()
        raise HTTPException(409, "master_concurrent_change_preview_again") from None


@admin_router.get("/history-candidates")
async def history_candidates(
    account_id: int = Query(gt=0),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_admin),
):
    """Show unverified historical associations without granting access to old account data."""
    rows = (
        await db.scalars(
            select(XHSAccountHistoryLink).where(
                XHSAccountHistoryLink.account_id == account_id
            )
        )
    ).all()
    return ApiResponse(
        data=[
            {
                "id": r.id,
                "account_id": r.account_id,
                "environment_id": r.environment_id,
                "xhs_id_snapshot": r.xhs_id_snapshot,
                "status": r.status,
            }
            for r in rows
        ]
    )


@admin_router.post("/cloud-data/import")
async def import_cloud_results(
    body: CloudImportRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_admin),
):
    """Import already-collected, verified mobile observations without starting any device tasks."""
    from app.adapters.phone_cloud_xhs_data import CloudDataError
    from app.services.xhs_cloud_data_service import XHSCloudDataService

    ids = set(body.account_ids)
    accounts = list(
        (
            await db.scalars(
                select(XHSAccount)
                .where(
                    XHSAccount.id.in_(ids),
                    XHSAccount.status == "active",
                    XHSAccount.department.in_(("xhs", "brand")),
                )
                .order_by(XHSAccount.id)
            )
        ).all()
    )
    if len(ids) != len(body.account_ids) or len(accounts) != len(ids):
        raise HTTPException(422, "master_select_active_accounts_only")
    try:
        return ApiResponse(data=await XHSCloudDataService(db).sync(accounts))
    except CloudDataError as exc:
        await db.rollback()
        raise HTTPException(409, str(exc)) from None


@admin_router.post("/history-review")
async def review_history(
    body: HistoryReviewRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_admin),
):
    """Attribute only manually reviewed note IDs, keeping the original environment and note contents."""
    try:
        return ApiResponse(
            data=await XHSAccountMasterService(db).confirm_history(
                body.account_id,
                body.environment_id,
                body.note_ids,
                body.expected_revision,
                user,
            )
        )
    except MasterError as exc:
        await db.rollback()
        raise HTTPException(409, str(exc)) from None
    except (IntegrityError, OperationalError):
        await db.rollback()
        raise HTTPException(409, "master_history_conflict_review_again") from None
