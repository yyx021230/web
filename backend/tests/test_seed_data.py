from __future__ import annotations

import pytest
from sqlalchemy import func, select

from app.db.session import async_session
from app.models.material import Material
from app.models.template import Template
from app.models.user import User, UserRole
from app.scripts import seed_data


def _configure_admin(monkeypatch, *, username: str = "seed-admin") -> None:
    monkeypatch.setenv("SEED_ADMIN_USERNAME", username)
    monkeypatch.setenv("SEED_ADMIN_EMAIL", f"{username}@example.com")
    monkeypatch.setenv("SEED_ADMIN_PASSWORD", "local-test-password")


def _configure_seed_session(monkeypatch, *argv: str) -> None:
    monkeypatch.setattr(seed_data, "get_local_session", lambda: async_session)
    monkeypatch.setattr(seed_data.sys, "argv", ["seed_data", *argv])


async def _counts() -> tuple[int, int, int, int]:
    async with async_session() as db:
        return (
            int((await db.execute(select(func.count(User.id)))).scalar_one()),
            int((await db.execute(select(func.count(UserRole.id)))).scalar_one()),
            int((await db.execute(select(func.count(Template.id)))).scalar_one()),
            int((await db.execute(select(func.count(Material.id)))).scalar_one()),
        )


@pytest.mark.asyncio
async def test_seed_data_creates_admin_role_assignments(monkeypatch, client):
    _configure_admin(monkeypatch)
    _configure_seed_session(monkeypatch)

    await seed_data.seed()

    async with async_session() as db:
        admin = (
            await db.execute(select(User).where(User.username == "seed-admin"))
        ).scalar_one()
        roles = (
            await db.execute(
                select(UserRole.role).where(UserRole.user_id == admin.id)
            )
        ).scalars().all()

    assert admin.role == "admin"
    assert roles == ["admin"]
    assert await _counts() == (1, 1, 5, 46)


@pytest.mark.asyncio
async def test_seeded_admin_can_login_and_access_admin_api(monkeypatch, client):
    _configure_admin(monkeypatch)
    _configure_seed_session(monkeypatch)
    await seed_data.seed()

    login = await client.post(
        "/api/v1/auth/login",
        json={"username": "seed-admin", "password": "local-test-password"},
    )
    assert login.status_code == 200
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    me = await client.get("/api/v1/auth/me", headers=headers)
    jobs = await client.get("/api/v1/admin/reliability/jobs", headers=headers)
    assert me.status_code == 200
    assert me.json()["roles"] == ["admin"]
    assert jobs.status_code == 200


@pytest.mark.asyncio
async def test_seed_data_rejects_missing_admin_credentials_without_partial_rows(
    monkeypatch, client
):
    for name in (
        "SEED_ADMIN_USERNAME",
        "SEED_ADMIN_EMAIL",
        "SEED_ADMIN_PASSWORD",
    ):
        monkeypatch.delenv(name, raising=False)
    _configure_seed_session(monkeypatch)

    with pytest.raises(RuntimeError, match="缺少 SEED_ADMIN"):
        await seed_data.seed()

    assert await _counts() == (0, 0, 0, 0)


@pytest.mark.asyncio
async def test_seed_data_second_run_is_idempotent_without_credentials(
    monkeypatch, client
):
    _configure_admin(monkeypatch)
    _configure_seed_session(monkeypatch)
    await seed_data.seed()

    for name in (
        "SEED_ADMIN_USERNAME",
        "SEED_ADMIN_EMAIL",
        "SEED_ADMIN_PASSWORD",
    ):
        monkeypatch.delenv(name, raising=False)
    await seed_data.seed()

    assert await _counts() == (1, 1, 5, 46)


@pytest.mark.asyncio
async def test_seed_data_repairs_partial_database_with_missing_admin(
    monkeypatch, client
):
    async with async_session() as db:
        db.add(
            Template(
                name="已有模板",
                fabric_json='{"objects": []}',
                category="poster",
                tags=[],
            )
        )
        await db.commit()

    _configure_admin(monkeypatch, username="repair-admin")
    _configure_seed_session(monkeypatch)
    await seed_data.seed()

    assert await _counts() == (1, 1, 1, 0)
    async with async_session() as db:
        admin = (
            await db.execute(select(User).where(User.username == "repair-admin"))
        ).scalar_one()
    assert admin.role == "admin"


@pytest.mark.asyncio
async def test_seed_reset_reseeds_assets_without_deleting_users(monkeypatch, client):
    _configure_admin(monkeypatch)
    _configure_seed_session(monkeypatch)
    await seed_data.seed()
    async with async_session() as db:
        db.add(
            User(
                username="kept-viewer",
                email="kept-viewer@example.com",
                hashed_password="x",
                role="viewer",
            )
        )
        await db.commit()

    for name in (
        "SEED_ADMIN_USERNAME",
        "SEED_ADMIN_EMAIL",
        "SEED_ADMIN_PASSWORD",
    ):
        monkeypatch.delenv(name, raising=False)
    _configure_seed_session(monkeypatch, "--reset")
    await seed_data.seed()

    assert await _counts() == (2, 1, 5, 46)
    async with async_session() as db:
        usernames = set((await db.execute(select(User.username))).scalars())
    assert usernames == {"seed-admin", "kept-viewer"}


@pytest.mark.asyncio
async def test_seed_data_rejects_non_admin_credential_conflict(monkeypatch, client):
    async with async_session() as db:
        db.add(
            User(
                username="seed-admin",
                email="viewer@example.com",
                hashed_password="x",
                role="viewer",
            )
        )
        await db.commit()

    _configure_admin(monkeypatch)
    _configure_seed_session(monkeypatch)
    with pytest.raises(RuntimeError, match="非管理员账户占用"):
        await seed_data.seed()

    assert await _counts() == (1, 0, 0, 0)
