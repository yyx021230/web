from __future__ import annotations

from datetime import datetime
import hashlib
import hmac
import json
from types import SimpleNamespace

import httpx
import pytest
from sqlalchemy import func, select

from app.adapters.phone_cloud_xhs_data import CloudDataError, PhoneCloudXHSDataClient
from app.config import settings
from app.db.session import async_session
from app.models.user import User
from app.models.xhs_account_note import XHSAccountNote
from app.models.xhs_cloud_import import XHSCloudImport
from app.models.xhs_environment import XHSEnvironment
from app.models.user_xhs_env import UserXHSEnvironment
from app.services.xhs_cloud_data_service import XHSCloudDataService
import app.services.xhs_cloud_data_service as cloud
from app.services.xhs_service import XHSService
from tests.conftest import make_auth_headers


NOW = datetime(2026, 11, 12, 4)
RUN = "a" * 64
BINDING = {"xhs_id": "123456789", "device_id": "device-one", "app_slot": "app1",
           "verified_at": "2026-11-01T00:00:00Z"}


def item(**changes):
    value = {"itemId": "0", "xhsId": BINDING["xhs_id"], "deviceId": BINDING["device_id"],
             "appSlot": "app1", "identitySource": "platform_binding_snapshot", "status": "succeeded",
             "data": {"schema_version": 3, "window_days": 30,
                      "source": "xhs_creator_center_works_analysis_list", "window_start_date": "2026-10-14",
                      "window_end_date": "2026-11-12", "captured_at": "2026-11-12T04:00:00Z",
                      "account_bound": True, "app_slot": "app1", "complete": True,
                      "stop_reason": "older_than_window_visible",
                      "recovery_events": ["collection_integrity:verified_two_pass"], "warnings": [],
                      "notes": [{"title": "A car buying guide", "published_date": "2026-11-12", "note_id": None,
                                 "list_view_count": 101, "list_like_count": 5, "list_comment_count": 0}]}}
    value.update(changes)
    return value


@pytest.fixture(autouse=True)
def cloud_settings(monkeypatch):
    monkeypatch.setattr(cloud, "utc_now_naive", lambda: NOW)
    monkeypatch.setattr(settings, "phone_cloud_xhs_data_client_id", "test-client")
    monkeypatch.setattr(settings, "phone_cloud_xhs_data_secret", "test-secret")
    monkeypatch.setattr(settings, "phone_cloud_xhs_data_base_url", "https://phone.invalid")
    monkeypatch.setattr(settings, "phone_cloud_xhs_verified_bindings", json.dumps([BINDING]))


async def environment(db, **changes):
    env = XHSEnvironment(shop_id="shop-main", account_name="Test account", status="active",
                         xhs_account_id=BINDING["xhs_id"], profile_url="https://www.xiaohongshu.com/user/profile/profile-one")
    for key, value in changes.items():
        setattr(env, key, value)
    db.add(env)
    await db.commit()
    return env


@pytest.mark.asyncio
async def test_hmac_matches_exact_raw_query_and_get_only():
    requests = []
    def handler(request):
        requests.append(request)
        canonical = "\n".join(("GET", request.url.raw_path.decode(), request.headers["X-Timestamp"],
                               request.headers["X-Nonce"], hashlib.sha256(b"").hexdigest()))
        assert request.headers["X-Signature"] == hmac.new(b"test-secret", canonical.encode(), hashlib.sha256).hexdigest()
        assert request.method == "GET" and request.content == b""
        return httpx.Response(200, json={"batches": [], "offset": 0, "nextOffset": None})
    c = PhoneCloudXHSDataClient("https://phone.invalid", "client", "test-secret", transport=httpx.MockTransport(handler))
    assert await c.latest_items({"1"}) == {}
    assert await c.latest_items({"1"}) == {}
    assert requests[0].headers["X-Nonce"] != requests[1].headers["X-Nonce"]


