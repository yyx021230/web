from __future__ import annotations

import argparse
import json
import httpx
import pytest
from sqlalchemy import func, select
from app.db.session import async_session
from app.models.user import User, UserRole
from app.models.user_xhs_env import UserXHSEnvironment
from app.models.xhs_environment import XHSEnvironment
from app.services.phone_cloud_account_registry import register_verified_account
from app.services.xhs_schedule_service import _resolve_target_environment_ids
from app.services.xhs_service import XHSService
from app.scripts import register_phone_cloud_account as registry_cli
from tests.conftest import make_auth_headers


async def seed(db):
    admin = User(username="registry-admin", email="registry-admin@test.invalid", hashed_password="x", role="admin")
    other = User(username="registry-other", email="registry-other@test.invalid", hashed_password="x", role="xhs_ops")
    db.add_all([admin, other])
    await db.flush()
    return admin, other


@pytest.mark.asyncio
async def test_registration_idempotent_and_workbench_visible(client):
    async with async_session() as db:
        admin, _ = await seed(db)
        env = await register_verified_account(db, operator=admin, owner=admin, xhs_id="95998925567", name="102")
        assert env.shop_id == "phone-cloud:95998925567" and env.is_phone_cloud
        env_id, admin_id = env.id, admin.id
        again = await register_verified_account(db, operator=admin, owner=admin, xhs_id="95998925567", name="Do not rename")
        assert again.id == env_id and again.account_name == "102"
        await db.commit()
        assert await db.scalar(select(func.count()).select_from(UserXHSEnvironment)) == 1
        assert await XHSService(db).list_environments(admin) == []
        assert await XHSService(db).list_browser_environment_statuses(refresh=True) == []
        assert await _resolve_target_environment_ids(db, {}) == []
    response = await client.get('/api/v1/hermes-workflows/bootstrap', headers=make_auth_headers(admin_id))
    assert response.status_code == 200
    assert [row['id'] for row in response.json()['data']['accounts']] == [env_id]


@pytest.mark.asyncio
async def test_existing_browser_identity_reused_without_stealing(client):
    async with async_session() as db:
        admin, other = await seed(db)
        legacy = XHSEnvironment(shop_id="real-yundeng-id", account_name="Existing", xhs_account_id="95998925567", status="active")
        db.add(legacy)
        await db.flush()
        db.add(UserXHSEnvironment(user_id=other.id, environment_id=legacy.id))
        await db.commit()
        with pytest.raises(ValueError, match="already belongs"):
            await register_verified_account(db, operator=admin, owner=admin, xhs_id="95998925567", name="102")
        assert legacy.shop_id == "real-yundeng-id"
        assert await db.scalar(select(func.count()).select_from(XHSEnvironment)) == 1
        reused = await register_verified_account(db, operator=admin, owner=other, xhs_id="95998925567", name="102")
        assert reused.id == legacy.id and reused.account_name == "Existing"


@pytest.mark.asyncio
@pytest.mark.parametrize("identity", ["", "123", "phone-cloud:123456", "12345/xx", "１２３４５６", "1" * 41])
async def test_invalid_identity_rejected_without_writes(client, identity):
    async with async_session() as db:
        admin, _ = await seed(db)
        with pytest.raises(ValueError, match="Invalid"):
            await register_verified_account(db, operator=admin, owner=admin, xhs_id=identity, name="102")
        assert await db.scalar(select(func.count()).select_from(XHSEnvironment)) == 0


@pytest.mark.asyncio
async def test_non_admin_and_duplicate_identity_rejected(client):
    async with async_session() as db:
        admin, other = await seed(db)
        with pytest.raises(ValueError, match="administrator"):
            await register_verified_account(db, operator=other, owner=other, xhs_id="95998925567", name="102")
        db.add_all([XHSEnvironment(shop_id="real-a", account_name="a", xhs_account_id="95998925567"),
                    XHSEnvironment(shop_id="real-b", account_name="b", xhs_account_id="95998925567")])
        await db.flush()
        with pytest.raises(ValueError, match="Conflicting"):
            await register_verified_account(db, operator=admin, owner=admin, xhs_id="95998925567", name="102")


