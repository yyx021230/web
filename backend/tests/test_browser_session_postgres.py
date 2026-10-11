"""Opt-in isolated PG tests. Never point SESSION_TEST_PG_URL at a shared DB."""

import asyncio
from datetime import timedelta
import os
import uuid

import pytest
import pytest_asyncio
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.schema import CreateSchema, DropSchema

from app.models.auth_session import AuthSession
from app.models.user import User, UserRole
from app.services.auth_session_service import create_session, refresh_value, revoke_cookie, rotate_session, utcnow

PG_URL = os.getenv("SESSION_TEST_PG_URL", "")
pytestmark = [pytest.mark.asyncio, pytest.mark.skipif(not PG_URL, reason="isolated PostgreSQL not configured")]


@pytest_asyncio.fixture
async def pg_factory():
    # Each test has its own schema; production databases are never a valid target.
    if "ztqc-session-pg." not in PG_URL or "host=/tmp/" not in PG_URL:
        pytest.fail("SESSION_TEST_PG_URL must use the disposable local Unix socket")
    schema = "session_test_" + uuid.uuid4().hex
    admin = create_async_engine(PG_URL)
    async with admin.begin() as connection:
        await connection.execute(CreateSchema(schema))
    engine = create_async_engine(PG_URL, connect_args={"server_settings": {"search_path": schema}})
    try:
        async with engine.begin() as connection:
            for table in (User.__table__, UserRole.__table__, AuthSession.__table__):
                await connection.run_sync(table.create)
        yield async_sessionmaker(engine, expire_on_commit=False)
    finally:
        await engine.dispose()
        async with admin.begin() as connection:
            await connection.execute(DropSchema(schema, cascade=True))
        await admin.dispose()


async def seeded(factory):
    async with factory() as db:
        user = User(username="pg_user", email="pg@example.com", hashed_password="fake-test-hash", role="viewer")
        db.add(user)
        await db.commit()
        row, _ = await create_session(db, user)
        return row.id, refresh_value(row)


async def test_postgres_independent_connections_rotate_once(pg_factory):
    sid, cookie = await seeded(pg_factory)
    async with pg_factory() as db:
        before = (await db.get(AuthSession, sid)).last_active_at

    async def rotate():
        async with pg_factory() as db:
            row, _ = await rotate_session(db, cookie, "a" * 32)
            return refresh_value(row)

    cookies = await asyncio.gather(*(rotate() for _ in range(10)))
    assert len(set(cookies)) == 1
    async with pg_factory() as db:
        row = await db.get(AuthSession, sid)
        assert row.generation == 1
        assert row.last_active_at == before


async def test_postgres_logout_wins_over_inflight_rotations(pg_factory):
    sid, cookie = await seeded(pg_factory)

    async def rotate():
        async with pg_factory() as db:
            try:
                await rotate_session(db, cookie, "a" * 32)
            except Exception as error:
                assert getattr(error, "status_code", None) == 401

    async def logout():
        async with pg_factory() as db:
            await revoke_cookie(db, cookie)

    await asyncio.gather(*(rotate() for _ in range(5)), logout())
    async with pg_factory() as db:
        assert (await db.get(AuthSession, sid)).revoked_at is not None
        with pytest.raises(Exception) as failure:
            await rotate_session(db, cookie, "a" * 32)
        assert failure.value.status_code == 401


async def test_postgres_rotation_survives_connection_restart_without_activity_write(pg_factory):
    sid, cookie = await seeded(pg_factory)
    before = utcnow() - timedelta(days=2)
    async with pg_factory() as db:
        await db.execute(update(AuthSession).where(AuthSession.id == sid).values(last_active_at=before))
        await db.commit()
    async with pg_factory() as db:
        row, _ = await rotate_session(db, cookie, "a" * 32)
        new_cookie = refresh_value(row)
    async with pg_factory() as db:
        row, _ = await rotate_session(db, cookie, "a" * 32)
        assert refresh_value(row) == new_cookie
        assert row.last_active_at == before
        assert (await db.execute(select(User))).scalar_one().username == "pg_user"
