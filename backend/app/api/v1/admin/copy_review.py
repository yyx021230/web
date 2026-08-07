from __future__ import annotations

import re

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import require_admin
from app.db.session import get_db
from app.models.scrape_review import ScrapeCandidate, ScrapeTask, ScrapeTaskReviewer
from app.models.user import User
from app.services.scrape_review_service import ScrapeReviewService

router = APIRouter(prefix="/copy-review", tags=["管理-抓取审核"])


async def _fetch_reviewers(db: AsyncSession, task_ids: list[int]) -> dict[int, list[dict]]:
    if not task_ids:
        return {}
    rows = (
        await db.execute(
            select(ScrapeTaskReviewer.task_id, User.id, User.username)
            .join(User, User.id == ScrapeTaskReviewer.user_id)
            .where(ScrapeTaskReviewer.task_id.in_(task_ids))
            .order_by(ScrapeTaskReviewer.task_id.asc(), User.username.asc())
        )
    ).all()
    payload: dict[int, list[dict]] = {}
    for task_id, user_id, username in rows:
        payload.setdefault(task_id, []).append({"id": user_id, "username": username})
    return payload


async def _ensure_reviewers_exist(db: AsyncSession, reviewer_ids: list[int]) -> list[int]:
    normalized = sorted({int(x) for x in reviewer_ids if x})
    if not normalized:
        return []
    rows = (
        await db.execute(
            select(User.id).where(
                User.id.in_(normalized),
                User.is_active.is_(True),
            )
        )
    ).scalars().all()
    found = sorted({int(x) for x in rows})
    if found != normalized:
        raise HTTPException(status_code=400, detail="存在无效审核用户")
    return found


def _parse_keywords(source_config: dict) -> list[str]:
    raw = str(source_config.get("rawKeywords") or "").strip()
    mode = str(source_config.get("keywordMode") or "phrase")
    if not raw:
        return []
    if mode == "multi":
        seen: set[str] = set()
        keywords: list[str] = []
        for item in re.split(r"[,，\r\n]+", raw):
            item = item.strip()
            if item and item not in seen:
                seen.add(item)
                keywords.append(item)
        return keywords
    return [raw]


def _build_run_summary(task: ScrapeTask) -> dict:
    source_config = task.source_config or {}
    run_meta = task.run_meta or {}
    stats = run_meta.get("stats") or {}
    keywords = run_meta.get("keywords") or _parse_keywords(source_config)
    requested_max_items = int(task.max_items or 0)
    actual_count = int(task.candidate_count or 0)
    saved_count = int(stats.get("saved_count") or actual_count)
    search_returned_count = int(stats.get("search_returned_count") or 0)
    duplicate_filtered_count = int(stats.get("duplicate_filtered_count") or 0)
    history_filtered_count = int(stats.get("history_filtered_count") or 0)
    shortfall_count = max(0, requested_max_items - saved_count)
    return {
        "requested_max_items": requested_max_items,
        "actual_count": actual_count,
        "saved_count": saved_count,
        "keyword_mode": str(source_config.get("keywordMode") or ("multi" if len(keywords) > 1 else "phrase")),
        "configured_keywords": keywords,
        "configured_keyword_count": len(keywords),
        "history_dedupe_days": int(source_config.get("historyDedupeDays") or 0),
        "search_returned_count": search_returned_count,
        "considered_count": int(stats.get("considered_count") or 0),
        "duplicate_filtered_count": duplicate_filtered_count,
        "history_filtered_count": history_filtered_count,
        "shortfall_count": shortfall_count,
        "search_shortage_count": max(0, shortfall_count - duplicate_filtered_count - history_filtered_count),
    }


@router.get("/tasks")
async def list_scrape_tasks(
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=20, ge=1, le=100),
    status: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    _ = current_user
    stmt = select(ScrapeTask)
    if status:
        stmt = stmt.where(ScrapeTask.status == status)
    count_result = await db.execute(stmt.with_only_columns(ScrapeTask.id))
    total = len(count_result.scalars().all())
    tasks = (
        await db.execute(
            stmt.order_by(desc(ScrapeTask.created_at))
            .offset((page - 1) * limit)
            .limit(limit)
        )
    ).scalars().all()
    reviewers = await _fetch_reviewers(db, [task.id for task in tasks])
    return {
        "code": 0,
        "message": "success",
        "data": {
            "items": [
                {
                    "id": task.id,
                    "name": task.name,
                    "source": task.source,
                    "status": task.status,
                    "max_items": task.max_items,
                    "candidate_count": task.candidate_count,
                    "pending_count": task.pending_count,
                    "approved_count": task.approved_count,
                    "rejected_count": task.rejected_count,
                    "needs_second_review_count": task.needs_second_review_count,
                    "saved_path": task.saved_path,
                    "last_error": task.last_error,
                    "source_config": task.source_config or {},
                    "run_meta": task.run_meta or {},
                    "run_summary": _build_run_summary(task),
                    "reviewers": reviewers.get(task.id, []),
                    "created_at": str(task.created_at),
                    "started_at": str(task.started_at) if task.started_at else None,
                    "finished_at": str(task.finished_at) if task.finished_at else None,
                }
                for task in tasks
            ],
            "total": total,
            "page": page,
            "limit": limit,
        },
    }