@pytest.mark.asyncio
async def test_multi_role_admin_and_disabled_users(client):
    async with async_session() as db:
        admin, owner = await seed(db)
        admin.role = "viewer"
        db.add(UserRole(user_id=admin.id, role="admin"))
        await db.flush()
        env = await register_verified_account(db, operator=admin, owner=owner, xhs_id="95998925567", name="102")
        assert env.is_phone_cloud
        for disabled in (admin, owner):
            disabled.is_active = False
            await db.flush()
            with pytest.raises(ValueError, match="administrator"):
                await register_verified_account(db, operator=admin, owner=owner, xhs_id="95998925568", name="103")
            disabled.is_active = True
            await db.flush()
        assert await db.scalar(select(func.count()).select_from(XHSEnvironment)) == 1


@pytest.mark.asyncio
async def test_yundeng_sync_preserves_phone_identity_and_never_opens_browser(client, monkeypatch):
    async with async_session() as db:
        admin, _ = await seed(db)
        phone = await register_verified_account(db, operator=admin, owner=admin, xhs_id="95998925567", name="102")
        db.add(XHSEnvironment(shop_id="removed-browser", account_name="Removed", status="active"))
        await db.commit()
        service = XHSService(db)
        monkeypatch.setattr(service, '_should_delegate_browser_ops', lambda: False)
        monkeypatch.setattr(service, '_require_local_browser_ops', lambda *args: None)
        calls = []
        def handler(request):
            calls.append(request.url.path)
            if request.url.path.endswith('shopseriallist'):
                return httpx.Response(200, json={"code": 0, "data": {"list": [{"shopId": "real-current"}]}})
            assert request.url.path.endswith('shopdetaillist')
            return httpx.Response(200, json={"code": 0, "data": {"browser": [{"browserid": "real-current", "name": "Current"}]}})
        original_client = httpx.AsyncClient
        monkeypatch.setattr('app.services.xhs_service.httpx.AsyncClient',
                            lambda **kwargs: original_client(transport=httpx.MockTransport(handler), **kwargs))
        assert await service.sync_environments_from_yundeng() == 1
        await db.refresh(phone)
        assert phone.status == "active" and phone.account_name == "102"
        assert (await db.scalar(select(XHSEnvironment).where(XHSEnvironment.shop_id == "removed-browser"))).status == "inactive"
        for operation in (service._request_browser_ws_for_online_environment, service.get_browser_environment_status):
            with pytest.raises(ValueError, match="云手机"):
                await operation(phone)
        with pytest.raises(ValueError, match="云手机"):
            await service._stop_browser(phone.shop_id)
        assert len(calls) == 2


@pytest.mark.asyncio
async def test_cli_verifies_mapping_and_registers_without_publishing(client, monkeypatch, capsys):
    async with async_session() as db:
        await seed(db)
        await db.commit()
    calls = []

    class ReadOnlyPublisher:
        async def devices(self):
            calls.append("devices")
            return [{"verified": True}]

        def target(self, devices, xhs_id):
            assert devices == [{"verified": True}] and xhs_id == "95998925567"
            calls.append("target")
            return {"device_id": "fake-device", "app_slot": "app1"}

    monkeypatch.setattr(registry_cli, "PhoneCloudPublisher", ReadOnlyPublisher)
    monkeypatch.setattr(registry_cli.settings, "phone_cloud_publish_verified_xhs_ids", "95998925567")
    args = argparse.Namespace(operator="registry-admin", owner="registry-admin", xhs_id="95998925567", name="102")
    for _ in range(2):
        await registry_cli.register(args)
        receipt = json.loads(capsys.readouterr().out)
        assert receipt["created_publish_tasks"] == 0 and receipt["source"] == "phone-cloud"
        assert receipt["app_slot"] == "app1"
    assert calls == ["devices", "target"] * 2
    async with async_session() as db:
        assert await db.scalar(select(func.count()).select_from(XHSEnvironment)) == 1
        assert await db.scalar(select(func.count()).select_from(UserXHSEnvironment)) == 1
    args.xhs_id = "95998925568"
    with pytest.raises(ValueError, match="allowlist"):
        await registry_cli.register(args)
    assert len(calls) == 4
    args.xhs_id, args.owner = "95998925567", "unknown"
    with pytest.raises(ValueError, match="Unknown"):
        await registry_cli.register(args)
