"""Additional branch coverage for the administrative statistics dashboard."""

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
from app.utils.timezone import cst_naive_to_utc_naive
from tests.conftest import make_auth_headers


CST = timezone(timedelta(hours=8))


def _now_cst() -> datetime:
    return datetime.now(CST).replace(tzinfo=None)


async def _seed_users() -> None:
    async with async_session() as db:
        db.add_all(
            [
                User(id=1, username="admin", email="admin@stats.test", hashed_password="x", role="admin"),
                User(id=2, username="operator", email="operator@stats.test", hashed_password="x", role="viewer"),
            ]
        )
        await db.commit()


@pytest.mark.asyncio
async def test_overview_ai_trend_storage_and_rankings_cover_all_statuses(client):
    await _seed_users()
    now_cst = _now_cst()
    now_utc = cst_naive_to_utc_naive(now_cst - timedelta(minutes=5))

    async with async_session() as db:
        workflow = DifyWorkflowConfig(
            api_key="stats-key",
            base_url="https://workflow.test",
            app_name="统计工作流",
            app_type="workflow",
            created_by=1,
        )
        db.add(workflow)
        await db.flush()
        db.add_all(
            [
                Project(user_id=2, name="统计项目"),
                Material(name="图片", type="image", url="/image.png", created_by=2, file_size=2 * 1024 * 1024),
                Material(name="视频", type="video", url="/video.mp4", created_by=2, file_size=None),
                AITask(
                    user_id=2,
                    model_name="image-model",
                    prompt="ok",
                    status="completed",
                    elapsed_seconds=2.5,
                    created_at=now_utc,
                ),
                AITask(
                    user_id=2,
                    model_name="image-model",
                    prompt="bad",
                    status="failed",
                    elapsed_seconds=None,
                    created_at=now_utc,
                ),
                AITask(
                    user_id=2,
                    model_name="other-model",
                    prompt="pending",
                    status="processing",
                    elapsed_seconds=1,
                    created_at=now_utc,
                ),
                DifyTask(workflow_id=workflow.id, user_id=2, status="running", created_at=now_cst),
                DifyRunLog(workflow_id=workflow.id, user_id=2, status="succeeded", started_at=now_cst),
                DifyRunLog(workflow_id=workflow.id, user_id=2, status="failed", started_at=now_cst),
                DifyRunLog(workflow_id=workflow.id, user_id=2, status="running", started_at=now_cst),
                DifyRunLog(workflow_id=workflow.id, user_id=2, status="stopped", started_at=now_cst),
                DifyRunLog(workflow_id=workflow.id, user_id=2, status="unknown", started_at=now_cst),
            ]
        )
        await db.commit()

    headers = make_auth_headers(1)
    overview = (await client.get("/api/v1/admin/stats/overview", headers=headers)).json()["data"]
    assert overview["user_count"] == 2
    assert overview["project_count"] == 1
    assert overview["material_count"] == 2
    assert overview["ai_task_count"] == 3
    assert overview["ai_tasks_today"] == 3
    assert overview["ai_success_rate_today"] == 66.7

    trend = (await client.get("/api/v1/admin/stats/ai-trend", params={"days": 2}, headers=headers)).json()["data"]
    model = next(row for row in trend["ai_models"] if row["model"] == "image-model")
    assert model["total"] == 2
    assert model["success"] == 1
    assert model["failed"] == 1
    assert model["avg_seconds"] == 2.5
    assert {row["date"] for row in trend["wf_daily"]}

    storage = (await client.get("/api/v1/admin/stats/storage", headers=headers)).json()["data"]
    assert storage["total_mb"] == 2
    assert {row["type"] for row in storage["by_type"]} == {"image", "video"}

    rankings = (await client.get("/api/v1/admin/stats/rankings", headers=headers)).json()["data"]
    assert rankings["storage_ranking"][0]["username"] == "operator"
    assert rankings["workflow_ranking"][0] == {"name": "统计工作流", "count": 1}
    assert rankings["active_users"][0]["task_count"] == 3


