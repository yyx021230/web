from __future__ import annotations

import pytest

from app.config import Settings
from app.core.remote_download import download_allowed_remote_image
from app.core.security import create_access_token
from app.db.session import async_session
from app.models.ai_task import AITask
from app.models.dify_run_log import DifyRunLog
from app.models.user import User


def auth_headers(user_id: int) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(subject=str(user_id))}"}


async def create_user(user_id: int, username: str, *, role: str = "viewer") -> None:
    async with async_session() as db:
        db.add(
            User(
                id=user_id,
                username=username,
                email=f"{username}@example.com",
                hashed_password="x",
                role=role,
                is_active=True,
            )
        )
        await db.commit()


def test_production_config_requires_explicit_secrets():
    settings = Settings(_env_file=None, app_env="production", jwt_secret_key="", xhs_worker_internal_token="")
    missing = settings.validate_critical()
    assert "JWT_SECRET_KEY" in missing
    assert "DATABASE_URL" in missing
    assert "XHS_WORKER_INTERNAL_TOKEN" in missing


def test_production_config_rejects_default_database_password():
    settings = Settings(
        _env_file=None,
        app_env="production",
        database_url=f"postgresql+asyncpg://postgres:{'postgres'}@db:5432/app",
        jwt_secret_key="strong-test-secret",
        xhs_worker_internal_token="internal-test-token",
    )
    assert "DATABASE_URL_NON_DEFAULT_PASSWORD" in settings.validate_critical()


@pytest.mark.asyncio
async def test_remote_image_download_rejects_private_hosts(client):
    with pytest.raises(Exception) as exc_info:
        await download_allowed_remote_image("http://127.0.0.1/internal.png")
    assert "远程图片来源不被允许" in str(exc_info.value)


@pytest.mark.asyncio
async def test_material_upload_rejects_svg(client):
    await create_user(1, "svg_user")
    resp = await client.post(
        "/api/v1/materials/upload",
        headers=auth_headers(1),
        files={"file": ("bad.svg", b"<svg><script>alert(1)</script></svg>", "image/svg+xml")},
    )
    assert resp.status_code == 400
    assert "SVG" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_ai_task_status_requires_owner(client):
    await create_user(1, "task_owner")
    await create_user(2, "task_other")
    async with async_session() as db:
        db.add(
            AITask(
                id=101,
                user_id=1,
                model_name="gptimage2",
                prompt="private prompt",
                status="completed",
                result_urls=["/uploads/ai-images/private.png"],
            )
        )
        await db.commit()

    unauth = await client.get("/api/v1/ai-image/tasks/101")
    assert unauth.status_code in (401, 403)

    forbidden = await client.get("/api/v1/ai-image/tasks/101", headers=auth_headers(2))
    assert forbidden.status_code == 404

    allowed = await client.get("/api/v1/ai-image/tasks/101", headers=auth_headers(1))
    assert allowed.status_code == 200
    assert allowed.json()["data"]["task_id"] == "101"


@pytest.mark.asyncio
async def test_ai_queue_status_requires_admin(client):
    await create_user(1, "queue_viewer")
    await create_user(2, "queue_admin", role="admin")

    unauth = await client.get("/api/v1/ai-image/queue/status")
    assert unauth.status_code in (401, 403)

    viewer = await client.get("/api/v1/ai-image/queue/status", headers=auth_headers(1))
    assert viewer.status_code == 403

    admin = await client.get("/api/v1/ai-image/queue/status", headers=auth_headers(2))
    assert admin.status_code == 200


@pytest.mark.asyncio
async def test_workflow_logs_require_auth_and_filter_by_user(client):
    await create_user(1, "log_owner")
    await create_user(2, "log_other")
    async with async_session() as db:
        db.add_all(
            [
                DifyRunLog(
                    id=201,
                    workflow_id=10,
                    user_id=1,
                    status="succeeded",
                    inputs={"secret": "owner-input"},
                    outputs={"result": "owner-output"},
                ),
                DifyRunLog(
                    id=202,
                    workflow_id=10,
                    user_id=2,
                    status="succeeded",
                    inputs={"secret": "other-input"},
                    outputs={"result": "other-output"},
                ),
            ]
        )
        await db.commit()

    unauth = await client.get("/api/v1/workflows/logs")
    assert unauth.status_code in (401, 403)

    owner = await client.get("/api/v1/workflows/logs", headers=auth_headers(1))
    assert owner.status_code == 200
    items = owner.json()["data"]["items"]
    assert [item["id"] for item in items] == [201]
    assert items[0]["inputs"]["secret"] == "owner-input"

    filtered = await client.get("/api/v1/workflows/10/logs", headers=auth_headers(2))
    assert filtered.status_code == 200
    assert [item["id"] for item in filtered.json()["data"]["items"]] == [202]
