"""The complete sheet is authoritative; only genuinely unreferenced identities are removed."""

import pytest
from sqlalchemy import Column, ForeignKey, Integer, MetaData, Table, select

from app.db.session import async_session
from app.models.xhs_account import XHSAccount, XHSAccountHistoryLink
from app.models.xhs_account_note import XHSAccountNote
from app.models.xhs_cloud_import import XHSCloudImport
from app.models.xhs_environment import XHSEnvironment
from app.services.xhs_account_master_service import MasterError
from tests.conftest import make_auth_headers
from tests.test_xhs_account_master import apply, csv_file, seed


async def apply_full(service, admin, content):
    preview = await service.preview(content, admin)
    result = await service.apply(
        preview["preview_id"],
        preview["source_hash"],
        [row["row"] for row in preview["rows"]],
        admin,
        replace_all=True,
    )
    return preview, result


@pytest.mark.asyncio
async def test_full_roster_removes_empty_and_archives_referenced_accounts(client):
    async with async_session() as db:
        admin, owner, *_ = await seed(db)
        service, _, _ = await apply(
            db,
            admin,
            {},
            {"xhs_account_id": "10000002"},
            {"xhs_account_id": "10000003"},
        )
        by_id = {
            a.xhs_account_id: a for a in (await db.scalars(select(XHSAccount))).all()
        }
        empty_id, historical_id = by_id["10000002"].id, by_id["10000003"].id
        note = XHSAccountNote(
            account_id=historical_id,
            account_name="Keep snapshot",
            title="Keep title",
            content="Keep body",
            view_count=6700,
        )
        db.add(note)
        await db.commit()
        preview, result = await apply_full(service, admin, csv_file({}))
        assert {row["action"] for row in preview["unlisted_accounts"]} == {
            "delete_empty",
            "archive_history",
        }
        assert (
            result["unlisted_accounts_deleted"] == 1
            and result["unlisted_accounts_archived"] == 1
        )
        assert await db.get(XHSAccount, empty_id) is None
        archive = await db.get(XHSAccount, historical_id)
        assert archive.status == "archived" and archive.owner_user_id == owner.id
        await db.refresh(note)
        assert note.content == "Keep body" and note.view_count == 6700
        assert [a["xhs_account_id"] for a in await service.accounts(owner)] == [
            "10000001"
        ]
        assert (await service.notes(owner))[1] == 0
        assert (await service.notes(admin))[1] == 1
        again = await service.apply(
            preview["preview_id"], preview["source_hash"], [3], admin, replace_all=True
        )
        assert again == result
        with pytest.raises(MasterError, match="replay_scope_changed"):
            await service.apply(
                preview["preview_id"], preview["source_hash"], [3], admin
            )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "reference", ["cloud_receipt", "history_link", "extension_table"]
)
async def test_no_posts_does_not_mean_no_history(client, reference):
    async with async_session() as db:
        admin, *_ = await seed(db)
        service, _, _ = await apply(db, admin, {}, {"xhs_account_id": "10000002"})
        account = await db.scalar(
            select(XHSAccount).where(XHSAccount.xhs_account_id == "10000002")
        )
        if reference == "cloud_receipt":
            db.add(
                XHSCloudImport(
                    account_id=account.id,
                    client_id="test",
                    run_id="a" * 64,
                    item_id="1",
                    payload_hash="b" * 64,
                    payload={"test": True},
                    status="quarantined",
                )
            )
        elif reference == "history_link":
            env = XHSEnvironment(shop_id="history", account_name="Old environment")
            db.add(env)
            await db.flush()
            db.add(
                XHSAccountHistoryLink(
                    account_id=account.id,
                    environment_id=env.id,
                    xhs_id_snapshot="10000002",
                )
            )
        else:
            metadata = MetaData()
            connection = await db.connection()
            await connection.run_sync(
                lambda sync: Table("xhs_accounts", metadata, autoload_with=sync)
            )
            extension = Table(
                "test_roster_extension",
                metadata,
                Column("id", Integer, primary_key=True),
                Column(
                    "identity_id",
                    Integer,
                    ForeignKey("xhs_accounts.id", ondelete="CASCADE"),
                ),
            )
            await connection.run_sync(lambda sync: extension.create(sync))
            await db.execute(extension.insert().values(id=1, identity_id=account.id))
        await db.commit()
        try:
            preview, result = await apply_full(service, admin, csv_file({}))
            assert preview["unlisted_accounts"][0]["action"] == "archive_history"
            assert (
                result["unlisted_accounts_deleted"] == 0
                and result["unlisted_accounts_archived"] == 1
            )
            await db.refresh(account)
            assert account.status == "archived"
            if reference == "extension_table":
                assert await db.scalar(select(extension.c.id)) == 1
        finally:
            if reference == "extension_table":
                await db.rollback()
                connection = await db.connection()
                await connection.run_sync(lambda sync: extension.drop(sync))
                await db.commit()