@pytest.mark.parametrize("url", ["http://phone.invalid", "https://user:password@phone.invalid", "https://phone.invalid/v1", "https://phone.invalid?x=1"])
def test_reject_unapproved_origins(url):
    with pytest.raises(CloudDataError):
        PhoneCloudXHSDataClient(url, "client", "secret")


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [301, 401, 403, 500])
async def test_transport_errors_never_disclose_upstream_body(status):
    c = PhoneCloudXHSDataClient("https://phone.invalid", "c", "secret",
        transport=httpx.MockTransport(lambda _: httpx.Response(status, text="private credential")))
    with pytest.raises(CloudDataError, match=f"cloud_data_http_{status}") as error:
        await c.latest_items({"1"})
    assert "private" not in str(error.value)


@pytest.mark.asyncio
async def test_complete_pagination_and_new_failure_not_hidden_by_old_success():
    all_items = [item(itemId=str(i), xhsId=str(1000 + i)) for i in range(21)]
    all_items[-1]["status"] = "failed"
    def handler(request):
        offset = int(request.url.params["offset"])
        if request.url.path.endswith("/batches"):
            return httpx.Response(200, json={"batches": [{"runId": RUN, "createdAt": "2026-11-12T02:00:00Z"}], "offset": 0, "nextOffset": None})
        return httpx.Response(200, json={"runId": RUN, "counts": {"total": 21}, "offset": offset,
                                        "nextOffset": offset + 10 if offset < 20 else None,
                                        "items": all_items[offset:offset + 10]})
    c = PhoneCloudXHSDataClient("https://phone.invalid", "c", "s", transport=httpx.MockTransport(handler))
    found = await c.latest_items({"1020"})
    assert found["1020"][1]["status"] == "failed"


@pytest.mark.asyncio
@pytest.mark.parametrize("corruption", ["offset", "duplicate", "missing_page", "wrong_run"])
async def test_bad_pagination_is_rejected(corruption):
    def handler(request):
        if request.url.path.endswith("/batches"):
            return httpx.Response(200, json={"batches": [{"runId": RUN, "createdAt": "2026-11-12T02:00:00Z"}], "offset": 0, "nextOffset": None})
        body = {"runId": RUN, "offset": 0, "nextOffset": None, "counts": {"total": 1}, "items": [item()]}
        if corruption == "offset":
            body["nextOffset"] = 0
        elif corruption == "duplicate":
            body["items"].append(item())
        elif corruption == "missing_page":
            body["counts"]["total"] = 2
        else:
            body["runId"] = "b" * 64
        return httpx.Response(200, json=body)
    c = PhoneCloudXHSDataClient("https://phone.invalid", "c", "s", transport=httpx.MockTransport(handler))
    with pytest.raises(CloudDataError):
        await c.latest_items({BINDING["xhs_id"]})


@pytest.mark.asyncio
async def test_mobile_to_homepage_to_detail_same_note(client, monkeypatch):
    async with async_session() as db:
        env = await environment(db)
        service = XHSCloudDataService(db)
        first = await service.import_item(env, RUN, item(), BINDING)
        assert first["created_notes"] == 1
        assert (await service.import_item(env, RUN, item(), BINDING))["duplicate"]
        note = await db.scalar(select(XHSAccountNote))
        note_id = note.id
        assert note.creator_synced_at == NOW and note.published_at == datetime(2026, 11, 11, 16)
        assert note.published_at_precision == "date" and note.feed_id is None
        async def profile(*args, **kwargs):
            return {"feeds": [{"feed_id": "feed-mobile", "title": note.title,
                                "published_at": datetime(2026, 11, 12, 1), "xsec_token": "test-xsec",
                                "liked_count": 999, "collected_count": 7, "share_count": 2}]}
        async def nothing(*args, **kwargs):
            return None
        monkeypatch.setattr(XHSService, "_fetch_profile_account_notes", profile)
        monkeypatch.setattr(XHSService, "_sleep_sync_profile_prep", nothing)
        monkeypatch.setattr(XHSService, "list_sync_runner_environments", nothing)
        await XHSService(db)._sync_account_notes_with_api(env, api_base="http://fake", total_accounts=1)
        await db.refresh(note)
        assert note.id == note_id and note.feed_id == "feed-mobile" and note.post_url
        assert note.liked_count == 5 and note.collected_count == 7 and note.share_count == 2
        assert note.published_at == datetime(2026, 11, 12, 1) and note.published_at_precision == "second"
        async def details(*args, **kwargs):
            return {"content": "Actual post body", "image_urls": ["https://images.invalid/car.jpg"],
                    "liked_count": 999, "collected_count": 8, "share_count": 4}
        monkeypatch.setattr(XHSService, "_fetch_account_note_detail_metrics", details)
        assert await XHSService(db)._sync_account_note_metrics(note)
        await db.commit()
        assert note.content == "Actual post body" and note.image_urls
        assert note.liked_count == 5 and note.collected_count == 8 and note.share_count == 4
        assert await db.scalar(select(func.count()).select_from(XHSAccountNote)) == 1


