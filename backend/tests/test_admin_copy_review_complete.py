from __future__ import annotations

from datetime import date, datetime

import pytest

from app.db.session import async_session
from app.models.scrape_review import ScrapeCandidate, ScrapeTask, ScrapeTaskReviewer
from app.models.user import User
from app.services.scrape_review_service import ScrapeReviewService
from tests.conftest import make_auth_headers


async def _seed_review_data():
    async with async_session() as db:
        admin = User(id=1, username="admin", email="admin@example.com", hashed_password="x", role="admin")
        reviewer = User(id=2, username="reviewer", email="reviewer@example.com", hashed_password="x")
        inactive = User(
            id=3,
            username="inactive",
            email="inactive@example.com",
            hashed_password="x",
            is_active=False,
        )
        task = ScrapeTask(
            id=10,
            name="汽车内容审核",
            source="keyword",
            status="completed",
            source_config={"rawKeywords": "零跑， 小鹏\n零跑", "keywordMode": "multi", "historyDedupeDays": 30},
            max_items=10,
            created_by=admin.id,
            candidate_count=1,
            pending_count=1,
            saved_path="/tmp/results.json",
            run_meta={
                "stats": {
                    "saved_count": 1,
                    "search_returned_count": 8,
                    "considered_count": 5,
                    "duplicate_filtered_count": 2,
                    "history_filtered_count": 1,
                }
            },
            started_at=datetime(2026, 8, 1, 10),
            finished_at=datetime(2026, 8, 1, 11),
        )
        db.add_all([admin, reviewer, inactive])
        await db.flush()
        db.add(task)
        await db.flush()
        db.add(ScrapeTaskReviewer(task_id=task.id, user_id=reviewer.id))
        db.add(
            ScrapeCandidate(
                id=20,
                task_id=task.id,
                external_id="note-1",
                title="零跑价格变化",
                content="完整正文",
                author="作者",
                source="keyword",
                source_keyword="零跑",
                post_url="https://xhs/note-1",
                publish_date=date(2026, 8, 1),
                copy_type="行情",
                brand="零跑",
                likes=12,
                comments=3,
                collects=4,
                shares=2,
                views=100,
                reviewer_id=reviewer.id,
            )
        )
        await db.commit()
    return admin, reviewer, inactive, task


def test_copy_review_helpers_cover_empty_phrase_and_shortfall():
    from app.api.v1.admin.copy_review import _build_run_summary, _parse_keywords

    assert _parse_keywords({}) == []
    assert _parse_keywords({"rawKeywords": "完整短语"}) == ["完整短语"]
    assert _parse_keywords({"rawKeywords": "A,A，B\nC", "keywordMode": "multi"}) == ["A", "B", "C"]
    task = ScrapeTask(
        name="test",
        source="keyword",
        source_config={"rawKeywords": "A"},
        max_items=5,
        created_by=1,
        candidate_count=2,
        run_meta={},
    )
    summary = _build_run_summary(task)
    assert summary["saved_count"] == 2
    assert summary["shortfall_count"] == 3
    assert summary["search_shortage_count"] == 3


@pytest.mark.asyncio
async def test_admin_copy_review_list_detail_candidates_and_filters(client):
    admin, _, _, task = await _seed_review_data()
    headers = make_auth_headers(admin.id)
    listed = await client.get("/api/v1/admin/copy-review/tasks", headers=headers)
    assert listed.status_code == 200
    item = listed.json()["data"]["items"][0]
    assert item["reviewers"][0]["username"] == "reviewer"
    assert item["run_summary"]["configured_keywords"] == ["零跑", "小鹏"]
    assert item["run_summary"]["search_shortage_count"] == 6
    assert (await client.get("/api/v1/admin/copy-review/tasks?status=draft", headers=headers)).json()["data"]["total"] == 0

    detail = await client.get(f"/api/v1/admin/copy-review/tasks/{task.id}", headers=headers)
    assert detail.status_code == 200
    assert detail.json()["data"]["started_at"] is not None
    assert (await client.get("/api/v1/admin/copy-review/tasks/999", headers=headers)).status_code == 404

    candidates = await client.get(f"/api/v1/admin/copy-review/tasks/{task.id}/candidates", headers=headers)
    assert candidates.status_code == 200
    candidate = candidates.json()["data"]["items"][0]
    assert candidate["reviewer_name"] == "reviewer"
    assert candidate["publish_date"] == "2026-08-01"
    filtered = await client.get(
        f"/api/v1/admin/copy-review/tasks/{task.id}/candidates?status=approved",
        headers=headers,
    )
    assert filtered.json()["data"]["items"] == []
    assert (await client.get("/api/v1/admin/copy-review/tasks/999/candidates", headers=headers)).status_code == 404


