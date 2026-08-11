from __future__ import annotations

from datetime import date

import pytest

from app.api.v1.admin import xhs as module
from app.db.session import async_session
from app.models.user import User
from app.models.xhs_ad_account_assignment import XHSAdAccountBuyerAssignment, XHSAdAccountProfessionalMapping
from app.models.xhs_environment import XHSEnvironment
from app.models.xhs_report import XHSReportDaily, XHSReportToken
from app.services.xhs_schedule_service import XHSScheduleService
from app.services.xhs_service import XHSService
from tests.conftest import make_auth_headers


async def _seed_admin_xhs_data():
    async with async_session() as db:
        users = [
            User(id=1, username="admin", email="admin@example.com", hashed_password="x", role="admin"),
            User(id=2, username="operator", email="operator@example.com", hashed_password="x", role="xhs_ops"),
            User(id=3, username="brand", email="brand@example.com", hashed_password="x", role="brand_ops"),
            User(id=4, username="viewer", email="viewer@example.com", hashed_password="x", role="viewer"),
            User(id=5, username="buyer", display_name="投手甲", email="buyer@example.com", hashed_password="x", role="buyer"),
        ]
        db.add_all(users)
        await db.flush()
        envs = [
            XHSEnvironment(id=10, shop_id="shop-10", account_name="小红书号", department="xhs"),
            XHSEnvironment(id=11, shop_id="shop-11", account_name="品牌号", department="brand"),
        ]
        db.add_all(envs)
        await db.flush()
        db.add_all(
            [
                XHSReportToken(account_id="A1", account_name="广告账户一", token_status="成功"),
                XHSReportDaily(
                    report_type="simple",
                    account_id="A2",
                    account_name="广告账户二",
                    report_date=date(2026, 8, 1),
                    campaign_id="p1",
                    payload={"fee": 10},
                ),
                XHSAdAccountBuyerAssignment(account_id="A1", account_name="广告账户一", user_id=5),
                XHSAdAccountProfessionalMapping(
                    account_id="A1",
                    account_name="广告账户一",
                    xhs_account_id="X1",
                    xhs_account_name="专业号一",
                    xhs_owner_name="运营甲",
                ),
            ]
        )
        await db.commit()
    return users, envs


@pytest.mark.asyncio
async def test_admin_xhs_service_and_schedule_routes(client, monkeypatch):
    users, _ = await _seed_admin_xhs_data()
    headers = make_auth_headers(users[0].id)

    async def sync_posts(self):
        return 8

    async def sync_envs(self):
        return 3

    async def list_settings(self):
        return [{"task_key": "report_refresh"}]

    async def list_logs(self, **kwargs):
        return [{"status": "success", **kwargs}]

    async def update_setting(self, task_key, **kwargs):
        if kwargs["run_time"] == "bad":
            raise ValueError("时间格式错误")
        return {"task_key": task_key, **kwargs}

    monkeypatch.setattr(XHSService, "sync_all_posts", sync_posts)
    monkeypatch.setattr(XHSService, "sync_environments_from_yundeng", sync_envs)
    monkeypatch.setattr(XHSScheduleService, "list_settings", list_settings)
    monkeypatch.setattr(XHSScheduleService, "list_run_logs", list_logs)
    monkeypatch.setattr(XHSScheduleService, "update_setting", update_setting)

    assert (await client.post("/api/v1/admin/xhs/sync-all", headers=headers)).json()["data"]["synced_count"] == 8
    assert (await client.post("/api/v1/admin/xhs/sync-environments", headers=headers)).json()["data"]["synced_count"] == 3
    assert (await client.get("/api/v1/admin/xhs/schedule-settings", headers=headers)).status_code == 200
    assert (await client.get("/api/v1/admin/xhs/schedule-run-logs?task_key=invalid", headers=headers)).status_code == 404
    logs = await client.get("/api/v1/admin/xhs/schedule-run-logs?limit=20", headers=headers)
    assert logs.json()["data"][0]["limit"] == 20
    assert (
        await client.put(
            "/api/v1/admin/xhs/schedule-settings/invalid",
            json={"enabled": True, "run_time": "10:00"},
            headers=headers,
        )
    ).status_code == 404
    task_key = next(iter(module.ALL_SCHEDULE_TASK_KEYS))
    invalid = await client.put(
        f"/api/v1/admin/xhs/schedule-settings/{task_key}",
        json={"enabled": True, "run_time": "bad"},
        headers=headers,
    )
    assert invalid.status_code == 400
    saved = await client.put(
        f"/api/v1/admin/xhs/schedule-settings/{task_key}",
        json={"enabled": True, "run_time": "10:00", "config": {"days": 2}},
        headers=headers,
    )
    assert saved.status_code == 200

    assert (await client.post("/api/v1/admin/xhs/schedule-settings/invalid/run", headers=headers)).status_code == 404

    async def launch(key, source):
        return False

    monkeypatch.setattr(module, "trigger_xhs_scheduled_task", launch)
    running = await client.post(f"/api/v1/admin/xhs/schedule-settings/{task_key}/run", headers=headers)
    assert "已在执行" in running.json()["message"]

    async def launch_error(key, source):
        raise ValueError("任务参数错误")

    monkeypatch.setattr(module, "trigger_xhs_scheduled_task", launch_error)
    assert (await client.post(f"/api/v1/admin/xhs/schedule-settings/{task_key}/run", headers=headers)).status_code == 400


