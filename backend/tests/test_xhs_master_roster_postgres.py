"""Real FK/row-lock protection for complete roster replacement on an isolated local PG."""

import asyncio
import os

import pytest
from sqlalchemy import select
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import selectinload

from app.models.user import User
from app.models.xhs_account import XHSAccount
from app.models.xhs_account_note import XHSAccountNote
from app.services.xhs_account_master_service import XHSAccountMasterService
from tests.test_xhs_account_master import apply, csv_file, seed


@pytest.mark.asyncio
async def test_postgres_roster_replacement_rejects_late_write_to_deleted_identity(
    monkeypatch,
):
    dsn = os.environ.get("XHS_CLOUD_TEST_POSTGRES_URL")
    if not dsn:
        pytest.skip(
            "requires an explicitly provisioned disposable local PostgreSQL database"
        )
    url = make_url(dsn)
    assert url.host == "127.0.0.1" and url.database.startswith("xhs_cloud_test_")
    engine = create_async_engine(dsn)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with sessions() as db:
            admin = await db.scalar(
                select(User)
                .options(selectinload(User.role_assignments))
                .where(User.id == 1)
            )
            if admin is None:
                admin, *_ = await seed(db)
            service, _, _ = await apply(
                db,
                admin,
                {"xhs_account_id": "10000101"},
                {"xhs_account_id": "10000102"},
                {"xhs_account_id": "10000103"},
            )
            empty_id = await db.scalar(
                select(XHSAccount.id).where(XHSAccount.xhs_account_id == "10000102")
            )
            history_id = await db.scalar(
                select(XHSAccount.id).where(XHSAccount.xhs_account_id == "10000103")
            )
            db.add(
                XHSAccountNote(
                    account_id=history_id,
                    account_name="Keep historical capture",
                    title="Keep title",
                    content="Preserve body",
                )
            )
            await db.commit()
            preview = await service.preview(
                csv_file({"xhs_account_id": "10000101"}), admin
            )

        locked, writer_started = asyncio.Event(), asyncio.Event()
        original = XHSAccountMasterService.retirement_snapshot

        async def after_lock(self, ids):
            locked.set()
            await asyncio.wait_for(writer_started.wait(), timeout=5)
            return await original(self, ids)

        monkeypatch.setattr(XHSAccountMasterService, "retirement_snapshot", after_lock)

        async def replace():
            async with sessions() as db:
                admin = await db.scalar(
                    select(User)
                    .options(selectinload(User.role_assignments))
                    .where(User.id == 1)
                )
                return await XHSAccountMasterService(db).apply(
                    preview["preview_id"],
                    preview["source_hash"],
                    [3],
                    admin,
                    replace_all=True,
                )

        async def late_write():
            await asyncio.wait_for(locked.wait(), timeout=5)
            async with sessions() as db:
                writer_started.set()
                db.add(
                    XHSAccountNote(
                        account_id=empty_id,
                        account_name="Late writer",
                        title="Must not be orphaned",
                    )
                )
                try:
                    await db.commit()
                except IntegrityError:
                    await db.rollback()
                    return "removed_identity_rejected"
                return "unexpected_write"

        result, writer = await asyncio.wait_for(
            asyncio.gather(replace(), late_write()), timeout=10
        )
        assert empty_id in result["removed_account_ids"]
        assert history_id in result["archived_account_ids"]
        assert writer == "removed_identity_rejected"
        async with sessions() as db:
            assert await db.get(XHSAccount, empty_id) is None
            assert (await db.get(XHSAccount, history_id)).status == "archived"
            assert (
                await db.scalar(
                    select(XHSAccountNote.content).where(
                        XHSAccountNote.account_id == history_id
                    )
                )
                == "Preserve body"
            )
            assert not (
                await db.scalars(
                    select(XHSAccountNote.id).where(
                        XHSAccountNote.account_id == empty_id
                    )
                )
            ).all()
    finally:
        await engine.dispose()