@router.post("/tasks")
async def create_scrape_task(
    data: dict,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    reviewer_ids = await _ensure_reviewers_exist(db, list(data.get("reviewer_ids") or []))
    name = str(data.get("name") or "").strip()
    raw_keywords = str(((data.get("source_config") or {}).get("rawKeywords") or "")).strip()
    if not name:
        raise HTTPException(status_code=400, detail="任务名称不能为空")
    if str(data.get("source") or "keyword") == "keyword" and not raw_keywords:
        raise HTTPException(status_code=400, detail="关键词不能为空")

    service = ScrapeReviewService(db)
    task = await service.create_task(
        name=name,
        source=str(data.get("source") or "keyword"),
        source_config=data.get("source_config") or {},
        max_items=max(1, min(int(data.get("max_items") or 50), 300)),
        reviewer_ids=reviewer_ids,
        created_by=current_user.id,
    )
    return {
        "code": 0,
        "message": "success",
        "data": {
            "id": task.id,
            "name": task.name,
            "status": task.status,
        },
    }


@router.post("/tasks/assign")
async def assign_scrape_tasks(
    data: dict,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    _ = current_user
    task_ids = sorted({int(x) for x in list(data.get("task_ids") or []) if x})
    if not task_ids:
        raise HTTPException(status_code=400, detail="task_ids 不能为空")
    reviewer_ids = await _ensure_reviewers_exist(db, list(data.get("reviewer_ids") or []))
    if not reviewer_ids:
        raise HTTPException(status_code=400, detail="reviewer_ids 不能为空")

    service = ScrapeReviewService(db)
    try:
        assigned_count = await service.bulk_assign_reviewers(task_ids, reviewer_ids)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {
        "code": 0,
        "message": "success",
        "data": {
            "assigned_task_count": assigned_count,
            "task_ids": task_ids,
            "reviewer_ids": reviewer_ids,
        },
    }


@router.get("/tasks/{task_id}")
async def get_scrape_task_detail(
    task_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    _ = current_user
    task = await db.get(ScrapeTask, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    reviewers = await _fetch_reviewers(db, [task.id])
    return {
        "code": 0,
        "message": "success",
        "data": {
            "id": task.id,
            "name": task.name,
            "source": task.source,
            "status": task.status,
            "source_config": task.source_config or {},
            "max_items": task.max_items,
            "candidate_count": task.candidate_count,
            "pending_count": task.pending_count,
            "approved_count": task.approved_count,
            "rejected_count": task.rejected_count,
            "needs_second_review_count": task.needs_second_review_count,
            "saved_path": task.saved_path,
            "last_error": task.last_error,
            "run_meta": task.run_meta or {},
            "run_summary": _build_run_summary(task),
            "reviewers": reviewers.get(task.id, []),
            "created_at": str(task.created_at),
            "started_at": str(task.started_at) if task.started_at else None,
            "finished_at": str(task.finished_at) if task.finished_at else None,
        },
    }


@router.get("/tasks/{task_id}/candidates")
async def get_scrape_task_candidates(
    task_id: int,
    status: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    _ = current_user
    task = await db.get(ScrapeTask, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    stmt = select(ScrapeCandidate).where(ScrapeCandidate.task_id == task_id)
    if status:
        stmt = stmt.where(ScrapeCandidate.review_status == status)
    rows = (
        await db.execute(
            stmt.order_by(
                ScrapeCandidate.review_status.asc(),
                ScrapeCandidate.likes.desc(),
                ScrapeCandidate.collects.desc(),
                ScrapeCandidate.created_at.desc(),
            )
        )
    ).scalars().all()
    reviewer_map = {
        row.id: row.username
        for row in (
            await db.execute(select(User.id, User.username).where(User.id.in_([x.reviewer_id for x in rows if x.reviewer_id])))
        ).all()
    }
    return {
        "code": 0,
        "message": "success",
        "data": {
            "items": [
                {
                    "id": item.id,
                    "external_id": item.external_id,
                    "title": item.title,
                    "content": item.content,
                    "author": item.author,
                    "source": item.source,
                    "source_keyword": item.source_keyword,
                    "post_url": item.post_url,
                    "publish_date": item.publish_date.isoformat() if item.publish_date else None,
                    "copy_type": item.copy_type,
                    "brand": item.brand,
                    "likes": item.likes,
                    "comments": item.comments,
                    "collects": item.collects,
                    "shares": item.shares,
                    "views": item.views,
                    "review_status": item.review_status,
                    "reviewer_id": item.reviewer_id,
                    "reviewer_name": reviewer_map.get(item.reviewer_id),
                    "review_note": item.review_note,
                    "reviewed_at": str(item.reviewed_at) if item.reviewed_at else None,
                    "copywriting_id": item.copywriting_id,
                }
                for item in rows
            ]
        },
    }


@router.post("/tasks/{task_id}/run")
async def run_scrape_task(
    task_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    _ = current_user
    task = await db.get(ScrapeTask, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    service = ScrapeReviewService(db)
    try:
        result = await service.run_task(task)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    return {
        "code": 0,
        "message": "抓取完成",
        "data": result,
    }