@pytest.mark.asyncio
async def test_admin_xhs_environment_assignment_profile_and_status(client, monkeypatch):
    users, envs = await _seed_admin_xhs_data()
    headers = make_auth_headers(users[0].id)

    assert (
        await client.post("/api/v1/admin/xhs/assign", json={"user_id": 999, "environment_id": 10}, headers=headers)
    ).status_code == 404
    wrong_department = await client.post(
        "/api/v1/admin/xhs/assign",
        json={"user_id": users[2].id, "environment_id": envs[0].id},
        headers=headers,
    )
    assert wrong_department.status_code == 400
    assigned = await client.post(
        "/api/v1/admin/xhs/assign",
        json={"user_id": users[1].id, "environment_id": envs[0].id},
        headers=headers,
    )
    assert assigned.status_code == 200
    assignments = await client.get("/api/v1/admin/xhs/assignments", headers=headers)
    assert assignments.json()["data"] == [{"user_id": users[1].id, "environment_id": envs[0].id}]
    assert (
        await client.post("/api/v1/admin/xhs/unassign", json={"user_id": 999, "environment_id": 10}, headers=headers)
    ).status_code == 404
    assert (
        await client.post(
            "/api/v1/admin/xhs/unassign",
            json={"user_id": users[1].id, "environment_id": envs[0].id},
            headers=headers,
        )
    ).status_code == 200

    assert (
        await client.post("/api/v1/admin/xhs/profile-url", json={"environment_id": 999}, headers=headers)
    ).status_code == 404
    invalid_json = await client.post(
        "/api/v1/admin/xhs/profile-url",
        json={"environment_id": 10, "sync_cloud_update_config": "[1]"},
        headers=headers,
    )
    assert invalid_json.status_code == 400
    invalid_browser = await client.post(
        "/api/v1/admin/xhs/profile-url",
        json={"environment_id": 10, "sync_browser_start_config": "{"},
        headers=headers,
    )
    assert invalid_browser.status_code == 400
    invalid_department = await client.post(
        "/api/v1/admin/xhs/profile-url",
        json={"environment_id": 10, "department": "sales"},
        headers=headers,
    )
    assert invalid_department.status_code == 400
    saved = await client.post(
        "/api/v1/admin/xhs/profile-url",
        json={
            "environment_id": 10,
            "profile_url": " https://xhs/profile/a ",
            "sync_cloud_session_id": " session ",
            "sync_cloud_api_key": " key ",
            "sync_cloud_update_config": '{"ua":"new"}',
            "sync_browser_start_config": '{"width":1080}',
            "login_phone_number": " 13800138000 ",
            "department": "brand",
        },
        headers=headers,
    )
    assert saved.status_code == 200
    assert saved.json()["data"]["department"] == "brand"

    assert (
        await client.post("/api/v1/admin/xhs/sync-runner", json={"environment_id": 999, "is_sync_runner": True}, headers=headers)
    ).status_code == 404
    runner = await client.post(
        "/api/v1/admin/xhs/sync-runner",
        json={"environment_id": 10, "is_sync_runner": True},
        headers=headers,
    )
    assert runner.json()["data"]["is_sync_runner"] is True

    async def overview(self, **kwargs):
        return kwargs

    async def statuses(self, **kwargs):
        return [{"online": True, **kwargs}]

    async def refresh(self, environment_id):
        if environment_id == 999:
            raise RuntimeError("环境不存在")
        return {"environment_id": environment_id, "online": True}

    monkeypatch.setattr(XHSService, "get_sync_runner_browse_overview", overview)
    monkeypatch.setattr(XHSService, "list_browser_environment_statuses", statuses)
    monkeypatch.setattr(XHSService, "refresh_browser_environment_status", refresh)
    assert (await client.get("/api/v1/admin/xhs/sync-runner-browse-overview?days=3&limit=20", headers=headers)).status_code == 200
    assert (await client.get("/api/v1/admin/xhs/browser-statuses?refresh=true", headers=headers)).json()["data"][0]["refresh"] is True
    assert (await client.post("/api/v1/admin/xhs/browser-status/999/refresh", headers=headers)).status_code == 404
    assert (await client.post("/api/v1/admin/xhs/browser-status/10/refresh", headers=headers)).status_code == 200


