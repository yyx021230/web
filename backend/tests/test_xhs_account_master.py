"""Account master migration, import, isolation and legacy history invariants."""

import csv
from datetime import datetime
import io

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from app.db.session import async_session
from app.models.user import User
from app.models.xhs_account import (
    XHSAccount,
    XHSAccountHistoryLink,
    XHSAccountMasterImport,
)
from app.models.xhs_account_note import XHSAccountNote
from app.models.xhs_environment import XHSEnvironment
from app.services.xhs_account_master_service import (
    FIELDS,
    MasterError,
    XHSAccountMasterService,
    parse_master_csv,
)
from tests.conftest import make_auth_headers


def csv_file(*rows):
    stream = io.StringIO()
    writer = csv.writer(stream)
    writer.writerow(["Account master"])
    writer.writerow(list(FIELDS.values()))
    for changes in rows:
        row = dict(
            xhs_account_id="10000001",
            account_name="Account one",
            account_type="企业专业号",
            owner_label="Operator One",
            department="小红书部",
            login_phone_number="13800000001",
            sim_device_label="10",
            login_device_label="11",
        )
        row.update(changes)
        writer.writerow([row[k] for k in FIELDS])
    return stream.getvalue().encode("utf-8-sig")


async def seed(db):
    users = [
        User(
            id=i,
            username=f"user{i}",
            email=f"u{i}@example.invalid",
            hashed_password="unused",
            display_name=name,
            role=role,
            is_active=True,
            role_assignments=[],
        )
        for i, name, role in [
            (1, "Administrator", "admin"),
            (2, "Operator One", "xhs_ops"),
            (3, "Operator Two", "brand_ops"),
            (4, "Department Lead", "xhs_lead"),
        ]
    ]
    db.add_all(users)
    await db.commit()
    return users


async def apply(db, admin, *rows, include_history=False):
    service = XHSAccountMasterService(db)
    preview = await service.preview(csv_file(*rows), admin)
    result = await service.apply(
        preview["preview_id"],
        preview["source_hash"],
        [r["row"] for r in preview["rows"]],
        admin,
        include_history=include_history,
    )
    return service, preview, result


def test_parse_export_quoted_fields_and_placeholder_without_carry_forward():
    rows, skipped = parse_master_csv(
        csv_file(
            {"account_name": "Car, buying\nguide"},
            {"xhs_account_id": "-", "account_name": "-"},
            {"xhs_account_id": "10000002", "owner_label": ""},
        )
    )
    assert rows[0]["account_name"] == "Car, buying\nguide"
    assert rows[1]["owner_label"] == "" and rows[1]["source_row"] == 5
    assert skipped == [{"row": 4, "reason": "missing_or_placeholder_id"}]


@pytest.mark.parametrize(
    "field,value,error",
    [
        ("xhs_account_id", "1.23E10", "master_id_invalid"),
        ("login_phone_number", "private-phone", "master_phone_invalid"),
        ("account_name", "a" * 201, "master_field_too_long"),
    ],
)
def test_bad_source_data_is_bounded_and_never_disclosed(field, value, error):
    with pytest.raises(MasterError, match=error) as exc:
        parse_master_csv(csv_file({field: value}))
    assert value not in str(exc.value)


@pytest.mark.parametrize(
    "content", [b"", b"x" * 2_000_001, b"no correct headers", b"\xff"]
)
def test_reject_bad_files(content):
    with pytest.raises(MasterError):
        parse_master_csv(content)


def test_duplicate_real_ids_rejected_even_if_names_differ():
    with pytest.raises(MasterError, match="duplicate_account_id"):
        parse_master_csv(csv_file({}, {"account_name": "Other"}))


@pytest.mark.asyncio
async def test_preview_apply_idempotency_and_no_environment_required(client):
    async with async_session() as db:
        admin, *_ = await seed(db)
        service = XHSAccountMasterService(db)
        preview = await service.preview(csv_file({}), admin)
        assert await db.scalar(select(func.count()).select_from(XHSAccount)) == 0
        assert "13800000001" not in str(preview)
        result = await service.apply(
            preview["preview_id"], preview["source_hash"], [3], admin
        )
        assert result["created"] == 1 and result["history_notes_moved"] == 0
        assert await db.scalar(select(func.count()).select_from(XHSEnvironment)) == 0
        assert (
            await service.apply(
                preview["preview_id"], preview["source_hash"], [3], admin
            )
            == result
        )
        assert await db.scalar(select(func.count()).select_from(XHSAccount)) == 1
        with pytest.raises(MasterError, match="replay_scope_changed"):
            await service.apply(
                preview["preview_id"], preview["source_hash"], [4], admin
            )


