"""Master accounts can import mobile observations with no browser record at all."""

import json
from datetime import date

import pytest
from sqlalchemy import func, select

from app.adapters.phone_cloud_xhs_data import CloudDataError, PhoneCloudXHSDataClient
from app.config import settings
from app.db.session import async_session
from app.models.xhs_account import XHSAccount
from app.models.xhs_account_note import XHSAccountNote
from app.models.xhs_cloud_import import XHSCloudImport
from app.models.xhs_environment import XHSEnvironment
from app.services.xhs_cloud_data_service import XHSCloudDataService
import app.services.xhs_cloud_data_service as cloud
from tests.test_xhs_account_master import apply, seed
from tests.test_xhs_cloud_data import BINDING, NOW, RUN, item
from tests.conftest import make_auth_headers


@pytest.fixture(autouse=True)
def isolated_cloud_settings(monkeypatch):
    monkeypatch.setattr(cloud, "utc_now_naive", lambda: NOW)
    monkeypatch.setattr(
        settings, "phone_cloud_xhs_data_client_id", "master-test-client"
    )
    monkeypatch.setattr(settings, "phone_cloud_xhs_data_secret", "test-only")
    monkeypatch.setattr(
        settings, "phone_cloud_xhs_data_base_url", "https://phone.invalid"
    )
    monkeypatch.setattr(
        settings, "phone_cloud_xhs_verified_bindings", json.dumps([BINDING])
    )


@pytest.mark.asyncio
async def test_no_browser_master_import_replay_and_current_owner_visibility(client):
    async with async_session() as db:
        admin, owner, *_ = await seed(db)
        master, _, _ = await apply(db, admin, {"xhs_account_id": BINDING["xhs_id"]})
        account = await db.scalar(select(XHSAccount))
        service = XHSCloudDataService(db)
        result = await service.import_item(account, RUN, item(), BINDING)
        assert result["created_notes"] == 1
        assert (await service.import_item(account, RUN, item(), BINDING))[
            "duplicate"
        ] is True
        note = await db.scalar(select(XHSAccountNote))
        receipt = await db.scalar(select(XHSCloudImport))
        assert note.environment_id is None and note.account_id == account.id
        assert receipt.environment_id is None and receipt.account_id == account.id
        assert await db.scalar(select(func.count()).select_from(XHSEnvironment)) == 0
        assert (await master.notes(owner))[1] == 1
        dashboard = await master.insights(owner, date(2026, 11, 12), date(2026, 11, 12))
        assert dashboard["metrics"]["totalPosts"] == 1
        assert dashboard["trend"][0]["posts"] == 1
        await apply(
            db,
            admin,
            {
                "xhs_account_id": BINDING["xhs_id"],
                "owner_label": "Operator Two",
                "department": "品牌部",
            },
        )
        assert (await master.notes(owner))[1] == 0


@pytest.mark.asyncio
async def test_receipt_cannot_be_replayed_between_legacy_and_master_subjects(client):
    async with async_session() as db:
        admin, *_ = await seed(db)
        await apply(db, admin, {"xhs_account_id": BINDING["xhs_id"]})
        account = await db.scalar(select(XHSAccount))
        service = XHSCloudDataService(db)
        await service.import_item(account, RUN, item(), BINDING)
        env = XHSEnvironment(
            shop_id="legacy",
            account_name="old",
            xhs_account_id=BINDING["xhs_id"],
            status="active",
        )
        db.add(env)
        await db.commit()
        with pytest.raises(CloudDataError, match="observation_conflict"):
            await service.import_item(env, RUN, item(), BINDING)
        assert await db.scalar(select(func.count()).select_from(XHSAccountNote)) == 1


@pytest.mark.asyncio
async def test_api_import_uses_only_existing_observations_and_excludes_retired(
    client, monkeypatch
):
    requests = []

    async def latest(_self, ids):
        requests.append(ids)
        return {BINDING["xhs_id"]: (RUN, item())}

    monkeypatch.setattr(PhoneCloudXHSDataClient, "latest_items", latest)
    async with async_session() as db:
        admin, *_ = await seed(db)
        await apply(db, admin, {"xhs_account_id": BINDING["xhs_id"]})
        account = await db.scalar(select(XHSAccount))
        account_id = account.id
    url = "/api/v1/admin/xhs/account-master/cloud-data/import"
    assert (
        await client.post(
            url, json={"account_ids": [account_id]}, headers=make_auth_headers(2)
        )
    ).status_code == 403
    response = await client.post(
        url, json={"account_ids": [account_id]}, headers=make_auth_headers(1)
    )
    assert response.status_code == 200 and response.json()["data"]["created_notes"] == 1
    assert requests == [{BINDING["xhs_id"]}]
    response = await client.post(
        url, json={"account_ids": [account_id, 999]}, headers=make_auth_headers(1)
    )
    assert response.status_code == 422 and len(requests) == 1
    async with async_session() as db:
        account = await db.get(XHSAccount, account_id)
        account.status = "retired"
        await db.commit()
    assert (
        await client.post(
            url, json={"account_ids": [account_id]}, headers=make_auth_headers(1)
        )
    ).status_code == 422