@pytest.mark.asyncio
@pytest.mark.parametrize(("granularity", "expected_count"), [("day", 14), ("week", 8)])
async def test_usage_series_day_and_week_include_workflow_and_unknown_model(
    client,
    granularity,
    expected_count,
):
    await _seed_users()
    now_cst = _now_cst()
    created_cst = now_cst - timedelta(days=2)
    async with async_session() as db:
        db.add_all(
            [
                AITask(
                    user_id=2,
                    model_name=" ",
                    prompt="series",
                    status="completed",
                    created_at=cst_naive_to_utc_naive(created_cst),
                ),
                # SQLite does not enforce this model's logical FK. The orphaned
                # task exercises the API's "unnamed workflow" outer-join path.
                DifyTask(workflow_id=999, user_id=2, status="completed", created_at=created_cst),
            ]
        )
        await db.commit()

    response = await client.get(
        "/api/v1/admin/stats/usage-series",
        params={"granularity": granularity},
        headers=make_auth_headers(1),
    )
    assert response.status_code == 200
    data = response.json()["data"]
    assert len(data["buckets"]) == expected_count
    assert data["ai"]["names"] == ["unknown"]
    assert data["ai"]["raw_model_counts"] == {"(empty)": 1}
    assert data["workflow"]["names"] == ["未命名工作流"]
    assert data["workflow"]["total_records"] == 1
    if granularity == "week":
        assert "-" in data["buckets"][0]["label"]


@pytest.mark.asyncio
async def test_xhs_publish_hour_week_and_manual_owner_resolution(client):
    await _seed_users()
    now_cst = _now_cst().replace(minute=10, second=0, microsecond=0)
    published_utc = cst_naive_to_utc_naive(now_cst)

    async with async_session() as db:
        db.add_all(
            [
                XHSEnvironment(id=201, shop_id="shop-201", account_name="账号甲", status="active"),
                XHSEnvironment(id=202, shop_id="shop-202", account_name="账号乙", status="active"),
            ]
        )
        await db.flush()
        db.add(UserXHSEnvironment(user_id=2, environment_id=201))
        db.add_all(
            [
                XHSPost(
                    id=501,
                    user_id=2,
                    environment_id=201,
                    title="自动发布",
                    content="content",
                    image_urls=[],
                    tags=[],
                    status="success",
                    feed_id="auto-feed",
                    published_at=published_utc,
                ),
                XHSAccountNote(
                    id=601,
                    environment_id=201,
                    account_name="账号甲",
                    profile_nickname="账号甲",
                    feed_id="manual-feed-a",
                    title="自主发布甲",
                    published_at=published_utc,
                    first_synced_at=published_utc,
                ),
                XHSAccountNote(
                    id=602,
                    environment_id=202,
                    account_name="账号乙",
                    profile_nickname="账号乙",
                    feed_id="manual-feed-b",
                    title="自主发布乙",
                    published_at=published_utc,
                    first_synced_at=published_utc,
                ),
            ]
        )
        await db.commit()

    headers = make_auth_headers(1)
    hour = (
        await client.get(
            "/api/v1/admin/stats/xhs-publish-series",
            params={"granularity": "hour"},
            headers=headers,
        )
    ).json()["data"]
    assert len(hour["buckets"]) == 24
    assert hour["total_records"] == 3

    week = (
        await client.get(
            "/api/v1/admin/stats/xhs-publish-series",
            params={"granularity": "week"},
            headers=headers,
        )
    ).json()["data"]
    assert len(week["buckets"]) == 8
    assert week["total_records"] == 3

    all_posts = (
        await client.get(
            "/api/v1/admin/stats/xhs-published-posts",
            params={"page": 1, "limit": 10},
            headers=headers,
        )
    ).json()["data"]
    assert all_posts["total"] == 3
    manual_a = next(item for item in all_posts["items"] if item["title"] == "自主发布甲")
    manual_b = next(item for item in all_posts["items"] if item["title"] == "自主发布乙")
    assert manual_a["username"] == "operator"
    assert manual_b["username"] == "自主发布"

    filtered = (
        await client.get(
            "/api/v1/admin/stats/xhs-published-posts",
            params={"username": "operator"},
            headers=headers,
        )
    ).json()["data"]
    assert filtered["total"] == 2
    assert {item["title"] for item in filtered["items"]} == {"自动发布", "自主发布甲"}