@pytest.mark.asyncio
async def test_existing_content_precise_date_and_unprovided_metrics_preserved(client):
    async with async_session() as db:
        env = await environment(db)
        note = XHSAccountNote(environment_id=env.id, feed_id="known", title=item()["data"]["notes"][0]["title"],
            published_at=datetime(2026, 11, 12, 1), content="body", image_urls=["old.jpg"],
            collected_count=9, share_count=4, exposure_count=600, liked_count=8)
        db.add(note)
        await db.commit()
        payload = item()
        payload["data"]["notes"][0]["list_like_count"] = 0
        payload["data"]["notes"][0]["list_comment_count"] = None
        outcome = await XHSCloudDataService(db).import_item(env, RUN, payload, BINDING)
        assert outcome["updated_notes"] == 1 and note.liked_count == 0
        assert (note.collected_count, note.share_count, note.exposure_count) == (9, 4, 600)
        assert note.content == "body" and note.image_urls == ["old.jpg"]
        assert note.published_at == datetime(2026, 11, 12, 1)


@pytest.mark.asyncio
@pytest.mark.parametrize("mutation,code", [
    ("incomplete", "incomplete"), ("wrong_slot", "identity"), ("wrong_account", "identity"),
    ("mismatch_event", "unproven"), ("duplicate_title", "duplicate_title"),
    ("negative", "invalid_metric"), ("stale", "stale"), ("failed", "upstream_failed"),
    ("truncated", "ambiguous"), ("invalid_date", "invalid_note_date"),
])
async def test_bad_snapshots_quarantined_without_business_writes(client, mutation, code):
    payload = item()
    if mutation == "incomplete":
        payload["data"]["complete"] = False
    elif mutation == "wrong_slot":
        payload["appSlot"] = "app2"
    elif mutation == "wrong_account":
        payload["xhsId"] = "different"
    elif mutation == "mismatch_event":
        payload["data"]["recovery_events"].append("account_identity:configured_id_mismatch_collected_current_slot")
    elif mutation == "duplicate_title":
        payload["data"]["notes"] *= 2
    elif mutation == "negative":
        payload["data"]["notes"][0]["list_view_count"] = -1
    elif mutation == "stale":
        payload["data"]["captured_at"] = "2026-10-01T01:00:00Z"
    elif mutation == "failed":
        payload["status"] = "failed"
    elif mutation == "truncated":
        payload["data"]["notes"][0]["title"] = "x" * 180
    else:
        payload["data"]["notes"][0]["published_date"] = "2026-02-30"
    async with async_session() as db:
        env = await environment(db)
        outcome = await XHSCloudDataService(db).import_item(env, RUN, payload, BINDING)
        assert code in outcome["error"]
        assert await db.scalar(select(func.count()).select_from(XHSAccountNote)) == 0
        assert (await db.scalar(select(XHSCloudImport))).status == "quarantined"