@pytest.mark.asyncio
async def test_admin_copy_review_create_and_assign_validation(client, monkeypatch):
    admin, reviewer, inactive, task = await _seed_review_data()
    headers = make_auth_headers(admin.id)
    assert (
        await client.post(
            "/api/v1/admin/copy-review/tasks",
            json={"name": "", "source_config": {"rawKeywords": "A"}},
            headers=headers,
        )
    ).status_code == 400
    assert (
        await client.post(
            "/api/v1/admin/copy-review/tasks",
            json={"name": "任务", "source": "keyword", "source_config": {}},
            headers=headers,
        )
    ).status_code == 400
    assert (
        await client.post(
            "/api/v1/admin/copy-review/tasks",
            json={
                "name": "任务",
                "source": "keyword",
                "source_config": {"rawKeywords": "A"},
                "reviewer_ids": [999],
            },
            headers=headers,
        )
    ).status_code == 400
    assert (
        await client.post(
            "/api/v1/admin/copy-review/tasks",
            json={
                "name": "任务",
                "source": "keyword",
                "source_config": {"rawKeywords": "A"},
                "reviewer_ids": [inactive.id],
            },
            headers=headers,
        )
    ).status_code == 400

    created = await client.post(
        "/api/v1/admin/copy-review/tasks",
        json={
            "name": "新抓取任务",
            "source": "keyword",
            "source_config": {"rawKeywords": "A"},
            "max_items": 999,
            "reviewer_ids": [reviewer.id, reviewer.id],
        },
        headers=headers,
    )
    assert created.status_code == 200
    assert created.json()["data"]["status"] == "draft"

    assert (await client.post("/api/v1/admin/copy-review/tasks/assign", json={}, headers=headers)).status_code == 400
    no_reviewers = await client.post(
        "/api/v1/admin/copy-review/tasks/assign",
        json={"task_ids": [task.id]},
        headers=headers,
    )
    assert no_reviewers.status_code == 400

    async def invalid_assign(self, task_ids, reviewer_ids):
        raise ValueError("任务状态错误")

    monkeypatch.setattr(ScrapeReviewService, "bulk_assign_reviewers", invalid_assign)
    invalid = await client.post(
        "/api/v1/admin/copy-review/tasks/assign",
        json={"task_ids": [task.id], "reviewer_ids": [reviewer.id]},
        headers=headers,
    )
    assert invalid.status_code == 400

    async def assigned(self, task_ids, reviewer_ids):
        return len(task_ids)

    monkeypatch.setattr(ScrapeReviewService, "bulk_assign_reviewers", assigned)
    success = await client.post(
        "/api/v1/admin/copy-review/tasks/assign",
        json={"task_ids": [task.id, task.id], "reviewer_ids": [reviewer.id]},
        headers=headers,
    )
    assert success.json()["data"]["assigned_task_count"] == 1


@pytest.mark.asyncio
async def test_admin_copy_review_run_success_and_errors(client, monkeypatch):
    admin, _, _, task = await _seed_review_data()
    headers = make_auth_headers(admin.id)
    assert (await client.post("/api/v1/admin/copy-review/tasks/999/run", headers=headers)).status_code == 404

    async def success(self, row):
        return {"created": 3}

    monkeypatch.setattr(ScrapeReviewService, "run_task", success)
    response = await client.post(f"/api/v1/admin/copy-review/tasks/{task.id}/run", headers=headers)
    assert response.status_code == 200
    assert response.json()["data"] == {"created": 3}

    async def bad_request(self, row):
        raise ValueError("已经完成")

    monkeypatch.setattr(ScrapeReviewService, "run_task", bad_request)
    assert (await client.post(f"/api/v1/admin/copy-review/tasks/{task.id}/run", headers=headers)).status_code == 400

    async def server_error(self, row):
        raise RuntimeError("scraper down")

    monkeypatch.setattr(ScrapeReviewService, "run_task", server_error)
    assert (await client.post(f"/api/v1/admin/copy-review/tasks/{task.id}/run", headers=headers)).status_code == 500
