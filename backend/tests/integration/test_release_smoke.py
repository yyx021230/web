from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.session import get_db
from app.main import app
from app.models.user import User
from app.scripts import seed_data
from app.services.job_service import JobService


BACKEND_DIR = Path(__file__).resolve().parents[2]


def _upgrade_fresh_database(path: Path) -> None:
    env = os.environ.copy()
    env["DATABASE_URL"] = f"sqlite+aiosqlite:///{path.as_posix()}"
    subprocess.run(
        [sys.executable, "-m", "alembic", "-c", "alembic.ini", "upgrade", "head"],
        cwd=BACKEND_DIR,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )


@pytest.mark.asyncio
async def test_fresh_migrated_release_cross_module_smoke(
    monkeypatch,
    tmp_path,
):
    database_path = tmp_path / "release-smoke.db"
    _upgrade_fresh_database(database_path)
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{database_path.as_posix()}",
    )
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    monkeypatch.setenv("SEED_ADMIN_USERNAME", "release-admin")
    monkeypatch.setenv("SEED_ADMIN_EMAIL", "release-admin@example.com")
    monkeypatch.setenv("SEED_ADMIN_PASSWORD", "release-admin-password")
    monkeypatch.setattr(seed_data, "get_local_session", lambda: session_factory)
    monkeypatch.setattr(seed_data.sys, "argv", ["seed_data"])
    await seed_data.seed()

    async with session_factory() as db:
        admin = (
            await db.execute(select(User).where(User.username == "release-admin"))
        ).scalar_one()
        job, created = await JobService(db).create_job(
            job_type="release_smoke",
            requested_by_user_id=admin.id,
            idempotency_key="fresh-release-smoke",
            payload={
                "api_key": "must-not-leak",
                "prompt": "must-not-leak-either",
                "safe_label": "release evidence",
            },
            progress_total=1,
        )
        await JobService(db).add_item(
            job,
            item_key="smoke-item",
            display_name="迁移库冒烟项",
            payload={"authorization": "must-not-leak"},
        )
        await db.commit()
        job_id = job.id

    async def migrated_get_db():
        async with session_factory() as session:
            yield session

    previous_override = app.dependency_overrides.get(get_db)
    app.dependency_overrides[get_db] = migrated_get_db
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://release") as client:
            login = await client.post(
                "/api/v1/auth/login",
                json={
                    "username": "release-admin",
                    "password": "release-admin-password",
                },
            )
            assert login.status_code == 200
            headers = {
                "Authorization": f"Bearer {login.json()['access_token']}"
            }

            me = await client.get("/api/v1/auth/me", headers=headers)
            assert me.status_code == 200
            assert me.json()["roles"] == ["admin"]

            templates = await client.get("/api/v1/templates?limit=100")
            materials = await client.get(
                "/api/v1/materials?limit=100",
                headers=headers,
            )
            assert templates.status_code == 200
            assert templates.json()["data"]["total"] == 5
            assert materials.status_code == 200
            assert materials.json()["data"]["total"] == 46

            create_project = await client.post(
                "/api/v1/projects",
                headers=headers,
                json={"name": "发布冒烟项目"},
            )
            assert create_project.status_code == 200
            project_id = create_project.json()["data"]["id"]
            project = await client.get(
                f"/api/v1/projects/{project_id}",
                headers=headers,
            )
            assert project.status_code == 200
            assert project.json()["data"]["name"] == "发布冒烟项目"

            surface_paths = [
                "/api/v1/ai-image/active",
                "/api/v1/ai-image/runtime-config",
                "/api/v1/ai-image/history",
                "/api/v1/ai-image/models",
                "/api/v1/workflows",
                "/api/v1/car-models/brands",
                "/api/v1/copywritings",
                "/api/v1/copywritings/categories",
                "/api/v1/prompts",
                "/api/v1/prompts/categories",
                "/api/v1/xhs/environments",
                "/api/v1/xhs/posts",
                "/api/v1/xhs/account-notes",
                "/api/v1/admin/stats/overview",
                "/api/v1/admin/users",
                "/api/v1/admin/workflows",
                "/api/v1/admin/ai-image/providers",
                "/api/v1/admin/xhs/assignments",
                "/api/v1/admin/xhs/ad-account-assignments",
                "/api/v1/admin/reliability/scheduler-leader",
            ]
            failures: dict[str, tuple[int, str]] = {}
            for path in surface_paths:
                response = await client.get(path, headers=headers)
                if response.status_code != 200:
                    failures[path] = (response.status_code, response.text[:500])
            assert failures == {}

            job_list = await client.get(
                "/api/v1/admin/reliability/jobs?job_type=release_smoke",
                headers=headers,
            )
            job_detail = await client.get(
                f"/api/v1/admin/reliability/jobs/{job_id}",
                headers=headers,
            )
            assert job_list.status_code == 200
            assert job_list.json()["data"]["total"] == 1
            assert job_detail.status_code == 200
            assert job_detail.json()["data"]["items"][0]["display_name"] == (
                "迁移库冒烟项"
            )
            assert "must-not-leak" not in job_detail.text

            register = await client.post(
                "/api/v1/auth/register",
                headers=headers,
                json={
                    "username": "release-viewer",
                    "email": "release-viewer@example.com",
                    "password": "release-viewer-password",
                },
            )
            assert register.status_code == 200
            viewer_headers = {
                "Authorization": f"Bearer {register.json()['access_token']}"
            }
            denied = await client.get(
                "/api/v1/admin/reliability/jobs",
                headers=viewer_headers,
            )
            assert denied.status_code == 403
    finally:
        if previous_override is None:
            app.dependency_overrides.pop(get_db, None)
        else:
            app.dependency_overrides[get_db] = previous_override
        await engine.dispose()