@pytest.mark.asyncio
async def test_account_apply_is_atomic_on_late_ambiguity(client):
    async with async_session() as db:
        env = await environment(db)
        db.add_all([XHSAccountNote(environment_id=env.id, title="duplicate", feed_id=f"feed-{i}",
                                  published_at=NOW) for i in range(2)])
        await db.commit()
        payload = item()
        payload["data"]["notes"].append({**payload["data"]["notes"][0], "title": "duplicate"})
        outcome = await XHSCloudDataService(db).import_item(env, RUN, payload, BINDING)
        assert outcome["error"] == "cloud_data_ambiguous_existing_note"
        assert await db.scalar(select(func.count()).select_from(XHSAccountNote)) == 2


@pytest.mark.asyncio
async def test_empty_success_keeps_history_and_changed_payload_is_conflict(client):
    async with async_session() as db:
        env = await environment(db)
        db.add(XHSAccountNote(environment_id=env.id, feed_id="old", title="old", status="active"))
        await db.commit()
        payload = item()
        payload["data"]["notes"] = []
        assert (await XHSCloudDataService(db).import_item(env, RUN, payload, BINDING))["created_notes"] == 0
        with pytest.raises(CloudDataError, match="observation_conflict"):
            await XHSCloudDataService(db).import_item(env, RUN, item(), BINDING)
        assert (await db.scalar(select(XHSAccountNote))).status == "active"


@pytest.mark.asyncio
async def test_pending_can_later_complete_and_old_snapshots_cannot_overwrite(client):
    async with async_session() as db:
        env = await environment(db)
        service = XHSCloudDataService(db)
        with pytest.raises(CloudDataError, match="pending"):
            await service.import_item(env, RUN, item(status="running"), BINDING)
        assert (await service.import_item(env, RUN, item(), BINDING))["created_notes"] == 1
        older = item()
        older["data"]["captured_at"] = "2026-11-12T03:00:00Z"
        outcome = await service.import_item(env, "b" * 64, older, BINDING)
        assert "superseded" in outcome["error"]


@pytest.mark.asyncio
async def test_switch_bypasses_all_browser_operations_and_respects_scope(client, monkeypatch):
    monkeypatch.setattr(settings, "xhs_creator_sync_source", "phone_cloud")
    async with async_session() as db:
        env = await environment(db, login_phone_number=None)
        user = User(username="own", email="own@example.test", hashed_password="x", role="xhs_ops", is_active=True,
                    role_assignments=[])
        db.add(user)
        await db.flush()
        db.add(UserXHSEnvironment(user_id=user.id, environment_id=env.id))
        await db.commit()
        async def read(*args, **kwargs):
            return {BINDING["xhs_id"]: (RUN, item())}
        async def forbidden(*args, **kwargs):
            raise AssertionError("Browser/phone task must not be launched")
        monkeypatch.setattr(PhoneCloudXHSDataClient, "latest_items", read)
        monkeypatch.setattr(XHSService, "_acquire_ready_sync_browser_ws_with_fallback", forbidden)
        monkeypatch.setattr(XHSService, "_delegate_account_note_engagement_sync", forbidden)
        result = await XHSService(db).sync_account_note_engagements(user=user, environment_id=env.id)
        assert result["synced_accounts"] == 1
        with pytest.raises(ValueError, match="无权限"):
            await XHSService(db).sync_account_note_engagements(user=user, environment_id=99999)


def test_cloud_schedule_does_not_require_browser_login_phone(monkeypatch):
    from app.services.xhs_schedule_service import _creator_sync_configuration_issues
    env = SimpleNamespace(account_name="a", xhs_account_id="123", login_phone_number=None, xhs_account_type=None)
    monkeypatch.setattr(settings, "xhs_creator_sync_source", "phone_cloud")
    assert _creator_sync_configuration_issues(env) == []
    monkeypatch.setattr(settings, "xhs_creator_sync_source", "browser")
    assert "登录手机号" in _creator_sync_configuration_issues(env)