@pytest.mark.asyncio
async def test_partial_import_never_removes_other_accounts_and_full_mode_needs_all_rows(
    client,
):
    async with async_session() as db:
        admin, *_ = await seed(db)
        service, _, _ = await apply(db, admin, {}, {"xhs_account_id": "10000002"})
        _, _, result = await apply(db, admin, {})
        assert (
            result["unlisted_accounts_deleted"] == 0
            and len(await service.accounts(admin)) == 2
        )
        preview = await service.preview(
            csv_file({}, {"xhs_account_id": "10000003"}), admin
        )
        with pytest.raises(MasterError, match="full_sheet_selection_required"):
            await service.apply(
                preview["preview_id"],
                preview["source_hash"],
                [3],
                admin,
                replace_all=True,
            )
        await db.rollback()
        assert len((await db.scalars(select(XHSAccount))).all()) == 2


@pytest.mark.asyncio
async def test_new_history_since_preview_aborts_roster_replacement_atomically(client):
    async with async_session() as db:
        admin, *_ = await seed(db)
        service, _, _ = await apply(db, admin, {}, {"xhs_account_id": "10000002"})
        account = await db.scalar(
            select(XHSAccount).where(XHSAccount.xhs_account_id == "10000002")
        )
        account_id = account.id
        preview = await service.preview(
            csv_file({"account_name": "Should not apply"}), admin
        )
        db.add(
            XHSAccountNote(
                account_id=account.id, account_name="Late history", title="Keep me"
            )
        )
        await db.commit()
        with pytest.raises(MasterError, match="retirement_changed"):
            await service.apply(
                preview["preview_id"],
                preview["source_hash"],
                [3],
                admin,
                replace_all=True,
            )
        await db.rollback()
        assert (
            await db.scalar(
                select(XHSAccount.account_name).where(
                    XHSAccount.xhs_account_id == "10000001"
                )
            )
        ) == "Account one"
        assert (await db.get(XHSAccount, account_id)).status == "active"


@pytest.mark.asyncio
async def test_removed_account_pk_is_not_reused_for_a_different_identity(client):
    async with async_session() as db:
        admin, *_ = await seed(db)
        service, _, _ = await apply(db, admin, {}, {"xhs_account_id": "10000002"})
        maximum = max(a["id"] for a in await service.accounts(admin))
        await apply_full(service, admin, csv_file({}))
        await apply(db, admin, {"xhs_account_id": "10000003"})
        assert (
            await db.scalar(
                select(XHSAccount.id).where(XHSAccount.xhs_account_id == "10000003")
            )
        ) > maximum


@pytest.mark.asyncio
async def test_api_complete_roster_and_archived_account_cannot_sync(client):
    async with async_session() as db:
        admin, *_ = await seed(db)
        _, _, _ = await apply(db, admin, {}, {"xhs_account_id": "10000002"})
        historical_id = await db.scalar(
            select(XHSAccount.id).where(XHSAccount.xhs_account_id == "10000002")
        )
        db.add(XHSAccountNote(account_id=historical_id, account_name="History"))
        await db.commit()
    root = "/api/v1/admin/xhs/account-master"
    p = (
        await client.post(
            f"{root}/previews",
            files={"file": ("master.csv", csv_file({}), "text/csv")},
            headers=make_auth_headers(1),
        )
    ).json()["data"]
    response = await client.post(
        f"{root}/previews/{p['preview_id']}/apply",
        json={"source_hash": p["source_hash"], "rows": [3], "replace_all": True},
        headers=make_auth_headers(1),
    )
    assert (
        response.status_code == 200
        and response.json()["data"]["unlisted_accounts_archived"] == 1
    )
    response = await client.post(
        f"{root}/cloud-data/import",
        json={"account_ids": [historical_id]},
        headers=make_auth_headers(1),
    )
    assert response.status_code == 422
