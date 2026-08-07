from __future__ import annotations

import json

from pydantic import BaseModel
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import delete, select, update
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.session import get_db
from app.core.deps import require_admin
from app.core.roles import (
    ROLE_BRAND_LEAD,
    ROLE_BRAND_OPS,
    ROLE_XHS_LEAD,
    ROLE_XHS_OPS,
    get_user_roles,
    has_role,
)
from app.models.xhs_ad_account_assignment import XHSAdAccountBuyerAssignment, XHSAdAccountProfessionalMapping
from app.models.xhs_account_note import XHSAccountNote
from app.models.xhs_report import XHSReportDaily, XHSReportToken
from app.models.user import User
from app.schemas.common import ApiResponse
from app.services.xhs_schedule_service import (
    ALL_SCHEDULE_TASK_KEYS,
    XHSScheduleService,
    trigger_xhs_scheduled_task,
)
from app.services.xhs_service import XHSService

router = APIRouter(prefix="/xhs", tags=["管理-小红书"])


class AssignRequest(BaseModel):
    user_id: int
    environment_id: int


class UpdateProfileUrlRequest(BaseModel):
    environment_id: int
    profile_url: str | None = None
    sync_cloud_session_id: str | None = None
    sync_cloud_api_key: str | None = None
    sync_cloud_update_config: str | None = None
    sync_browser_start_config: str | None = None
    login_phone_number: str | None = None
    department: str | None = None


class UpdateSyncRunnerRequest(BaseModel):
    environment_id: int
    is_sync_runner: bool


class AssignAdAccountRequest(BaseModel):
    account_id: str
    user_id: int


class UnassignAdAccountRequest(BaseModel):
    account_id: str


class UpsertAdAccountRequest(BaseModel):
    account_id: str
    account_name: str


class UpdateAdAccountRequest(BaseModel):
    account_id: str
    new_account_id: str | None = None
    account_name: str


class UpdateAdAccountProfessionalRequest(BaseModel):
    account_id: str
    xhs_account_id: str | None = None
    xhs_account_name: str | None = None
    xhs_owner_name: str | None = None


class UpdateScheduleSettingRequest(BaseModel):
    enabled: bool
    run_time: str
    config: dict | None = None


