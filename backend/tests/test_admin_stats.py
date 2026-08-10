"""Admin stats API tests."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.db.session import async_session
from app.models.ai_task import AITask
from app.models.dify_run_log import DifyRunLog
from app.models.dify_task import DifyTask
from app.models.dify_workflow import DifyWorkflowConfig
from app.models.material import Material
from app.models.project import Project
from app.models.user import User
from app.models.user_xhs_env import UserXHSEnvironment
from app.models.xhs_account_note import XHSAccountNote
from app.models.xhs_environment import XHSEnvironment
from app.models.xhs_post import XHSPost
from tests.conftest import make_auth_headers
from app.utils.timezone import cst_naive_to_utc_naive


CST = timezone(timedelta(hours=8))


def _now_cst_naive() -> datetime:
    return datetime.now(CST).replace(tzinfo=None)


def _cst_to_ai_utc_naive(value: datetime) -> datetime:
    # AI task created_at 历史上按 UTC naive 存储
    return value - timedelta(hours=8)


async def _seed_base_users() -> None:
    async with async_session() as db:
        db.add_all([
            User(id=1, username="admin", email="admin@test.com", hashed_password="x", role="admin"),
            User(id=2, username="alice", email="alice@test.com", hashed_password="x", role="viewer"),
            User(id=3, username="bob", email="bob@test.com", hashed_password="x", role="viewer"),
        ])
        await db.commit()


@pytest.mark.asyncio
async def test_usage_series_hour_is_calendar_day_and_ai_timezone_fixed(client):
    await _seed_base_users()
    now_cst = _now_cst_naive()
    day_start = now_cst.replace(hour=0, minute=0, second=0, microsecond=0)

    in_bucket_07 = day_start + timedelta(hours=7, minutes=30)
    in_bucket_09 = day_start + timedelta(hours=9, minutes=10)
    out_of_today = day_start + timedelta(days=1, hours=1)

    async with async_session() as db:
        db.add_all([
            AITask(user_id=2, model_name="seedream", prompt="p1", status="completed", created_at=_cst_to_ai_utc_naive(in_bucket_07)),
            AITask(user_id=2, model_name="custom-model", prompt="p2", status="completed", created_at=_cst_to_ai_utc_naive(in_bucket_09)),
            AITask(user_id=2, model_name="future-model", prompt="p3", status="completed", created_at=_cst_to_ai_utc_naive(out_of_today)),
        ])
        await db.commit()

    resp = await client.get("/api/v1/admin/stats/usage-series", params={"granularity": "hour"}, headers=make_auth_headers(1))
    assert resp.status_code == 200
    data = resp.json()["data"]

    assert len(data["buckets"]) == 24
    assert data["buckets"][0]["label"] == "00:00"
    assert data["buckets"][-1]["label"] == "23:00"

    ai = data["ai"]
    assert set(ai["names"]) >= {"seedream", "custom-model"}
    assert "future-model" not in ai["names"]
    assert ai["total_records"] == 2

    total_from_series = sum(sum(v) for v in ai["series"].values())
    assert total_from_series == ai["total_records"]
    assert ai["series"]["seedream"][7] == 1
    assert ai["series"]["custom-model"][9] == 1


@pytest.mark.asyncio
async def test_username_filter_applies_to_overview_active_rankings_and_usage(client):
    await _seed_base_users()
    now_cst = _now_cst_naive()
    day_start = now_cst.replace(hour=0, minute=0, second=0, microsecond=0)
    # Keep this fixture in the past at every time of day. A fixed 10:00 value
    # makes the test fail before 10:00 because the API correctly excludes future tasks.
    ai_time_today_utc = _cst_to_ai_utc_naive(day_start)

    async with async_session() as db:
        wf = DifyWorkflowConfig(api_key="k", base_url="http://x", app_name="WF-1", app_type="workflow", created_by=1)
        db.add(wf)
        await db.flush()

        db.add_all([
            Project(user_id=2, name="alice-project"),
            Project(user_id=3, name="bob-project"),
            Material(name="a", type="image", url="/a.png", created_by=2, file_size=1024),
            Material(name="b", type="image", url="/b.png", created_by=3, file_size=2048),
            AITask(user_id=2, model_name="alice-model", prompt="p", status="processing", created_at=ai_time_today_utc),
            AITask(user_id=3, model_name="bob-model", prompt="p", status="processing", created_at=ai_time_today_utc),
            DifyTask(workflow_id=wf.id, user_id=2, status="running", created_at=day_start + timedelta(hours=11)),
            DifyTask(workflow_id=wf.id, user_id=3, status="running", created_at=day_start + timedelta(hours=12)),
            DifyRunLog(workflow_id=wf.id, user_id=2, status="succeeded", started_at=day_start + timedelta(hours=11)),
            DifyRunLog(workflow_id=wf.id, user_id=3, status="succeeded", started_at=day_start + timedelta(hours=12)),
        ])
        await db.commit()

    headers = make_auth_headers(1)

    overview_resp = await client.get("/api/v1/admin/stats/overview", params={"username": "alice"}, headers=headers)
    assert overview_resp.status_code == 200
    overview = overview_resp.json()["data"]
    assert overview["user_count"] == 1
    assert overview["project_count"] == 1
    assert overview["material_count"] == 1
    assert overview["ai_task_count"] == 1
    assert overview["run_log_count"] == 1
    assert overview["ai_tasks_today"] == 1

    active_resp = await client.get("/api/v1/admin/stats/active-tasks", params={"username": "alice"}, headers=headers)
    assert active_resp.status_code == 200
    active = active_resp.json()["data"]
    assert len(active) >= 1
    assert all(item["username"] == "alice" for item in active)

    rankings_resp = await client.get("/api/v1/admin/stats/rankings", params={"username": "alice"}, headers=headers)
    assert rankings_resp.status_code == 200
    rankings = rankings_resp.json()["data"]
    assert rankings["storage_ranking"][0]["username"] == "alice"
    assert len(rankings["active_users"]) == 1
    assert rankings["active_users"][0]["username"] == "alice"

    usage_resp = await client.get(
        "/api/v1/admin/stats/usage-series",
        params={"granularity": "day", "username": "alice"},
        headers=headers,
    )
    assert usage_resp.status_code == 200
    usage = usage_resp.json()["data"]
    assert usage["ai"]["total_records"] == 1
    assert usage["workflow"]["total_records"] == 1
    assert "alice-model" in usage["ai"]["names"]
    assert "bob-model" not in usage["ai"]["names"]


@pytest.mark.asyncio
async def test_xhs_published_posts_return_aware_iso(client):
    await _seed_base_users()
    published_cst = _now_cst_naive().replace(hour=13, minute=57, second=0, microsecond=0)

    async with async_session() as db:
        db.add(XHSEnvironment(id=101, shop_id="shop_101", account_name="账号A", status="active"))
        db.add(
            XHSPost(
                id=301,
                user_id=2,
                environment_id=101,
                title="alice-post",
                content="content",
                image_urls=["/tmp/a.jpg"],
                tags=["tag"],
                status="success",
                feed_id="feed_301",
                published_at=cst_naive_to_utc_naive(published_cst),
            )
        )
        await db.commit()

    resp = await client.get("/api/v1/admin/stats/xhs-published-posts", headers=make_auth_headers(1))
    assert resp.status_code == 200
    payload = resp.json()["data"]
    assert payload["total"] == 1
    assert payload["items"][0]["published_at"].endswith("Z")


@pytest.mark.asyncio
async def test_xhs_publish_series_and_list_include_manual_synced_posts(client):
    await _seed_base_users()
    published_cst = _now_cst_naive().replace(hour=14, minute=0, second=0, microsecond=0)
    manual_cst = published_cst - timedelta(hours=2)

    async with async_session() as db:
        db.add(XHSEnvironment(id=101, shop_id="shop_101", account_name="账号A", status="active"))
        await db.flush()
        db.add(UserXHSEnvironment(user_id=2, environment_id=101))
        db.add_all([
            XHSPost(
                id=301,
                user_id=2,
                environment_id=101,
                title="auto-post",
                content="content",
                image_urls=["/tmp/a.jpg"],
                tags=["tag"],
                status="success",
                feed_id="feed_auto",
                published_at=cst_naive_to_utc_naive(published_cst),
            ),
            XHSAccountNote(
                id=401,
                environment_id=101,
                account_name="账号A",
                profile_nickname="账号A",
                feed_id="feed_auto",
                title="duplicate-auto-note",
                published_at=cst_naive_to_utc_naive(published_cst),
                first_synced_at=cst_naive_to_utc_naive(published_cst + timedelta(minutes=10)),
            ),
            XHSAccountNote(
                id=402,
                environment_id=101,
                account_name="账号A",
                profile_nickname="账号A",
                feed_id="feed_manual",
                title="manual-note",
                published_at=cst_naive_to_utc_naive(manual_cst),
                first_synced_at=cst_naive_to_utc_naive(manual_cst + timedelta(minutes=10)),
            ),
        ])
        await db.commit()

    headers = make_auth_headers(1)
    series_resp = await client.get(
        "/api/v1/admin/stats/xhs-publish-series",
        params={"granularity": "day", "username": "alice"},
        headers=headers,
    )
    assert series_resp.status_code == 200
    series_payload = series_resp.json()["data"]
    assert series_payload["total_records"] == 2
    assert sum(series_payload["series"]["自动工具发布"]) == 1
    assert sum(series_payload["series"]["自主发布"]) == 1

    list_resp = await client.get(
        "/api/v1/admin/stats/xhs-published-posts",
        params={"username": "alice"},
        headers=headers,
    )
    assert list_resp.status_code == 200
    list_payload = list_resp.json()["data"]
    assert list_payload["total"] == 2
    assert {item["source_label"] for item in list_payload["items"]} == {"自动工具发布", "自主发布"}
    manual_item = next(item for item in list_payload["items"] if item["source_label"] == "自主发布")
    assert manual_item["title"] == "manual-note"
    assert manual_item["username"] == "alice"
    assert manual_item["published_at"].endswith("Z")


@pytest.mark.asyncio
async def test_unknown_username_returns_zero_payloads(client):
    await _seed_base_users()
    headers = make_auth_headers(1)

    overview_resp = await client.get("/api/v1/admin/stats/overview", params={"username": "nobody"}, headers=headers)
    assert overview_resp.status_code == 200
    overview = overview_resp.json()["data"]
    assert overview["user_count"] == 0
    assert overview["ai_task_count"] == 0

    active_resp = await client.get("/api/v1/admin/stats/active-tasks", params={"username": "nobody"}, headers=headers)
    assert active_resp.status_code == 200
    assert active_resp.json()["data"] == []

    rankings_resp = await client.get("/api/v1/admin/stats/rankings", params={"username": "nobody"}, headers=headers)
    assert rankings_resp.status_code == 200
    rankings = rankings_resp.json()["data"]
    assert rankings["storage_ranking"] == []
    assert rankings["workflow_ranking"] == []
    assert rankings["active_users"] == []

    usage_resp = await client.get(
        "/api/v1/admin/stats/usage-series",
        params={"granularity": "hour", "username": "nobody"},
        headers=headers,
    )
    assert usage_resp.status_code == 200
    usage = usage_resp.json()["data"]
    assert usage["ai"]["total_records"] == 0
    assert usage["ai"]["names"] == []
    assert usage["workflow"]["total_records"] == 0
