from __future__ import annotations

import importlib

import pytest
from redis.asyncio import Redis

from app.config import Settings
from app.core.security import create_access_token, hash_password
from app.db import session as db_session_module
from app.models.user import User, UserRole
from tests.conftest import make_auth_headers, session_factory


main_module = importlib.import_module("app.main")


def test_complete_production_configuration_passes_critical_validation():
    settings = Settings(
        _env_file=None,
        app_env="production",
        deployment_environment="production",
        production_confirmation="ALLOW_PRODUCTION_DEPLOYMENT",
        jwt_secret_key="production-jwt-secret",
        database_url="postgresql+asyncpg://app:strong-password@db/app",
        xhs_worker_internal_token="worker-secret",
        storage_type="s3",
        s3_access_key="access-key",
        s3_secret_key="secret-key",
    )

    assert settings.validate_critical() == []


def test_production_s3_configuration_reports_each_missing_secret():
    settings = Settings(
        _env_file=None,
        app_env="production",
        deployment_environment="production",
        production_confirmation="ALLOW_PRODUCTION_DEPLOYMENT",
        jwt_secret_key="production-jwt-secret",
        database_url="postgresql+asyncpg://app:strong-password@db/app",
        xhs_worker_internal_token="worker-secret",
        storage_type="s3",
        s3_access_key="",
        s3_secret_key="",
    )

    assert settings.validate_critical() == ["S3_ACCESS_KEY", "S3_SECRET_KEY"]


@pytest.mark.asyncio
async def test_login_accepts_case_insensitive_email_and_rejects_disabled_user(client):
    async with session_factory() as db:
        db.add_all(
            [
                User(
                    username="email-login",
                    email="mixed.case@example.com",
                    hashed_password=hash_password("test-password"),
                ),
                User(
                    username="disabled-user",
                    email="disabled@example.com",
                    hashed_password=hash_password("test-password"),
                    is_active=False,
                ),
            ]
        )
        await db.commit()

    email_login = await client.post(
        "/api/v1/auth/login",
        json={
            "username": "MIXED.CASE@EXAMPLE.COM",
            "password": "test-password",
        },
    )
    disabled_login = await client.post(
        "/api/v1/auth/login",
        json={"username": "disabled-user", "password": "test-password"},
    )

    assert email_login.status_code == 200
    assert disabled_login.status_code == 403
    assert disabled_login.json()["detail"] == "账户已禁用"


@pytest.mark.asyncio
async def test_current_user_rejects_invalid_missing_and_inactive_tokens(client):
    invalid = await client.get(
        "/api/v1/auth/me",
        headers={"Authorization": "Bearer not-a-jwt"},
    )
    missing = await client.get(
        "/api/v1/auth/me",
        headers={
            "Authorization": (
                f"Bearer {create_access_token(subject='999999')}"
            )
        },
    )

    async with session_factory() as db:
        inactive = User(
            username="inactive-token-user",
            email="inactive-token@example.com",
            hashed_password="x",
            is_active=False,
        )
        db.add(inactive)
        await db.commit()
        await db.refresh(inactive)
        inactive_headers = make_auth_headers(inactive.id)
    inactive_response = await client.get(
        "/api/v1/auth/me",
        headers=inactive_headers,
    )

    assert invalid.status_code == 401
    assert missing.status_code == 401
    assert inactive_response.status_code == 403


@pytest.mark.asyncio
async def test_role_assignments_override_legacy_primary_role(client):
    async with session_factory() as db:
        assigned_admin = User(
            username="assigned-admin",
            email="assigned-admin@example.com",
            hashed_password="x",
            role="viewer",
        )
        assigned_viewer = User(
            username="assigned-viewer",
            email="assigned-viewer@example.com",
            hashed_password="x",
            role="admin",
        )
        db.add_all([assigned_admin, assigned_viewer])
        await db.flush()
        db.add_all(
            [
                UserRole(user_id=assigned_admin.id, role="admin"),
                UserRole(user_id=assigned_viewer.id, role="viewer"),
            ]
        )
        await db.commit()
        admin_headers = make_auth_headers(assigned_admin.id)
        viewer_headers = make_auth_headers(assigned_viewer.id)

    allowed = await client.get(
        "/api/v1/admin/reliability/jobs",
        headers=admin_headers,
    )
    denied = await client.get(
        "/api/v1/admin/reliability/jobs",
        headers=viewer_headers,
    )

    assert allowed.status_code == 200
    assert denied.status_code == 403


class _HealthySession:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None

    async def execute(self, _statement):
        return None


class _BrokenSession(_HealthySession):
    async def execute(self, _statement):
        raise RuntimeError("database unavailable")


class _FakeRedis:
    def __init__(self, *, healthy: bool):
        self.healthy = healthy
        self.closed = False

    async def ping(self):
        if not self.healthy:
            raise ConnectionError("redis unavailable")
        return True

    async def aclose(self):
        self.closed = True


@pytest.mark.asyncio
async def test_readiness_requires_database_redis_and_storage(
    monkeypatch,
    tmp_path,
):
    redis_client = _FakeRedis(healthy=True)
    monkeypatch.setattr(db_session_module, "async_session", _HealthySession)
    monkeypatch.setattr(
        Redis,
        "from_url",
        lambda *_args, **_kwargs: redis_client,
    )
    monkeypatch.setattr(main_module, "uploads_path", tmp_path / "uploads")

    payload, status_code = await main_module._build_readiness_payload()

    assert status_code == 200
    assert payload["status"] == "ready"
    assert payload["checks"] == {
        "database": "ok",
        "redis": "ok",
        "storage": "ok (local)",
    }
    assert redis_client.closed is True


@pytest.mark.asyncio
async def test_readiness_reports_dependency_failures_without_crashing(
    monkeypatch,
    tmp_path,
):
    redis_client = _FakeRedis(healthy=False)
    monkeypatch.setattr(db_session_module, "async_session", _BrokenSession)
    monkeypatch.setattr(
        Redis,
        "from_url",
        lambda *_args, **_kwargs: redis_client,
    )
    monkeypatch.setattr(main_module, "uploads_path", tmp_path / "uploads")

    payload, status_code = await main_module._build_readiness_payload()

    assert status_code == 503
    assert payload["status"] == "degraded"
    assert payload["checks"]["database"] == "error: database unavailable"
    assert payload["checks"]["redis"] == "error: ConnectionError"
    assert payload["checks"]["storage"] == "ok (local)"
    assert redis_client.closed is True