@router.post("/sync-all")
async def sync_all_posts(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """全量同步所有帖子数据（仅管理员）"""
    service = XHSService(db)
    count = await service.sync_all_posts()

    return ApiResponse(data={"synced_count": count}, message=f"同步完成: {count} 条")


@router.get("/schedule-settings")
async def list_schedule_settings(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    service = XHSScheduleService(db)
    return ApiResponse(data=await service.list_settings())


@router.get("/schedule-run-logs")
async def list_schedule_run_logs(
    task_key: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    if task_key and task_key not in ALL_SCHEDULE_TASK_KEYS:
        raise HTTPException(status_code=404, detail="定时任务不存在")
    service = XHSScheduleService(db)
    return ApiResponse(data=await service.list_run_logs(task_key=task_key, limit=limit))


@router.put("/schedule-settings/{task_key}")
async def update_schedule_setting(
    task_key: str,
    req: UpdateScheduleSettingRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    if task_key not in ALL_SCHEDULE_TASK_KEYS:
        raise HTTPException(status_code=404, detail="定时任务不存在")
    service = XHSScheduleService(db)
    try:
        data = await service.update_setting(
            task_key,
            enabled=req.enabled,
            run_time=req.run_time,
            config=req.config,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return ApiResponse(data=data, message="定时任务配置已保存")


@router.post("/schedule-settings/{task_key}/run")
async def run_schedule_setting(
    task_key: str,
    current_user: User = Depends(require_admin),
):
    if task_key not in ALL_SCHEDULE_TASK_KEYS:
        raise HTTPException(status_code=404, detail="定时任务不存在")
    try:
        launched = await trigger_xhs_scheduled_task(task_key, source="manual")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not launched:
        return ApiResponse(data={"task_key": task_key, "running": True}, message="任务已在执行中")
    return ApiResponse(data={"task_key": task_key, "running": True}, message="任务已开始执行")


@router.post("/sync-environments")
async def sync_environments(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """从云登 API 同步环境列表（仅管理员）"""
    service = XHSService(db)
    count = await service.sync_environments_from_yundeng()

    return ApiResponse(data={"synced_count": count}, message=f"环境同步完成: {count} 条")


@router.post("/assign")
async def assign_environment(
    req: AssignRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """设置小红书环境运营负责人（仅管理员）"""
    service = XHSService(db)

    user_result = await db.execute(select(User).where(User.id == req.user_id))
    target_user = user_result.scalar_one_or_none()
    if not target_user:
        raise HTTPException(status_code=404, detail="用户不存在")

    env = await service.get_environment(req.environment_id)
    if not env:
        raise HTTPException(status_code=404, detail="云登环境不存在")

    department = (env.department or "xhs").strip().lower()
    expected_roles = {ROLE_XHS_LEAD, ROLE_XHS_OPS} if department == "xhs" else {ROLE_BRAND_LEAD, ROLE_BRAND_OPS}
    if not set(get_user_roles(target_user)).intersection(expected_roles):
        department_name = "小红书" if department == "xhs" else "品牌"
        raise HTTPException(status_code=400, detail=f"只能将{department_name}部门账号分配给对应部门负责人或运营")

    success = await service.assign_environment(req.user_id, req.environment_id)

    return ApiResponse(data={"success": success}, message="负责人已设置")


@router.post("/profile-url")
async def update_environment_profile_url(
    req: UpdateProfileUrlRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """更新云登环境对应的小红书个人主页链接和同步浏览器配置（仅管理员）"""
    service = XHSService(db)
    env = await service.get_environment(req.environment_id)
    if not env:
        raise HTTPException(status_code=404, detail="云登环境不存在")

    normalized = (req.profile_url or "").strip()
    raw_sync_cloud_update_config = (req.sync_cloud_update_config or "").strip()
    raw_sync_browser_config = (req.sync_browser_start_config or "").strip()
    normalized_sync_cloud_update_config: str | None = None
    normalized_sync_browser_config: str | None = None
    if raw_sync_cloud_update_config:
        try:
            parsed = json.loads(raw_sync_cloud_update_config)
        except json.JSONDecodeError as exc:
            raise HTTPException(status_code=400, detail=f"开放平台指纹更新参数 JSON 无效: {exc.msg}") from exc
        if not isinstance(parsed, dict):
            raise HTTPException(status_code=400, detail="开放平台指纹更新参数必须是 JSON 对象")
        normalized_sync_cloud_update_config = json.dumps(parsed, ensure_ascii=False, indent=2, sort_keys=True)
    if raw_sync_browser_config:
        try:
            parsed = json.loads(raw_sync_browser_config)
        except json.JSONDecodeError as exc:
            raise HTTPException(status_code=400, detail=f"同步浏览器参数 JSON 无效: {exc.msg}") from exc
        if not isinstance(parsed, dict):
            raise HTTPException(status_code=400, detail="同步浏览器参数必须是 JSON 对象")
        normalized_sync_browser_config = json.dumps(parsed, ensure_ascii=False, indent=2, sort_keys=True)

    env.profile_url = normalized or None
    env.sync_cloud_session_id = (req.sync_cloud_session_id or "").strip() or None
    env.sync_cloud_api_key = (req.sync_cloud_api_key or "").strip() or None
    env.sync_cloud_update_config = normalized_sync_cloud_update_config
    env.sync_browser_start_config = normalized_sync_browser_config
    env.login_phone_number = (req.login_phone_number or "").strip() or None
    if req.department is not None:
        department = req.department.strip().lower()
        if department not in {"xhs", "brand"}:
            raise HTTPException(status_code=400, detail="账号部门仅支持 xhs 或 brand")
        env.department = department
    await db.commit()
    await db.refresh(env)
    return ApiResponse(
        data={
            "environment_id": env.id,
            "profile_url": env.profile_url,
            "sync_cloud_session_id": env.sync_cloud_session_id,
            "sync_cloud_api_key": env.sync_cloud_api_key,
            "sync_cloud_update_config": env.sync_cloud_update_config,
            "sync_browser_start_config": env.sync_browser_start_config,
            "login_phone_number": env.login_phone_number,
            "department": env.department,
        },
        message="保存成功",
    )


@router.post("/sync-runner")
async def update_environment_sync_runner(
    req: UpdateSyncRunnerRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    service = XHSService(db)
    env = await service.get_environment(req.environment_id)
    if not env:
        raise HTTPException(status_code=404, detail="云登环境不存在")

    env.is_sync_runner = bool(req.is_sync_runner)
    await db.commit()
    await db.refresh(env)

    return ApiResponse(
        data={
            "environment_id": env.id,
            "is_sync_runner": bool(env.is_sync_runner),
        },
        message="同步环境设置已更新",
    )


@router.post("/unassign")
async def unassign_environment(
    req: AssignRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """移除用户云登环境（仅管理员）"""
    service = XHSService(db)

    user_result = await db.execute(select(User).where(User.id == req.user_id))
    target_user = user_result.scalar_one_or_none()
    if not target_user:
        raise HTTPException(status_code=404, detail="用户不存在")

    env = await service.get_environment(req.environment_id)
    if not env:
        raise HTTPException(status_code=404, detail="云登环境不存在")

    await service.remove_environment(req.user_id, req.environment_id)

    return ApiResponse(message="已移除")


@router.get("/sync-runner-browse-overview")
async def get_sync_runner_browse_overview(
    days: int = Query(default=7, ge=1, le=30),
    limit: int = Query(default=80, ge=20, le=300),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    service = XHSService(db)
    data = await service.get_sync_runner_browse_overview(days=days, limit=limit)
    return ApiResponse(data=data)


@router.get("/browser-statuses")
async def list_browser_statuses(
    refresh: bool = Query(default=False),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """查看云登环境在线状态。refresh=true 会主动探测，默认返回最近缓存。"""
    service = XHSService(db)
    data = await service.list_browser_environment_statuses(refresh=refresh)
    return ApiResponse(data=data)


@router.post("/browser-status/{environment_id}/refresh")
async def refresh_browser_status(
    environment_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """刷新单个云登环境在线状态。"""
    service = XHSService(db)
    try:
        data = await service.refresh_browser_environment_status(environment_id)
    except RuntimeError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return ApiResponse(data=data)


@router.get("/assignments")
async def list_assignments(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """获取所有用户-环境分配关系（仅管理员）"""
    from app.models.user_xhs_env import UserXHSEnvironment
    result = await db.execute(
        select(UserXHSEnvironment.user_id, UserXHSEnvironment.environment_id)
        .order_by(UserXHSEnvironment.user_id, UserXHSEnvironment.environment_id)
    )

    return ApiResponse(data=[{"user_id": user_id, "environment_id": environment_id} for user_id, environment_id in result.all()])


@router.get("/ad-account-assignments")
async def list_ad_account_assignments(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """获取广告账户-投手分配关系（仅管理员）"""
    token_result = await db.execute(
        select(
            XHSReportToken.account_id,
            XHSReportToken.account_name,
            XHSReportToken.token_status,
        )
        .order_by(XHSReportToken.account_name.asc())
    )
    daily_result = await db.execute(
        select(
            XHSReportDaily.account_id,
            XHSReportDaily.account_name,
        )
        .group_by(XHSReportDaily.account_id, XHSReportDaily.account_name)
        .order_by(XHSReportDaily.account_name.asc())
    )
    assignment_result = await db.execute(
        select(
            XHSAdAccountBuyerAssignment.account_id,
            XHSAdAccountBuyerAssignment.user_id,
            User.username,
            User.display_name,
            User.email,
        )
        .join(User, User.id == XHSAdAccountBuyerAssignment.user_id)
    )
    assignments = {
        str(account_id): {
            "user_id": user_id,
            "buyer_username": username,
            "buyer_display_name": display_name or username,
            "buyer_email": email,
        }
        for account_id, user_id, username, display_name, email in assignment_result.all()
    }
    professional_result = await db.execute(
        select(
            XHSAdAccountProfessionalMapping.account_id,
            XHSAdAccountProfessionalMapping.xhs_account_id,
            XHSAdAccountProfessionalMapping.xhs_account_name,
            XHSAdAccountProfessionalMapping.xhs_owner_name,
        )
    )
    professional_mappings = {
        str(account_id): {
            "xhs_account_id": xhs_account_id,
            "xhs_account_name": xhs_account_name,
            "xhs_owner_name": xhs_owner_name,
        }
        for account_id, xhs_account_id, xhs_account_name, xhs_owner_name in professional_result.all()
    }
    accounts: dict[str, dict] = {}
    for account_id, account_name, token_status in token_result.all():
        accounts[str(account_id)] = {
            "account_id": str(account_id),
            "account_name": account_name or str(account_id),
            "token_status": token_status,
        }
    for account_id, account_name in daily_result.all():
        accounts.setdefault(str(account_id), {
            "account_id": str(account_id),
            "account_name": account_name or str(account_id),
            "token_status": None,
        })
    return ApiResponse(data=[
        {
            **item,
            **assignments.get(
                item["account_id"],
                {"user_id": None, "buyer_username": None, "buyer_display_name": None, "buyer_email": None},
            ),
            **professional_mappings.get(
                item["account_id"],
                {"xhs_account_id": None, "xhs_account_name": None, "xhs_owner_name": None},
            ),
        }
        for item in sorted(accounts.values(), key=lambda row: str(row["account_name"]))
    ])


@router.post("/ad-accounts")
async def create_ad_account(
    req: UpsertAdAccountRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """新增广告账户清单项。"""
    account_id = (req.account_id or "").strip()
    account_name = (req.account_name or "").strip()
    if not account_id:
        raise HTTPException(status_code=400, detail="缺少广告账户ID")
    if not account_name:
        raise HTTPException(status_code=400, detail="缺少广告账户名称")
    existing = (
        await db.execute(select(XHSReportToken).where(XHSReportToken.account_id == account_id))
    ).scalar_one_or_none()
    if existing:
        raise HTTPException(status_code=400, detail="广告账户ID已存在")
    db.add(XHSReportToken(account_id=account_id, account_name=account_name))
    await db.commit()
    return ApiResponse(data={"account_id": account_id, "account_name": account_name}, message="广告账户已新增")


@router.patch("/ad-accounts")
async def update_ad_account(
    req: UpdateAdAccountRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """编辑广告账户基础信息，并同步分配关系和历史报表行中的名称。"""
    account_id = (req.account_id or "").strip()
    new_account_id = (req.new_account_id or req.account_id or "").strip()
    account_name = (req.account_name or "").strip()
    if not account_id:
        raise HTTPException(status_code=400, detail="缺少原广告账户ID")
    if not new_account_id:
        raise HTTPException(status_code=400, detail="缺少广告账户ID")
    if not account_name:
        raise HTTPException(status_code=400, detail="缺少广告账户名称")

    token = (
        await db.execute(select(XHSReportToken).where(XHSReportToken.account_id == account_id))
    ).scalar_one_or_none()
    if not token:
        raise HTTPException(status_code=404, detail="广告账户不存在")
    if new_account_id != account_id:
        conflict = (
            await db.execute(select(XHSReportToken).where(XHSReportToken.account_id == new_account_id))
        ).scalar_one_or_none()
        if conflict:
            raise HTTPException(status_code=400, detail="新的广告账户ID已存在")

    token.account_id = new_account_id
    token.account_name = account_name
    await db.execute(
        update(XHSAdAccountBuyerAssignment)
        .where(XHSAdAccountBuyerAssignment.account_id == account_id)
        .values(account_id=new_account_id, account_name=account_name)
    )
    await db.execute(
        update(XHSAdAccountProfessionalMapping)
        .where(XHSAdAccountProfessionalMapping.account_id == account_id)
        .values(account_id=new_account_id, account_name=account_name)
    )
    await db.execute(
        update(XHSReportDaily)
        .where(XHSReportDaily.account_id == account_id)
        .values(account_id=new_account_id, account_name=account_name)
    )
    await db.commit()
    return ApiResponse(data={"account_id": new_account_id, "account_name": account_name}, message="广告账户已更新")


@router.delete("/ad-accounts/{account_id}")
async def delete_ad_account(
    account_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """删除广告账户及其投手分配、历史投流报表行。"""
    account_id = (account_id or "").strip()
    if not account_id:
        raise HTTPException(status_code=400, detail="缺少广告账户ID")
    await db.execute(delete(XHSAdAccountBuyerAssignment).where(XHSAdAccountBuyerAssignment.account_id == account_id))
    await db.execute(delete(XHSAdAccountProfessionalMapping).where(XHSAdAccountProfessionalMapping.account_id == account_id))
    await db.execute(delete(XHSReportDaily).where(XHSReportDaily.account_id == account_id))
    result = await db.execute(delete(XHSReportToken).where(XHSReportToken.account_id == account_id))
    await db.commit()
    if (result.rowcount or 0) <= 0:
        return ApiResponse(message="广告账户已从分配关系和报表中移除")
    return ApiResponse(message="广告账户已删除")


@router.post("/ad-account-professional-mapping")
async def update_ad_account_professional_mapping(
    req: UpdateAdAccountProfessionalRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """设置广告账户对应的小红书专业号。一个广告账户只绑定一个专业号。"""
    account_id = (req.account_id or "").strip()
    xhs_account_id = (req.xhs_account_id or "").strip()
    xhs_account_name = (req.xhs_account_name or "").strip()
    xhs_owner_name = (req.xhs_owner_name or "").strip()
    if not account_id:
        raise HTTPException(status_code=400, detail="缺少广告账户ID")

    token = (await db.execute(select(XHSReportToken).where(XHSReportToken.account_id == account_id))).scalar_one_or_none()
    if token:
        account_name = token.account_name or token.account_id
    else:
        daily_row = (
            await db.execute(
                select(XHSReportDaily.account_name)
                .where(XHSReportDaily.account_id == account_id)
                .order_by(XHSReportDaily.report_date.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        if not daily_row:
            raise HTTPException(status_code=404, detail="广告账户不存在")
        account_name = daily_row or account_id

    existing = (
        await db.execute(
            select(XHSAdAccountProfessionalMapping)
            .where(XHSAdAccountProfessionalMapping.account_id == account_id)
        )
    ).scalar_one_or_none()

    if not xhs_account_id and not xhs_account_name:
        if existing:
            await db.delete(existing)
            await db.commit()
        return ApiResponse(data={"account_id": account_id}, message="专业号映射已清空")

    if not xhs_account_id:
        raise HTTPException(status_code=400, detail="请填写专业号ID")
    if not xhs_account_name:
        raise HTTPException(status_code=400, detail="请填写专业号名称")

    if existing:
        existing.account_name = account_name
        existing.xhs_account_id = xhs_account_id
        existing.xhs_account_name = xhs_account_name
        existing.xhs_owner_name = xhs_owner_name
    else:
        db.add(XHSAdAccountProfessionalMapping(
            account_id=account_id,
            account_name=account_name,
            xhs_account_id=xhs_account_id,
            xhs_account_name=xhs_account_name,
            xhs_owner_name=xhs_owner_name,
        ))
    await db.commit()
    return ApiResponse(
        data={
            "account_id": account_id,
            "xhs_account_id": xhs_account_id,
            "xhs_account_name": xhs_account_name,
            "xhs_owner_name": xhs_owner_name,
        },
        message="专业号映射已保存",
    )


@router.post("/ad-account-assign")
async def assign_ad_account_buyer(
    req: AssignAdAccountRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """给广告账户设置投手。一个广告账户只保留一个投手。"""
    account_id = (req.account_id or "").strip()
    if not account_id:
        raise HTTPException(status_code=400, detail="缺少广告账户ID")

    user = (
        await db.execute(
            select(User).options(selectinload(User.role_assignments)).where(User.id == req.user_id)
        )
    ).scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")

    # 投流负责人可以是投手、运营负责人或管理员；看板只读取这里的账号归属关系。
    if not has_role(user, "buyer", "xhs_ops", "xhs_lead", "admin"):
        raise HTTPException(status_code=400, detail="该用户不能作为投流负责人")

    token = (await db.execute(select(XHSReportToken).where(XHSReportToken.account_id == account_id))).scalar_one_or_none()
    if token:
        account_name = token.account_name or token.account_id
    else:
        daily_row = (
            await db.execute(
                select(XHSReportDaily.account_name)
                .where(XHSReportDaily.account_id == account_id)
                .order_by(XHSReportDaily.report_date.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        if not daily_row:
            raise HTTPException(status_code=404, detail="广告账户不存在")
        account_name = daily_row or account_id

    if not account_name:
        raise HTTPException(status_code=404, detail="广告账户不存在")

    bind = db.get_bind()
    if bind and bind.dialect.name == "sqlite":
        stmt = sqlite_insert(XHSAdAccountBuyerAssignment).values(
            account_id=account_id,
            account_name=account_name,
            user_id=user.id,
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=["account_id"],
            set_={"user_id": user.id, "account_name": account_name},
        )
        await db.execute(stmt)
    else:
        existing = (
            await db.execute(
                select(XHSAdAccountBuyerAssignment)
                .where(XHSAdAccountBuyerAssignment.account_id == account_id)
            )
        ).scalar_one_or_none()
        if existing:
            existing.user_id = user.id
            existing.account_name = account_name
        else:
            db.add(XHSAdAccountBuyerAssignment(
                account_id=account_id,
                account_name=account_name,
                user_id=user.id,
            ))
    await db.commit()
    return ApiResponse(data={"account_id": account_id, "user_id": user.id}, message="投手已分配")


@router.post("/ad-account-unassign")
async def unassign_ad_account_buyer(
    req: UnassignAdAccountRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    account_id = (req.account_id or "").strip()
    if not account_id:
        raise HTTPException(status_code=400, detail="缺少广告账户ID")
    existing = (
        await db.execute(
            select(XHSAdAccountBuyerAssignment)
            .where(XHSAdAccountBuyerAssignment.account_id == account_id)
        )
    ).scalar_one_or_none()
    if existing:
        await db.delete(existing)
        await db.commit()
    return ApiResponse(message="已解除分配")