@pytest.mark.asyncio
async def test_id_change_creates_new_account_same_name_never_reuses_history(client):
    async with async_session() as db:
        admin, one, *_ = await seed(db)
        service, _, _ = await apply(db, admin, {})
        old = await db.scalar(select(XHSAccount))
        note = XHSAccountNote(
            account_id=old.id,
            environment_id=None,
            title="Old account post",
            account_name="old",
            feed_id="old-feed",
        )
        db.add(note)
        await db.commit()
        _, _, result = await apply(db, admin, {"xhs_account_id": "10000002"})
        assert result["created"] == 1
        accounts = await service.accounts(one)
        assert len(accounts) == 2
        await db.refresh(note)
        assert note.account_id == old.id and old.xhs_account_id == "10000001"
        old.xhs_account_id = "10000003"
        with pytest.raises(ValueError, match="separate account"):
            await db.flush()
        await db.rollback()


@pytest.mark.asyncio
async def test_current_owner_and_department_scopes_no_private_or_unresolved_access(
    client,
):
    async with async_session() as db:
        admin, one, two, lead = await seed(db)
        service, _, _ = await apply(
            db,
            admin,
            {},
            {
                "xhs_account_id": "10000002",
                "owner_label": "Operator Two",
                "department": "品牌部",
            },
            {"xhs_account_id": "10000003", "owner_label": "Unknown"},
            {"xhs_account_id": "10000004", "department": "私域中心"},
        )
        assert len(await service.accounts(admin)) == 3
        assert len(await service.accounts(one)) == 1
        assert len(await service.accounts(two)) == 1
        assert len(await service.accounts(lead)) == 1
        original = await db.scalar(
            select(XHSAccount).where(XHSAccount.xhs_account_id == "10000001")
        )
        db.add(
            XHSAccountNote(
                account_id=original.id,
                title="History",
                account_name="Old",
                feed_id="f1",
            )
        )
        await db.commit()
        await apply(db, admin, {"owner_label": "Operator Two", "department": "品牌部"})
        assert (await service.notes(one))[1] == 0
        assert (await service.notes(two))[1] == 1
        assert (await service.notes(lead))[1] == 0
        assert len(await service.accounts(one)) == 0


@pytest.mark.asyncio
async def test_cancelled_and_unresolved_rows_not_enabled_by_import(client):
    async with async_session() as db:
        admin, *_ = await seed(db)
        service, _, _ = await apply(
            db,
            admin,
            {"account_name": "Old 已注销"},
            {"xhs_account_id": "10000002", "account_name": "", "owner_label": "-"},
            {"xhs_account_id": "10000003", "department": "Unknown"},
        )
        accounts = await service.accounts(admin)
        assert {a["status"] for a in accounts} == {"retired", "needs_review"}
        assert sum(a["status"] == "needs_review" for a in accounts) == 2


@pytest.mark.asyncio
async def test_legacy_is_not_auto_assigned_or_mutated_and_review_only_links_subset(
    client,
):
    async with async_session() as db:
        admin, one, *_ = await seed(db)
        env = XHSEnvironment(
            shop_id="browser-1",
            account_name="stale",
            xhs_account_id="10000001",
            status="active",
        )
        db.add(env)
        await db.flush()
        first = XHSAccountNote(
            environment_id=env.id,
            title="old",
            content="keep full content",
            account_name="snapshot",
            feed_id="f1",
        )
        second = XHSAccountNote(
            environment_id=env.id,
            title="other account?",
            account_name="snapshot",
            feed_id="f2",
        )
        db.add_all([first, second])
        await db.commit()
        service, _, _ = await apply(db, admin, {})
        account = await db.scalar(select(XHSAccount))
        assert (await service.notes(one))[1] == 0
        assert (
            await db.scalar(select(func.count()).select_from(XHSAccountHistoryLink))
            == 1
        )
        assert first.account_id is None and env.account_name == "stale"
        result = await service.confirm_history(
            account.id, env.id, [first.id], account.revision, admin
        )
        assert result["linked_notes"] == 1
        assert (
            first.environment_id == env.id
            and first.content == "keep full content"
            and first.account_name == "snapshot"
        )
        assert second.account_id is None and (await service.notes(one))[1] == 1
        env.xhs_account_id = "another-account"
        db.add(
            XHSAccountNote(
                environment_id=env.id,
                title="future replacement",
                account_name="replacement",
            )
        )
        await db.commit()
        assert (await service.notes(one))[1] == 1
        assert await db.scalar(select(func.count()).select_from(XHSAccountNote)) == 3


