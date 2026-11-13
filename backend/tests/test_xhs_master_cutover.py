"""Old HTTP entrypoints, mobile imports, browser enrichment and timer cutover."""

import asyncio
from datetime import date, datetime
import io
import json

import openpyxl
import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from app.adapters.phone_cloud_xhs_data import PhoneCloudXHSDataClient
from app.config import settings
from app.db.session import async_session
from app.models.user import User
from app.models.xhs_account import XHSAccount
from app.models.xhs_account_note import XHSAccountNote
from app.models.xhs_account_sync_run import XHSAccountSyncRun
from app.models.xhs_creator_sync_row import XHSCreatorSyncRow
from app.models.xhs_environment import XHSEnvironment
from app.models.xhs_report import XHSProfileStatDaily
from app.models.user_xhs_env import UserXHSEnvironment
from app.schemas.xhs_account_master import MasterSyncRequest
from app.services.xhs_account_master_service import (
    XHSAccountMasterService,
    valid_profile_url,
)
from app.services.xhs_cloud_data_service import XHSCloudDataService
from app.services.xhs_master_sync import XHSMasterSync
from app.services.xhs_profile_stat_service import XHSProfileStatService
from app.services.xhs_schedule_service import _execute_account_data_sync
from app.services.xhs_service import XHSService
from tests.conftest import make_auth_headers
from tests.test_xhs_account_master import csv_file, seed
from tests.test_xhs_cloud_data import BINDING, NOW, RUN, item


@pytest.fixture(autouse=True)
def isolated_settings(monkeypatch):
    monkeypatch.setattr(settings, "xhs_account_master_enabled", True)
    monkeypatch.setattr(settings, "phone_cloud_xhs_data_client_id", "cutover-test")
    monkeypatch.setattr(settings, "phone_cloud_xhs_data_secret", "test-only")
    monkeypatch.setattr(
        settings, "phone_cloud_xhs_data_base_url", "https://phone.invalid"
    )
    monkeypatch.setattr(
        settings, "phone_cloud_xhs_verified_bindings", json.dumps([BINDING])
    )
    import app.services.xhs_cloud_data_service as cloud

    monkeypatch.setattr(cloud, "utc_now_naive", lambda: NOW)
    monkeypatch.setattr(
        XHSService, "_should_delegate_browser_ops", staticmethod(lambda: False)
    )


async def roster(db):
    users = await seed(db)
    master = XHSAccountMasterService(db)
    preview = await master.preview(
        csv_file(
            {"xhs_account_id": BINDING["xhs_id"]},
            {
                "xhs_account_id": "10000002",
                "account_name": "Brand account",
                "department": "品牌部",
                "owner_label": "Operator Two",
            },
        ),
        users[0],
    )
    await master.apply(
        preview["preview_id"],
        preview["source_hash"],
        [r["row"] for r in preview["rows"]],
        users[0],
        replace_all=True,
    )
    accounts = list(
        (await db.scalars(select(XHSAccount).order_by(XHSAccount.id))).all()
    )
    for index, account in enumerate(accounts):
        account.profile_url = f"https://www.xiaohongshu.com/user/profile/abcd{index}"
    db.add_all(
        [
            XHSEnvironment(
                id=accounts[0].id,
                shop_id="unrelated-old",
                account_name="Unrelated environment",
                status="active",
                xhs_account_id="99999999",
            ),
            XHSEnvironment(
                id=100,
                shop_id="test-runner4",
                account_name="测试4",
                status="active",
                is_sync_runner=True,
            ),
            XHSEnvironment(
                id=101,
                shop_id="test-runner5",
                account_name="测试5",
                status="active",
                is_sync_runner=True,
            ),
        ]
    )
    await db.flush()
    db.add(UserXHSEnvironment(user_id=2, environment_id=accounts[0].id))
    await db.commit()
    return users, accounts


