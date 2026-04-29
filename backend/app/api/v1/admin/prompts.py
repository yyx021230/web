"""Admin prompt management API"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, desc, or_
from datetime import datetime

from app.db.session import get_db
from app.schemas.common import ApiResponse
from app.core.deps import require_admin
from app.models.user import User
from app.models.prompt import PromptCategory, PromptExample
from app.models.prompt_moderation import PromptReport, PromptAuditLog

router = APIRouter()


def _log_prompt_action(
    db: AsyncSession,
    prompt_id: int,
    action: str,
    operator_id: int | None,
    details: str | None = None,
):
    db.add(
        PromptAuditLog(
            prompt_id=prompt_id,
            action=action,
            operator_id=operator_id,
            details=details,
        )
    )


# ============================================================
# Category CRUD
# ============================================================

@router.get("/categories")
async def list_categories(
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=100, ge=1, le=500),
    search: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """提示词分类列表"""
    conditions = [PromptCategory.deleted_at.is_(None)]
    if search:
        conditions.append(PromptCategory.name.ilike(f"%{search}%"))

    example_count_sq = (
        select(
            PromptExample.category_id.label("category_id"),
            func.count(PromptExample.id).label("example_count"),
        )
        .where(PromptExample.deleted_at.is_(None))
        .group_by(PromptExample.category_id)
        .subquery()
    )

    count_stmt = select(func.count()).select_from(PromptCategory).where(*conditions)
    count_result = await db.execute(count_stmt)
    total = count_result.scalar() or 0

    stmt = (
        select(
            PromptCategory,
            func.coalesce(example_count_sq.c.example_count, 0).label("example_count"),
        )
        .outerjoin(example_count_sq, example_count_sq.c.category_id == PromptCategory.id)
        .where(*conditions)
        .order_by(PromptCategory.sort_order, PromptCategory.id)
        .offset((page - 1) * limit)
        .limit(limit)
    )
    result = await db.execute(stmt)
    items = result.all()

    return ApiResponse(data={
        "items": [
            {
                "id": c.id,
                "name": c.name,
                "start_intro": c.start_intro,
                "sort_order": c.sort_order,
                "example_count": int(example_count or 0),
                "created_at": str(c.created_at),
            }
            for c, example_count in items
        ],
        "total": total,
        "page": page,
        "limit": limit,
    })


@router.post("/categories")
async def create_category(
    data: dict,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """创建提示词分类"""
    if not data.get("name"):
        raise HTTPException(status_code=400, detail="名称不能为空")

    category = PromptCategory(
        name=data["name"],
        start_intro=data.get("start_intro"),
        sort_order=data.get("sort_order", 0),
    )
    db.add(category)
    await db.commit()
    await db.refresh(category)
    return ApiResponse(data={"id": category.id}, message="创建成功")


@router.put("/categories/{category_id}")
async def update_category(
    category_id: int,
    data: dict,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """更新提示词分类"""
    result = await db.execute(select(PromptCategory).where(PromptCategory.id == category_id))
    cat = result.scalar_one_or_none()
    if not cat:
        raise HTTPException(status_code=404, detail="分类不存在")

    if "name" in data:
        cat.name = data["name"]
    if "start_intro" in data:
        cat.start_intro = data["start_intro"]
    if "sort_order" in data:
        cat.sort_order = data["sort_order"]

    await db.commit()
    return ApiResponse(message="更新成功")


@router.delete("/categories/{category_id}")
async def delete_category(
    category_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """删除提示词分类（级联删除示例）"""
    result = await db.execute(select(PromptCategory).where(PromptCategory.id == category_id))
    cat = result.scalar_one_or_none()
    if not cat:
        raise HTTPException(status_code=404, detail="分类不存在")

    # 软删除
    cat.deleted_at = datetime.now()
    await db.commit()
    return ApiResponse(message="已删除")


# ============================================================
# Example CRUD
# ============================================================

@router.get("/examples")
async def list_examples(
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=50, ge=1, le=200),
    category_id: int | None = Query(default=None),
    param_type: str | None = Query(default=None),
    search: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """提示词示例列表"""
    conditions = [PromptExample.deleted_at.is_(None)]
    if category_id:
        conditions.append(PromptExample.category_id == category_id)
    if param_type:
        conditions.append(PromptExample.param_type == param_type)
    if search:
        conditions.append(
            or_(
                PromptExample.chinese_example.ilike(f"%{search}%"),
                PromptExample.english_example.ilike(f"%{search}%"),
                PromptExample.name.ilike(f"%{search}%"),
            )
        )

    count_stmt = select(func.count()).select_from(PromptExample).where(*conditions)
    count_result = await db.execute(count_stmt)
    total = count_result.scalar() or 0

    stmt = (
        select(PromptExample, User.username)
        .outerjoin(User, User.id == PromptExample.created_by)
        .where(*conditions)
        .order_by(PromptExample.category_id, PromptExample.sort_order, PromptExample.id)
        .offset((page - 1) * limit)
        .limit(limit)
    )
    result = await db.execute(stmt)
    items = result.all()

    # 批量获取分类名称
    cat_ids = set(e.category_id for e, _ in items)
    cat_names = {}
    if cat_ids:
        cat_result = await db.execute(
            select(PromptCategory).where(PromptCategory.id.in_(cat_ids))
        )
        for c in cat_result.scalars().all():
            cat_names[c.id] = c.name

    return ApiResponse(data={
        "items": [
            {
                "id": e.id,
                "category_id": e.category_id,
                "category_name": cat_names.get(e.category_id, ""),
                "param_type": e.param_type,
                "image_num": e.image_num,
                "image_url": e.image_url,
                "name": e.name,
                "chinese_example": e.chinese_example,
                "english_example": e.english_example,
                "ul_list": e.ul_list,
                "sort_order": e.sort_order,
                "is_public": e.is_public,
                "created_by": e.created_by,
                "created_by_name": username,
                "created_at": str(e.created_at),
            }
            for e, username in items
        ],
        "total": total,
        "page": page,
        "limit": limit,
    })


@router.get("/overview")
async def prompts_overview(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    _ = current_user
    total_categories = (
        await db.execute(
            select(func.count())
            .select_from(PromptCategory)
            .where(PromptCategory.deleted_at.is_(None))
        )
    ).scalar() or 0
    total_examples = (
        await db.execute(
            select(func.count())
            .select_from(PromptExample)
            .where(PromptExample.deleted_at.is_(None))
        )
    ).scalar() or 0
    public_examples = (
        await db.execute(
            select(func.count())
            .select_from(PromptExample)
            .where(
                PromptExample.deleted_at.is_(None),
                PromptExample.is_public.is_(True),
            )
        )
    ).scalar() or 0
    with_image_examples = (
        await db.execute(
            select(func.count())
            .select_from(PromptExample)
            .where(
                PromptExample.deleted_at.is_(None),
                PromptExample.image_url.is_not(None),
                PromptExample.image_url != "",
            )
        )
    ).scalar() or 0
    pending_reports = (
        await db.execute(
            select(func.count())
            .select_from(PromptReport)
            .where(PromptReport.status == "pending")
        )
    ).scalar() or 0

    return ApiResponse(
        data={
            "total_categories": total_categories,
            "total_examples": total_examples,
            "public_examples": public_examples,
            "private_examples": max(total_examples - public_examples, 0),
            "with_image_examples": with_image_examples,
            "pending_reports": pending_reports,
        }
    )


@router.post("/examples")
async def create_example(
    data: dict,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """创建提示词示例"""
    if not data.get("category_id") or not data.get("param_type"):
        raise HTTPException(status_code=400, detail="分类ID和参数类型不能为空")

    example = PromptExample(
        category_id=data["category_id"],
        param_type=data["param_type"],
        chinese_example=data.get("chinese_example", ""),
        english_example=data.get("english_example", ""),
        image_url=data.get("image_url"),
        name=data.get("name"),
        ul_list=data.get("ul_list", []),
        sort_order=data.get("sort_order", 0),
        is_public=bool(data.get("is_public", True)),
        created_by=current_user.id,
        updated_by=current_user.id,
    )
    db.add(example)
    await db.commit()
    await db.refresh(example)
    return ApiResponse(data={"id": example.id}, message="创建成功")


@router.put("/examples/{example_id}")
async def update_example(
    example_id: int,
    data: dict,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """更新提示词示例"""
    result = await db.execute(select(PromptExample).where(PromptExample.id == example_id))
    example = result.scalar_one_or_none()
    if not example:
        raise HTTPException(status_code=404, detail="示例不存在")

    old_public = example.is_public
    for field in ["param_type", "chinese_example", "english_example", "image_url", "name", "ul_list", "sort_order", "category_id", "is_public"]:
        if field in data:
            setattr(example, field, data[field])
    example.updated_by = current_user.id
    if "is_public" in data and bool(data.get("is_public")) != bool(old_public):
        _log_prompt_action(
            db,
            prompt_id=example.id,
            action="show" if bool(data.get("is_public")) else "hide",
            operator_id=current_user.id,
            details=f"is_public: {old_public} -> {bool(data.get('is_public'))}",
        )

    await db.commit()
    return ApiResponse(message="更新成功")


@router.delete("/examples/{example_id}")
async def delete_example(
    example_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """删除提示词示例"""
    result = await db.execute(select(PromptExample).where(PromptExample.id == example_id))
    example = result.scalar_one_or_none()
    if not example:
        raise HTTPException(status_code=404, detail="示例不存在")

    example.deleted_at = datetime.now()
    _log_prompt_action(
        db,
        prompt_id=example.id,
        action="delete",
        operator_id=current_user.id,
        details="admin deleted prompt example",
    )
    await db.commit()
    return ApiResponse(message="已删除")


@router.get("/reports")
async def list_reports(
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=20, ge=1, le=200),
    status: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    conditions = []
    if status:
        conditions.append(PromptReport.status == status)

    count_stmt = select(func.count()).select_from(PromptReport).where(*conditions)
    total_result = await db.execute(count_stmt)
    total = total_result.scalar() or 0

    stmt = (
        select(PromptReport, PromptExample, User.username)
        .join(PromptExample, PromptExample.id == PromptReport.prompt_id)
        .join(User, User.id == PromptReport.reporter_id)
        .where(*conditions)
        .order_by(PromptReport.created_at.desc())
        .offset((page - 1) * limit)
        .limit(limit)
    )
    result = await db.execute(stmt)
    items = result.all()

    return ApiResponse(data={
        "items": [
            {
                "id": report.id,
                "prompt_id": report.prompt_id,
                "prompt_name": prompt.name or f"#{prompt.id}",
                "prompt_text": prompt.chinese_example[:80],
                "reason": report.reason,
                "details": report.details,
                "status": report.status,
                "reporter_id": report.reporter_id,
                "reporter_name": reporter_name,
                "created_at": str(report.created_at),
                "resolved_at": str(report.resolved_at) if report.resolved_at else None,
                "resolution_note": report.resolution_note,
            }
            for report, prompt, reporter_name in items
        ],
        "total": total,
        "page": page,
        "limit": limit,
    })


@router.get("/reports/stats")
async def report_stats(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    _ = current_user
    total = (await db.execute(select(func.count()).select_from(PromptReport))).scalar() or 0
    pending = (await db.execute(select(func.count()).select_from(PromptReport).where(PromptReport.status == "pending"))).scalar() or 0
    resolved = (await db.execute(select(func.count()).select_from(PromptReport).where(PromptReport.status == "resolved"))).scalar() or 0
    rejected = (await db.execute(select(func.count()).select_from(PromptReport).where(PromptReport.status == "rejected"))).scalar() or 0

    reason_rows = await db.execute(
        select(PromptReport.reason, func.count(PromptReport.id))
        .group_by(PromptReport.reason)
        .order_by(func.count(PromptReport.id).desc())
    )
    return ApiResponse(data={
        "total": total,
        "pending": pending,
        "resolved": resolved,
        "rejected": rejected,
        "by_reason": [{"reason": r, "count": c} for r, c in reason_rows.all()],
    })


@router.post("/reports/{report_id}/resolve")
async def resolve_report(
    report_id: int,
    data: dict,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    action = (data.get("action") or "").strip()  # hide/reject
    note = (data.get("note") or "").strip() or None
    if action not in {"hide", "reject"}:
        raise HTTPException(status_code=400, detail="action 仅支持 hide / reject")

    result = await db.execute(
        select(PromptReport, PromptExample)
        .join(PromptExample, PromptExample.id == PromptReport.prompt_id)
        .where(PromptReport.id == report_id)
    )
    row = result.first()
    if not row:
        raise HTTPException(status_code=404, detail="举报不存在")

    report, prompt = row
    if report.status != "pending":
        raise HTTPException(status_code=400, detail="该举报已处理")

    if action == "hide":
        prompt.is_public = False
        report.status = "resolved"
        _log_prompt_action(
            db,
            prompt_id=prompt.id,
            action="hide",
            operator_id=current_user.id,
            details=f"resolve report #{report.id}; note={note or ''}",
        )
    else:
        report.status = "rejected"
        _log_prompt_action(
            db,
            prompt_id=prompt.id,
            action="reject_report",
            operator_id=current_user.id,
            details=f"report #{report.id}; note={note or ''}",
        )

    report.resolved_by = current_user.id
    report.resolved_at = datetime.now()
    report.resolution_note = note
    await db.commit()
    return ApiResponse(message="举报处理完成")


@router.post("/reports/batch-resolve")
async def batch_resolve_reports(
    data: dict,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    report_ids: list[int] = data.get("report_ids") or []
    action = (data.get("action") or "").strip()  # hide/reject
    note = (data.get("note") or "").strip() or None
    if not report_ids:
        raise HTTPException(status_code=400, detail="report_ids 不能为空")
    if action not in {"hide", "reject"}:
        raise HTTPException(status_code=400, detail="action 仅支持 hide / reject")

    result = await db.execute(
        select(PromptReport, PromptExample)
        .join(PromptExample, PromptExample.id == PromptReport.prompt_id)
        .where(PromptReport.id.in_(report_ids))
    )
    rows = result.all()
    if not rows:
        raise HTTPException(status_code=404, detail="未找到可处理的举报")

    processed = 0
    for report, prompt in rows:
        if report.status != "pending":
            continue
        if action == "hide":
            prompt.is_public = False
            report.status = "resolved"
            _log_prompt_action(
                db,
                prompt_id=prompt.id,
                action="hide",
                operator_id=current_user.id,
                details=f"batch resolve report #{report.id}; note={note or ''}",
            )
        else:
            report.status = "rejected"
            _log_prompt_action(
                db,
                prompt_id=prompt.id,
                action="reject_report",
                operator_id=current_user.id,
                details=f"batch reject report #{report.id}; note={note or ''}",
            )
        report.resolved_by = current_user.id
        report.resolved_at = datetime.now()
        report.resolution_note = note
        processed += 1

    await db.commit()
    return ApiResponse(data={"processed": processed}, message=f"批量处理完成（{processed} 条）")


@router.post("/cleanup-no-image")
async def cleanup_no_image_prompts(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """软删除所有无图片提示词（管理员）"""
    result = await db.execute(
        select(PromptExample).where(
            PromptExample.deleted_at.is_(None),
            or_(
                PromptExample.image_url.is_(None),
                PromptExample.image_url == "",
            ),
        )
    )
    items = result.scalars().all()
    if not items:
        return ApiResponse(
            data={
                "deleted_count": 0,
                "sample_ids": [],
                "executed_at": datetime.now().isoformat(),
            },
            message="无需清理",
        )

    sample_ids = [p.id for p in items[:20]]
    for p in items:
        p.deleted_at = datetime.now()
        p.updated_by = current_user.id
        _log_prompt_action(
            db,
            prompt_id=p.id,
            action="cleanup_no_image",
            operator_id=current_user.id,
            details="admin cleanup: no image_url",
        )
    await db.commit()
    return ApiResponse(
        data={
            "deleted_count": len(items),
            "sample_ids": sample_ids,
            "executed_at": datetime.now().isoformat(),
        },
        message=f"已清理 {len(items)} 条无图提示词",
    )


@router.get("/audit-logs")
async def list_audit_logs(
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=20, ge=1, le=200),
    action: str | None = Query(default=None),
    operator_name: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    conditions = []
    if action:
        conditions.append(PromptAuditLog.action == action)
    if operator_name:
        conditions.append(User.username.ilike(f"%{operator_name}%"))

    count_stmt = (
        select(func.count())
        .select_from(PromptAuditLog)
        .outerjoin(User, User.id == PromptAuditLog.operator_id)
        .where(*conditions)
    )
    total_result = await db.execute(count_stmt)
    total = total_result.scalar() or 0

    stmt = (
        select(PromptAuditLog, PromptExample, User.username)
        .join(PromptExample, PromptExample.id == PromptAuditLog.prompt_id)
        .outerjoin(User, User.id == PromptAuditLog.operator_id)
        .where(*conditions)
        .order_by(PromptAuditLog.created_at.desc())
        .offset((page - 1) * limit)
        .limit(limit)
    )
    result = await db.execute(stmt)
    rows = result.all()

    return ApiResponse(data={
        "items": [
            {
                "id": log.id,
                "prompt_id": log.prompt_id,
                "prompt_name": prompt.name or f"#{prompt.id}",
                "action": log.action,
                "operator_id": log.operator_id,
                "operator_name": username,
                "details": log.details,
                "created_at": str(log.created_at),
            }
            for log, prompt, username in rows
        ],
        "total": total,
        "page": page,
        "limit": limit,
    })


# ============================================================
# Bulk import (for seeding)
# ============================================================

@router.post("/import")
async def import_prompts(
    data: dict,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """批量导入提示词（从 prompts.json 格式）"""
    categories = data.get("categories", [])
    imported_cats = 0
    imported_examples = 0

    for cat_data in categories:
        # 查找或创建分类
        existing = await db.execute(
            select(PromptCategory).where(
                PromptCategory.name == cat_data["name"],
                PromptCategory.deleted_at.is_(None),
            )
        )
        cat = existing.scalar_one_or_none()

        if not cat:
            cat = PromptCategory(
                name=cat_data["name"],
                start_intro=cat_data.get("start_intro"),
                sort_order=cat_data.get("id", 0),
            )
            db.add(cat)
            await db.flush()

        # 导入示例
        for param in cat_data.get("params", []):
            examples = param.get("examples", [])
            if not examples:
                # 扁平格式（旧数据）
                examples = [{
                    "image": param.get("image", 0),
                    "imageUrl": param.get("imageUrl"),
                    "chineseExample": param.get("chineseExample", ""),
                    "englishExample": param.get("englishExample", ""),
                }]

            for ex_data in examples:
                existing_ex = await db.execute(
                    select(PromptExample).where(
                        PromptExample.category_id == cat.id,
                        PromptExample.param_type == param["type"],
                        PromptExample.chinese_example == ex_data.get("chineseExample", ""),
                        PromptExample.deleted_at.is_(None),
                    )
                )
                if existing_ex.scalar_one_or_none():
                    continue  # 已存在

                example = PromptExample(
                    category_id=cat.id,
                    param_type=param["type"],
                    image_num=ex_data.get("image", 0),
                    image_url=ex_data.get("imageUrl"),
                    name=ex_data.get("name"),
                    chinese_example=ex_data.get("chineseExample", ""),
                    english_example=ex_data.get("englishExample", ""),
                    ul_list=param.get("ulList", []),
                    sort_order=ex_data.get("image", 0),
                )
                db.add(example)
                imported_examples += 1

        imported_cats += 1

    await db.commit()
    return ApiResponse(data={
        "imported_categories": imported_cats,
        "imported_examples": imported_examples,
    }, message="导入完成")