@pytest.mark.asyncio
async def test_preview_staleness_and_partial_invalid_apply_are_atomic(client):
    async with async_session() as db:
        admin, *_ = await seed(db)
        service = XHSAccountMasterService(db)
        preview = await service.preview(csv_file({}), admin)
        with pytest.raises(MasterError, match="selected_rows_invalid"):
            await service.apply(
                preview["preview_id"], preview["source_hash"], [3, 999], admin
            )
        await db.rollback()
        assert await db.scalar(select(func.count()).select_from(XHSAccount)) == 0
        assert (
            await db.get(XHSAccountMasterImport, preview["preview_id"])
        ).status == "preview"
        user = await db.get(User, 2)
        user.display_name = "Renamed person"
        await db.commit()
        admin = await db.scalar(
            select(User)
            .options(selectinload(User.role_assignments))
            .where(User.id == 1)
        )
        with pytest.raises(MasterError, match="preview_stale"):
            await service.apply(
                preview["preview_id"], preview["source_hash"], [3], admin
            )
        await db.rollback()
        assert await db.scalar(select(func.count()).select_from(XHSAccount)) == 0


@pytest.mark.asyncio
async def test_private_excluded_preview_expiry_and_admin_boundary(client):
    async with async_session() as db:
        admin, one, *_ = await seed(db)
        service = XHSAccountMasterService(db)
        with pytest.raises(MasterError, match="admin_required"):
            await service.preview(csv_file({}), one)
        preview = await service.preview(csv_file({"department": "私域中心"}), admin)
        assert preview["rows"] == [] and preview["skipped"] == [
            {"row": 3, "reason": "private_department_excluded"}
        ]
        preview = await service.preview(csv_file({}), admin)
        receipt = await db.get(XHSAccountMasterImport, preview["preview_id"])
        receipt.expires_at = datetime(2000, 1, 1)
        await db.commit()
        with pytest.raises(MasterError, match="preview_expired"):
            await service.apply(
                preview["preview_id"], preview["source_hash"], [3], admin
            )
        await db.rollback()


@pytest.mark.asyncio
async def test_api_complete_import_and_authorization(client):
    async with async_session() as db:
        await seed(db)
    url = "/api/v1/admin/xhs/account-master/previews"
    assert (
        await client.post(
            url,
            files={"file": ("master.csv", csv_file({}), "text/csv")},
            headers=make_auth_headers(2),
        )
    ).status_code == 403
    r = await client.post(
        url,
        files={"file": ("master.csv", csv_file({}), "text/csv")},
        headers=make_auth_headers(1),
    )
    assert r.status_code == 200 and "13800000001" not in r.text
    p = r.json()["data"]
    result = await client.post(
        f"{url}/{p['preview_id']}/apply",
        json={"source_hash": p["source_hash"], "rows": [3]},
        headers=make_auth_headers(1),
    )
    assert result.status_code == 200 and result.json()["data"]["created"] == 1
    response = await client.get("/api/v1/xhs/accounts", headers=make_auth_headers(2))
    assert response.status_code == 200 and len(response.json()["data"]) == 1
    assert "login_phone_number" not in response.text
    assert (
        await client.get("/api/v1/xhs/accounts", headers=make_auth_headers(3))
    ).json()["data"] == []