@pytest.mark.asyncio
async def test_manual_export_merges_mobile_date_and_missing_metrics_remain_enrichable(client):
    async with async_session() as db:
        env = await environment(db)
        await XHSCloudDataService(db).import_item(env, RUN, item(), BINDING)
        row = {"title": item()["data"]["notes"][0]["title"], "published_at": datetime(2026, 11, 12, 10),
               "published_at_raw": "2026-11-12 10:00", "source_row_index": 2,
               "view_count": 150, "collect_count": 12}
        result = await XHSService(db)._import_creator_note_stats_rows(env, [row])
        await db.commit()
        assert result["created_notes"] == 0 and result["updated_notes"] == 1
        note = await db.scalar(select(XHSAccountNote))
        assert note.published_at == datetime(2026, 11, 12, 2) and note.published_at_precision == "second"
        assert note.view_count == 150 and note.collected_count == 12


@pytest.mark.asyncio
async def test_legacy_primary_metrics_not_reset_and_newer_export_not_overwritten(client):
    async with async_session() as db:
        env = await environment(db)
        note = XHSAccountNote(environment_id=env.id, feed_id="legacy", title=item()["data"]["notes"][0]["title"],
            published_at=NOW, creator_synced_at=NOW.replace(hour=5), liked_count=20,
            collected_count=9, exposure_count=600, view_count=200)
        db.add(note)
        await db.commit()
        await XHSCloudDataService(db).import_item(env, RUN, item(), BINDING)
        assert (note.view_count, note.liked_count, note.collected_count, note.exposure_count) == (200, 20, 9, 600)
        assert note.metric_sources['collected_count']['source'] == 'creator_export'


@pytest.mark.asyncio
async def test_applied_but_now_stale_receipt_is_not_reported_as_fresh(client, monkeypatch):
    async with async_session() as db:
        env = await environment(db)
        service = XHSCloudDataService(db)
        await service.import_item(env, RUN, item(), BINDING)
        monkeypatch.setattr(cloud, 'utc_now_naive', lambda: datetime(2026, 11, 15, 4))
        with pytest.raises(CloudDataError, match='stale'):
            await service.import_item(env, RUN, item(), BINDING)
        assert (await db.scalar(select(XHSCloudImport))).status == 'applied'


@pytest.mark.asyncio
async def test_title_change_held_instead_of_creating_a_duplicate(client):
    async with async_session() as db:
        env = await environment(db)
        db.add(XHSAccountNote(environment_id=env.id, title="Old title", feed_id="existing", published_at=NOW))
        await db.commit()
        result = await XHSCloudDataService(db).import_item(env, RUN, item(), BINDING)
        assert result['error'] == 'cloud_data_possible_title_change'
        assert await db.scalar(select(func.count()).select_from(XHSAccountNote)) == 1


@pytest.mark.asyncio
async def test_admin_receipts_and_replay_are_private_and_do_not_recapture(client, monkeypatch):
    async with async_session() as db:
        env = await environment(db)
        db.add_all([User(id=1, username='admin', email='a@example.test', hashed_password='x', role='admin'),
                    User(id=2, username='ops', email='b@example.test', hashed_password='x', role='xhs_ops')])
        await db.commit()
        original = XHSCloudDataService._apply_rows
        async def failed(*args, **kwargs):
            raise RuntimeError('do not expose this payload')
        monkeypatch.setattr(XHSCloudDataService, '_apply_rows', failed)
        result = await XHSCloudDataService(db).import_item(env, RUN, item(), BINDING)
        assert result['error'] == 'cloud_data_apply_failed'
        receipt_id = (await db.scalar(select(XHSCloudImport))).id
        monkeypatch.setattr(XHSCloudDataService, '_apply_rows', original)
    assert (await client.get('/api/v1/admin/xhs/cloud-imports')).status_code == 401
    assert (await client.get('/api/v1/admin/xhs/cloud-imports', headers=make_auth_headers(2))).status_code == 403
    response = await client.get('/api/v1/admin/xhs/cloud-imports', headers=make_auth_headers(1))
    assert response.status_code == 200 and response.json()['data'][0]['id'] == receipt_id
    assert 'payload' not in response.json()['data'][0] and 'do not expose' not in response.text
    monkeypatch.setattr(settings, 'xhs_creator_sync_source', 'phone_cloud')
    async def forbidden(*args, **kwargs):
        raise AssertionError('replay must not fetch or submit a task')
    monkeypatch.setattr(PhoneCloudXHSDataClient, 'latest_items', forbidden)
    response = await client.post(f'/api/v1/admin/xhs/cloud-imports/{receipt_id}/retry', headers=make_auth_headers(1))
    assert response.status_code == 200 and response.json()['data']['created_notes'] == 1
    monkeypatch.setattr(settings, 'phone_cloud_xhs_data_client_id', 'different-client')
    response = await client.post(f'/api/v1/admin/xhs/cloud-imports/{receipt_id}/retry', headers=make_auth_headers(1))
    assert response.status_code == 409 and response.json()['detail'] == 'cloud_data_receipt_client_changed'