def workbook():
    book = openpyxl.Workbook()
    sheet = book.active
    sheet.append(
        ["笔记标题", "首次发布时间", "曝光", "观看", "点赞", "评论", "收藏", "分享"]
    )
    sheet.append(["Manual post", "2026-11-12 10:30", 1000, 800, 10, 2, 3, 4])
    output = io.BytesIO()
    book.save(output)
    return output.getvalue()


async def wait_job(client, job_id):
    for _ in range(200):
        response = await client.get(
            f"/api/v1/xhs/account-notes/sync-jobs/{job_id}",
            headers=make_auth_headers(1),
        )
        data = response.json()["data"]
        if data["status"] not in ("queued", "running"):
            return data
        await asyncio.sleep(0.01)
    raise AssertionError("local job did not terminate")


@pytest.mark.asyncio
async def test_old_read_api_and_dashboard_use_canonical_identity_current_owner_and_department(
    client,
):
    async with async_session() as db:
        users, accounts = await roster(db)
        aid = accounts[0].id
        db.add_all(
            [
                XHSAccountNote(
                    account_id=a.id,
                    account_name="captured old name",
                    title="Post",
                    view_count=100,
                    published_at=datetime(2026, 11, 11, 16, 30),
                    status="active",
                )
                for a in accounts
            ]
        )
        db.add(
            XHSAccountNote(
                environment_id=aid,
                account_name="Legacy unrelated",
                title="Never expose",
                status="active",
            )
        )
        await db.commit()

    async def read(uid):
        r = await client.get(
            "/api/v1/xhs/account-notes", headers=make_auth_headers(uid)
        )
        assert r.status_code == 200, r.text
        return r.json()["data"]

    owner = await read(2)
    assert owner["total"] == 1 and owner["items"][0]["account_name"] == "Account one"
    assert owner["items"][0]["environment_id"] is None
    assert (await read(4))["total"] == 1  # Department lead, not brand team.
    assert (await read(1))[
        "total"
    ] == 2  # Admin still cannot accidentally read unmapped legacy notes.
    response = await client.get(
        "/api/v1/xhs/account-notes?environment_id=1", headers=make_auth_headers(1)
    )
    assert response.status_code == 422
    response = await client.get(
        "/api/v1/xhs/account-notes/insights?start_date=2026-11-12&end_date=2026-11-12",
        headers=make_auth_headers(2),
    )
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["total"] == 1 and data["dashboard"]["metrics"]["totalPosts"] == 1
    async with async_session() as db:
        account = await db.get(XHSAccount, aid)
        account.owner_user_id = 3
        account.department = "brand"
        account.revision += 1
        await db.commit()
    assert (await read(2))["total"] == 0
    assert (await read(4))["total"] == 0
    moved = await read(3)
    assert moved["total"] == 2 and {n["owner_username"] for n in moved["items"]} == {
        "Operator Two"
    }
    async with async_session() as db:
        assert (
            await db.scalar(
                select(XHSAccountNote.account_name).where(
                    XHSAccountNote.account_id == aid
                )
            )
            == "captured old name"
        )