@pytest.mark.asyncio
async def test_independent_insights_follow_owner_without_mutating_note_snapshot(client):
    async with async_session() as db:
        admin, one, *_ = await seed(db)
        service, _, _ = await apply(db, admin, {})
        account = await db.scalar(select(XHSAccount))
        note = XHSAccountNote(
            account_id=account.id,
            title="Car guide",
            account_name="Old name",
            view_count=5000,
            liked_count=20,
            comment_count=30,
            published_at=datetime(2026, 11, 12, 0),
        )
        db.add(note)
        await db.commit()
        dashboard = await service.insights(one)
        assert dashboard["metrics"]["totalPosts"] == 1
        await db.refresh(note)
        assert note.account_name == "Old name" and note.environment_id is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "old_id,new_id",
    [
        ("63025106935", "94546474724"),
        ("63082245293", "94558682071"),
        ("6301727690", "63017276905"),
    ],
)
async def test_confirmed_corrections_attribute_history_without_changing_legacy_identity(
    client, old_id, new_id
):
    async with async_session() as db:
        admin, one, *_ = await seed(db)
        env = XHSEnvironment(
            shop_id="old",
            account_name="Old nickname",
            xhs_account_id=old_id,
            status="inactive",
        )
        db.add(env)
        await db.flush()
        note = XHSAccountNote(
            environment_id=env.id,
            account_name="Capture snapshot",
            red_id=old_id,
            title="Historical post",
            content="keep original",
            feed_id="abc",
            view_count=5100,
        )
        db.add(note)
        await db.commit()
        service, preview, result = await apply(
            db, admin, {"xhs_account_id": new_id}, include_history=True
        )
        assert preview["rows"][0]["confirmed_old_id"] == old_id
        assert result["history_notes_moved"] == 1 and result["history_conflicts"] == []
        assert (await service.notes(one))[1] == 1
        await db.refresh(note)
        await db.refresh(env)
        assert (
            env.xhs_account_id == old_id
            and note.red_id == old_id
            and note.content == "keep original"
        )
        assert note.environment_id == env.id and note.view_count == 5100


@pytest.mark.asyncio
async def test_history_duplicate_and_wrong_identity_retained_and_reported(client):
    async with async_session() as db:
        admin, one, *_ = await seed(db)
        for index in range(2):
            env = XHSEnvironment(
                shop_id=f"old{index}", account_name="Old", xhs_account_id="10000001"
            )
            db.add(env)
            await db.flush()
            db.add(
                XHSAccountNote(
                    environment_id=env.id,
                    account_name="Old",
                    feed_id="same",
                    title="Same post",
                )
            )
            if index == 0:
                db.add(
                    XHSAccountNote(
                        environment_id=env.id,
                        account_name="Other",
                        red_id="10000099",
                        feed_id="other",
                    )
                )
        await db.commit()
        service, _, result = await apply(db, admin, {}, include_history=True)
        assert (
            result["history_notes_moved"] == 1 and len(result["history_conflicts"]) == 2
        )
        assert (await service.notes(one))[1] == 1
        assert await db.scalar(select(func.count()).select_from(XHSAccountNote)) == 3


@pytest.mark.asyncio
async def test_history_modified_after_preview_rejects_whole_transaction(client):
    async with async_session() as db:
        admin, *_ = await seed(db)
        env = XHSEnvironment(
            shop_id="old", account_name="Old", xhs_account_id="10000001"
        )
        db.add(env)
        await db.flush()
        note = XHSAccountNote(environment_id=env.id, account_name="Old", title="Before")
        db.add(note)
        await db.commit()
        service = XHSAccountMasterService(db)
        preview = await service.preview(csv_file({}), admin)
        note.title = "Concurrent update"
        await db.commit()
        with pytest.raises(MasterError, match="history_changed"):
            await service.apply(
                preview["preview_id"],
                preview["source_hash"],
                [3],
                admin,
                include_history=True,
            )
        await db.rollback()
        assert await db.scalar(select(func.count()).select_from(XHSAccount)) == 0


@pytest.mark.asyncio
async def test_master_rename_invalidates_dashboard_without_mutating_note(client):
    async with async_session() as db:
        admin, owner, *_ = await seed(db)
        service, _, _ = await apply(db, admin, {"account_name": "Before rename"})
        account = await db.scalar(select(XHSAccount))
        note = XHSAccountNote(
            account_id=account.id, account_name="Capture name", title="Car guide"
        )
        db.add(note)
        await db.commit()
        first = await service.insights(owner)
        assert first["accountSummaries"][0]["accountName"] == "Before rename"
        await apply(db, admin, {"account_name": "After rename"})
        second = await service.insights(owner)
        assert second["accountSummaries"][0]["accountName"] == "After rename"
        await db.refresh(note)
        assert note.account_name == "Capture name"
