"""Opt-in master import race tests on a disposable, explicitly selected local PG database."""

import asyncio
import os

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import selectinload

from app.models.user import User
from app.models.xhs_account import XHSAccount
from app.models.xhs_account_note import XHSAccountNote
from app.models.xhs_environment import XHSEnvironment
from app.services.xhs_account_master_service import MasterError, XHSAccountMasterService
from tests.test_xhs_account_master import csv_file, seed


@pytest.mark.asyncio
async def test_postgres_master_concurrent_apply_and_history_retention():
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
            admin, *_ = await seed(db)
            env = XHSEnvironment(
                shop_id="master-pg-only",
                account_name="Historical snapshot",
                xhs_account_id="63025106935",
                status="inactive",
            )
            db.add(env)
            await db.flush()
            note = XHSAccountNote(
                environment_id=env.id,
                account_name="Capture name",
                feed_id="pg-history",
                title="Preserve this post",
                content="Keep full body",
                view_count=4000,
            )
            db.add(note)
            await db.commit()
            note_id = note.id
            env_id = env.id
            preview = await XHSAccountMasterService(db).preview(
                csv_file({"xhs_account_id": "94546474724"}), admin
            )

        async def apply():
            async with sessions() as db:
                admin = await db.scalar(
                    select(User)
                    .options(selectinload(User.role_assignments))
                    .where(User.id == 1)
                )
                try:
                    return await XHSAccountMasterService(db).apply(
                        preview["preview_id"],
                        preview["source_hash"],
                        [3],
                        admin,
                        include_history=True,
                    )
                except MasterError as exc:
                    await db.rollback()
                    return {"error": str(exc)}

        results = await asyncio.gather(apply(), apply())
        assert any(result.get("created") == 1 for result in results)
        assert all(
            result.get("error") in {None, "master_import_busy"} for result in results
        )
        async with sessions() as db:
            assert await db.scalar(select(func.count()).select_from(XHSAccount)) == 1
            note = await db.get(XHSAccountNote, note_id)
            assert note.account_id is not None and note.environment_id == env_id
            assert note.content == "Keep full body" and note.view_count == 4000
            assert (
                await db.get(XHSEnvironment, env_id)
            ).xhs_account_id == "63025106935"
            # A stale preview must not authorize a new owner assignment.
            admin = await db.scalar(
                select(User)
                .options(selectinload(User.role_assignments))
                .where(User.id == 1)
            )
            service = XHSAccountMasterService(db)
            stale = await service.preview(
                csv_file(
                    {"xhs_account_id": "94546474724", "owner_label": "Operator Two"}
                ),
                admin,
            )
            account = await db.scalar(select(XHSAccount))
            account.revision += 1
            await db.commit()
            with pytest.raises(MasterError, match="preview_stale"):
                await service.apply(
                    stale["preview_id"], stale["source_hash"], [3], admin
                )
            await db.rollback()
            assert await db.scalar(select(XHSAccount.owner_user_id)) == 2
            assert (
                await db.scalar(text("SELECT version_num FROM alembic_version"))
                == "e61113b0b002"
            )
    finally:
        await engine.dispose()