@pytest.mark.asyncio
async def test_uninitialized_master_fails_closed_and_bad_date_returns_422(client):
    async with async_session() as db:
        await seed(db)
    assert (
        await client.get("/api/v1/xhs/account-notes", headers=make_auth_headers(1))
    ).status_code == 409
    assert (
        await client.get("/api/v1/xhs/accounts/mode", headers=make_auth_headers(1))
    ).json()["data"]["ready"] is False
    async with async_session() as db:
        master = XHSAccountMasterService(db)
        admin = await db.scalar(
            select(User)
            .where(User.id == 1)
            .options(selectinload(User.role_assignments))
        )
        p = await master.preview(csv_file({}), admin)
        await master.apply(
            p["preview_id"],
            p["source_hash"],
            [p["rows"][0]["row"]],
            admin,
            replace_all=True,
        )
    response = await client.get(
        "/api/v1/xhs/account-notes/insights?start_date=2026-11-12&end_date=2026-11-01",
        headers=make_auth_headers(1),
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_manual_export_real_parser_native_audit_and_no_environment_link(client):
    async with async_session() as db:
        _, accounts = await roster(db)
        aid = accounts[0].id
    response = await client.post(
        f"/api/v1/xhs/account-notes/import-creator-export?account_id={aid}",
        headers=make_auth_headers(1),
        files={"file": ("export.xlsx", workbook())},
    )
    assert response.status_code == 200, response.text
    async with async_session() as db:
        note = await db.scalar(select(XHSAccountNote))
        assert (
            note.account_id == aid
            and note.environment_id is None
            and note.view_count == 800
        )
        assert note.published_at == datetime(2026, 11, 12, 2, 30)
        audit = await db.scalar(select(XHSCreatorSyncRow))
        assert audit.account_id == aid and audit.environment_id is None
    wrong = await client.post(
        f"/api/v1/xhs/account-notes/import-creator-export?environment_id={aid}",
        headers=make_auth_headers(1),
        files={"file": ("export.xlsx", workbook())},
    )
    assert wrong.status_code == 422


@pytest.mark.asyncio
async def test_native_job_real_cloud_import_history_retry_and_permission(
    client, monkeypatch
):
    async with async_session() as db:
        _, accounts = await roster(db)
        aid = accounts[0].id
    calls = []

    async def latest(self, ids):
        calls.append(ids)
        return {BINDING["xhs_id"]: (RUN, item())}

    monkeypatch.setattr(PhoneCloudXHSDataClient, "latest_items", latest)
    body = {"kind": "engagement", "account_ids": [aid]}
    assert (
        await client.post(
            "/api/v1/xhs/accounts/sync", json=body, headers=make_auth_headers(2)
        )
    ).status_code == 403
    response = await client.post(
        "/api/v1/xhs/accounts/sync", json=body, headers=make_auth_headers(1)
    )
    assert response.status_code == 200, response.text
    job = await wait_job(client, response.json()["data"]["job_id"])
    assert job["status"] == "succeeded" and calls == [{BINDING["xhs_id"]}]
    assert job["result"]["created_notes"] == 1
    assert job["result"]["metric_synced_notes"] == 1
    async with async_session() as db:
        note = await db.scalar(select(XHSAccountNote))
        assert (
            note.account_id == aid
            and note.view_count == 101
            and note.environment_id is None
        )
        run = await db.scalar(
            select(XHSAccountSyncRun).options(selectinload(XHSAccountSyncRun.items))
        )
        assert run.items[0].account_id == aid and run.items[0].status == "succeeded"
    history = (
        await client.get(
            "/api/v1/xhs/account-notes/sync-history", headers=make_auth_headers(1)
        )
    ).json()["data"]
    assert history[0]["items"][0]["account_id"] == aid
    for path in ("sync", "sync-engagement", "sync-details"):
        assert (
            await client.post(
                "/api/v1/xhs/account-notes/" + path, headers=make_auth_headers(1)
            )
        ).status_code == 409


@pytest.mark.asyncio
async def test_timer_uses_master_owner_scope_retries_only_failed_once_and_keeps_history(
    client, monkeypatch
):
    async with async_session() as db:
        _, accounts = await roster(db)
        ids = [a.id for a in accounts]
    calls = []

    async def latest(self, xids):
        calls.append(xids)
        return {BINDING["xhs_id"]: (RUN, item())}

    monkeypatch.setattr(PhoneCloudXHSDataClient, "latest_items", latest)
    async with async_session() as db:
        result = await _execute_account_data_sync(
            db,
            {
                "engagement_sync_enabled": True,
                "post_sync_enabled": False,
                "detail_sync_enabled": False,
                "content_tag_enabled": False,
            },
        )
        assert "重试一次" in result
        runs = list(
            (
                await db.scalars(
                    select(XHSAccountSyncRun)
                    .order_by(XHSAccountSyncRun.id)
                    .options(selectinload(XHSAccountSyncRun.items))
                )
            ).all()
        )
        assert len(runs) == 2
        assert runs[0].request_config["account_ids"] == ids
        assert runs[1].request_config["account_ids"] == [ids[1]]
        assert runs[1].parent_run_id == runs[0].id
        assert runs[1].items[0].error == "cloud_data_identity_not_verified"
    assert calls == [{BINDING["xhs_id"], "10000002"}, {"10000002"}]
    async with async_session() as db:
        with pytest.raises(ValueError, match="云登环境"):
            await _execute_account_data_sync(
                db, {"target_scope": "environment_ids", "target_environment_ids": [1]}
            )


@pytest.mark.asyncio
async def test_youju_current_master_not_old_environment_assignments_or_ambiguous_aliases(
    client,
):
    async with async_session() as db:
        _, accounts = await roster(db)
        first, second = accounts
        db.add_all(
            [
                XHSProfileStatDaily(
                    stat_date=date(2026, 11, 12),
                    channel_account_name="Account one",
                    channel_account_key="one",
                    natural_leads=7,
                    special_natural_leads=2,
                    ad_leads=3,
                    payload={},
                ),
                XHSProfileStatDaily(
                    stat_date=date(2026, 11, 12),
                    channel_account_name="Unrelated environment",
                    channel_account_key="old",
                    natural_leads=100,
                    payload={},
                ),
            ]
        )
        await db.commit()
        stats = await XHSProfileStatService(db).owner_rows(
            start_date="2026-11-12", end_date="2026-11-12"
        )
        assert stats["total"]["natural_leads"] == 7
        first.owner_user_id = 3
        first.department = "brand"
        first.revision += 1
        await db.commit()
        profiles, names, owners, _ = await XHSProfileStatService(
            db
        )._current_assignment_context(allowed_owner_roles={"brand_ops", "brand_lead"})
        from app.services.xhs_profile_stat_service import normalize_profile_account_name

        assert names[normalize_profile_account_name("Account one")]["owner_id"] == "3"
        assert owners["3"]["account_names"] == {"Account one", "Brand account"}
        assert "2" not in owners
        db.add_all(
            [
                XHSAccountNote(
                    account_id=a.id,
                    account_name="Shared stale alias",
                    title="Alias",
                    status="active",
                )
                for a in accounts
            ]
        )
        await db.commit()
        _, names, _, _ = await XHSProfileStatService(db)._current_assignment_context()
        from app.services.xhs_profile_stat_service import normalize_profile_account_name

        assert normalize_profile_account_name("Shared stale alias") not in names


@pytest.mark.parametrize(
    "value",
    [
        "https://www.xiaohongshu.com:bad/user/profile/abc",
        "http://www.xiaohongshu.com/user/profile/abc",
        "https://evil.invalid/user/profile/abc",
        "https://user:pass@www.xiaohongshu.com/user/profile/abc",
    ],
)
def test_profile_locator_invalid_values(value):
    assert not valid_profile_url(value)


@pytest.mark.asyncio
async def test_homepage_native_verifies_public_id_and_enriches_cloud_note_without_duplicate(
    client, monkeypatch
):
    async with async_session() as db:
        _, accounts = await roster(db)
        aid = accounts[0].id
        await XHSCloudDataService(db).import_item(accounts[0], RUN, item(), BINDING)

    async def fetch(self, *args, **kwargs):
        return {
            "red_id": BINDING["xhs_id"],
            "profile_nickname": "renamed remote",
            "feeds": [
                {
                    "feed_id": "a" * 24,
                    "title": "A car buying guide",
                    "published_at": datetime(2026, 11, 12, 2, 30),
                    "cover_image_url": None,
                    "liked_count": 1,
                    "comment_count": 0,
                    "sort_index": 0,
                }
            ],
        }

    async def no_sleep(*args, **kwargs):
        pass

    monkeypatch.setattr(XHSService, "_fetch_profile_account_notes", fetch)
    monkeypatch.setattr(XHSService, "_sleep_sync_profile_prep", no_sleep)
    async with async_session() as db:
        account = await db.get(XHSAccount, aid)
        runner = await db.get(XHSEnvironment, 100)
        result = await XHSService(db)._sync_account_notes_with_api(
            account,
            api_base="https://mcp.invalid",
            assigned_runner_env=runner,
            runner_envs=[runner],
        )
        assert result["updated_notes"] == 1
        assert await db.scalar(select(func.count()).select_from(XHSAccountNote)) == 1
        note = await db.scalar(select(XHSAccountNote))
        assert (
            note.feed_id == "a" * 24
            and note.view_count == 101
            and note.liked_count == 5
        )
        assert note.environment_id is None and note.account_id == aid

    async def wrong(*args, **kwargs):
        return {"red_id": "wrong", "feeds": []}

    monkeypatch.setattr(XHSService, "_fetch_profile_account_notes", wrong)
    async with async_session() as db:
        with pytest.raises(RuntimeError, match="公开号"):
            await XHSService(db)._sync_account_notes_with_api(
                await db.get(XHSAccount, aid), api_base="https://mcp.invalid"
            )
        await db.rollback()
        assert await db.scalar(select(XHSAccountNote.status)) == "active"


@pytest.mark.asyncio
async def test_profile_worker_rejects_source_env_as_runner_and_stale_revision_before_browser(
    client,
):
    async with async_session() as db:
        _, accounts = await roster(db)
        aid = accounts[0].id
        sync = XHSMasterSync(db)
        with pytest.raises(ValueError, match="测试采集环境"):
            await sync.prepare(
                MasterSyncRequest(kind="posts", account_ids=[aid], runner_ids=[aid])
            )
        with pytest.raises(ValueError, match="版本"):
            await sync.homepage_local(aid, 999, 100, 60, "supplement_only")
        run = await sync.prepare(
            MasterSyncRequest(kind="posts", account_ids=[aid], runner_ids=[100])
        )
        result = await sync.execute(run.id, cancel_check=lambda: True)
        assert result["status"] == "cancelled"


@pytest.mark.asyncio
async def test_failed_manual_import_retains_durable_failure_and_no_partial_notes(
    client,
):
    async with async_session() as db:
        _, accounts = await roster(db)
        aid = accounts[0].id
    response = await client.post(
        f"/api/v1/xhs/account-notes/import-creator-export?account_id={aid}",
        headers=make_auth_headers(1),
        files={"file": ("bad.xlsx", b"not a workbook")},
    )
    assert response.status_code == 400
    async with async_session() as db:
        history = await db.scalar(
            select(XHSAccountSyncRun).options(selectinload(XHSAccountSyncRun.items))
        )
        assert history.status == "failed" and history.items[0].status == "failed"
        assert history.items[0].account_id == aid
        assert await db.scalar(select(func.count()).select_from(XHSAccountNote)) == 0


@pytest.mark.asyncio
async def test_worker_contract_and_native_failure_retry_api(client, monkeypatch):
    from app.adapters.phone_cloud_xhs_data import CloudDataError

    async with async_session() as db:
        _, accounts = await roster(db)
        aid = accounts[0].id
        revision = accounts[0].revision
    body = {
        "account_id": aid,
        "expected_revision": revision,
        "runner_id": 100,
        "note_ids": [999],
    }
    monkeypatch.setattr(settings, "xhs_worker_internal_token", "test-worker-key")
    url = "/api/v1/xhs/accounts/internal/details"
    assert (
        await client.post(url, json=body, headers=make_auth_headers(1))
    ).status_code == 403
    response = await client.post(
        url, json=body, headers={"X-XHS-Worker-Token": "test-worker-key"}
    )
    assert response.status_code == 422

    async def failed(*args, **kwargs):
        raise CloudDataError("cloud_data_http_503")

    monkeypatch.setattr(PhoneCloudXHSDataClient, "latest_items", failed)
    response = await client.post(
        "/api/v1/xhs/accounts/sync",
        json={"kind": "engagement", "account_ids": [aid]},
        headers=make_auth_headers(1),
    )
    first = await wait_job(client, response.json()["data"]["job_id"])
    assert first["status"] == "failed"

    async def success(self, ids):
        assert ids == {BINDING["xhs_id"]}
        return {BINDING["xhs_id"]: (RUN, item())}

    monkeypatch.setattr(PhoneCloudXHSDataClient, "latest_items", success)
    response = await client.post(
        f"/api/v1/xhs/account-notes/sync-history/{first['history_run_id']}/retry-failed",
        headers=make_auth_headers(1),
    )
    assert response.status_code == 200, response.text
    retry = await wait_job(client, response.json()["data"]["job_id"])
    assert retry["status"] == "succeeded"
    async with async_session() as db:
        assert await db.scalar(select(func.count()).select_from(XHSAccountNote)) == 1
        histories = list(
            (
                await db.scalars(
                    select(XHSAccountSyncRun).order_by(XHSAccountSyncRun.id)
                )
            ).all()
        )
        assert (
            histories[0].status == "failed"
            and histories[1].parent_run_id == histories[0].id
        )


@pytest.mark.asyncio
async def test_independent_locator_revision_and_current_note_actions(client):
    async with async_session() as db:
        _, accounts = await roster(db)
        aid = accounts[0].id
        revision = accounts[0].revision
        note = XHSAccountNote(
            account_id=aid, account_name="Capture alias", title="Post", status="active"
        )
        db.add(note)
        await db.commit()
        nid = note.id
    url = f"/api/v1/admin/xhs/account-master/accounts/{aid}/profile"
    body = {
        "profile_url": "https://www.xiaohongshu.com/user/profile/newabc",
        "expected_revision": revision,
    }
    assert (
        await client.patch(url, json=body, headers=make_auth_headers(2))
    ).status_code == 403
    assert (
        await client.patch(url, json=body, headers=make_auth_headers(1))
    ).status_code == 200
    assert (
        await client.patch(url, json=body, headers=make_auth_headers(1))
    ).status_code == 409
    body.update(
        expected_revision=revision + 1,
        profile_url="https://evil.invalid/user/profile/abc",
    )
    assert (
        await client.patch(url, json=body, headers=make_auth_headers(1))
    ).status_code == 422
    response = await client.patch(
        f"/api/v1/xhs/account-notes/{nid}",
        json={"ai_origin_type": "manual"},
        headers=make_auth_headers(2),
    )
    assert response.status_code == 200, response.text
    assert response.json()["data"]["account_name"] == "Account one"
    assert response.json()["data"]["owner_username"] == "Operator One"
    async with async_session() as db:
        account = await db.get(XHSAccount, aid)
        account.owner_user_id = 3
        account.department = "brand"
        account.revision += 1
        await db.commit()
    response = await client.patch(
        f"/api/v1/xhs/account-notes/{nid}",
        json={"ai_origin_type": "all_ai"},
        headers=make_auth_headers(2),
    )
    assert response.status_code == 400
    async with async_session() as db:
        assert (await db.get(XHSAccountNote, nid)).ai_origin_type == "manual"


@pytest.mark.asyncio
async def test_pending_run_rechecks_roster_and_fails_without_legacy_fallback(client):
    async with async_session() as db:
        _, accounts = await roster(db)
        sync = XHSMasterSync(db)
        run = await sync.prepare(
            MasterSyncRequest(kind="engagement", account_ids=[accounts[0].id])
        )
        accounts[0].status = "retired"
        await db.commit()
        result = await sync.execute(run.id)
        assert result["status"] == "failed"
        assert "主名单" in result["failed_accounts"][0]["error"]
