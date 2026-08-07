"""Department separation for managed Xiaohongshu accounts."""

from __future__ import annotations

import pytest

from app.db.session import async_session
from app.models.user import User
from app.models.xhs_environment import XHSEnvironment
from tests.conftest import make_auth_headers


async def _seed_department_users_and_environments() -> None:
    async with async_session() as db:
        db.add_all([
            User(id=1, username="admin", email="admin@test.com", hashed_password="x", role="admin"),
            User(id=2, username="brand-ops", email="brand@test.com", hashed_password="x", role="brand_ops"),
            User(id=3, username="xhs-ops", email="xhs@test.com", hashed_password="x", role="xhs_ops"),
            User(id=4, username="brand-lead", email="lead@test.com", hashed_password="x", role="brand_lead"),
        ])
        db.add_all([
            XHSEnvironment(id=101, shop_id="xhs-account", account_name="小红书账号", department="xhs", status="active"),
            XHSEnvironment(id=102, shop_id="brand-account", account_name="品牌账号", department="brand", status="active"),
        ])
        await db.commit()


@pytest.mark.asyncio
async def test_department_controls_assignment_candidates(client):
    await _seed_department_users_and_environments()

    allowed = await client.post(
        "/api/v1/admin/xhs/assign",
        headers=make_auth_headers(1),
        json={"user_id": 2, "environment_id": 102},
    )
    assert allowed.status_code == 200

    rejected = await client.post(
        "/api/v1/admin/xhs/assign",
        headers=make_auth_headers(1),
        json={"user_id": 3, "environment_id": 102},
    )
    assert rejected.status_code == 400
    assert "品牌部门" in rejected.json()["detail"]


@pytest.mark.asyncio
async def test_brand_lead_sees_brand_department_even_before_assignment(client):
    await _seed_department_users_and_environments()

    response = await client.get("/api/v1/xhs/environments", headers=make_auth_headers(4))
    assert response.status_code == 200
    data = response.json()["data"]
    assert [(row["id"], row["department"]) for row in data] == [(102, "brand")]
