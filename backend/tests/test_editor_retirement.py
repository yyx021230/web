"""Retired editor routes stay unavailable without removing gallery data."""

import pytest

from app.main import app
from app.models.material import Material
from app.models.project import Project
from app.models.template import Template
from app.models.user import User
from tests.conftest import make_auth_headers, session_factory


@pytest.mark.asyncio
async def test_retired_routes_are_not_registered(client):
    paths = {route.path for route in app.routes if hasattr(route, "path")}
    assert not any(
        path.startswith(("/api/v1/projects", "/api/v1/templates", "/api/v1/admin/resources/projects"))
        for path in paths
    )
    assert "/api/v1/materials/design" not in paths
    for path in ("/api/v1/templates", "/api/v1/projects", "/api/v1/admin/resources/projects"):
        assert (await client.get(path)).status_code == 404
        assert (await client.post(path, json={})).status_code == 404
    assert (await client.post("/api/v1/materials/design", json={})).status_code == 405
    assert {"/api/v1/materials/template", "/api/v1/materials/draft-ai"} <= paths


@pytest.mark.asyncio
async def test_legacy_assets_remain_private_and_previewable(client):
    async with session_factory() as db:
        db.add_all([
            User(id=1, username="owner", email="owner@test.com", hashed_password="x"),
            User(id=2, username="other", email="other@test.com", hashed_password="x"),
            Template(id=10, name="legacy", fabric_json="{}", created_by=1),
            Project(id=11, name="legacy", user_id=1, fabric_json="{}"),
            Material(id=12, name="legacy", type="design", category="editor-design",
                     url="/uploads/legacy.png", created_by=1, design_json={"objects": []}),
        ])
        await db.commit()
    headers = make_auth_headers(1)
    detail = await client.get("/api/v1/materials/12", headers=headers)
    assert detail.status_code == 200
    assert detail.json()["data"]["url"] == "/uploads/legacy.png"
    assert "design_json" not in detail.json()["data"]
    assert (await client.get("/api/v1/materials/12", headers=make_auth_headers(2))).status_code == 404
    updated = await client.put(
        "/api/v1/materials/12", headers=headers,
        json={"name": "renamed", "tags": ["archived"], "design_json": {"objects": ["overwrite"]}},
    )
    assert updated.status_code == 200
    async with session_factory() as db:
        assert (await db.get(Material, 12)).design_json == {"objects": []}
        assert await db.get(Template, 10) is not None
        assert await db.get(Project, 11) is not None
