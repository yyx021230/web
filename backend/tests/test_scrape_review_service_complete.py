from __future__ import annotations

import pytest
from sqlalchemy import select

from app.db.session import async_session
from app.models.scrape_review import ScrapeCandidate, ScrapeCandidateReview
from app.models.user import User
from app.services.scrape_review_service import ScrapeReviewService, _parse_publish_date


def _user(username: str, role: str = "viewer") -> User:
    return User(
        username=username,
        email=f"{username}@example.com",
        hashed_password="hashed",
        role=role,
    )


def test_parse_publish_date_variants():
    assert str(_parse_publish_date("2026-08-11")) == "2026-08-11"
    assert str(_parse_publish_date("2026/08/11")) == "2026-08-11"
    assert str(_parse_publish_date("2026-08-11 12:30:00")) == "2026-08-11"
    assert _parse_publish_date("") is None
    assert _parse_publish_date("bad") is None


@pytest.mark.asyncio
async def test_scrape_task_run_assign_and_review_lifecycle(client, monkeypatch):
    async with async_session() as db:
        admin = _user("admin", "admin")
        reviewer = _user("reviewer")
        outsider = _user("outsider")
        db.add_all([admin, reviewer, outsider])
        await db.commit()
        for user in (admin, reviewer, outsider):
            await db.refresh(user)

        service = ScrapeReviewService(db)
        task = await service.create_task(
            name="  汽车笔记  ",
            source="keyword",
            source_config={"keywords": ["汽车"]},
            max_items=10,
            reviewer_ids=[reviewer.id],
            created_by=admin.id,
        )
        assert task.name == "汽车笔记"
        await service.replace_reviewers(task, [reviewer.id, outsider.id])
        await service.replace_reviewers(task, [])
        await service.replace_reviewers(task, [reviewer.id])
        assert await service.bulk_assign_reviewers([], [reviewer.id]) == 0
        with pytest.raises(ValueError, match="无效任务"):
            await service.bulk_assign_reviewers([task.id, 99999], [reviewer.id])
        with pytest.raises(ValueError, match="尚未抓取完成"):
            await service.bulk_assign_reviewers([task.id], [reviewer.id])

        class _Scraper:
            async def scrape(self, payload):
                assert payload["maxItems"] == 10
                return {
                    "count": 4,
                    "source": "keyword",
                    "saved_path": "/tmp/result.json",
                    "commands": ["search"],
                    "keywords": ["汽车"],
                    "history_dedupe": {"skipped": 1},
                    "stats": {"ok": 3},
                    "notes": [
                        {
                            "id": "note-1",
                            "title": "零跑降价",
                            "content": "正文 #优惠",
                            "author": "作者",
                            "publishDate": "2026-08-11",
                            "type": "行情",
                            "brand": "零跑",
                            "likes": 10,
                            "comments": 2,
                            "collects": 3,
                            "shares": 1,
                            "views": 100,
                        },
                        {"id": "note-2", "title": "只有标题", "publishDate": "bad"},
                        {"id": "", "title": "缺 ID"},
                        {"id": "note-1", "title": "重复"},
                    ],
                }

        monkeypatch.setattr("app.services.scrape_review_service.XHSScrapeLabClient", _Scraper)
        result = await service.run_task(task)
        assert result == {"created": 2, "total": 4, "saved_path": "/tmp/result.json"}
        await db.refresh(task)
        assert task.status == "completed"
        assert task.candidate_count == 2
        assert task.pending_count == 2
        assert task.run_meta["stats"] == {"ok": 3}
        with pytest.raises(ValueError, match="已抓取完成"):
            await service.run_task(task)

        assert await service.bulk_assign_reviewers([task.id], [reviewer.id]) == 1
        assert await service.ensure_reviewer_access(task.id, reviewer.id) is True
        assert await service.ensure_reviewer_access(task.id, admin.id) is True
        assert await service.ensure_reviewer_access(task.id, outsider.id) is False

        candidate = (
            await db.execute(select(ScrapeCandidate).where(ScrapeCandidate.external_id == "note-1"))
        ).scalar_one()
        with pytest.raises(ValueError, match="无效"):
            await service.review_candidate(candidate=candidate, reviewer=reviewer, action="bad")
        with pytest.raises(PermissionError):
            await service.review_candidate(candidate=candidate, reviewer=outsider, action="rejected")

        approved = await service.review_candidate(
            candidate=candidate,
            reviewer=reviewer,
            action="approved",
            note="  可入库  ",
        )
        assert approved.copywriting_id is not None
        assert approved.review_note == "可入库"
        assert await service.get_copywriting_title(approved.copywriting_id) == "零跑降价"
        assert await service.get_copywriting_title(None) is None
        assert await service.get_copywriting_title(99999) is None
        with pytest.raises(ValueError, match="已入库"):
            await service.review_candidate(candidate=approved, reviewer=reviewer, action="approved")

        second = (
            await db.execute(select(ScrapeCandidate).where(ScrapeCandidate.external_id == "note-2"))
        ).scalar_one()
        await service.review_candidate(candidate=second, reviewer=reviewer, action="needs_second_review")
        await service.refresh_task_counts(task.id)
        await service.refresh_task_counts(99999)
        await db.refresh(task)
        assert task.approved_count == 1
        assert task.needs_second_review_count == 1
        reviews = (await db.execute(select(ScrapeCandidateReview))).scalars().all()
        assert len(reviews) == 2


@pytest.mark.asyncio
async def test_scrape_task_records_client_failure(client, monkeypatch):
    async with async_session() as db:
        owner = _user("owner")
        db.add(owner)
        await db.commit()
        await db.refresh(owner)
        service = ScrapeReviewService(db)
        task = await service.create_task(
            name="失败任务",
            source="account",
            source_config={},
            max_items=5,
            reviewer_ids=[],
            created_by=owner.id,
        )

        class _FailingScraper:
            async def scrape(self, payload):
                raise RuntimeError("upstream offline")

        monkeypatch.setattr("app.services.scrape_review_service.XHSScrapeLabClient", _FailingScraper)
        with pytest.raises(RuntimeError, match="offline"):
            await service.run_task(task)
        await db.refresh(task)
        assert task.status == "failed"
        assert task.last_error == "upstream offline"