@pytest.mark.asyncio
async def test_admin_ad_account_crud_mapping_assignment_and_listing(client):
    users, _ = await _seed_admin_xhs_data()
    headers = make_auth_headers(users[0].id)
    listed = await client.get("/api/v1/admin/xhs/ad-account-assignments", headers=headers)
    rows = listed.json()["data"]
    assert [row["account_id"] for row in rows] == ["A1", "A2"]
    assert rows[0]["buyer_display_name"] == "投手甲"
    assert rows[0]["xhs_account_name"] == "专业号一"
    assert rows[1]["user_id"] is None

    assert (
        await client.post("/api/v1/admin/xhs/ad-accounts", json={"account_id": "", "account_name": "x"}, headers=headers)
    ).status_code == 400
    assert (
        await client.post("/api/v1/admin/xhs/ad-accounts", json={"account_id": "A3", "account_name": ""}, headers=headers)
    ).status_code == 400
    assert (
        await client.post("/api/v1/admin/xhs/ad-accounts", json={"account_id": "A1", "account_name": "重复"}, headers=headers)
    ).status_code == 400
    created = await client.post(
        "/api/v1/admin/xhs/ad-accounts",
        json={"account_id": "A3", "account_name": "广告账户三"},
        headers=headers,
    )
    assert created.status_code == 200
    assert (
        await client.patch(
            "/api/v1/admin/xhs/ad-accounts",
            json={"account_id": "missing", "account_name": "x"},
            headers=headers,
        )
    ).status_code == 404
    assert (
        await client.patch(
            "/api/v1/admin/xhs/ad-accounts",
            json={"account_id": "A3", "new_account_id": "A1", "account_name": "冲突"},
            headers=headers,
        )
    ).status_code == 400
    updated = await client.patch(
        "/api/v1/admin/xhs/ad-accounts",
        json={"account_id": "A3", "new_account_id": "A4", "account_name": "账户四"},
        headers=headers,
    )
    assert updated.json()["data"]["account_id"] == "A4"

    assert (
        await client.post(
            "/api/v1/admin/xhs/ad-account-professional-mapping",
            json={"account_id": "unknown", "xhs_account_id": "X", "xhs_account_name": "专业号"},
            headers=headers,
        )
    ).status_code == 404
    assert (
        await client.post(
            "/api/v1/admin/xhs/ad-account-professional-mapping",
            json={"account_id": "A4", "xhs_account_name": "专业号"},
            headers=headers,
        )
    ).status_code == 400
    mapped = await client.post(
        "/api/v1/admin/xhs/ad-account-professional-mapping",
        json={"account_id": "A4", "xhs_account_id": "X4", "xhs_account_name": "专业号四", "xhs_owner_name": "运营四"},
        headers=headers,
    )
    assert mapped.status_code == 200
    cleared = await client.post(
        "/api/v1/admin/xhs/ad-account-professional-mapping",
        json={"account_id": "A4"},
        headers=headers,
    )
    assert cleared.status_code == 200

    assert (
        await client.post("/api/v1/admin/xhs/ad-account-assign", json={"account_id": "A1", "user_id": 999}, headers=headers)
    ).status_code == 404
    assert (
        await client.post(
            "/api/v1/admin/xhs/ad-account-assign",
            json={"account_id": "A1", "user_id": users[3].id},
            headers=headers,
        )
    ).status_code == 400
    reassigned = await client.post(
        "/api/v1/admin/xhs/ad-account-assign",
        json={"account_id": "A1", "user_id": users[1].id},
        headers=headers,
    )
    assert reassigned.status_code == 200
    assert (
        await client.post("/api/v1/admin/xhs/ad-account-unassign", json={"account_id": "A1"}, headers=headers)
    ).status_code == 200
    assert (await client.delete("/api/v1/admin/xhs/ad-accounts/A4", headers=headers)).status_code == 200
    assert (await client.delete("/api/v1/admin/xhs/ad-accounts/unknown", headers=headers)).status_code == 200
