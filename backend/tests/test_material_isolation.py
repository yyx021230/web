import pytest
from app.core.security import create_access_token, hash_password
from app.models.material import Material
from app.models.user import User
from tests.conftest import test_session_factory


async def create_user(username: str, email: str) -> User:
    async with test_session_factory() as session:
        user = User(
            username=username,
            email=email,
            hashed_password=hash_password("password123"),
            is_active=True,
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)
        return user


async def create_material(user_id: int, name: str) -> Material:
    async with test_session_factory() as session:
        material = Material(
            name=name,
            type="design",
            category="editor-design",
            design_json={"objects": []},
            created_by=user_id,
        )
        session.add(material)
        await session.commit()
        await session.refresh(material)
        return material


def auth_headers(user_id: int) -> dict[str, str]:
    token = create_access_token(subject=str(user_id))
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
async def test_material_list_is_scoped_to_current_user(client):
    user_a = await create_user("material_scope_a", "material_scope_a@example.com")
    user_b = await create_user("material_scope_b", "material_scope_b@example.com")
    await create_material(user_a.id, "A 的草稿")
    await create_material(user_b.id, "B 的草稿")

    resp_a = await client.get("/api/v1/materials", headers=auth_headers(user_a.id))
    assert resp_a.status_code == 200
    items_a = resp_a.json()["data"]["items"]
    assert len(items_a) == 1
    assert items_a[0]["name"] == "A 的草稿"

    resp_b = await client.get("/api/v1/materials", headers=auth_headers(user_b.id))
    assert resp_b.status_code == 200
    items_b = resp_b.json()["data"]["items"]
    assert len(items_b) == 1
    assert items_b[0]["name"] == "B 的草稿"


@pytest.mark.asyncio
async def test_material_detail_is_scoped_to_current_user(client):
    user_a = await create_user("material_detail_a", "material_detail_a@example.com")
    user_b = await create_user("material_detail_b", "material_detail_b@example.com")
    material = await create_material(user_a.id, "A 的私有设计")

    own_resp = await client.get(f"/api/v1/materials/{material.id}", headers=auth_headers(user_a.id))
    assert own_resp.status_code == 200
    assert own_resp.json()["data"]["name"] == "A 的私有设计"

    other_resp = await client.get(f"/api/v1/materials/{material.id}", headers=auth_headers(user_b.id))
    assert other_resp.status_code == 404

