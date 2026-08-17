"""XHS publish + post management flow tests."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

import app.api.v1.xhs as xhs_api_module
from app.db.session import async_session
from app.models.user import User
from app.models.user_xhs_env import UserXHSEnvironment
from app.models.xhs_account_note import XHSAccountNote
from app.models.xhs_creator_sync_row import XHSCreatorSyncRow
from app.models.xhs_environment import XHSEnvironment
from app.models.xhs_post import XHSPost
from app.models.xhs_report import XHSReportDaily
from app.models.copywriting import Copywriting
from app.services.request_queue import RateLimitedQueue, xhs_publish_queue
import app.services.xhs_service as xhs_service_module
from app.services.xhs_service import XHSService, SyncJobCancelled
from tests.conftest import make_auth_headers
from app.utils.timezone import utc_now_naive


async def _async_true() -> bool:
    return True


async def _async_ws() -> str:
    return "ws://fake-browser"


async def _seed_users_and_envs() -> None:
    async with async_session() as db:
        db.add_all([
            User(id=1, username="admin", email="admin@test.com", hashed_password="x", role="admin"),
            User(id=2, username="alice", email="alice@test.com", hashed_password="x", role="viewer"),
            User(id=3, username="bob", email="bob@test.com", hashed_password="x", role="viewer"),
        ])
        db.add_all([
            XHSEnvironment(id=101, shop_id="shop_101", account_name="账号A", status="active"),
            XHSEnvironment(id=102, shop_id="shop_102", account_name="测试2", status="active", is_sync_runner=True),
        ])
        await db.flush()
        db.add(UserXHSEnvironment(user_id=2, environment_id=101))
        await db.commit()


async def _seed_posts() -> None:
    async with async_session() as db:
        db.add_all([
            XHSPost(
                id=201,
                user_id=2,
                environment_id=101,
                title="alice-success",
                content="c1",
                image_urls=["/tmp/a.jpg"],
                tags=["t1"],
                status="success",
                feed_id="feed_a",
                xsec_token="token_a",
            ),
            XHSPost(
                id=202,
                user_id=2,
                environment_id=101,
                title="alice-failed",
                content="c2",
                image_urls=["/tmp/b.jpg"],
                tags=["t2"],
                status="failed",
            ),
            XHSPost(
                id=203,
                user_id=3,
                environment_id=102,
                title="bob-success",
                content="c3",
                image_urls=["/tmp/c.jpg"],
                tags=["t3"],
                status="success",
                feed_id="feed_b",
                xsec_token="token_b",
            ),
        ])
        await db.commit()


def _patch_publish_runtime(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_allocate_free_port(self: XHSService) -> int:
        return 18061

    async def fake_resolve_publish_image_paths(self: XHSService, image_paths: list[str]) -> list[str]:
        return image_paths

    async def fake_start_mcp(self: XHSService, ws_url: str, port: int):
        return 12345

    async def fake_wait_mcp_ready(self: XHSService, api_base=None, timeout: int = 15):
        return None

    async def fake_stop_mcp(self: XHSService, pid: int):
        return None

    monkeypatch.setattr(XHSService, "_allocate_free_port", fake_allocate_free_port)
    monkeypatch.setattr(XHSService, "_resolve_publish_image_paths", fake_resolve_publish_image_paths)
    monkeypatch.setattr(XHSService, "_start_mcp", fake_start_mcp)
    monkeypatch.setattr(XHSService, "_wait_mcp_ready", fake_wait_mcp_ready)
    monkeypatch.setattr(XHSService, "_stop_mcp", fake_stop_mcp)


@pytest.mark.asyncio
async def test_list_environments_scope_for_admin_and_viewer(client):
    await _seed_users_and_envs()
    async with async_session() as db:
        env = await db.get(XHSEnvironment, 101)
        assert env is not None
        env.sync_cloud_session_id = "session_101"
        env.sync_cloud_api_key = "api_key_101"
        env.sync_cloud_update_config = '{"flag":2}'
        env.sync_browser_start_config = '{"headless":"1"}'
        await db.commit()

    viewer_resp = await client.get("/api/v1/xhs/environments", headers=make_auth_headers(2))
    assert viewer_resp.status_code == 200
    viewer_envs = viewer_resp.json()["data"]
    assert [item["id"] for item in viewer_envs] == [101]
    assert viewer_envs[0]["sync_cloud_session_id"] is None
    assert viewer_envs[0]["sync_cloud_api_key"] is None
    assert viewer_envs[0]["sync_cloud_update_config"] is None
    assert viewer_envs[0]["sync_browser_start_config"] is None

    admin_resp = await client.get("/api/v1/xhs/environments", headers=make_auth_headers(1))
    assert admin_resp.status_code == 200
    admin_envs = admin_resp.json()["data"]
    assert {item["id"] for item in admin_envs} == {101, 102}
    admin_env = next(item for item in admin_envs if item["id"] == 101)
    assert admin_env["sync_cloud_session_id"] == "session_101"
    assert admin_env["sync_cloud_api_key"] == "api_key_101"


@pytest.mark.asyncio
async def test_admin_environment_auto_sync_when_empty(client, monkeypatch):
    async with async_session() as db:
        db.add(User(id=1, username="admin", email="admin@test.com", hashed_password="x", role="admin"))
        await db.commit()

    async def fake_sync(self: XHSService) -> int:
        self.db.add(XHSEnvironment(shop_id="shop_new", account_name="新账号", status="active"))
        await self.db.commit()
        return 1

    monkeypatch.setattr(XHSService, "sync_environments_from_yundeng", fake_sync)

    resp = await client.get("/api/v1/xhs/environments", headers=make_auth_headers(1))
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["code"] == 0
    assert len(payload["data"]) == 1
    assert payload["data"][0]["shop_id"] == "shop_new"


@pytest.mark.asyncio
async def test_publish_rejects_nonexistent_environment(client):
    await _seed_users_and_envs()

    resp = await client.post(
        "/api/v1/xhs/publish",
        headers=make_auth_headers(2),
        json={
            "environment_id": 999,
            "title": "test",
            "content": "test",
            "image_paths": ["/tmp/a.jpg"],
        },
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_publish_rejects_unassigned_environment_for_viewer(client):
    await _seed_users_and_envs()

    resp = await client.post(
        "/api/v1/xhs/publish",
        headers=make_auth_headers(2),
        json={
            "environment_id": 102,
            "title": "test",
            "content": "test",
            "image_paths": ["/tmp/a.jpg"],
        },
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload,err_part",
    [
        (
            {
                "environment_id": 101,
                "title": "   ",
                "content": "正文",
                "image_paths": ["/tmp/a.jpg"],
            },
            "标题不能为空",
        ),
        (
            {
                "environment_id": 101,
                "title": "x" * 21,
                "content": "正文",
                "image_paths": ["/tmp/a.jpg"],
            },
            "标题不能超过20字",
        ),
        (
            {
                "environment_id": 101,
                "title": "合法标题",
                "content": "   ",
                "image_paths": ["/tmp/a.jpg"],
            },
            "正文不能为空",
        ),
        (
            {
                "environment_id": 101,
                "title": "合法标题",
                "content": "正文",
                "image_paths": [],
            },
            "请至少上传1张图片",
        ),
    ],
)
async def test_publish_request_validation(client, payload, err_part):
    await _seed_users_and_envs()

    resp = await client.post(
        "/api/v1/xhs/publish",
        headers=make_auth_headers(2),
        json=payload,
    )
    assert resp.status_code == 422
    assert err_part in str(resp.json())


@pytest.mark.asyncio
async def test_publish_success_returns_post_payload(client, monkeypatch):
    await _seed_users_and_envs()

    async def fake_publish(
        self: XHSService,
        user,
        env,
        title,
        content,
        image_paths,
        tags=None,
        ai_origin_type="manual",
        is_original=False,
        visibility="公开可见",
        scheduled_at=None,
    ):
        post = XHSPost(
            user_id=user.id,
            environment_id=env.id,
            title=title,
            content=content,
            image_urls=image_paths,
            tags=tags or [],
            status="success",
            feed_id="feed_x",
            xsec_token="token_x",
            published_at=utc_now_naive(),
        )
        self.db.add(post)
        await self.db.commit()
        await self.db.refresh(post)
        return post

    monkeypatch.setattr(XHSService, "publish", fake_publish)

    resp = await client.post(
        "/api/v1/xhs/publish",
        headers=make_auth_headers(2),
        json={
            "environment_id": 101,
            "title": "发布成功",
            "content": "正文",
            "image_paths": ["/tmp/a.jpg", "/tmp/b.jpg"],
            "tags": ["tag1", "tag2"],
        },
    )
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["code"] == 0
    assert payload["data"]["status"] == "success"
    assert payload["data"]["feed_id"] == "feed_x"


@pytest.mark.asyncio
async def test_publish_immediate_returns_publishing_and_schedules_background_job(client, monkeypatch):
    await _seed_users_and_envs()

    scheduled: dict[str, object] = {}

    async def fake_resolve_paths(self: XHSService, image_paths: list[str]) -> list[str]:
        raise AssertionError("immediate publish should not resolve image paths before returning")

    def fake_schedule_background_publish(
        self: XHSService,
        post_id: int,
        env_id: int,
        title: str,
        content: str,
        image_paths: list[str],
        tags: list[str],
        ai_origin_type: str,
        is_original: bool,
        visibility: str,
    ) -> None:
        scheduled.update({
            "post_id": post_id,
            "env_id": env_id,
            "title": title,
            "content": content,
            "image_paths": image_paths,
            "tags": tags,
            "ai_origin_type": ai_origin_type,
            "is_original": is_original,
            "visibility": visibility,
        })

    monkeypatch.setattr(XHSService, "_resolve_publish_image_paths", fake_resolve_paths)
    monkeypatch.setattr(XHSService, "_schedule_background_publish", fake_schedule_background_publish)

    resp = await client.post(
        "/api/v1/xhs/publish",
        headers=make_auth_headers(2),
        json={
            "environment_id": 101,
            "title": "立即发布",
            "content": "正文 #话题",
            "image_paths": ["/tmp/a.jpg"],
            "tags": ["已有标签"],
        },
    )
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["code"] == 0
    assert payload["message"] == "已提交发布任务"
    assert payload["data"]["status"] == "publishing"
    assert scheduled["env_id"] == 101
    assert scheduled["title"] == "立即发布"
    assert scheduled["image_paths"] == ["/tmp/a.jpg"]


@pytest.mark.asyncio
async def test_publish_runtime_error_returns_business_failure(client, monkeypatch):
    await _seed_users_and_envs()

    async def fake_publish(*args, **kwargs):
        raise RuntimeError("无法获取环境 shop_101 的浏览器连接")

    monkeypatch.setattr(XHSService, "publish", fake_publish)

    resp = await client.post(
        "/api/v1/xhs/publish",
        headers=make_auth_headers(2),
        json={
            "environment_id": 101,
            "title": "发布失败",
            "content": "正文",
            "image_paths": ["/tmp/a.jpg"],
        },
    )
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["code"] == 1
    assert "无法获取环境" in payload["message"]


@pytest.mark.asyncio
async def test_publish_without_feed_id_returns_failed_status(client, monkeypatch):
    await _seed_users_and_envs()

    async def fake_publish(
        self: XHSService,
        user,
        env,
        title,
        content,
        image_paths,
        tags=None,
        ai_origin_type="manual",
        is_original=False,
        visibility="公开可见",
        scheduled_at=None,
    ):
        post = XHSPost(
            user_id=user.id,
            environment_id=env.id,
            title=title,
            content=content,
            image_urls=image_paths,
            tags=tags or [],
            status="failed",
            feed_id=None,
            xsec_token=None,
            published_at=utc_now_naive(),
        )
        self.db.add(post)
        await self.db.commit()
        await self.db.refresh(post)
        return post

    monkeypatch.setattr(XHSService, "publish", fake_publish)

    resp = await client.post(
        "/api/v1/xhs/publish",
        headers=make_auth_headers(2),
        json={
            "environment_id": 101,
            "title": "发布中",
            "content": "正文",
            "image_paths": ["/tmp/a.jpg"],
        },
    )
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["code"] == 1
    assert payload["message"] == "发布失败，请检查环境或稍后重试"
    assert payload["data"]["status"] == "failed"
    assert payload["data"]["feed_id"] is None


@pytest.mark.asyncio
async def test_publish_future_time_returns_scheduled(client, monkeypatch):
    await _seed_users_and_envs()
    captured: dict[str, datetime | None] = {"scheduled_at": None}

    async def fake_publish(
        self: XHSService,
        user,
        env,
        title,
        content,
        image_paths,
        tags=None,
        ai_origin_type="manual",
        is_original=False,
        visibility="公开可见",
        scheduled_at=None,
    ):
        captured["scheduled_at"] = scheduled_at
        post = XHSPost(
            user_id=user.id,
            environment_id=env.id,
            title=title,
            content=content,
            image_urls=image_paths,
            tags=tags or [],
            status="scheduled",
            scheduled_at=scheduled_at,
        )
        self.db.add(post)
        await self.db.commit()
        await self.db.refresh(post)
        return post

    monkeypatch.setattr(XHSService, "publish", fake_publish)
    future_aware = datetime.now(timezone.utc) + timedelta(hours=2)

    resp = await client.post(
        "/api/v1/xhs/publish",
        headers=make_auth_headers(2),
        json={
            "environment_id": 101,
            "title": "定时发布",
            "content": "正文",
            "image_paths": ["/tmp/a.jpg"],
            "scheduled_at": future_aware.isoformat().replace("+00:00", "Z"),
        },
    )
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["code"] == 0
    assert payload["message"] == "定时发布已创建"
    assert payload["data"]["status"] == "scheduled"
    assert captured["scheduled_at"] is not None
    assert captured["scheduled_at"] == future_aware
    assert payload["data"]["scheduled_at"] == future_aware.isoformat().replace("+00:00", "Z")


@pytest.mark.asyncio
async def test_publish_scheduled_time_too_close_returns_400(client):
    await _seed_users_and_envs()
    near = datetime.now(timezone.utc) + timedelta(seconds=30)

    resp = await client.post(
        "/api/v1/xhs/publish",
        headers=make_auth_headers(2),
        json={
            "environment_id": 101,
            "title": "定时发布太近",
            "content": "正文",
            "image_paths": ["/tmp/a.jpg"],
            "scheduled_at": near.isoformat().replace("+00:00", "Z"),
        },
    )
    assert resp.status_code == 400
    assert "至少 1 分钟" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_posts_listing_and_status_filter(client):
    await _seed_users_and_envs()
    await _seed_posts()

    viewer_resp = await client.get(
        "/api/v1/xhs/posts",
        headers=make_auth_headers(2),
        params={"status": "success"},
    )
    assert viewer_resp.status_code == 200
    viewer_data = viewer_resp.json()["data"]
    assert viewer_data["total"] == 1
    assert viewer_data["items"][0]["title"] == "alice-success"
    assert viewer_data["items"][0]["created_at"].endswith("Z")

    admin_resp = await client.get("/api/v1/xhs/posts", headers=make_auth_headers(1))
    assert admin_resp.status_code == 200
    admin_data = admin_resp.json()["data"]
    assert admin_data["total"] == 3


@pytest.mark.asyncio
async def test_post_detail_enforces_owner_scope(client):
    await _seed_users_and_envs()
    await _seed_posts()

    own_resp = await client.get("/api/v1/xhs/posts/201", headers=make_auth_headers(2))
    assert own_resp.status_code == 200

    other_resp = await client.get("/api/v1/xhs/posts/203", headers=make_auth_headers(2))
    assert other_resp.status_code == 404


@pytest.mark.asyncio
async def test_post_delete_only_for_unpublished_records(client):
    await _seed_users_and_envs()
    await _seed_posts()

    failed_delete = await client.delete("/api/v1/xhs/posts/202", headers=make_auth_headers(2))
    assert failed_delete.status_code == 200
    assert failed_delete.json()["code"] == 0
    assert failed_delete.json()["data"]["post_id"] == 202

    deleted_get = await client.get("/api/v1/xhs/posts/202", headers=make_auth_headers(2))
    assert deleted_get.status_code == 404

    success_delete = await client.delete("/api/v1/xhs/posts/201", headers=make_auth_headers(2))
    assert success_delete.status_code == 400
    assert "已发布帖子暂不支持管理编辑/删除" in success_delete.json()["detail"]


@pytest.mark.asyncio
async def test_update_post_for_scheduled_and_success(client):
    await _seed_users_and_envs()
    await _seed_posts()
    async with async_session() as db:
        db.add(
            XHSPost(
                id=205,
                user_id=2,
                environment_id=101,
                title="to-schedule",
                content="old",
                image_urls=["/tmp/a.jpg"],
                tags=[],
                status="scheduled",
                scheduled_at=utc_now_naive() + timedelta(hours=2),
            )
        )
        await db.commit()

    before_resp = await client.get("/api/v1/xhs/posts/205", headers=make_auth_headers(2))
    before_payload = before_resp.json()["data"]
    assert before_payload["scheduled_at"].endswith("Z")

    edit_scheduled = await client.patch(
        "/api/v1/xhs/posts/205",
        headers=make_auth_headers(2),
        json={
            "title": "to-schedule-new",
            "content": "new content #标签",
            "scheduled_at": before_payload["scheduled_at"],
        },
    )
    assert edit_scheduled.status_code == 200
    payload = edit_scheduled.json()
    assert payload["code"] == 0
    assert payload["data"]["title"] == "to-schedule-new"
    assert payload["data"]["status"] == "scheduled"
    assert payload["data"]["scheduled_at"] == before_payload["scheduled_at"]

    edit_success = await client.patch(
        "/api/v1/xhs/posts/201",
        headers=make_auth_headers(2),
        json={"title": "alice-success-new", "content": "success edited"},
    )
    assert edit_success.status_code == 400
    assert "已发布帖子暂不支持管理编辑/删除" in edit_success.json()["detail"]




@pytest.mark.asyncio
async def test_cancel_and_publish_now_for_scheduled(client, monkeypatch):
    await _seed_users_and_envs()
    async with async_session() as db:
        db.add(
            XHSPost(
                id=206,
                user_id=2,
                environment_id=101,
                title="to-run",
                content="to-run",
                image_urls=["/tmp/a.jpg"],
                tags=[],
                status="scheduled",
                scheduled_at=utc_now_naive() + timedelta(hours=2),
            )
        )
        db.add(
            XHSPost(
                id=207,
                user_id=2,
                environment_id=101,
                title="to-cancel",
                content="to-cancel",
                image_urls=["/tmp/a.jpg"],
                tags=[],
                status="scheduled",
                scheduled_at=utc_now_naive() + timedelta(hours=2),
            )
        )
        await db.commit()

    async def fake_run_now(self: XHSService, post: XHSPost):
        post.status = "success"
        post.feed_id = "feed_207"
        post.xsec_token = "token_207"
        await self.db.commit()
        await self.db.refresh(post)
        return post

    monkeypatch.setattr(XHSService, "run_scheduled_post_now", fake_run_now)

    run_resp = await client.post("/api/v1/xhs/posts/206/publish-now", headers=make_auth_headers(2))
    assert run_resp.status_code == 200
    run_payload = run_resp.json()
    assert run_payload["code"] == 0
    assert run_payload["data"]["status"] == "success"

    cancel_resp = await client.post("/api/v1/xhs/posts/207/cancel", headers=make_auth_headers(2))
    assert cancel_resp.status_code == 200
    cancel_payload = cancel_resp.json()
    assert cancel_payload["code"] == 0
    assert cancel_payload["data"]["status"] == "cancelled"


@pytest.mark.asyncio
async def test_publish_now_runtime_error_returns_code_one_with_failed_status(client, monkeypatch):
    await _seed_users_and_envs()
    async with async_session() as db:
        db.add(
            XHSPost(
                id=209,
                user_id=2,
                environment_id=101,
                title="to-run-runtime-error",
                content="to-run-runtime-error",
                image_urls=["/tmp/a.jpg"],
                tags=[],
                status="scheduled",
                scheduled_at=utc_now_naive() + timedelta(hours=2),
            )
        )
        await db.commit()

    async def fake_run_now(self: XHSService, post: XHSPost):
        post.status = "failed"
        await self.db.commit()
        raise RuntimeError("无法获取环境 shop_101 的浏览器连接")

    monkeypatch.setattr(XHSService, "run_scheduled_post_now", fake_run_now)

    resp = await client.post("/api/v1/xhs/posts/209/publish-now", headers=make_auth_headers(2))
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["code"] == 1
    assert payload["data"]["status"] == "failed"
    assert "无法获取环境" in payload["message"]


@pytest.mark.asyncio
async def test_posts_listing_keeps_publishing_status(client):
    await _seed_users_and_envs()
    await _seed_posts()
    async with async_session() as db:
        db.add(
            XHSPost(
                id=204,
                user_id=2,
                environment_id=101,
                title="legacy-publishing",
                content="legacy",
                image_urls=["/tmp/z.jpg"],
                tags=[],
                status="publishing",
            )
        )
        await db.commit()

    resp = await client.get("/api/v1/xhs/posts", headers=make_auth_headers(2))
    assert resp.status_code == 200
    items = resp.json()["data"]["items"]
    target = next(item for item in items if item["id"] == 204)
    assert target["status"] == "publishing"


@pytest.mark.asyncio
async def test_sync_stats_returns_failure_message_when_sync_failed(client, monkeypatch):
    await _seed_users_and_envs()
    await _seed_posts()

    async def fake_sync_single_post_verbose(self: XHSService, post: XHSPost):
        return type("R", (), {"success": False, "reason": "feed_detail_http_error", "message": "帖子详情接口异常（HTTP 500）"})()

    monkeypatch.setattr(XHSService, "sync_single_post_verbose", fake_sync_single_post_verbose)

    resp = await client.get("/api/v1/xhs/posts/201/stats", headers=make_auth_headers(2))
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["code"] == 1
    assert payload["message"] == "帖子详情接口异常（HTTP 500）"
    assert payload["data"]["status"] == "success"
    assert payload["data"]["sync_reason"] == "feed_detail_http_error"


@pytest.mark.asyncio
async def test_sync_stats_success_path_updates_payload(client, monkeypatch):
    await _seed_users_and_envs()
    await _seed_posts()

    async def fake_sync_single_post_verbose(self: XHSService, post: XHSPost):
        post.like_count = 10
        post.comment_count = 8
        post.collect_count = 6
        post.share_count = 4
        post.view_count = 100
        post.last_synced_at = utc_now_naive()
        await self.db.commit()
        return type("R", (), {"success": True, "reason": "ok", "message": "同步成功"})()

    monkeypatch.setattr(XHSService, "sync_single_post_verbose", fake_sync_single_post_verbose)

    resp = await client.get("/api/v1/xhs/posts/201/stats", headers=make_auth_headers(2))
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["code"] == 0
    assert payload["message"] == "同步成功"
    assert payload["data"]["like_count"] == 10
    assert payload["data"]["view_count"] == 100
    assert payload["data"]["sync_reason"] == "ok"
    assert payload["data"]["last_synced_at"].endswith("Z")


@pytest.mark.asyncio
async def test_admin_sync_all_requires_admin_role(client):
    await _seed_users_and_envs()

    resp = await client.post("/api/v1/admin/xhs/sync-all", headers=make_auth_headers(2))
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_admin_assign_and_unassign_flow(client):
    await _seed_users_and_envs()
    async with async_session() as db:
        target_user = await db.get(User, 3)
        assert target_user is not None
        target_user.role = "xhs_ops"
        await db.commit()

    assign_resp = await client.post(
        "/api/v1/admin/xhs/assign",
        headers=make_auth_headers(1),
        json={"user_id": 3, "environment_id": 102},
    )
    assert assign_resp.status_code == 200
    assert assign_resp.json()["data"]["success"] is True

    list_resp = await client.get("/api/v1/admin/xhs/assignments", headers=make_auth_headers(1))
    assert list_resp.status_code == 200
    pairs = {(item["user_id"], item["environment_id"]) for item in list_resp.json()["data"]}
    assert (3, 102) in pairs

    unassign_resp = await client.post(
        "/api/v1/admin/xhs/unassign",
        headers=make_auth_headers(1),
        json={"user_id": 3, "environment_id": 102},
    )
    assert unassign_resp.status_code == 200

    list_resp2 = await client.get("/api/v1/admin/xhs/assignments", headers=make_auth_headers(1))
    pairs2 = {(item["user_id"], item["environment_id"]) for item in list_resp2.json()["data"]}
    assert (3, 102) not in pairs2


@pytest.mark.asyncio
async def test_admin_assign_nonexistent_ids_returns_404(client):
    await _seed_users_and_envs()

    resp = await client.post(
        "/api/v1/admin/xhs/assign",
        headers=make_auth_headers(1),
        json={"user_id": 9999, "environment_id": 8888},
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_sync_existing_account_note_stats_unpublished_only_uses_selected_scrape_env(client, monkeypatch):
    await _seed_users_and_envs()
    async with async_session() as db:
        db.add_all([
            XHSAccountNote(
                id=301,
                environment_id=101,
                account_name="账号A",
                feed_id="feed_301",
                title="未同步",
                ai_origin_type="manual",
                published_at=None,
                sort_index=0,
            ),
            XHSAccountNote(
                id=302,
                environment_id=101,
                account_name="账号A",
                feed_id="feed_302",
                title="仅缺发布时间",
                content="这里已经有正文",
                ai_origin_type="manual",
                published_at=None,
                sort_index=1,
            ),
            XHSAccountNote(
                id=303,
                environment_id=101,
                account_name="账号A",
                feed_id="feed_303",
                title="仅缺正文",
                ai_origin_type="manual",
                content="",
                published_at=utc_now_naive(),
                detail_synced_at=utc_now_naive(),
                sort_index=2,
            ),
            XHSAccountNote(
                id=304,
                environment_id=101,
                account_name="账号A",
                feed_id="feed_304",
                title="已同步",
                ai_origin_type="manual",
                published_at=utc_now_naive(),
                detail_synced_at=utc_now_naive(),
                content="这里有正文",
                sort_index=3,
            ),
        ])
        await db.commit()

    seen_scrape_env_ids: list[int] = []
    synced_note_ids: list[int] = []

    async def fake_acquire_ready_sync_browser_ws(self: XHSService, scrape_env: XHSEnvironment):
        seen_scrape_env_ids.append(scrape_env.id)
        return "ws://fake-browser"

    async def fake_start_mcp(self: XHSService, ws_url: str, port: int):
        return 12345

    async def fake_allocate_free_port(self: XHSService) -> int:
        return 18061

    async def fake_wait_mcp_ready(self: XHSService, api_base=None, timeout: int = 15):
        return None

    async def fake_stop_mcp(self: XHSService, pid: int):
        return None

    async def fake_stop_browser(self: XHSService, shop_id: str):
        return None

    async def fake_sync_account_note_metrics(
        self: XHSService,
        note: XHSAccountNote,
        api_base: str | None = None,
        persona=None,
        **kwargs,
    ):
        synced_note_ids.append(note.id)
        note.comment_count = 1
        return True

    monkeypatch.setattr(XHSService, "_acquire_ready_sync_browser_ws", fake_acquire_ready_sync_browser_ws)
    monkeypatch.setattr(XHSService, "_allocate_free_port", fake_allocate_free_port)
    monkeypatch.setattr(XHSService, "_start_mcp", fake_start_mcp)
    monkeypatch.setattr(XHSService, "_wait_mcp_ready", fake_wait_mcp_ready)
    monkeypatch.setattr(XHSService, "_stop_mcp", fake_stop_mcp)
    monkeypatch.setattr(XHSService, "_stop_browser", fake_stop_browser)
    monkeypatch.setattr(XHSService, "_sync_account_note_metrics", fake_sync_account_note_metrics)

    async with async_session() as db:
        service = XHSService(db)
        result = await service.sync_existing_account_note_stats(
            environment_id=101,
            scrape_environment_id=102,
            sync_mode="unpublished_only",
        )

    assert result["total_notes"] == 3
    assert result["synced_notes"] == 3
    assert result["failed_notes"] == 0
    assert result["skipped_notes"] == 0
    assert seen_scrape_env_ids == [102]
    assert sorted(synced_note_ids) == [301, 302, 303]


@pytest.mark.asyncio
async def test_sync_account_note_engagement_stats_updates_metrics_from_creator_center(client, monkeypatch):
    await _seed_users_and_envs()
    async with async_session() as db:
        db.add_all([
            XHSEnvironment(id=801, shop_id="shop_publish_801", account_name="发布账号801", status="active"),
            XHSAccountNote(
                id=802,
                environment_id=801,
                account_name="发布账号801",
                feed_id="feed_802",
                title="帖子802",
                ai_origin_type="manual",
                liked_count=1,
                comment_count=1,
                collected_count=1,
                share_count=1,
                sort_index=0,
            ),
        ])
        await db.commit()

    async def fake_acquire_ready_sync_browser_ws_with_fallback(
        self: XHSService,
        env_id: int,
        allow_fallback: bool = True,
    ):
        assert env_id == 801
        return None, "ws://publish-browser"

    async def fake_allocate_free_port(self: XHSService) -> int:
        return 18123

    async def fake_start_mcp(self: XHSService, ws_url: str, port: int):
        assert ws_url == "ws://publish-browser"
        assert port == 18123
        return 12345

    async def fake_wait_mcp_ready(self: XHSService, api_base=None, timeout: int = 15):
        assert api_base == "http://localhost:18123"
        return None

    async def fake_stop_mcp(self: XHSService, pid: int):
        return None

    async def fake_stop_browser(self: XHSService, shop_id: str):
        assert shop_id == "shop_publish_801"
        return None

    async def fake_fetch_creator_note_stats(
        self: XHSService,
        *,
        api_base: str | None = None,
        env: XHSEnvironment | None = None,
    ):
        assert api_base == "http://localhost:18123"
        return [
            {
                "note_id": "feed_802",
                "title": "帖子802",
                "view_count": 555,
                "like_count": 12,
                "comment_count": 8,
                "collect_count": 5,
                "share_count": 3,
            }
        ]

    monkeypatch.setattr(XHSService, "_acquire_ready_sync_browser_ws_with_fallback", fake_acquire_ready_sync_browser_ws_with_fallback)
    monkeypatch.setattr(XHSService, "_allocate_free_port", fake_allocate_free_port)
    monkeypatch.setattr(XHSService, "_start_mcp", fake_start_mcp)
    monkeypatch.setattr(XHSService, "_wait_mcp_ready", fake_wait_mcp_ready)
    monkeypatch.setattr(XHSService, "_stop_mcp", fake_stop_mcp)
    monkeypatch.setattr(XHSService, "_stop_browser", fake_stop_browser)
    monkeypatch.setattr(XHSService, "_fetch_creator_note_stats", fake_fetch_creator_note_stats)

    async with async_session() as db:
        service = XHSService(db)
        user = await db.get(User, 1)
        assert user is not None
        note, synced = await service.sync_account_note_engagement_stats(user, 802)

    assert synced is True
    assert note.view_count == 555
    assert note.liked_count == 12
    assert note.comment_count == 8
    assert note.collected_count == 5
    assert note.share_count == 3

    async with async_session() as db:
        refreshed = await db.get(XHSAccountNote, 802)

    assert refreshed is not None
    assert refreshed.view_count == 555
    assert refreshed.liked_count == 12
    assert refreshed.comment_count == 8
    assert refreshed.collected_count == 5
    assert refreshed.share_count == 3


@pytest.mark.asyncio
async def test_sync_account_note_engagements_updates_metrics_for_selected_accounts(client, monkeypatch):
    await _seed_users_and_envs()
    async with async_session() as db:
        db.add_all([
            XHSEnvironment(id=811, shop_id="shop_publish_811", account_name="发布账号811", status="active"),
            XHSEnvironment(id=812, shop_id="shop_publish_812", account_name="发布账号812", status="active"),
            XHSAccountNote(
                id=813,
                environment_id=811,
                account_name="发布账号811",
                feed_id="feed_813",
                title="帖子813",
                ai_origin_type="manual",
                sort_index=0,
            ),
            XHSAccountNote(
                id=814,
                environment_id=812,
                account_name="发布账号812",
                feed_id="feed_814",
                title="帖子814",
                ai_origin_type="manual",
                sort_index=0,
            ),
        ])
        await db.commit()

    started_env_ids: list[int] = []
    stopped_shop_ids: list[str] = []

    async def fake_acquire_ready_sync_browser_ws_with_fallback(
        self: XHSService,
        env_id: int,
        allow_fallback: bool = True,
    ):
        started_env_ids.append(env_id)
        return None, f"ws://publish-browser-{env_id}"

    async def fake_allocate_free_port(self: XHSService) -> int:
        return 19123 + len(started_env_ids)

    async def fake_start_mcp(self: XHSService, ws_url: str, port: int):
        return 12000 + port

    async def fake_wait_mcp_ready(self: XHSService, api_base=None, timeout: int = 15):
        return None

    async def fake_stop_mcp(self: XHSService, pid: int):
        return None

    async def fake_stop_browser(self: XHSService, shop_id: str):
        stopped_shop_ids.append(shop_id)
        return None

    async def fake_fetch_creator_note_stats(
        self: XHSService,
        *,
        api_base: str | None = None,
        env: XHSEnvironment | None = None,
    ):
        if env is not None and int(env.id) == 811:
            return [{
                "note_id": "feed_813",
                "title": "帖子813",
                "view_count": 88,
                "like_count": 6,
                "comment_count": 2,
                "collect_count": 1,
                "share_count": 0,
            }]
        if env is not None and int(env.id) == 812:
            return [{
                "note_id": "feed_814",
                "title": "帖子814",
                "view_count": 99,
                "like_count": 7,
                "comment_count": 3,
                "collect_count": 2,
                "share_count": 1,
            }]
        return []

    monkeypatch.setattr(XHSService, "_acquire_ready_sync_browser_ws_with_fallback", fake_acquire_ready_sync_browser_ws_with_fallback)
    monkeypatch.setattr(XHSService, "_allocate_free_port", fake_allocate_free_port)
    monkeypatch.setattr(XHSService, "_start_mcp", fake_start_mcp)
    monkeypatch.setattr(XHSService, "_wait_mcp_ready", fake_wait_mcp_ready)
    monkeypatch.setattr(XHSService, "_stop_mcp", fake_stop_mcp)
    monkeypatch.setattr(XHSService, "_stop_browser", fake_stop_browser)
    monkeypatch.setattr(XHSService, "_fetch_creator_note_stats", fake_fetch_creator_note_stats)

    async with async_session() as db:
        service = XHSService(db)
        user = await db.get(User, 1)
        assert user is not None
        result = await service.sync_account_note_engagements(
            user=user,
            target_environment_ids=[811, 812],
        )

    assert result["synced_accounts"] == 2
    assert result["metric_synced_notes"] == 2
    assert result["total_notes"] == 2
    assert sorted(started_env_ids) == [811, 812]
    assert stopped_shop_ids == []

    async with async_session() as db:
        note_813 = await db.get(XHSAccountNote, 813)
        note_814 = await db.get(XHSAccountNote, 814)

    assert note_813 is not None
    assert note_813.view_count == 88
    assert note_813.comment_count == 2
    assert note_814 is not None
    assert note_814.view_count == 99
    assert note_814.share_count == 1


@pytest.mark.asyncio
async def test_sync_account_note_engagements_respects_requested_concurrency(client, monkeypatch):
    await _seed_users_and_envs()
    environment_ids = list(range(821, 829))
    async with async_session() as db:
        db.add_all([
            XHSEnvironment(
                id=environment_id,
                shop_id=f"shop_publish_{environment_id}",
                account_name=f"发布账号{environment_id}",
                status="active",
            )
            for environment_id in environment_ids
        ])
        await db.commit()

    running = 0
    peak = 0
    guard = asyncio.Lock()

    async def fake_sync_environment(self: XHSService, environment_id: int, **kwargs):
        nonlocal running, peak
        async with guard:
            running += 1
            peak = max(peak, running)
        await asyncio.sleep(0.02)
        async with guard:
            running -= 1
        return {
            "synced_accounts": 1,
            "created_notes": 0,
            "updated_notes": 0,
            "metric_synced_notes": 1,
            "total_notes": 1,
            "ambiguous_notes": 0,
        }

    monkeypatch.setattr(XHSService, "sync_account_note_engagement_environment", fake_sync_environment)

    async with async_session() as db:
        service = XHSService(db)
        user = await db.get(User, 1)
        assert user is not None
        result = await service.sync_account_note_engagements(
            user=user,
            target_environment_ids=environment_ids,
            concurrency=3,
        )

    assert peak == 3
    assert result["synced_accounts"] == len(environment_ids)
    assert result["metric_synced_notes"] == len(environment_ids)


@pytest.mark.asyncio
async def test_creator_center_import_creates_primary_note_and_preserves_missing_metrics(client):
    async with async_session() as db:
        db.add(XHSEnvironment(id=821, shop_id="shop_821", account_name="创作者主账号", status="active"))
        await db.commit()

    first_row = {
        "source_row_index": 2,
        "title": "创作者中心先发现的帖子",
        "published_at": datetime(2026, 8, 14, 10, 30),
        "published_at_raw": "2026-08-14 10:30",
        "like_count": 9,
        "comment_count": 7,
        "collect_count": 3,
        "share_count": 1,
        "view_count": 88,
        "exposure_count": 120,
        "cover_click_rate": 12.5,
    }
    async with async_session() as db:
        service = XHSService(db)
        env = await db.get(XHSEnvironment, 821)
        assert env is not None
        result = await service._import_creator_note_stats_rows(env, [first_row])
        await db.commit()

    assert result["created_notes"] == 1
    async with async_session() as db:
        note = (await db.execute(
            select(XHSAccountNote).where(XHSAccountNote.environment_id == 821)
        )).scalar_one()
        assert note.feed_id is None
        assert note.identity_status == "creator_only"
        assert note.published_at == datetime(2026, 8, 14, 2, 30)
        assert note.liked_count == 9
        assert note.comment_count == 7
        assert note.creator_synced_at is not None
        assert (await db.execute(select(XHSCreatorSyncRow))).scalars().one().matched_note_id == note.id

    second_row = {
        **first_row,
        "like_count": 0,
        "comment_count": None,
        "collect_count": None,
        "share_count": None,
    }
    async with async_session() as db:
        service = XHSService(db)
        env = await db.get(XHSEnvironment, 821)
        assert env is not None
        result = await service._import_creator_note_stats_rows(env, [second_row])
        await db.commit()

    assert result["updated_notes"] == 1
    async with async_session() as db:
        note = (await db.execute(
            select(XHSAccountNote).where(XHSAccountNote.environment_id == 821)
        )).scalar_one()
        assert note.liked_count == 0
        assert note.comment_count == 7
        assert note.collected_count == 3
        assert note.share_count == 1


@pytest.mark.asyncio
async def test_homepage_sync_resolves_creator_note_without_duplicate_or_metric_regression(client, monkeypatch):
    async with async_session() as db:
        db.add_all([
            XHSEnvironment(
                id=831,
                shop_id="shop_831",
                account_name="发布账号831",
                status="active",
                profile_url="https://www.xiaohongshu.com/user/profile/user831",
            ),
            XHSEnvironment(id=832, shop_id="shop_832", account_name="测试4", status="active", is_sync_runner=True),
        ])
        await db.commit()
        service = XHSService(db)
        env = await db.get(XHSEnvironment, 831)
        assert env is not None
        await service._import_creator_note_stats_rows(env, [{
            "source_row_index": 2,
            "title": "同一条帖子",
            "published_at": datetime(2026, 8, 14, 10, 30),
            "published_at_raw": "2026-08-14 10:30",
            "like_count": 50,
            "comment_count": 8,
            "collect_count": 6,
            "share_count": 2,
            "view_count": 500,
            "exposure_count": 800,
        }])
        await db.commit()

    async def fake_fetch_profile_account_notes(self, profile_url, api_base, limit=60, **kwargs):
        return {
            "profile_nickname": "发布账号831",
            "red_id": "red831",
            "feeds": [{
                "feed_id": "feed_831",
                "xsec_token": "token831",
                "title": "同一条帖子",
                "published_at": datetime(2026, 8, 14, 2, 30),
                "cover_image_url": None,
                "liked_count": 3,
                "comment_count": 1,
                "collected_count": 1,
                "share_count": 0,
                "sort_index": 0,
            }],
        }

    async def fake_sleep(self, persona=None):
        return None

    async def fake_localize(self, pending):
        return None

    monkeypatch.setattr(XHSService, "_fetch_profile_account_notes", fake_fetch_profile_account_notes)
    monkeypatch.setattr(XHSService, "_sleep_sync_profile_prep", fake_sleep)
    monkeypatch.setattr(XHSService, "_apply_pending_account_note_cover_localizations", fake_localize)

    async with async_session() as db:
        service = XHSService(db)
        env = await db.get(XHSEnvironment, 831)
        runner = await db.get(XHSEnvironment, 832)
        assert env is not None and runner is not None
        result = await service._sync_account_notes_with_api(
            env,
            api_base="http://localhost:18061",
            runner_envs=[runner],
            assigned_runner_env=runner,
        )

    assert result["created_notes"] == 0
    assert result["updated_notes"] == 1
    async with async_session() as db:
        notes = list((await db.execute(
            select(XHSAccountNote).where(XHSAccountNote.environment_id == 831)
        )).scalars().all())
    assert len(notes) == 1
    assert notes[0].feed_id == "feed_831"
    assert notes[0].identity_status == "resolved"
    assert notes[0].identity_match_method == "homepage_title_time"
    assert notes[0].liked_count == 50
    assert notes[0].comment_count == 8
    assert notes[0].homepage_synced_at is not None


@pytest.mark.asyncio
async def test_duplicate_creator_rows_are_kept_as_ambiguous_instead_of_reused(client):
    async with async_session() as db:
        db.add(XHSEnvironment(id=841, shop_id="shop_841", account_name="重复标题账号", status="active"))
        await db.commit()
        service = XHSService(db)
        env = await db.get(XHSEnvironment, 841)
        assert env is not None
        duplicate_rows = [
            {
                "source_row_index": index,
                "title": "完全相同标题",
                "published_at": datetime(2026, 8, 14, 10, 30),
                "published_at_raw": "2026-08-14 10:30",
                "view_count": 100 + index,
            }
            for index in (2, 3)
        ]
        result = await service._import_creator_note_stats_rows(env, duplicate_rows)
        await db.commit()

    assert result["created_notes"] == 2
    assert result["ambiguous_notes"] == 1
    async with async_session() as db:
        notes = list((await db.execute(
            select(XHSAccountNote)
            .where(XHSAccountNote.environment_id == 841)
            .order_by(XHSAccountNote.id.asc())
        )).scalars().all())
    assert len(notes) == 2
    assert notes[0].identity_status == "creator_only"
    assert notes[1].identity_status == "ambiguous"
    assert notes[0].creator_identity_key != notes[1].creator_identity_key


def test_open_sms_api_headers_follow_documented_hmac_format(monkeypatch):
    service = XHSService(None)  # type: ignore[arg-type]
    monkeypatch.setattr(xhs_service_module, "SMS_CODE_CENTER_OPEN_API_CLIENT_ID", "xhs-backend")
    monkeypatch.setattr(xhs_service_module, "SMS_CODE_CENTER_OPEN_API_CLIENT_SECRET", "test-open-api-secret")
    monkeypatch.setattr(xhs_service_module.time, "time", lambda: 1782280063.148)
    monkeypatch.setattr(xhs_service_module.uuid, "uuid4", lambda: uuid.UUID("12345678-1234-5678-1234-567812345678"))

    raw_body = service._compact_json({"phoneNumber": "17570049665", "platform": "小红书"})
    path = "/api/v1/open/sms-code-requests"
    headers = service._open_sms_api_headers("POST", path, raw_body, idempotency_key="xhs-login-1")

    body_hash = hashlib.sha256(raw_body.encode("utf-8")).hexdigest()
    canonical = "\n".join(("POST", path, "1782280063148", "12345678123456781234567812345678", body_hash))
    expected_signature = hmac.new(b"test-open-api-secret", canonical.encode("utf-8"), hashlib.sha256).hexdigest()
    assert headers == {
        "Content-Type": "application/json",
        "X-Client-Id": "xhs-backend",
        "X-Timestamp": "1782280063148",
        "X-Nonce": "12345678123456781234567812345678",
        "X-Signature": expected_signature,
        "Idempotency-Key": "xhs-login-1",
    }


@pytest.mark.asyncio
async def test_create_open_sms_code_request_uses_signed_open_api_payload(monkeypatch):
    service = XHSService(None)  # type: ignore[arg-type]
    calls: list[dict[str, object]] = []

    class _FakeResponse:
        status_code = 201
        content = b"ok"

        @staticmethod
        def json():
            return {"ok": True, "request": {"requestId": "request-1", "status": "waiting"}}

    class _FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, url: str, *, headers: dict[str, str], content: bytes):
            calls.append({"url": url, "headers": headers, "content": content})
            return _FakeResponse()

    monkeypatch.setattr(xhs_service_module, "SMS_CODE_CENTER_BASE_URL", "https://sms.example.test")
    monkeypatch.setattr(xhs_service_module, "SMS_CODE_CENTER_OPEN_API_CLIENT_ID", "xhs-backend")
    monkeypatch.setattr(xhs_service_module, "SMS_CODE_CENTER_OPEN_API_CLIENT_SECRET", "test-open-api-secret")
    monkeypatch.setattr(xhs_service_module.httpx, "AsyncClient", _FakeClient)

    result = await service._create_open_sms_code_request("17570049665", "xhs-login-1")

    assert result == {"requestId": "request-1", "status": "waiting"}
    assert calls[0]["url"] == "https://sms.example.test/api/v1/open/sms-code-requests"
    assert calls[0]["content"] == b'{"phoneNumber":"17570049665","platform":"\xe5\xb0\x8f\xe7\xba\xa2\xe4\xb9\xa6"}'
    assert calls[0]["headers"]["X-Client-Id"] == "xhs-backend"  # type: ignore[index]
    assert calls[0]["headers"]["Idempotency-Key"] == "xhs-login-1"  # type: ignore[index]


@pytest.mark.asyncio
async def test_same_device_sms_fallback_accepts_xhs_code_from_other_sim(monkeypatch):
    service = XHSService(None)  # type: ignore[arg-type]

    class _FakeResponse:
        status_code = 200
        content = b"ok"

        @staticmethod
        def json():
            return {
                "messages": [
                    {
                        "messageId": "bank-new",
                        "deviceId": "device-1",
                        "platform": "招商银行",
                        "body": "账户5481发生变动",
                        "code": "5481",
                        "messageAt": "2026-08-14T10:00:06Z",
                        "slotIndex": 0,
                        "subscriptionId": 1,
                    },
                    {
                        "messageId": "xhs-other-sim",
                        "deviceId": "device-1",
                        "platform": "小红书",
                        "body": "【小红书】验证码 246810，请勿泄露",
                        "code": "246810",
                        "messageAt": "2026-08-14T10:00:05Z",
                        "slotIndex": 1,
                        "subscriptionId": 2,
                    },
                    {
                        "messageId": "xhs-old",
                        "deviceId": "device-1",
                        "platform": "小红书",
                        "body": "【小红书】验证码 111111",
                        "code": "111111",
                        "messageAt": "2026-08-14T09:59:00Z",
                        "slotIndex": 0,
                        "subscriptionId": 1,
                    },
                ]
            }

    class _FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def get(self, url: str, **kwargs):
            assert url == "https://sms.example.test/api/v1/sms-library"
            assert kwargs["params"]["deviceId"] == "device-1"
            return _FakeResponse()

    monkeypatch.setattr(xhs_service_module, "SMS_CODE_CENTER_BASE_URL", "https://sms.example.test")
    monkeypatch.setattr(xhs_service_module.httpx, "AsyncClient", _FakeClient)

    result = await service._find_same_device_xhs_sms(
        {
            "requestId": "request-1",
            "deviceId": "device-1",
            "startedAt": "2026-08-14T10:00:00Z",
            "expiresAt": "2026-08-14T10:05:00Z",
        },
        "admin-token",
    )

    assert result is not None
    assert result["code"] == "246810"
    assert result["slotIndex"] == 1
    assert result["matchSource"] == "same_device_all_sims"


@pytest.mark.asyncio
async def test_same_device_sms_fallback_rejects_two_different_xhs_codes(monkeypatch):
    service = XHSService(None)  # type: ignore[arg-type]

    class _FakeResponse:
        status_code = 200
        content = b"ok"

        @staticmethod
        def json():
            return {
                "messages": [
                    {
                        "deviceId": "device-1",
                        "platform": "小红书",
                        "body": "【小红书】验证码 123456",
                        "code": "123456",
                        "messageAt": "2026-08-14T10:00:05Z",
                        "slotIndex": 0,
                    },
                    {
                        "deviceId": "device-1",
                        "platform": "小红书",
                        "body": "【小红书】验证码 654321",
                        "code": "654321",
                        "messageAt": "2026-08-14T10:00:06Z",
                        "slotIndex": 1,
                    },
                ]
            }

    class _FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def get(self, url: str, **kwargs):
            return _FakeResponse()

    monkeypatch.setattr(xhs_service_module.httpx, "AsyncClient", _FakeClient)

    result = await service._find_same_device_xhs_sms(
        {
            "requestId": "request-1",
            "deviceId": "device-1",
            "startedAt": "2026-08-14T10:00:00Z",
            "expiresAt": "2026-08-14T10:05:00Z",
        },
        "admin-token",
    )

    assert result is None


@pytest.mark.asyncio
async def test_wait_sms_ignores_bank_message_matched_by_exact_order(monkeypatch):
    service = XHSService(None)  # type: ignore[arg-type]
    cancelled: list[str] = []

    async def fake_admin_token(self: XHSService):
        return "admin-token"

    async def fake_exact(self: XHSService, request_id: str):
        return {
            "requestId": request_id,
            "status": "received",
            "code": "5481",
            "sender": "10693495555",
            "body": "【招商银行】您账户5481发生变动",
        }

    async def fake_fallback(self: XHSService, request_context: dict, admin_token: str):
        return {
            "requestId": request_context["requestId"],
            "status": "received",
            "code": "246810",
            "sender": "10690000",
            "body": "【小红书】验证码 246810",
            "deviceId": request_context["deviceId"],
            "slotIndex": 1,
            "subscriptionId": 2,
            "matchSource": "same_device_all_sims",
        }

    async def fake_cancel(self: XHSService, request_id: str):
        cancelled.append(request_id)

    monkeypatch.setattr(XHSService, "_get_phone_cloud_admin_token", fake_admin_token)
    monkeypatch.setattr(XHSService, "_get_open_sms_code_request", fake_exact)
    monkeypatch.setattr(XHSService, "_find_same_device_xhs_sms", fake_fallback)
    monkeypatch.setattr(XHSService, "_cancel_open_sms_code_request", fake_cancel)

    result = await service._wait_open_sms_code_request(
        "request-2",
        initial_request={
            "requestId": "request-2",
            "status": "waiting",
            "deviceId": "device-1",
            "startedAt": "2026-08-14T10:00:00Z",
            "expiresAt": "2026-08-14T10:05:00Z",
        },
    )

    assert result["code"] == "246810"
    assert result["matchSource"] == "same_device_all_sims"
    assert cancelled == ["request-2"]


@pytest.mark.asyncio
async def test_create_xhs_qr_task_uses_existing_phone_cloud_admin_route(monkeypatch):
    service = XHSService(None)  # type: ignore[arg-type]
    calls: list[dict[str, object]] = []

    class _FakeResponse:
        status_code = 201
        content = b"ok"

        def __init__(self, payload: dict | None = None, status_code: int = 201):
            self._payload = payload or {"ok": True, "task": {"taskId": "qr-task-1", "status": "queued"}}
            self.status_code = status_code

        def json(self):
            return self._payload

    class _FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def get(self, url: str, *, headers: dict[str, str]):
            calls.append({"method": "GET", "url": url, "headers": headers})
            return _FakeResponse({
                "devices": [{
                    "deviceId": "adb:test-device",
                    "sims": [{"phoneNumber": "+86 17570049665", "enabled": True}],
                    "xhsAccounts": [{"appSlot": "app2", "accountName": "小迪买车情报站", "enabled": True}],
                }]
            }, status_code=200)

        async def post(self, url: str, *, headers: dict[str, str], json: dict):
            calls.append({"method": "POST", "url": url, "headers": headers, "json": json})
            return _FakeResponse()

    monkeypatch.setattr(xhs_service_module, "SMS_CODE_CENTER_BASE_URL", "https://sms.example.test")
    monkeypatch.setattr(xhs_service_module, "SMS_CODE_CENTER_ADMIN_API_TOKEN", "phone-cloud-admin-token")
    monkeypatch.setattr(xhs_service_module.httpx, "AsyncClient", _FakeClient)

    result = await service._create_phone_cloud_xhs_qr_task(
        "小迪买车情报站",
        "data:image/png;base64,cXItYnl0ZXM=",
        xhs_app_slot="app2",
    )

    assert result == {"taskId": "qr-task-1", "status": "queued", "_adminToken": "phone-cloud-admin-token"}
    assert calls[0] == {
        "method": "GET",
        "url": "https://sms.example.test/api/v1/devices",
        "headers": {"Authorization": "Bearer phone-cloud-admin-token"},
    }
    assert calls[1] == {
        "method": "POST",
        "url": "https://sms.example.test/api/v1/xhs/qr-scan-tasks",
        "headers": {"Authorization": "Bearer phone-cloud-admin-token"},
        "json": {
        "deviceId": "adb:test-device",
        "qrImageDataUrl": "data:image/png;base64,cXItYnl0ZXM=",
        "xhsAppSlot": "app2",
        },
    }


@pytest.mark.asyncio
async def test_create_xhs_qr_task_can_use_device_without_login_sim(monkeypatch):
    service = XHSService(None)  # type: ignore[arg-type]
    posted: list[dict[str, object]] = []

    class _FakeResponse:
        content = b"ok"

        def __init__(self, payload: dict, status_code: int = 200):
            self._payload = payload
            self.status_code = status_code

        def json(self):
            return self._payload

    class _FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def get(self, url: str, *, headers: dict[str, str]):
            return _FakeResponse({
                "devices": [
                    {
                        "deviceId": "sms-device",
                        "sims": [{"phoneNumber": "17570049665", "enabled": True}],
                        "xhsAccounts": [],
                    },
                    {
                        "deviceId": "scan-device",
                        "sims": [],
                        "xhsAccounts": [
                            {"appSlot": "app2", "accountName": "小迪买车情报站", "enabled": True}
                        ],
                    },
                ]
            })

        async def post(self, url: str, *, headers: dict[str, str], json: dict):
            posted.append(json)
            return _FakeResponse({"task": {"taskId": "qr-task-2", "status": "queued"}}, 201)

    monkeypatch.setattr(xhs_service_module, "SMS_CODE_CENTER_BASE_URL", "https://sms.example.test")
    monkeypatch.setattr(xhs_service_module, "SMS_CODE_CENTER_ADMIN_API_TOKEN", "phone-cloud-admin-token")
    monkeypatch.setattr(xhs_service_module.httpx, "AsyncClient", _FakeClient)

    await service._create_phone_cloud_xhs_qr_task(
        "小迪买车情报站",
        "data:image/png;base64,cXItYnl0ZXM=",
        xhs_app_slot="app2",
    )

    assert posted == [{
        "deviceId": "scan-device",
        "xhsAppSlot": "app2",
        "qrImageDataUrl": "data:image/png;base64,cXItYnl0ZXM=",
    }]


@pytest.mark.asyncio
async def test_resolve_phone_cloud_qr_target_prefers_xhs_account_id(monkeypatch):
    service = XHSService(None)  # type: ignore[arg-type]

    class _FakeResponse:
        status_code = 200
        content = b"ok"

        def json(self):
            return {
                "devices": [
                    {
                        "deviceId": "stale-name-device",
                        "xhsAccounts": [{
                            "appSlot": "app1",
                            "accountName": "目标账号",
                            "xhsAccountId": "old-id",
                            "enabled": True,
                        }],
                    },
                    {
                        "deviceId": "correct-id-device",
                        "xhsAccounts": [{
                            "appSlot": "app2",
                            "accountName": "已经改名",
                            "xhsAccountId": "26819980796",
                            "enabled": True,
                        }],
                    },
                ]
            }

    class _FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def get(self, url: str, *, headers: dict[str, str]):
            return _FakeResponse()

    monkeypatch.setattr(xhs_service_module, "SMS_CODE_CENTER_BASE_URL", "https://sms.example.test")
    monkeypatch.setattr(xhs_service_module.httpx, "AsyncClient", _FakeClient)

    target = await service._resolve_phone_cloud_xhs_target(
        "目标账号",
        "phone-cloud-admin-token",
        xhs_account_id="26819980796",
    )

    assert target == {"deviceId": "correct-id-device", "xhsAppSlot": "app2"}


@pytest.mark.asyncio
async def test_phone_cloud_qr_auth_can_create_short_lived_admin_session(monkeypatch):
    service = XHSService(None)  # type: ignore[arg-type]
    calls: list[dict[str, object]] = []

    class _FakeResponse:
        status_code = 200
        content = b"ok"

        @staticmethod
        def json():
            return {"ok": True, "session": {"token": "short-lived-admin-session"}}

    class _FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, url: str, *, json: dict):
            calls.append({"url": url, "json": json})
            return _FakeResponse()

    monkeypatch.setattr(xhs_service_module, "SMS_CODE_CENTER_BASE_URL", "https://sms.example.test")
    monkeypatch.setattr(xhs_service_module, "SMS_CODE_CENTER_ADMIN_API_TOKEN", "")
    monkeypatch.setattr(xhs_service_module, "SMS_CODE_CENTER_ADMIN_USERNAME", "phone-cloud-admin")
    monkeypatch.setattr(xhs_service_module, "SMS_CODE_CENTER_ADMIN_PASSWORD", "phone-cloud-password")
    monkeypatch.setattr(xhs_service_module.httpx, "AsyncClient", _FakeClient)

    assert await service._get_phone_cloud_admin_token() == "short-lived-admin-session"
    assert calls == [{
        "url": "https://sms.example.test/api/v1/auth/login",
        "json": {"username": "phone-cloud-admin", "password": "phone-cloud-password"},
    }]


@pytest.mark.asyncio
async def test_creator_auto_login_uses_signed_open_sms_request(monkeypatch):
    service = XHSService(None)  # type: ignore[arg-type]
    events: list[tuple[str, object]] = []
    env = XHSEnvironment(id=901, shop_id="shop_901", account_name="测试账号", login_phone_number="17570049665")

    async def fake_login_status(self: XHSService, api_base: str):
        events.append(("login-status", api_base))
        return {"is_logged_in": False}

    async def fake_create_request(self: XHSService, phone_number: str, client_request_id: str):
        events.append(("create-request", phone_number))
        assert client_request_id.startswith("xhs-login-901-")
        return {"requestId": "request-901", "status": "waiting", "deviceId": "device-901"}

    async def fake_wait_request(self: XHSService, request_id: str, **kwargs):
        events.append(("wait-request", request_id))
        assert kwargs["initial_request"]["deviceId"] == "device-901"
        return {"requestId": request_id, "status": "received", "code": "246810", "deviceId": "device-901"}

    class _FakeResponse:
        status_code = 200
        content = b"ok"

        def __init__(self, payload: dict):
            self._payload = payload

        def json(self):
            return self._payload

    class _FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, url: str, *, json: dict):
            events.append(("mcp-post", {"url": url, "json": json}))
            if url.endswith("/request-code"):
                return _FakeResponse({"success": True, "data": {}})
            if url.endswith("/submit-code"):
                return _FakeResponse({"success": True, "data": {"is_logged_in": True}})
            raise AssertionError(f"unexpected url: {url}")

    monkeypatch.setattr(xhs_service_module, "SMS_CODE_CENTER_OPEN_API_CLIENT_ID", "xhs-backend")
    monkeypatch.setattr(xhs_service_module, "SMS_CODE_CENTER_OPEN_API_CLIENT_SECRET", "test-open-api-secret")
    monkeypatch.setattr(XHSService, "_get_mcp_login_status", fake_login_status)
    monkeypatch.setattr(XHSService, "_create_open_sms_code_request", fake_create_request)
    monkeypatch.setattr(XHSService, "_wait_open_sms_code_request", fake_wait_request)
    monkeypatch.setattr(xhs_service_module.httpx, "AsyncClient", _FakeClient)

    await service._ensure_xhs_creator_login("http://mcp.test", env=env)

    assert events == [
        ("login-status", "http://mcp.test"),
        ("create-request", "17570049665"),
        ("wait-request", "request-901"),
        ("mcp-post", {"url": "http://mcp.test/api/v1/login/phone/request-code", "json": {"phone_number": "17570049665"}}),
        ("mcp-post", {"url": "http://mcp.test/api/v1/login/phone/submit-code", "json": {"phone_number": "17570049665", "code": "246810"}}),
    ]


@pytest.mark.asyncio
async def test_qr_login_arms_secondary_sms_before_phone_task(monkeypatch):
    service = XHSService(None)  # type: ignore[arg-type]
    events: list[tuple[str, object]] = []
    env = XHSEnvironment(id=902, shop_id="shop_902", account_name="测试账号", login_phone_number="17570049665")
    listener_started = asyncio.Event()

    async def fake_qrcode(self: XHSService, api_base: str):
        events.append(("get-qr", api_base))
        return {"is_logged_in": False, "img": "cXItYnl0ZXM="}

    async def fake_create_request(self: XHSService, phone_number: str, client_request_id: str):
        events.append(("arm-sms", phone_number))
        assert client_request_id.startswith("xhs-login-secondary-902-")
        return {"requestId": "secondary-902", "status": "waiting"}

    async def fake_create_qr_task(
        self: XHSService,
        xhs_account: str,
        qr_image_data_url: str,
        **kwargs,
    ):
        await listener_started.wait()
        events.append(("dispatch-qr", xhs_account))
        assert xhs_account == "测试账号"
        assert qr_image_data_url.startswith("data:image/png;base64,")
        assert kwargs["xhs_account_id"] is None
        return {"taskId": "qr-902", "_adminToken": "admin-token"}

    async def fake_wait_sms(self: XHSService, request_id: str, **kwargs):
        events.append(("listen-both-sims", request_id))
        assert kwargs["initial_request"]["status"] == "waiting"
        listener_started.set()
        await asyncio.Event().wait()

    async def fake_wait_qr(self: XHSService, task_id: str, admin_token: str):
        events.append(("qr-succeeded", task_id))
        return {"taskId": task_id, "status": "succeeded"}

    async def fake_finish_secondary(
        self: XHSService,
        api_base: str,
        phone_number: str,
        request_id: str,
        **kwargs,
    ):
        events.append(("check-secondary", request_id))
        return False

    async def fake_cancel(self: XHSService, request_id: str):
        events.append(("cancel-unused", request_id))

    monkeypatch.setattr(XHSService, "_get_mcp_login_qrcode", fake_qrcode)
    monkeypatch.setattr(XHSService, "_create_open_sms_code_request", fake_create_request)
    monkeypatch.setattr(XHSService, "_wait_open_sms_code_request", fake_wait_sms)
    monkeypatch.setattr(XHSService, "_create_phone_cloud_xhs_qr_task", fake_create_qr_task)
    monkeypatch.setattr(XHSService, "_wait_phone_cloud_xhs_qr_task", fake_wait_qr)
    monkeypatch.setattr(XHSService, "_complete_xhs_post_qr_verification", fake_finish_secondary)
    monkeypatch.setattr(XHSService, "_cancel_open_sms_code_request", fake_cancel)

    await service._complete_xhs_qr_login_if_needed(
        "http://mcp.test",
        "17570049665",
        {"deviceId": "device-902"},
        env=env,
    )

    assert events == [
        ("get-qr", "http://mcp.test"),
        ("arm-sms", "17570049665"),
        ("listen-both-sims", "secondary-902"),
        ("dispatch-qr", "测试账号"),
        ("qr-succeeded", "qr-902"),
        ("check-secondary", "secondary-902"),
        ("cancel-unused", "secondary-902"),
    ]


@pytest.mark.asyncio
async def test_post_qr_verification_submits_automatically_received_code(monkeypatch):
    service = XHSService(None)  # type: ignore[arg-type]
    events: list[tuple[str, object]] = []

    async def fake_login_status(self: XHSService, api_base: str):
        events.append(("login-status", api_base))
        return {"is_logged_in": False}

    async def fake_submit(self: XHSService, api_base: str, phone_number: str, code: str):
        events.append(("submit-secondary", {"phone": phone_number, "code": code}))
        return {"is_logged_in": True}

    monkeypatch.setattr(XHSService, "_get_mcp_login_status", fake_login_status)
    monkeypatch.setattr(XHSService, "_submit_mcp_phone_code", fake_submit)

    consumed = await service._complete_xhs_post_qr_verification(
        "http://mcp.test",
        "17570049665",
        "secondary-903",
        initial_request={"requestId": "secondary-903", "status": "received", "code": "135790"},
    )

    assert consumed is True
    assert events == [
        ("login-status", "http://mcp.test"),
        ("submit-secondary", {"phone": "17570049665", "code": "135790"}),
    ]


@pytest.mark.asyncio
async def test_post_qr_verification_cancels_listener_when_qr_login_is_direct(monkeypatch):
    service = XHSService(None)  # type: ignore[arg-type]

    async def fake_login_status(self: XHSService, api_base: str):
        return {"is_logged_in": True}

    async def fake_get_request(self: XHSService, request_id: str):
        return {"requestId": request_id, "status": "waiting"}

    monkeypatch.setattr(XHSService, "_get_mcp_login_status", fake_login_status)
    monkeypatch.setattr(XHSService, "_get_open_sms_code_request", fake_get_request)

    consumed = await service._complete_xhs_post_qr_verification(
        "http://mcp.test",
        "17570049665",
        "secondary-904",
        initial_request={"requestId": "secondary-904", "status": "waiting"},
    )

    assert consumed is False


@pytest.mark.asyncio
async def test_post_qr_verification_refreshes_waiting_request_before_first_decision(monkeypatch):
    service = XHSService(None)  # type: ignore[arg-type]
    events: list[str] = []

    async def fake_login_status(self: XHSService, api_base: str):
        events.append("login-status")
        return {"is_logged_in": False}

    async def fake_get_request(self: XHSService, request_id: str):
        events.append("refresh-sms")
        return {"requestId": request_id, "status": "received", "code": "246810"}

    async def fake_submit(self: XHSService, api_base: str, phone_number: str, code: str):
        events.append(f"submit:{code}")
        return {"is_logged_in": True}

    monkeypatch.setattr(XHSService, "_get_mcp_login_status", fake_login_status)
    monkeypatch.setattr(XHSService, "_get_open_sms_code_request", fake_get_request)
    monkeypatch.setattr(XHSService, "_submit_mcp_phone_code", fake_submit)

    consumed = await service._complete_xhs_post_qr_verification(
        "http://mcp.test",
        "17570049665",
        "secondary-906",
        initial_request={"requestId": "secondary-906", "status": "waiting"},
    )

    assert consumed is True
    assert set(events[:2]) == {"login-status", "refresh-sms"}
    assert events[2] == "submit:246810"


def test_normalize_cn_phone_number_accepts_country_code():
    assert XHSService._normalize_cn_phone_number("+86 175-7075-5085") == "17570755085"
    assert XHSService._normalize_cn_phone_number("17570755085") == "17570755085"


@pytest.mark.asyncio
async def test_post_qr_verification_keeps_waiting_when_login_status_check_fails(monkeypatch):
    service = XHSService(None)  # type: ignore[arg-type]
    submitted: list[str] = []

    async def fake_login_status(self: XHSService, api_base: str):
        raise RuntimeError("temporary browser status failure")

    async def fake_submit(self: XHSService, api_base: str, phone_number: str, code: str):
        submitted.append(code)
        return {"is_logged_in": True}

    monkeypatch.setattr(XHSService, "_get_mcp_login_status", fake_login_status)
    monkeypatch.setattr(XHSService, "_submit_mcp_phone_code", fake_submit)

    consumed = await service._complete_xhs_post_qr_verification(
        "http://mcp.test",
        "17570049665",
        "secondary-905",
        initial_request={"requestId": "secondary-905", "status": "received", "code": "975310"},
    )

    assert consumed is True
    assert submitted == ["975310"]


@pytest.mark.asyncio
async def test_sync_existing_account_note_stats_respects_sync_limit(client, monkeypatch):
    await _seed_users_and_envs()
    async with async_session() as db:
        db.add_all([
            XHSAccountNote(
                id=401,
                environment_id=101,
                account_name="账号A",
                feed_id="feed_401",
                title="待同步1",
                ai_origin_type="manual",
                published_at=None,
                sort_index=0,
            ),
            XHSAccountNote(
                id=402,
                environment_id=101,
                account_name="账号A",
                feed_id="feed_402",
                title="待同步2",
                ai_origin_type="manual",
                published_at=None,
                sort_index=1,
            ),
            XHSAccountNote(
                id=403,
                environment_id=101,
                account_name="账号A",
                feed_id="feed_403",
                title="待同步3",
                ai_origin_type="manual",
                published_at=None,
                sort_index=2,
            ),
        ])
        await db.commit()

    synced_note_ids: list[int] = []

    async def fake_acquire_ready_sync_browser_ws(self: XHSService, scrape_env: XHSEnvironment):
        return "ws://fake-browser"

    async def fake_start_mcp(self: XHSService, ws_url: str, port: int):
        return 12345

    async def fake_allocate_free_port(self: XHSService) -> int:
        return 18061

    async def fake_wait_mcp_ready(self: XHSService, api_base=None, timeout: int = 15):
        return None

    async def fake_stop_mcp(self: XHSService, pid: int):
        return None

    async def fake_stop_browser(self: XHSService, shop_id: str):
        return None

    async def fake_sync_account_note_metrics(
        self: XHSService,
        note: XHSAccountNote,
        api_base: str | None = None,
        persona=None,
        **kwargs,
    ):
        synced_note_ids.append(note.id)
        return True

    monkeypatch.setattr(XHSService, "_acquire_ready_sync_browser_ws", fake_acquire_ready_sync_browser_ws)
    monkeypatch.setattr(XHSService, "_allocate_free_port", fake_allocate_free_port)
    monkeypatch.setattr(XHSService, "_start_mcp", fake_start_mcp)
    monkeypatch.setattr(XHSService, "_wait_mcp_ready", fake_wait_mcp_ready)
    monkeypatch.setattr(XHSService, "_stop_mcp", fake_stop_mcp)
    monkeypatch.setattr(XHSService, "_stop_browser", fake_stop_browser)
    monkeypatch.setattr(XHSService, "_sync_account_note_metrics", fake_sync_account_note_metrics)

    async with async_session() as db:
        service = XHSService(db)
        result = await service.sync_existing_account_note_stats(
            environment_id=101,
            scrape_environment_id=102,
            sync_mode="all",
            sync_limit=2,
        )

    assert result["matched_notes"] == 3
    assert result["total_notes"] == 2
    assert result["synced_notes"] == 2
    assert len(synced_note_ids) == 2


@pytest.mark.asyncio
async def test_account_note_sync_limit_accepts_1000():
    async with async_session() as db:
        service = XHSService(db)
        assert service._normalize_account_note_sync_limit(1000) == 1000
        assert service._normalize_account_note_sync_limit(1200) == 1000


@pytest.mark.asyncio
async def test_sync_existing_account_note_stats_cancel_keeps_completed_rows(client, monkeypatch):
    await _seed_users_and_envs()
    async with async_session() as db:
        db.add_all([
            XHSAccountNote(
                id=421,
                environment_id=101,
                account_name="账号A",
                feed_id="feed_421",
                title="待同步1",
                ai_origin_type="manual",
                published_at=None,
                sort_index=0,
            ),
            XHSAccountNote(
                id=422,
                environment_id=101,
                account_name="账号A",
                feed_id="feed_422",
                title="待同步2",
                ai_origin_type="manual",
                published_at=None,
                sort_index=1,
            ),
        ])
        await db.commit()

    synced_note_ids: list[int] = []

    async def fake_acquire_ready_sync_browser_ws(self: XHSService, scrape_env: XHSEnvironment):
        return "ws://fake-browser"

    async def fake_start_mcp(self: XHSService, ws_url: str, port: int):
        return 12345

    async def fake_allocate_free_port(self: XHSService) -> int:
        return 18061

    async def fake_wait_mcp_ready(self: XHSService, api_base=None, timeout: int = 15):
        return None

    async def fake_stop_mcp(self: XHSService, pid: int):
        return None

    async def fake_stop_browser(self: XHSService, shop_id: str):
        return None

    async def fake_record_account_note_browse(self: XHSService, note: XHSAccountNote, **kwargs):
        return {"note_id": note.id}

    async def fake_sync_account_note_metrics(
        self: XHSService,
        note: XHSAccountNote,
        api_base: str | None = None,
        persona=None,
        **kwargs,
    ):
        synced_note_ids.append(note.id)
        note.comment_count = note.id
        note.detail_synced_at = utc_now_naive()
        return True

    monkeypatch.setattr(XHSService, "_acquire_ready_sync_browser_ws", fake_acquire_ready_sync_browser_ws)
    monkeypatch.setattr(XHSService, "_allocate_free_port", fake_allocate_free_port)
    monkeypatch.setattr(XHSService, "_start_mcp", fake_start_mcp)
    monkeypatch.setattr(XHSService, "_wait_mcp_ready", fake_wait_mcp_ready)
    monkeypatch.setattr(XHSService, "_stop_mcp", fake_stop_mcp)
    monkeypatch.setattr(XHSService, "_stop_browser", fake_stop_browser)
    monkeypatch.setattr(XHSService, "record_account_note_browse", fake_record_account_note_browse)
    monkeypatch.setattr(XHSService, "_sync_account_note_metrics", fake_sync_account_note_metrics)

    async with async_session() as db:
        service = XHSService(db)
        with pytest.raises(SyncJobCancelled):
            await service.sync_existing_account_note_stats(
                environment_id=101,
                scrape_environment_id=102,
                sync_mode="all",
                cancel_check=lambda: len(synced_note_ids) >= 1,
            )

    async with async_session() as db:
        first = await db.get(XHSAccountNote, 421)
        second = await db.get(XHSAccountNote, 422)

    assert len(synced_note_ids) == 1
    assert first is not None
    assert second is not None
    if synced_note_ids[0] == 421:
        assert first.comment_count == 421
        assert second.comment_count == 0
    else:
        assert synced_note_ids[0] == 422
        assert first.comment_count == 0
        assert second.comment_count == 422


@pytest.mark.asyncio
async def test_sync_account_notes_explicit_runner_only_reassigns_touched_notes(client, monkeypatch):
    async with async_session() as db:
        db.add_all([
            XHSEnvironment(id=510, shop_id="shop_publish", account_name="发布账号A", status="active", profile_url="https://example.com/profile"),
            XHSEnvironment(id=511, shop_id="shop_runner_new", account_name="测试2", status="active", is_sync_runner=True),
            XHSEnvironment(id=512, shop_id="shop_runner_old", account_name="测试3", status="active", is_sync_runner=True),
        ])
        db.add_all([
            XHSAccountNote(
                id=521,
                environment_id=510,
                account_name="发布账号A",
                feed_id="feed_touched",
                title="触达帖子",
                ai_origin_type="manual",
                assigned_runner_environment_id=512,
                sort_index=0,
            ),
            XHSAccountNote(
                id=522,
                environment_id=510,
                account_name="发布账号A",
                feed_id="feed_stale",
                title="旧帖子",
                ai_origin_type="manual",
                assigned_runner_environment_id=512,
                sort_index=1,
            ),
        ])
        await db.commit()

    async def fake_fetch_profile_account_notes(
        self: XHSService,
        profile_url: str,
        api_base: str,
        limit: int = 60,
        **kwargs,
    ):
        return {
            "profile_nickname": "发布账号A",
            "red_id": "red_publish_a",
            "feeds": [
                {
                    "feed_id": "feed_touched",
                    "xsec_token": "A" * 46,
                    "title": "触达帖子",
                    "cover_image_url": "https://example.com/cover.jpg",
                    "liked_count": 3,
                    "comment_count": 2,
                    "collected_count": 1,
                    "share_count": 0,
                    "sort_index": 0,
                }
            ],
        }

    async def fake_sleep_sync_profile_prep(self: XHSService, persona=None):
        return None

    async def fake_apply_pending_cover_localizations(self: XHSService, pending_cover_localizations):
        return None

    monkeypatch.setattr(XHSService, "_fetch_profile_account_notes", fake_fetch_profile_account_notes)
    monkeypatch.setattr(XHSService, "_sleep_sync_profile_prep", fake_sleep_sync_profile_prep)
    monkeypatch.setattr(XHSService, "_apply_pending_account_note_cover_localizations", fake_apply_pending_cover_localizations)

    async with async_session() as db:
        service = XHSService(db)
        publish_env = await db.get(XHSEnvironment, 510)
        new_runner = await db.get(XHSEnvironment, 511)
        old_runner = await db.get(XHSEnvironment, 512)
        assert publish_env is not None
        assert new_runner is not None
        assert old_runner is not None

        result = await service._sync_account_notes_with_api(
            publish_env,
            api_base="http://localhost:18061",
            limit=60,
            runner_envs=[new_runner, old_runner],
            assigned_runner_env=new_runner,
        )

    assert result["created_notes"] == 0
    assert result["updated_notes"] == 1

    async with async_session() as db:
        touched = await db.get(XHSAccountNote, 521)
        stale = await db.get(XHSAccountNote, 522)

    assert touched is not None and touched.assigned_runner_environment_id == 511
    assert stale is not None and stale.assigned_runner_environment_id == 512


@pytest.mark.asyncio
async def test_sync_account_notes_does_not_zero_missing_interact_counts(client, monkeypatch):
    async with async_session() as db:
        db.add(XHSEnvironment(id=710, shop_id="shop_publish_710", account_name="发布账号C", status="active", profile_url="https://example.com/profile"))
        db.add(XHSEnvironment(id=711, shop_id="shop_runner_711", account_name="测试2", status="active", is_sync_runner=True))
        db.add(
            XHSAccountNote(
                id=721,
                environment_id=710,
                account_name="发布账号C",
                feed_id="feed_keep_counts",
                title="旧帖子",
                ai_origin_type="manual",
                liked_count=10,
                comment_count=7,
                collected_count=5,
                share_count=3,
                sort_index=0,
            )
        )
        await db.commit()

    async def fake_fetch_profile_account_notes(
        self: XHSService,
        profile_url: str,
        api_base: str,
        limit: int = 60,
        **kwargs,
    ):
        return {
            "profile_nickname": "发布账号C",
            "red_id": "red_publish_c",
            "feeds": [
                {
                    "feed_id": "feed_keep_counts",
                    "xsec_token": "C" * 46,
                    "title": "旧帖子",
                    "cover_image_url": "https://example.com/cover-c.jpg",
                    "liked_count": 11,
                    "comment_count": None,
                    "collected_count": None,
                    "share_count": None,
                    "sort_index": 0,
                }
            ],
        }

    async def fake_sleep_sync_profile_prep(self: XHSService, persona=None):
        return None

    async def fake_apply_pending_cover_localizations(self: XHSService, pending_cover_localizations):
        return None

    monkeypatch.setattr(XHSService, "_fetch_profile_account_notes", fake_fetch_profile_account_notes)
    monkeypatch.setattr(XHSService, "_sleep_sync_profile_prep", fake_sleep_sync_profile_prep)
    monkeypatch.setattr(XHSService, "_apply_pending_account_note_cover_localizations", fake_apply_pending_cover_localizations)

    async with async_session() as db:
        service = XHSService(db)
        publish_env = await db.get(XHSEnvironment, 710)
        runner = await db.get(XHSEnvironment, 711)
        assert publish_env is not None
        assert runner is not None

        await service._sync_account_notes_with_api(
            publish_env,
            api_base="http://localhost:18061",
            limit=60,
            runner_envs=[runner],
            assigned_runner_env=runner,
        )

    async with async_session() as db:
        note = await db.get(XHSAccountNote, 721)

    assert note is not None
    assert note.liked_count == 11
    assert note.comment_count == 7
    assert note.collected_count == 5
    assert note.share_count == 3


@pytest.mark.asyncio
async def test_resolve_account_note_owner_runner_does_not_trigger_async_lazy_load(client):
    await _seed_users_and_envs()
    async with async_session() as db:
        db.add(
            XHSAccountNote(
                id=451,
                environment_id=101,
                account_name="账号A",
                feed_id="feed_451",
                title="待同步",
                ai_origin_type="manual",
                assigned_runner_environment_id=102,
                sort_index=0,
            )
        )
        await db.commit()

    async with async_session() as db:
        note = await db.get(XHSAccountNote, 451)
        assert note is not None
        service = XHSService(db)
        owner_runner = await service._resolve_account_note_owner_runner(note)

    assert owner_runner is not None
    assert owner_runner.id == 102


@pytest.mark.asyncio
async def test_get_sync_browser_ws_merges_admin_start_config(monkeypatch):
    async with async_session() as db:
        service = XHSService(db)
        env = XHSEnvironment(
            id=201,
            shop_id="shop_sync_runner",
            account_name="测试2",
            status="active",
            sync_browser_start_config='{"headless":{"$pick":["1"]},"proxy":{"proxyMethod":{"$rand_int":[2,2]}},"remote_debugging_port":{"$rand_int":[9333,9333]}}',
        )

        captured: dict[str, object] = {}

        class _FakeResponse:
            status_code = 200
            content = b"1"

            def json(self):
                return {"code": 0, "data": {"ws": {"puppeteer": "ws://127.0.0.1:9222/devtools/browser/abc"}}}

        class _FakeClient:
            def __init__(self, *args, **kwargs):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return False

            async def post(self, url: str, json: dict):
                captured["url"] = url
                captured["json"] = json
                return _FakeResponse()

        monkeypatch.setattr(xhs_service_module.httpx, "AsyncClient", _FakeClient)
        monkeypatch.setattr(XHSService, "_probe_browser_ws", lambda self, ws_url: _async_true())

        ws_url = await service._request_browser_ws_for_online_environment(env)

    assert ws_url == "ws://127.0.0.1:9222/devtools/browser/abc"
    assert captured["url"] == f"{xhs_service_module.YUNDENG_API}/api/v2/browser/start"
    assert captured["json"] == {
        "account_id": "shop_sync_runner",
        "headless": "1",
        "proxy": {"proxyMethod": 2},
        "remote_debugging_port": 9333,
    }


@pytest.mark.asyncio
async def test_get_sync_browser_ws_applies_cloud_update_before_local_start(monkeypatch):
    async with async_session() as db:
        service = XHSService(db)
        env = XHSEnvironment(
            id=202,
            shop_id="shop_sync_runner",
            account_name="测试2",
            status="active",
            sync_cloud_session_id="session_202",
            sync_cloud_api_key="api_key_202",
            sync_cloud_update_config='{"flag":2,"browser":{"system":{"$pick":["Windows 11"]},"publicIp":"1.2.3.4","kernel":"chrome","kernelVersion":{"$pick":["127"]}}}',
            sync_browser_start_config='{"headless":{"$pick":["1"]}}',
        )

        calls: list[tuple[dict[str, object], str, dict | None]] = []

        class _FakeResponse:
            def __init__(self, status_code: int, payload: dict):
                self.status_code = status_code
                self._payload = payload
                self.content = b"1"

            def json(self):
                return self._payload

        class _FakeClient:
            def __init__(self, *args, headers=None, **kwargs):
                self._headers = headers or {}

            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return False

            async def post(self, url: str, json: dict | None = None):
                calls.append((dict(self._headers), url, json))
                if url == f"{xhs_service_module.YUNDENG_CLOUD_API}/v2/cloudbrowser/api/user/sessions/update":
                    return _FakeResponse(200, {"code": 200, "msg": "OK"})
                if url == f"{xhs_service_module.YUNDENG_CLOUD_API}/v2/cloudbrowser/api/session/stop?apiKey=api_key_202&sessionId=session_202":
                    return _FakeResponse(200, {"code": 200, "msg": "OK"})
                if url == f"{xhs_service_module.YUNDENG_CLOUD_API}/v2/cloudbrowser/api/session/start?apiKey=api_key_202&sessionId=session_202":
                    return _FakeResponse(200, {"code": 200, "msg": "OK"})
                if url == f"{xhs_service_module.YUNDENG_API}/api/v2/browser/start":
                    return _FakeResponse(200, {"code": 0, "data": {"ws": {"puppeteer": "ws://127.0.0.1:9333/devtools/browser/xyz"}}})
                raise AssertionError(f"unexpected url: {url}")

        monkeypatch.setattr(xhs_service_module, "YUNDENG_CLOUD_OPEN_TOKEN", "cloud-open-token")
        monkeypatch.setattr(xhs_service_module.httpx, "AsyncClient", _FakeClient)
        monkeypatch.setattr(XHSService, "_probe_browser_ws", lambda self, ws_url: _async_true())

        ws_url = await service._request_browser_ws_for_online_environment(env)

    assert ws_url == "ws://127.0.0.1:9333/devtools/browser/xyz"
    assert [item[1] for item in calls] == [
        f"{xhs_service_module.YUNDENG_CLOUD_API}/v2/cloudbrowser/api/user/sessions/update",
        f"{xhs_service_module.YUNDENG_CLOUD_API}/v2/cloudbrowser/api/session/stop?apiKey=api_key_202&sessionId=session_202",
        f"{xhs_service_module.YUNDENG_CLOUD_API}/v2/cloudbrowser/api/session/start?apiKey=api_key_202&sessionId=session_202",
        f"{xhs_service_module.YUNDENG_API}/api/v2/browser/start",
    ]
    assert calls[0][0] == {"Authorization": "cloud-open-token"}
    assert calls[0][2] == {
        "flag": 2,
        "sessionId": "session_202",
        "sessionName": "测试2",
        "browser": {
            "system": "Windows 11",
            "publicIp": "1.2.3.4",
            "kernel": "chrome",
            "kernelVersion": "127",
        },
    }
    assert calls[3][2] == {
        "account_id": "shop_sync_runner",
        "headless": "1",
    }


@pytest.mark.asyncio
async def test_get_sync_browser_ws_falls_back_when_cloud_update_fails(monkeypatch):
    async with async_session() as db:
        service = XHSService(db)
        env = XHSEnvironment(
            id=203,
            shop_id="shop_sync_runner",
            account_name="测试3",
            status="active",
            sync_cloud_session_id="session_203",
            sync_cloud_api_key="api_key_203",
            sync_cloud_update_config='{"flag":2,"browser":{"system":{"$pick":["Windows 10"]},"publicIp":"2.3.4.5","kernel":"chrome","kernelVersion":"122"}}',
        )

        calls: list[str] = []

        class _FakeResponse:
            def __init__(self, status_code: int, payload: dict):
                self.status_code = status_code
                self._payload = payload
                self.content = b"1"

            def json(self):
                return self._payload

        class _FakeClient:
            def __init__(self, *args, headers=None, **kwargs):
                self._headers = headers or {}

            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return False

            async def post(self, url: str, json: dict | None = None):
                calls.append(url)
                if url == f"{xhs_service_module.YUNDENG_CLOUD_API}/v2/cloudbrowser/api/user/sessions/update":
                    return _FakeResponse(200, {"code": 500, "msg": "update failed"})
                if url == f"{xhs_service_module.YUNDENG_API}/api/v2/browser/start":
                    return _FakeResponse(200, {"code": 0, "data": {"ws": {"puppeteer": "ws://127.0.0.1:9444/devtools/browser/fallback"}}})
                raise AssertionError(f"unexpected url: {url}")

        monkeypatch.setattr(xhs_service_module, "YUNDENG_CLOUD_OPEN_TOKEN", "cloud-open-token")
        monkeypatch.setattr(xhs_service_module.httpx, "AsyncClient", _FakeClient)
        monkeypatch.setattr(XHSService, "_probe_browser_ws", lambda self, ws_url: _async_true())

        ws_url = await service._request_browser_ws_for_online_environment(env)

    assert ws_url == "ws://127.0.0.1:9444/devtools/browser/fallback"
    assert calls == [
        f"{xhs_service_module.YUNDENG_CLOUD_API}/v2/cloudbrowser/api/user/sessions/update",
        f"{xhs_service_module.YUNDENG_API}/api/v2/browser/start",
    ]


def test_materialize_sync_browser_start_config_supports_random_directives():
    result = XHSService._materialize_sync_browser_start_config(
        {
            "headless": {"$pick": ["0"]},
            "remote_debugging_port": {"$rand_int": [45000, 45000]},
            "session_tag": {"$uuid": True},
            "proxy": {
                "enabled": {"$bool": True},
            },
        }
    )

    assert result["headless"] == "0"
    assert result["remote_debugging_port"] == 45000
    assert isinstance(result["session_tag"], str)
    assert len(result["session_tag"]) == 32
    assert isinstance(result["proxy"]["enabled"], bool)


@pytest.mark.asyncio
async def test_run_sync_browser_warmup_prefetches_current_and_target_profile(monkeypatch):
    async with async_session() as db:
        service = XHSService(db)
        persona = xhs_service_module.SyncSessionPersona(
            profile_prep_range=(1.0, 1.0),
            account_pause_range=(1.0, 1.0),
            account_long_pause_range=(2.0, 2.0),
            detail_pause_range=(1.0, 1.0),
            detail_long_pause_range=(2.0, 2.0),
            retry_backoff_range=(1.0, 1.0),
            context_switch_range=(1.0, 1.0),
            inter_batch_pause_range=(1.0, 1.0),
            env_order_window=(2, 2),
            detail_order_window=(3, 3),
            warmup_rounds=2,
            warmup_note_limit=5,
            use_profile_peek=True,
            warmup_detail_peek_probability=0.9,
            extra_long_pause_probability=0.1,
        )
        seen: list[tuple[str, str, int]] = []

        async def fake_fetch_current_account_notes(self: XHSService, api_base: str | None = None, limit: int = 60):
            seen.append(("current", str(api_base), limit))
            return {"feeds": [{"feed_id": "feed_current", "xsec_token": "token_current"}]}

        async def fake_fetch_profile_account_notes(
            self: XHSService,
            profile_url: str,
            api_base: str | None = None,
            limit: int = 60,
            **kwargs,
        ):
            seen.append(("profile", str(api_base), limit))
            return {"feeds": [{"feed_id": "feed_profile", "xsec_token": "token_profile"}]}

        async def fake_sleep_between_sync_batches(self: XHSService, active_persona):
            seen.append(("sleep", "batch", active_persona.warmup_rounds))
            return None

        async def fake_sleep_between_account_note_details(self: XHSService, active_persona):
            seen.append(("sleep", "detail", active_persona.warmup_note_limit))
            return None

        async def fake_fetch_account_note_detail_metrics(
            self: XHSService,
            feed_id: str,
            xsec_token: str | None,
            *,
            api_base: str | None = None,
            persona=None,
        ):
            seen.append((f"detail:{feed_id}", str(api_base), 1))
            return {"liked_count": 1, "comment_count": 0, "collected_count": 0, "share_count": 0, "published_at": None}

        monkeypatch.setattr(XHSService, "_fetch_current_account_notes", fake_fetch_current_account_notes)
        monkeypatch.setattr(XHSService, "_fetch_profile_account_notes", fake_fetch_profile_account_notes)
        monkeypatch.setattr(XHSService, "_sleep_between_sync_batches", fake_sleep_between_sync_batches)
        monkeypatch.setattr(XHSService, "_sleep_between_account_note_details", fake_sleep_between_account_note_details)
        monkeypatch.setattr(XHSService, "_fetch_account_note_detail_metrics", fake_fetch_account_note_detail_metrics)
        monkeypatch.setattr(
            xhs_service_module,
            "_SYNC_BROWSER_CONFIG_RNG",
            type(
                "_WarmupRng",
                (),
                {
                    "random": lambda self: 0.1,
                    "choice": lambda self, items: items[0],
                },
            )(),
        )

        await service._run_sync_browser_warmup(
            api_base="http://mcp.test",
            persona=persona,
            target_profile_url="https://www.xiaohongshu.com/user/profile/abc?xsec_token=xyz",
        )

    assert seen == [
        ("current", "http://mcp.test", 5),
        ("sleep", "detail", 5),
        ("detail:feed_current", "http://mcp.test", 1),
        ("sleep", "batch", 2),
        ("current", "http://mcp.test", 5),
        ("sleep", "detail", 5),
        ("detail:feed_current", "http://mcp.test", 1),
        ("profile", "http://mcp.test", 5),
        ("sleep", "detail", 5),
        ("detail:feed_profile", "http://mcp.test", 1),
    ]


@pytest.mark.asyncio
async def test_fetch_profile_account_notes_allows_profile_url_without_xsec_token(monkeypatch):
    async with async_session() as db:
        service = XHSService(db)
        calls: list[tuple[str, dict | None]] = []
        client_kwargs: list[dict] = []

        class _FakeResponse:
            def __init__(self, status_code: int, payload: dict):
                self.status_code = status_code
                self._payload = payload
                self.content = b"1"

            def json(self):
                return self._payload

        class _FakeClient:
            def __init__(self, *args, **kwargs):
                client_kwargs.append(kwargs)

            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return False

            async def post(self, url: str, json: dict | None = None):
                calls.append((url, json))
                return _FakeResponse(
                    200,
                    {
                        "code": 0,
                        "data": {
                            "userBasicInfo": {"nickname": "云辉安懂车学长", "redId": "red_001"},
                            "feeds": [
                                {
                                    "id": "feed_001",
                                    "xsecToken": "feed_token_001",
                                    "noteCard": {
                                        "displayTitle": "帖子标题",
                                        "interactInfo": {
                                            "likedCount": 3,
                                            "commentCount": 2,
                                            "collectedCount": 1,
                                            "sharedCount": 4,
                                        },
                                    },
                                }
                            ],
                        },
                    },
                )

        monkeypatch.setattr(xhs_service_module.httpx, "AsyncClient", _FakeClient)

        payload = await service._fetch_profile_account_notes(
            "https://www.xiaohongshu.com/user/profile/69afd25c000000003303a2bd",
            api_base="http://mcp.test",
            limit=5,
        )

    assert calls == [
        (
            "http://mcp.test/api/v1/user/profile",
            {"user_id": "69afd25c000000003303a2bd"},
        )
    ]
    assert client_kwargs[0]["timeout"] == xhs_service_module.XHS_PROFILE_FETCH_TIMEOUT_SECONDS
    assert payload["profile_nickname"] == "云辉安懂车学长"
    assert payload["red_id"] == "red_001"
    assert payload["feeds"][0]["feed_id"] == "feed_001"
    assert payload["feeds"][0]["xsec_token"] == "feed_token_001"
    assert payload["feeds"][0]["liked_count"] == 3
    assert payload["feeds"][0]["comment_count"] == 2
    assert payload["feeds"][0]["collected_count"] == 1
    assert payload["feeds"][0]["share_count"] == 4


@pytest.mark.asyncio
async def test_fetch_profile_account_notes_includes_mcp_error_detail(monkeypatch):
    async with async_session() as db:
        service = XHSService(db)

        class _FakeResponse:
            status_code = 500
            content = b"error"
            text = ""

            @staticmethod
            def json():
                return {
                    "message": "获取用户主页失败",
                    "error": {"details": "browser context canceled"},
                }

        class _FakeClient:
            def __init__(self, *args, **kwargs):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return False

            async def post(self, url: str, json: dict | None = None):
                return _FakeResponse()

        monkeypatch.setattr(xhs_service_module.httpx, "AsyncClient", _FakeClient)

        with pytest.raises(RuntimeError, match="获取用户主页失败.*browser context canceled"):
            await service._fetch_profile_account_notes(
                "https://www.xiaohongshu.com/user/profile/69afd25c000000003303a2bd",
                api_base="http://mcp.test",
                limit=5,
            )


@pytest.mark.asyncio
async def test_fetch_profile_account_notes_preserves_missing_interact_fields_as_none(client, monkeypatch):
    async with async_session() as db:
        service = XHSService(db)
        calls: list[tuple[str, dict | None]] = []

        class _FakeResponse:
            def __init__(self, status_code: int, payload: dict):
                self.status_code = status_code
                self._payload = payload
                self.content = b"ok"

            def json(self):
                return self._payload

        class _FakeClient:
            def __init__(self, *args, **kwargs):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return False

            async def post(self, url: str, json: dict | None = None):
                calls.append((url, json))
                return _FakeResponse(
                    200,
                    {
                        "code": 0,
                        "data": {
                            "userBasicInfo": {"nickname": "云辉安懂车学长", "redId": "red_001"},
                            "feeds": [
                                {
                                    "id": "feed_001",
                                    "xsecToken": "feed_token_001",
                                    "noteCard": {
                                        "displayTitle": "帖子标题",
                                        "interactInfo": {
                                            "likedCount": 3,
                                        },
                                    },
                                }
                            ],
                        },
                    },
                )

        monkeypatch.setattr(xhs_service_module.httpx, "AsyncClient", _FakeClient)

        payload = await service._fetch_profile_account_notes(
            "https://www.xiaohongshu.com/user/profile/69afd25c000000003303a2bd",
            api_base="http://mcp.test",
            limit=5,
        )

    assert calls == [
        (
            "http://mcp.test/api/v1/user/profile",
            {"user_id": "69afd25c000000003303a2bd"},
        )
    ]
    assert payload["feeds"][0]["liked_count"] == 3
    assert payload["feeds"][0]["comment_count"] is None
    assert payload["feeds"][0]["collected_count"] is None
    assert payload["feeds"][0]["share_count"] is None


@pytest.mark.asyncio
async def test_sync_account_notes_keeps_unknown_posts_between_known_posts(client, monkeypatch):
    async with async_session() as db:
        db.add_all([
            XHSEnvironment(id=610, shop_id="shop_publish_610", account_name="发布账号B", status="active", profile_url="https://example.com/profile"),
            XHSEnvironment(id=611, shop_id="shop_runner_611", account_name="测试2", status="active", is_sync_runner=True),
        ])
        db.add_all([
            XHSAccountNote(
                id=621,
                environment_id=610,
                account_name="发布账号B",
                feed_id="feed_known_latest",
                title="已知最新",
                ai_origin_type="manual",
                sort_index=0,
            ),
            XHSAccountNote(
                id=622,
                environment_id=610,
                account_name="发布账号B",
                feed_id="feed_known_oldest",
                title="已知最老",
                ai_origin_type="manual",
                sort_index=1,
            ),
        ])
        await db.commit()

    fetch_calls: list[dict] = []

    async def fake_fetch_profile_account_notes(
        self: XHSService,
        profile_url: str,
        api_base: str,
        limit: int = 60,
        **kwargs,
    ):
        fetch_calls.append(kwargs)
        return {
            "profile_nickname": "发布账号B",
            "red_id": "red_publish_b",
            "feeds": [
                {
                    "feed_id": "feed_new_top",
                    "xsec_token": "N" * 46,
                    "title": "顶部新帖",
                    "cover_image_url": "https://example.com/new.jpg",
                    "liked_count": 9,
                    "comment_count": 4,
                    "collected_count": 3,
                    "share_count": 2,
                    "sort_index": 0,
                },
                {
                    "feed_id": "feed_known_latest",
                    "xsec_token": "K" * 46,
                    "title": "已知最新",
                    "cover_image_url": "https://example.com/known-latest.jpg",
                    "liked_count": 8,
                    "comment_count": 3,
                    "collected_count": 2,
                    "share_count": 1,
                    "sort_index": 1,
                },
                {
                    "feed_id": "feed_older_unknown",
                    "xsec_token": "O" * 46,
                    "title": "更老未知",
                    "cover_image_url": "https://example.com/older.jpg",
                    "liked_count": 1,
                    "comment_count": 0,
                    "collected_count": 0,
                    "share_count": 0,
                    "sort_index": 2,
                },
                {
                    "feed_id": "feed_known_oldest",
                    "xsec_token": "Z" * 46,
                    "title": "已知最老",
                    "cover_image_url": "https://example.com/known-oldest.jpg",
                    "liked_count": 5,
                    "comment_count": 2,
                    "collected_count": 1,
                    "share_count": 0,
                    "sort_index": 3,
                },
            ],
        }

    async def fake_sleep_sync_profile_prep(self: XHSService, persona=None):
        return None

    async def fake_apply_pending_cover_localizations(self: XHSService, pending_cover_localizations):
        return None

    monkeypatch.setattr(XHSService, "_fetch_profile_account_notes", fake_fetch_profile_account_notes)
    monkeypatch.setattr(XHSService, "_sleep_sync_profile_prep", fake_sleep_sync_profile_prep)
    monkeypatch.setattr(XHSService, "_apply_pending_account_note_cover_localizations", fake_apply_pending_cover_localizations)

    async with async_session() as db:
        service = XHSService(db)
        publish_env = await db.get(XHSEnvironment, 610)
        runner_env = await db.get(XHSEnvironment, 611)
        assert publish_env is not None
        assert runner_env is not None

        result = await service._sync_account_notes_with_api(
            publish_env,
            api_base="http://localhost:18061",
            limit=60,
            runner_envs=[runner_env],
            assigned_runner_env=runner_env,
        )

    assert result["created_notes"] == 2
    assert result["updated_notes"] == 2
    assert result["total_notes"] == 4
    assert fetch_calls and fetch_calls[0]["scroll_mode"] == "input"
    assert fetch_calls[0]["stop_feed_id"] == "feed_known_oldest"

    async with async_session() as db:
        notes = list((await db.execute(
            select(XHSAccountNote)
            .where(XHSAccountNote.environment_id == 610)
            .order_by(XHSAccountNote.sort_index.asc(), XHSAccountNote.id.asc())
        )).scalars().all())

    assert [note.feed_id for note in notes] == [
        "feed_new_top",
        "feed_known_latest",
        "feed_older_unknown",
        "feed_known_oldest",
    ]


@pytest.mark.asyncio
async def test_sync_account_notes_first_sync_does_not_force_profile_scroll(client, monkeypatch):
    async with async_session() as db:
        db.add_all([
            XHSEnvironment(id=710, shop_id="shop_publish_710", account_name="发布账号首刷", status="active", profile_url="https://example.com/profile"),
            XHSEnvironment(id=711, shop_id="shop_runner_711", account_name="测试2", status="active", is_sync_runner=True),
        ])
        await db.commit()

    fetch_calls: list[dict] = []

    async def fake_fetch_profile_account_notes(
        self: XHSService,
        profile_url: str,
        api_base: str,
        limit: int = 60,
        **kwargs,
    ):
        fetch_calls.append(kwargs)
        return {
            "profile_nickname": "发布账号首刷",
            "red_id": "red_publish_first_sync",
            "feeds": [
                {
                    "feed_id": "feed_first_sync_1",
                    "xsec_token": "A" * 46,
                    "title": "首刷帖子1",
                    "cover_image_url": "https://example.com/first-1.jpg",
                    "liked_count": 3,
                    "comment_count": 1,
                    "collected_count": 1,
                    "share_count": 0,
                    "sort_index": 0,
                },
                {
                    "feed_id": "feed_first_sync_2",
                    "xsec_token": "B" * 46,
                    "title": "首刷帖子2",
                    "cover_image_url": "https://example.com/first-2.jpg",
                    "liked_count": 2,
                    "comment_count": 0,
                    "collected_count": 0,
                    "share_count": 0,
                    "sort_index": 1,
                },
            ],
        }

    async def fake_sleep_sync_profile_prep(self: XHSService, persona=None):
        return None

    async def fake_apply_pending_cover_localizations(self: XHSService, pending_cover_localizations):
        return None

    monkeypatch.setattr(XHSService, "_fetch_profile_account_notes", fake_fetch_profile_account_notes)
    monkeypatch.setattr(XHSService, "_sleep_sync_profile_prep", fake_sleep_sync_profile_prep)
    monkeypatch.setattr(XHSService, "_apply_pending_account_note_cover_localizations", fake_apply_pending_cover_localizations)

    async with async_session() as db:
        service = XHSService(db)
        publish_env = await db.get(XHSEnvironment, 710)
        runner_env = await db.get(XHSEnvironment, 711)
        assert publish_env is not None
        assert runner_env is not None

        result = await service._sync_account_notes_with_api(
            publish_env,
            api_base="http://localhost:18061",
            limit=60,
            runner_envs=[runner_env],
            assigned_runner_env=runner_env,
        )

    assert result["created_notes"] == 2
    assert result["updated_notes"] == 0
    assert result["total_notes"] == 2
    assert fetch_calls
    assert fetch_calls[0]["scroll_mode"] is None
    assert fetch_calls[0]["stop_feed_id"] is None
    assert fetch_calls[0]["max_feeds"] is None
    assert fetch_calls[0]["max_scroll_rounds"] is None
    assert fetch_calls[0]["max_stagnant_rounds"] is None


@pytest.mark.asyncio
async def test_extract_account_note_detail_data_reads_top_level_notecard_fields():
    async with async_session() as db:
        service = XHSService(db)
        payload = {
            "noteCard": {
                "displayTitle": "帖子标题",
                "desc": "这是正文第一段",
                "imageList": [
                    {"urlDefault": "https://img.example.com/1.jpg"},
                    {"urlDefault": "https://img.example.com/2.jpg"},
                ],
                "cover": {"urlDefault": "https://img.example.com/cover.jpg"},
            }
        }

        detail = service._extract_account_note_detail_data(payload, title="帖子标题")

    assert detail["content"] == "这是正文第一段"
    assert detail["content_status"] == "from_detail"
    assert detail["cover_image_url"] == "https://img.example.com/cover.jpg"
    assert detail["image_urls"] == [
        "https://img.example.com/1.jpg",
        "https://img.example.com/2.jpg",
    ]


@pytest.mark.asyncio
async def test_extract_account_note_detail_data_marks_title_only_text_as_missing():
    async with async_session() as db:
        service = XHSService(db)
        payload = {
            "noteCard": {
                "displayTitle": "帖子标题",
                "desc": "帖子标题",
            }
        }

        detail = service._extract_account_note_detail_data(payload, title="帖子标题")

    assert detail["content"] is None
    assert detail["content_status"] == "missing_from_source"
    assert "仅返回标题" in str(detail["content_missing_reason"])


@pytest.mark.asyncio
async def test_refresh_report_cache_runs_as_background_job(client, monkeypatch):
    await _seed_users_and_envs()
    scheduled_tasks: list[asyncio.Task] = []
    original_create_task = asyncio.create_task

    async def fake_refresh_jg_report_cache(
        self: XHSService,
        report_type: str,
        account_id: str | None = None,
        account_name: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        days: int = 30,
    ) -> dict:
        assert report_type == "standard"
        assert account_id is None
        assert account_name is None
        assert start_date is None
        assert end_date is None
        assert days == 30
        return {
            "report_type": report_type,
            "start_date": "2026-04-22",
            "end_date": "2026-05-21",
            "account_id": account_id,
            "updated_accounts": 46,
            "updated_rows": 8508,
            "errors": [],
        }

    def fake_create_task(coro):
        task = original_create_task(coro)
        scheduled_tasks.append(task)
        return task

    monkeypatch.setattr(XHSService, "refresh_jg_report_cache", fake_refresh_jg_report_cache)
    monkeypatch.setattr(xhs_api_module.asyncio, "create_task", fake_create_task)

    response = await client.post(
        "/api/v1/xhs/report/refresh?report_type=standard&days=30",
        headers=make_auth_headers(1),
    )

    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["job_type"] == "report_refresh"
    assert payload["status"] == "queued"
    assert scheduled_tasks

    await asyncio.gather(*scheduled_tasks)

    job_resp = await client.get(
        f"/api/v1/xhs/report/refresh-jobs/{payload['job_id']}",
        headers=make_auth_headers(1),
    )
    assert job_resp.status_code == 200
    job = job_resp.json()["data"]
    assert job["status"] == "succeeded"
    assert job["result"]["updated_accounts"] == 46
    assert job["result"]["updated_rows"] == 8508


@pytest.mark.asyncio
async def test_fetch_report_token_delegates_to_report_worker_when_configured(monkeypatch):
    monkeypatch.setattr(xhs_service_module, "XHS_REPORT_WORKER_API_BASE", "http://report-worker.test")

    async def fake_call_report_worker_api(
        cls,
        method: str,
        path: str,
        *,
        json: dict | None = None,
        params: dict | None = None,
        timeout: float = 60.0,
    ) -> dict:
        assert method == "GET"
        assert path == "/api/v1/xhs/internal/report-token"
        assert params == {"account_id": "10279885"}
        assert json is None
        return {"code": 0, "data": {"account_id": "10279885", "token": "worker-token-001"}}

    monkeypatch.setattr(XHSService, "_call_report_worker_api", classmethod(fake_call_report_worker_api))

    async with async_session() as db:
        service = XHSService(db)
        token = await service._fetch_report_token("10279885")

    assert token == "worker-token-001"


@pytest.mark.asyncio
async def test_get_creative_report_ai_compare_excludes_missing_and_unset(client):
    await _seed_users_and_envs()
    today = utc_now_naive().date()
    day_one = today - timedelta(days=2)
    day_two = today - timedelta(days=1)

    async with async_session() as db:
        db.add_all([
            XHSAccountNote(
                environment_id=101,
                account_name="账号A",
                feed_id="feed_manual",
                title="手工",
                ai_origin_type="manual",
                sort_index=0,
            ),
            XHSAccountNote(
                environment_id=101,
                account_name="账号A",
                feed_id="feed_text_ai",
                title="文案AI",
                ai_origin_type="text_ai",
                sort_index=1,
            ),
            XHSAccountNote(
                environment_id=101,
                account_name="账号A",
                feed_id="feed_unset",
                title="未设置",
                ai_origin_type="",
                sort_index=2,
            ),
        ])
        db.add_all([
            XHSReportDaily(
                report_type="creative",
                account_id="acc_1",
                account_name="账号A",
                report_date=day_one,
                campaign_id="cmp_manual",
                payload={
                    "time": day_one.isoformat(),
                    "note_material": "feed_manual",
                    "fee": "100",
                    "impression": "1000",
                    "click": "50",
                    "interaction": "20",
                    "play_5s": "40",
                    "message_consult": "5",
                    "initiative_message": "4",
                    "msg_leads_num": "2",
                    "shop_pay_order_num_15d": "1",
                },
            ),
            XHSReportDaily(
                report_type="creative",
                account_id="acc_1",
                account_name="账号A",
                report_date=day_two,
                campaign_id="cmp_text_ai",
                payload={
                    "time": day_two.isoformat(),
                    "note_material": "feed_text_ai",
                    "fee": "60",
                    "impression": "800",
                    "click": "20",
                    "interaction": "10",
                    "play_5s": "18",
                    "message_consult": "3",
                    "initiative_message": "2",
                    "msg_leads_num": "1",
                    "shop_pay_order_num_15d": "1",
                },
            ),
            XHSReportDaily(
                report_type="creative",
                account_id="acc_1",
                account_name="账号A",
                report_date=day_two,
                campaign_id="cmp_missing",
                payload={
                    "time": day_two.isoformat(),
                    "note_material": "feed_missing",
                    "fee": "999",
                    "impression": "9999",
                    "click": "999",
                },
            ),
            XHSReportDaily(
                report_type="creative",
                account_id="acc_1",
                account_name="账号A",
                report_date=day_two,
                campaign_id="cmp_unset",
                payload={
                    "time": day_two.isoformat(),
                    "note_material": "feed_unset",
                    "fee": "500",
                    "impression": "5000",
                    "click": "500",
                },
            ),
        ])
        await db.commit()

    async with async_session() as db:
        service = XHSService(db)
        result = await service.get_creative_report_ai_compare(account_id="acc_1", days=30)

    assert result["report_type"] == "creative"
    assert [item["key"] for item in result["tags"]] == ["manual", "text_ai", "image_ai", "all_ai"]
    day_periods = result["granularities"]["day"]["periods"]
    assert len(day_periods) == 2
    first_day = next(item for item in day_periods if item["period_key"] == day_one.isoformat())
    second_day = next(item for item in day_periods if item["period_key"] == day_two.isoformat())
    assert first_day["tags"]["manual"]["fee"] == 100.0
    assert first_day["tags"]["manual"]["ctr"] == 5.0
    assert first_day["tags"]["manual"]["message_consult_cost"] == 20.0
    assert second_day["tags"]["text_ai"]["fee"] == 60.0
    assert second_day["tags"]["text_ai"]["shop_pay_order_cvr_15d"] == 5.0
    assert result["tags"][0]["all_time_note_count"] == 1
    assert result["tags"][1]["all_time_note_count"] == 1
    assert result["all_time_note_totals_by_tag"]["manual"] == 1
    assert result["all_time_note_totals_by_tag"]["text_ai"] == 1
    assert result["granularities"]["day"]["totals_by_tag"]["manual"]["impression"] == 1000
    assert result["granularities"]["day"]["totals_by_tag"]["text_ai"]["click"] == 20
    assert result["granularities"]["day"]["totals_by_tag"]["image_ai"]["fee"] == 0.0
    assert result["granularities"]["day"]["overall"]["fee"] == 160.0
    assert result["granularities"]["day"]["overall"]["note_count"] == 2
    assert result["granularities"]["day"]["overall"]["ctr"] == 3.89
    assert result["granularities"]["day"]["overall"]["cpc"] == 2.29
    assert result["granularities"]["month"]["overall"]["click"] == 70


@pytest.mark.asyncio
async def test_sync_stats_missing_identifiers_returns_specific_message(client):
    await _seed_users_and_envs()
    async with async_session() as db:
        db.add(
            XHSPost(
                id=204,
                user_id=2,
                environment_id=101,
                title="need-sync",
                content="c4",
                image_urls=["/tmp/d.jpg"],
                tags=["t4"],
                status="success",
                feed_id=None,
                xsec_token=None,
            )
        )
        await db.commit()

    resp = await client.get("/api/v1/xhs/posts/204/stats", headers=make_auth_headers(2))
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["code"] == 1
    assert "缺少 feed_id 或 xsec_token" in payload["message"]


def test_extract_deleted_message_from_500_body_text():
    text = '{"success":false,"message":"note not found","error":"deleted"}'
    marker = XHSService._extract_deleted_message(text)
    assert marker is not None


@pytest.mark.asyncio
async def test_sync_stats_deleted_result_returns_code_zero_and_deleted_status(client, monkeypatch):
    await _seed_users_and_envs()
    await _seed_posts()

    async def fake_sync_single_post_verbose(self: XHSService, post: XHSPost):
        post.status = "deleted"
        await self.db.commit()
        return type("R", (), {"success": False, "reason": "post_deleted", "message": "帖子已删除或不可见，无法同步"})()

    monkeypatch.setattr(XHSService, "sync_single_post_verbose", fake_sync_single_post_verbose)

    resp = await client.get("/api/v1/xhs/posts/201/stats", headers=make_auth_headers(2))
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["code"] == 0
    assert "状态已更新为已删除" in payload["message"]
    assert payload["data"]["status"] == "deleted"
    assert payload["data"]["sync_reason"] == "post_deleted"


@pytest.mark.asyncio
async def test_sync_marks_deleted_when_feed_detail_500_but_post_url_indicates_missing(client, monkeypatch):
    await _seed_users_and_envs()
    await _seed_posts()

    async def fake_fetch_and_update_stats(
        self: XHSService,
        post: XHSPost,
        api_base: str | None = None,
    ):
        post.status = "deleted"
        await self.db.commit()
        return type("R", (), {"success": False, "reason": "post_deleted", "message": "帖子已删除或不可见，无法同步"})()

    monkeypatch.setattr(XHSService, "_fetch_and_update_stats", fake_fetch_and_update_stats)
    async def fake_acquire_ready_browser_ws(self: XHSService, shop_id: str):
        return "ws://fake-browser"

    monkeypatch.setattr(XHSService, "_acquire_ready_browser_ws", fake_acquire_ready_browser_ws)
    async def fake_check_mcp_running(self: XHSService, api_base=None) -> bool:
        return True
    monkeypatch.setattr(XHSService, "_check_mcp_running", fake_check_mcp_running)
    _patch_publish_runtime(monkeypatch)

    resp = await client.get("/api/v1/xhs/posts/201/stats", headers=make_auth_headers(2))
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["code"] == 0
    assert payload["data"]["status"] == "deleted"


@pytest.mark.asyncio
async def test_publish_now_marks_success_when_api_success_but_missing_identifiers(client, monkeypatch):
    await _seed_users_and_envs()

    async with async_session() as db:
        service = XHSService(db)
        user = await db.get(User, 2)
        env = await db.get(XHSEnvironment, 101)
        assert user is not None
        assert env is not None

        async def fake_get_browser_ws(self: XHSService, shop_id: str):
            return "ws://fake-browser"

        async def fake_check_mcp_running(self: XHSService, api_base=None) -> bool:
            return True

        async def fake_call_publish_api(self: XHSService, *args, **kwargs):
            return None, None, True

        async def fake_recover(self: XHSService, *args, **kwargs):
            return None, None

        monkeypatch.setattr(XHSService, "_acquire_ready_browser_ws", fake_get_browser_ws)
        monkeypatch.setattr(XHSService, "_check_mcp_running", fake_check_mcp_running)
        monkeypatch.setattr(XHSService, "_call_publish_api", fake_call_publish_api)
        monkeypatch.setattr(XHSService, "_recover_published_identifiers", fake_recover)
        _patch_publish_runtime(monkeypatch)

        post = await service.publish_now(
            user=user,
            env=env,
            title="publish-ok-no-ids",
            content="正文",
            image_paths=["/tmp/a.jpg"],
            tags=[],
            is_original=False,
            visibility="公开可见",
            background=False,
        )

        assert post.status == "success"
        assert post.feed_id is None
        assert post.xsec_token is None
        assert post.published_at is not None
        assert post.scheduled_at is None
        result = await db.execute(
            select(Copywriting).where(
                Copywriting.created_by == user.id,
                Copywriting.title == "publish-ok-no-ids",
                Copywriting.content == "正文",
                Copywriting.deleted_at.is_(None),
            )
        )
        saved = result.scalar_one_or_none()
        assert saved is not None


@pytest.mark.asyncio
async def test_publish_now_recovers_identifiers_and_avoids_duplicate_tags(client, monkeypatch):
    await _seed_users_and_envs()

    async with async_session() as db:
        service = XHSService(db)
        user = await db.get(User, 2)
        env = await db.get(XHSEnvironment, 101)
        assert user is not None
        assert env is not None

        captured: dict[str, object] = {"tags": [], "content": ""}

        async def fake_get_browser_ws(self: XHSService, shop_id: str):
            return "ws://fake-browser"

        async def fake_check_mcp_running(self: XHSService, api_base=None) -> bool:
            return True

        async def fake_call_publish_api(self: XHSService, title, content, images, tags, is_original, visibility):
            captured["tags"] = tags
            captured["content"] = content
            return None, None, True

        async def fake_recover(
            self: XHSService,
            expected_title,
            expected_content,
            current_feed_id,
            current_xsec_token,
            mcp_api=None,
        ):
            return "feed_recovered_1", "xsec_recovered_1"

        monkeypatch.setattr(XHSService, "_acquire_ready_browser_ws", fake_get_browser_ws)
        monkeypatch.setattr(XHSService, "_check_mcp_running", fake_check_mcp_running)
        monkeypatch.setattr(XHSService, "_call_publish_api", fake_call_publish_api)
        monkeypatch.setattr(XHSService, "_recover_published_identifiers", fake_recover)
        _patch_publish_runtime(monkeypatch)

        post = await service.publish_now(
            user=user,
            env=env,
            title="publish-recover",
            content="正文里有 #高尔夫 标签",
            image_paths=["/tmp/a.jpg"],
            tags=["高尔夫"],
            is_original=False,
            visibility="公开可见",
            background=False,
        )

        assert captured["tags"] == ["高尔夫"]
        assert "#" not in str(captured["content"])
        assert post.status == "success"
        assert post.feed_id == "feed_recovered_1"
        assert post.xsec_token == "xsec_recovered_1"
        assert post.post_url == "https://www.xiaohongshu.com/explore/feed_recovered_1?xsec_token=xsec_recovered_1"


@pytest.mark.asyncio
async def test_sync_stats_recovers_identifiers_when_missing(client, monkeypatch):
    await _seed_users_and_envs()
    async with async_session() as db:
        db.add(
            XHSPost(
                id=210,
                user_id=2,
                environment_id=101,
                title="recover-sync",
                content="正文内容",
                image_urls=["/tmp/a.jpg"],
                tags=["t"],
                status="success",
                feed_id=None,
                xsec_token=None,
            )
        )
        await db.commit()

    async def fake_recover(
        self: XHSService,
        expected_title,
        expected_content,
        current_feed_id,
        current_xsec_token,
        **kwargs,
    ):
        return "feed_sync_1", "xsec_sync_1"

    async def fake_check_mcp_running(self: XHSService, api_base=None) -> bool:
        return True

    async def fake_fetch_and_update_stats(
        self: XHSService,
        post: XHSPost,
        api_base: str | None = None,
    ):
        assert post.feed_id == "feed_sync_1"
        assert post.xsec_token == "xsec_sync_1"
        post.like_count = 99
        await self.db.commit()
        return type("R", (), {"success": True, "reason": "ok", "message": "同步成功"})()

    monkeypatch.setattr(XHSService, "_recover_published_identifiers", fake_recover)
    monkeypatch.setattr(XHSService, "_check_mcp_running", fake_check_mcp_running)
    monkeypatch.setattr(XHSService, "_fetch_and_update_stats", fake_fetch_and_update_stats)
    monkeypatch.setattr(XHSService, "_acquire_ready_browser_ws", lambda self, shop_id: _async_ws())
    _patch_publish_runtime(monkeypatch)

    resp = await client.get("/api/v1/xhs/posts/210/stats", headers=make_auth_headers(2))
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["code"] == 0
    assert payload["data"]["feed_id"] == "feed_sync_1"
    assert payload["data"]["like_count"] == 99


@pytest.mark.asyncio
async def test_publish_now_keeps_failed_when_api_response_not_success(client, monkeypatch):
    await _seed_users_and_envs()

    async with async_session() as db:
        service = XHSService(db)
        user = await db.get(User, 2)
        env = await db.get(XHSEnvironment, 101)
        assert user is not None
        assert env is not None

        async def fake_get_browser_ws(self: XHSService, shop_id: str):
            return "ws://fake-browser"

        async def fake_check_mcp_running(self: XHSService, api_base=None) -> bool:
            return True

        async def fake_call_publish_api(self: XHSService, *args, **kwargs):
            return None, None, False

        monkeypatch.setattr(XHSService, "_acquire_ready_browser_ws", fake_get_browser_ws)
        monkeypatch.setattr(XHSService, "_check_mcp_running", fake_check_mcp_running)
        monkeypatch.setattr(XHSService, "_call_publish_api", fake_call_publish_api)
        _patch_publish_runtime(monkeypatch)

        post = await service.publish_now(
            user=user,
            env=env,
            title="publish-fail-no-ids",
            content="正文",
            image_paths=["/tmp/a.jpg"],
            tags=[],
            is_original=False,
            visibility="公开可见",
            background=False,
        )

        assert post.status == "failed"
        assert post.feed_id is None
        assert post.xsec_token is None
        assert post.published_at is None
        result = await db.execute(
            select(Copywriting).where(
                Copywriting.created_by == user.id,
                Copywriting.title == "publish-fail-no-ids",
                Copywriting.deleted_at.is_(None),
            )
        )
        saved = result.scalar_one_or_none()
        assert saved is None


@pytest.mark.asyncio
async def test_publish_now_uses_global_queue(client, monkeypatch):
    await _seed_users_and_envs()

    async with async_session() as db:
        service = XHSService(db)
        user = await db.get(User, 2)
        env = await db.get(XHSEnvironment, 101)
        assert user is not None
        assert env is not None

        calls: dict[str, int] = {"enqueue": 0}

        async def fake_enqueue(self, coro):
            calls["enqueue"] += 1
            return await coro

        async def fake_get_browser_ws(self: XHSService, shop_id: str):
            return "ws://fake-browser"

        async def fake_check_mcp_running(self: XHSService, api_base=None) -> bool:
            return True

        async def fake_call_publish_api(self: XHSService, *args, **kwargs):
            return "feed_queue_1", "token_queue_1", True

        monkeypatch.setattr(type(xhs_publish_queue), "enqueue", fake_enqueue)
        monkeypatch.setattr(XHSService, "_acquire_ready_browser_ws", fake_get_browser_ws)
        monkeypatch.setattr(XHSService, "_check_mcp_running", fake_check_mcp_running)
        monkeypatch.setattr(XHSService, "_call_publish_api", fake_call_publish_api)
        _patch_publish_runtime(monkeypatch)

        post = await service.publish_now(
            user=user,
            env=env,
            title="queue-test",
            content="正文",
            image_paths=["/tmp/a.jpg"],
            tags=[],
            is_original=False,
            visibility="公开可见",
            background=False,
        )

        assert calls["enqueue"] == 1
        assert post.status == "success"


@pytest.mark.asyncio
async def test_publish_now_serializes_same_environment(client, monkeypatch):
    await _seed_users_and_envs()

    order: list[str] = []
    running = 0
    max_running = 0

    async def fake_get_browser_ws(self: XHSService, shop_id: str):
        return "ws://fake-browser"

    async def fake_check_mcp_running(self: XHSService, api_base=None) -> bool:
        return True

    async def fake_call_publish_api(self: XHSService, title, *args, **kwargs):
        nonlocal running, max_running
        running += 1
        max_running = max(max_running, running)
        order.append(title)
        await asyncio.sleep(0.05)
        running -= 1
        return f"feed_{title}", f"token_{title}", True

    async def fake_enqueue(coro):
        return await coro

    monkeypatch.setattr(xhs_publish_queue, "enqueue", fake_enqueue)
    monkeypatch.setattr(XHSService, "_acquire_ready_browser_ws", fake_get_browser_ws)
    monkeypatch.setattr(XHSService, "_check_mcp_running", fake_check_mcp_running)
    monkeypatch.setattr(XHSService, "_call_publish_api", fake_call_publish_api)
    _patch_publish_runtime(monkeypatch)
    XHSService._env_publish_locks_by_loop = {}

    async def publish_one(title: str, content: str):
        async with async_session() as db:
            service = XHSService(db)
            user = await db.get(User, 2)
            env = await db.get(XHSEnvironment, 101)
            assert user is not None
            assert env is not None
            return await service.publish_now(
                user=user,
                env=env,
                title=title,
                content=content,
                image_paths=["/tmp/a.jpg"],
                tags=[],
                is_original=False,
                visibility="公开可见",
                background=False,
            )

    p1 = await publish_one("post-1", "正文1")
    p2 = await publish_one("post-2", "正文2")

    assert {p1.status, p2.status} == {"success"}
    assert order == ["post-1", "post-2"]
    assert max_running == 1


@pytest.mark.asyncio
async def test_publish_now_does_not_start_two_yundeng_in_parallel_across_envs(client, monkeypatch):
    await _seed_users_and_envs()

    await client.get("/api/v1/xhs/environments", headers=make_auth_headers(1))

    active_ws = 0
    max_active_ws = 0
    started: list[str] = []

    async def fake_get_browser_ws(self: XHSService, shop_id: str):
        nonlocal active_ws, max_active_ws
        active_ws += 1
        max_active_ws = max(max_active_ws, active_ws)
        started.append(shop_id)
        await asyncio.sleep(0.05)
        active_ws -= 1
        return "ws://fake-browser"

    async def fake_check_mcp_running(self: XHSService, api_base=None) -> bool:
        return True

    async def fake_call_publish_api(self: XHSService, *args, **kwargs):
        return "feed_parallel", "token_parallel", True

    monkeypatch.setattr(XHSService, "_acquire_ready_browser_ws", fake_get_browser_ws)
    monkeypatch.setattr(XHSService, "_check_mcp_running", fake_check_mcp_running)
    monkeypatch.setattr(XHSService, "_call_publish_api", fake_call_publish_api)
    _patch_publish_runtime(monkeypatch)

    async def publish_one(user_id: int, env_id: int, title: str):
        async with async_session() as db:
            service = XHSService(db)
            user = await db.get(User, user_id)
            env = await db.get(XHSEnvironment, env_id)
            assert user is not None
            assert env is not None
            return await service.publish_now(
                user=user,
                env=env,
                title=title,
                content="正文",
                image_paths=["/tmp/a.jpg"],
                tags=[],
                is_original=False,
                visibility="公开可见",
                background=False,
            )

    r1, r2 = await asyncio.gather(
        publish_one(2, 101, "env-101"),
        publish_one(1, 102, "env-102"),
    )

    assert {r1.status, r2.status} == {"success"}
    assert set(started) == {"shop_101", "shop_102"}
    assert max_active_ws == 2


@pytest.mark.asyncio
async def test_publish_queue_can_run_multiple_workers_across_different_envs(client, monkeypatch):
    await _seed_users_and_envs()

    temp_queue = RateLimitedQueue(max_concurrent=2, min_interval=0.0)
    monkeypatch.setattr(xhs_service_module, "xhs_publish_queue", temp_queue)

    active_ws = 0
    max_active_ws = 0
    entered: list[str] = []
    release = asyncio.Event()

    async def fake_get_browser_ws(self: XHSService, shop_id: str):
        nonlocal active_ws, max_active_ws
        active_ws += 1
        max_active_ws = max(max_active_ws, active_ws)
        entered.append(shop_id)
        if len(entered) >= 2:
            release.set()
        await asyncio.wait_for(release.wait(), timeout=1.0)
        active_ws -= 1
        return "ws://fake-browser"

    async def fake_check_mcp_running(self: XHSService, api_base=None) -> bool:
        return True

    async def fake_call_publish_api(self: XHSService, *args, **kwargs):
        return "feed_multi", "token_multi", True

    monkeypatch.setattr(XHSService, "_acquire_ready_browser_ws", fake_get_browser_ws)
    monkeypatch.setattr(XHSService, "_check_mcp_running", fake_check_mcp_running)
    monkeypatch.setattr(XHSService, "_call_publish_api", fake_call_publish_api)
    _patch_publish_runtime(monkeypatch)
    XHSService._env_publish_locks_by_loop = {}

    async def publish_one(user_id: int, env_id: int, title: str):
        async with async_session() as db:
            service = XHSService(db)
            user = await db.get(User, user_id)
            env = await db.get(XHSEnvironment, env_id)
            assert user is not None
            assert env is not None
            return await service.publish_now(
                user=user,
                env=env,
                title=title,
                content="正文",
                image_paths=["/tmp/a.jpg"],
                tags=[],
                is_original=False,
                visibility="公开可见",
                background=False,
            )

    r1, r2 = await asyncio.gather(
        publish_one(2, 101, "env-101"),
        publish_one(1, 102, "env-102"),
    )

    assert {r1.status, r2.status} == {"success"}
    assert set(entered) == {"shop_101", "shop_102"}
    assert max_active_ws == 2


@pytest.mark.asyncio
async def test_two_publish_jobs_can_enter_browser_start_concurrently_when_queue_has_two_workers(client, monkeypatch):
    await _seed_users_and_envs()
    queue = RateLimitedQueue(max_concurrent=2, min_interval=0.0)
    monkeypatch.setattr(xhs_service_module, "xhs_publish_queue", queue)
    XHSService._env_publish_locks_by_loop = {}

    active = 0
    max_active = 0
    entered: list[str] = []
    release = asyncio.Event()

    async def fake_get_browser_ws(self: XHSService, shop_id: str):
        nonlocal active, max_active
        active += 1
        max_active = max(max_active, active)
        entered.append(shop_id)
        if len(entered) >= 2:
            release.set()
        await asyncio.wait_for(release.wait(), timeout=1.0)
        active -= 1
        return "ws://fake-browser"

    async def fake_check_mcp_running(self: XHSService, api_base=None) -> bool:
        return True

    async def fake_call_publish_api(self: XHSService, *args, **kwargs):
        return "feed_x", "token_x", True

    async def fake_recover(self: XHSService, *args, **kwargs):
        return None, None

    monkeypatch.setattr(XHSService, "_acquire_ready_browser_ws", fake_get_browser_ws)
    monkeypatch.setattr(XHSService, "_check_mcp_running", fake_check_mcp_running)
    monkeypatch.setattr(XHSService, "_call_publish_api", fake_call_publish_api)
    monkeypatch.setattr(XHSService, "_recover_published_identifiers", fake_recover)
    _patch_publish_runtime(monkeypatch)

    async def run_one(env_id: int):
        async with async_session() as db:
            user = await db.get(User, 2 if env_id == 101 else 1)
            env = await db.get(XHSEnvironment, env_id)
            service = XHSService(db)
            return await service.publish_now(
                user=user,
                env=env,
                title=f"t-{env_id}",
                content="正文",
                image_paths=["/tmp/a.jpg"],
                tags=[],
                is_original=False,
                visibility="公开可见",
                background=False,
            )

    r1, r2 = await asyncio.gather(run_one(101), run_one(102))
    assert {r1.status, r2.status} == {"success"}
    assert set(entered) == {"shop_101", "shop_102"}
    assert max_active == 2


@pytest.mark.asyncio
async def test_homepage_profile_fetch_does_not_hold_database_transaction(client, monkeypatch):
    async with async_session() as db:
        db.add_all([
            XHSEnvironment(
                id=991,
                shop_id="shop_publish_991",
                account_name="事务边界账号",
                status="active",
                profile_url="https://example.com/profile/991",
            ),
            XHSEnvironment(
                id=992,
                shop_id="shop_runner_992",
                account_name="测试事务执行器",
                status="active",
                is_sync_runner=True,
            ),
            XHSAccountNote(
                id=993,
                environment_id=991,
                account_name="事务边界账号",
                feed_id="feed_991",
                title="已有帖子",
                ai_origin_type="manual",
                sort_index=0,
            ),
        ])
        await db.commit()

    transaction_states: list[bool] = []

    async def fake_fetch_profile_account_notes(
        self: XHSService,
        profile_url: str,
        api_base: str,
        limit: int = 60,
        **kwargs,
    ):
        transaction_states.append(self.db.in_transaction())
        return {
            "profile_nickname": "事务边界账号",
            "red_id": "red_991",
            "feeds": [{
                "feed_id": "feed_991",
                "xsec_token": "T" * 46,
                "title": "已有帖子",
                "cover_image_url": None,
                "liked_count": 1,
                "comment_count": 0,
                "collected_count": 0,
                "share_count": 0,
                "sort_index": 0,
            }],
        }

    async def fake_sleep_sync_profile_prep(self: XHSService, persona=None):
        return None

    monkeypatch.setattr(XHSService, "_fetch_profile_account_notes", fake_fetch_profile_account_notes)
    monkeypatch.setattr(XHSService, "_sleep_sync_profile_prep", fake_sleep_sync_profile_prep)

    async with async_session() as db:
        service = XHSService(db)
        publish_env = await db.get(XHSEnvironment, 991)
        runner_env = await db.get(XHSEnvironment, 992)
        assert publish_env is not None
        assert runner_env is not None

        result = await service._sync_account_notes_with_api(
            publish_env,
            api_base="http://localhost:18061",
            runner_envs=[runner_env],
            assigned_runner_env=runner_env,
        )

    assert result["updated_notes"] == 1
    assert transaction_states == [False]
