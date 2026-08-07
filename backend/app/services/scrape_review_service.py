from __future__ import annotations

from datetime import datetime

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.copywriting import Copywriting
from app.models.scrape_review import ScrapeCandidate, ScrapeCandidateReview, ScrapeTask, ScrapeTaskReviewer
from app.models.user import User
from app.services.copywriting_service import CopywritingService
from app.services.xhs_scrape_lab import XHSScrapeLabClient


def _parse_publish_date(value: str | None) -> datetime.date | None:
    text = str(value or "").strip()
    if not text:
        return None
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(text[:19], fmt).date()
        except ValueError:
            continue
    return None


class ScrapeReviewService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create_task(
        self,
        *,
        name: str,
        source: str,
        source_config: dict,
        max_items: int,
        reviewer_ids: list[int],
        created_by: int,
    ) -> ScrapeTask:
        task = ScrapeTask(
            name=name.strip(),
            source=source,
            source_config=source_config,
            max_items=max_items,
            created_by=created_by,
            status="draft",
        )
        self.db.add(task)
        await self.db.flush()
        if reviewer_ids:
            self.db.add_all([ScrapeTaskReviewer(task_id=task.id, user_id=user_id) for user_id in reviewer_ids])
        await self.db.commit()
        await self.db.refresh(task)
        return task

    async def replace_reviewers(self, task: ScrapeTask, reviewer_ids: list[int]) -> None:
        await self.db.execute(delete(ScrapeTaskReviewer).where(ScrapeTaskReviewer.task_id == task.id))
        if reviewer_ids:
            self.db.add_all([ScrapeTaskReviewer(task_id=task.id, user_id=user_id) for user_id in reviewer_ids])
        await self.db.commit()

    async def bulk_assign_reviewers(self, task_ids: list[int], reviewer_ids: list[int]) -> int:
        normalized_task_ids = sorted({int(x) for x in task_ids if x})
        if not normalized_task_ids:
            return 0
        rows = (
            await self.db.execute(
                select(ScrapeTask).where(ScrapeTask.id.in_(normalized_task_ids))
            )
        ).scalars().all()
        if len(rows) != len(normalized_task_ids):
            raise ValueError("存在无效任务")
        for task in rows:
            if task.status != "completed":
                raise ValueError(f"任务《{task.name}》尚未抓取完成，不能分配审核")
        for task in rows:
            await self.db.execute(delete(ScrapeTaskReviewer).where(ScrapeTaskReviewer.task_id == task.id))
            if reviewer_ids:
                self.db.add_all([ScrapeTaskReviewer(task_id=task.id, user_id=user_id) for user_id in reviewer_ids])
        await self.db.commit()
        return len(rows)

    async def run_task(self, task: ScrapeTask) -> dict:
        if task.candidate_count and task.status == "completed":
            raise ValueError("该任务已抓取完成，如需重抓请新建任务")

        task.status = "running"
        task.started_at = datetime.utcnow()
        task.last_error = None
        await self.db.commit()

        client = XHSScrapeLabClient()
        try:
            result = await client.scrape({
                "source": task.source,
                "maxItems": task.max_items,
                "sourceParams": task.source_config or {},
            })
        except Exception as exc:
            task.status = "failed"
            task.finished_at = datetime.utcnow()
            task.last_error = str(exc)
            await self.db.commit()
            raise

        notes = result.get("notes") or []
        created = 0
        for note in notes:
            external_id = str(note.get("id") or "").strip()
            if not external_id:
                continue
            exists = await self.db.execute(
                select(ScrapeCandidate.id).where(
                    ScrapeCandidate.task_id == task.id,
                    ScrapeCandidate.external_id == external_id,
                )
            )
            if exists.scalar_one_or_none():
                continue
            candidate = ScrapeCandidate(
                task_id=task.id,
                external_id=external_id,
                source=str(note.get("source") or task.source or "keyword"),
                source_keyword=str(note.get("sourceKeyword") or ""),
                post_url=str(note.get("link") or ""),
                title=str(note.get("title") or "未命名笔记").strip()[:255],
                content=str(note.get("content") or note.get("title") or "").strip(),
                author=str(note.get("author") or "").strip(),
                publish_date=_parse_publish_date(note.get("publishDate")),
                copy_type=str(note.get("type") or "").strip() or None,
                brand=str(note.get("brand") or "").strip() or None,
                likes=int(note.get("likes") or 0),
                comments=int(note.get("comments") or 0),
                collects=int(note.get("collects") or 0),
                shares=int(note.get("shares") or 0),
                views=int(note.get("views") or 0),
                raw_payload=note.get("raw") or note,
            )
            self.db.add(candidate)
            created += 1

        task.status = "completed"
        task.finished_at = datetime.utcnow()
        task.saved_path = str(result.get("saved_path") or "")
        task.run_meta = {
            "count": int(result.get("count") or len(notes)),
            "source": result.get("source"),
            "commands": result.get("commands") or [],
            "keywords": result.get("keywords") or [],
            "history_dedupe": result.get("history_dedupe") or {},
            "stats": result.get("stats") or {},
        }
        await self.db.commit()
        await self.refresh_task_counts(task.id)
        return {"created": created, "total": len(notes), "saved_path": task.saved_path}

    async def refresh_task_counts(self, task_id: int) -> None:
        task = await self.db.get(ScrapeTask, task_id)
        if not task:
            return
        total = (
            await self.db.execute(select(func.count()).select_from(ScrapeCandidate).where(ScrapeCandidate.task_id == task_id))
        ).scalar() or 0
        pending = (
            await self.db.execute(
                select(func.count()).select_from(ScrapeCandidate).where(
                    ScrapeCandidate.task_id == task_id,
                    ScrapeCandidate.review_status == "pending",
                )
            )
        ).scalar() or 0
        approved = (
            await self.db.execute(
                select(func.count()).select_from(ScrapeCandidate).where(
                    ScrapeCandidate.task_id == task_id,
                    ScrapeCandidate.review_status == "approved",
                )
            )
        ).scalar() or 0
        rejected = (
            await self.db.execute(
                select(func.count()).select_from(ScrapeCandidate).where(
                    ScrapeCandidate.task_id == task_id,
                    ScrapeCandidate.review_status == "rejected",
                )
            )
        ).scalar() or 0
        needs_second_review = (
            await self.db.execute(
                select(func.count()).select_from(ScrapeCandidate).where(
                    ScrapeCandidate.task_id == task_id,
                    ScrapeCandidate.review_status == "needs_second_review",
                )
            )
        ).scalar() or 0
        task.candidate_count = int(total)
        task.pending_count = int(pending)
        task.approved_count = int(approved)
        task.rejected_count = int(rejected)
        task.needs_second_review_count = int(needs_second_review)
        await self.db.commit()

    async def ensure_reviewer_access(self, task_id: int, user_id: int) -> bool:
        if (
            await self.db.execute(
                select(ScrapeTaskReviewer.id).where(
                    ScrapeTaskReviewer.task_id == task_id,
                    ScrapeTaskReviewer.user_id == user_id,
                )
            )
        ).scalar_one_or_none():
            return True
        user = await self.db.get(User, user_id)
        return bool(user and user.role == "admin")

    async def review_candidate(
        self,
        *,
        candidate: ScrapeCandidate,
        reviewer: User,
        action: str,
        note: str | None = None,
    ) -> ScrapeCandidate:
        if action not in {"approved", "rejected", "needs_second_review"}:
            raise ValueError("无效的审核动作")

        if not await self.ensure_reviewer_access(candidate.task_id, reviewer.id):
            raise PermissionError("无权审核该任务")

        if candidate.review_status == "approved" and candidate.copywriting_id:
            raise ValueError("该候选已入库")

        candidate.review_status = action
        candidate.reviewer_id = reviewer.id
        candidate.review_note = (note or "").strip() or None
        candidate.reviewed_at = datetime.utcnow()

        if action == "approved" and not candidate.copywriting_id:
            service = CopywritingService(self.db)
            item = await service.create(
                title=(candidate.title or "").strip()[:255],
                content=(candidate.content or candidate.title or "").strip(),
                user_id=reviewer.id,
            )
            candidate.copywriting_id = item.id

        self.db.add(
            ScrapeCandidateReview(
                task_id=candidate.task_id,
                candidate_id=candidate.id,
                reviewer_id=reviewer.id,
                action=action,
                note=candidate.review_note,
            )
        )
        await self.db.commit()
        await self.db.refresh(candidate)
        await self.refresh_task_counts(candidate.task_id)
        return candidate

    async def get_copywriting_title(self, copywriting_id: int | None) -> str | None:
        if not copywriting_id:
            return None
        item = await self.db.get(Copywriting, copywriting_id)
        return item.title if item else None