@pytest.mark.asyncio
async def test_missing_verification_fails_without_browser_fallback(client, monkeypatch):
    monkeypatch.setattr(settings, 'xhs_creator_sync_source', 'phone_cloud')
    monkeypatch.setattr(settings, 'phone_cloud_xhs_verified_bindings', '[]')
    async def read(*args, **kwargs):
        return {BINDING['xhs_id']: (RUN, item())}
    monkeypatch.setattr(PhoneCloudXHSDataClient, 'latest_items', read)
    async with async_session() as db:
        env = await environment(db)
        result = await XHSService(db).sync_account_note_engagement_environment(env.id)
        assert result['synced_accounts'] == 0 and result['failed_accounts'][0]['error'] == 'cloud_data_identity_not_verified'


@pytest.mark.asyncio
async def test_cloud_schedule_can_import_without_login_configuration(client, monkeypatch):
    from app.services.xhs_schedule_service import _execute_account_data_sync
    monkeypatch.setattr(settings, 'xhs_creator_sync_source', 'phone_cloud')
    async def read(*args, **kwargs):
        return {BINDING['xhs_id']: (RUN, item())}
    monkeypatch.setattr(PhoneCloudXHSDataClient, 'latest_items', read)
    async with async_session() as db:
        await environment(db, login_phone_number=None, xhs_account_type=None)
        db.add(User(username='system-admin', email='admin@example.test', hashed_password='x', role='admin'))
        await db.commit()
        result = await _execute_account_data_sync(db, {'engagement_sync_enabled': True, 'post_sync_enabled': False})
        assert '首轮成功 1/1' in result
        assert await db.scalar(select(func.count()).select_from(XHSAccountNote)) == 1


def test_partial_export_keeps_legacy_primary_field_protection():
    from app.services.xhs_metric_provenance import may_enrich_metric
    note = XHSAccountNote(id=7, creator_synced_at=NOW, metric_sources=None, collected_count=40)
    XHSService._apply_creator_metrics(note, {"view_count": 200})
    assert note.view_count == 200 and note.collected_count == 40
    assert not may_enrich_metric(note, "collected_count")
    assert note.metric_sources["collected_count"]["precision"] == "legacy"


@pytest.mark.asyncio
async def test_disabled_during_remote_query_fails_without_import(client, monkeypatch):
    async with async_session() as db:
        env = await environment(db)
        async def read(*args, **kwargs):
            env.status = "inactive"
            await db.commit()
            return {BINDING["xhs_id"]: (RUN, item())}
        monkeypatch.setattr(PhoneCloudXHSDataClient, "latest_items", read)
        result = await XHSCloudDataService(db).sync([env])
        assert result["synced_accounts"] == 0
        assert result["failed_accounts"][0]["error"] == "cloud_data_account_changed"
        assert await db.scalar(select(func.count()).select_from(XHSAccountNote)) == 0


@pytest.mark.asyncio
async def test_duplicate_receipt_not_reported_success_after_account_disabled(client):
    async with async_session() as db:
        env = await environment(db)
        service = XHSCloudDataService(db)
        await service.import_item(env, RUN, item(), BINDING)
        env.status = "inactive"
        await db.commit()
        with pytest.raises(CloudDataError, match="account_changed"):
            await service.import_item(env, RUN, item(), BINDING)
