"""Cross-module authorization contracts for the administration surface."""

import pytest
import pytest_asyncio

from app.core.security import hash_password
from app.db.session import async_session as session_factory
from app.models.user import User
from tests.conftest import make_auth_headers


ADMIN_GET_ENDPOINTS = (
    "/api/v1/admin/stats/overview",
    "/api/v1/admin/users",
    "/api/v1/admin/materials",
    "/api/v1/admin/workflows",
    "/api/v1/admin/prompts/overview",
    "/api/v1/admin/car-models/all",
    "/api/v1/admin/xhs/assignments",
    "/api/v1/admin/ai-image/providers",
    "/api/v1/admin/copy-review/tasks",
    "/api/v1/admin/reliability/jobs",
)


@pytest_asyncio.fixture
async def viewer_headers(client):
    async with session_factory() as db:
        viewer = User(
            username="authorization-viewer",
            email="authorization-viewer@example.com",
            hashed_password=hash_password("test-password"),
            role="viewer",
        )
        db.add(viewer)
        await db.commit()
        await db.refresh(viewer)
        return make_auth_headers(viewer.id)


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ADMIN_GET_ENDPOINTS)
async def test_admin_endpoints_reject_anonymous_users(client, path):
    response = await client.get(path)

    assert response.status_code == 401


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ADMIN_GET_ENDPOINTS)
async def test_admin_endpoints_reject_viewers(client, viewer_headers, path):
    response = await client.get(path, headers=viewer_headers)

    assert response.status_code == 403
