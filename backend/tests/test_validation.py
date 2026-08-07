"""测试安全校验"""

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import select

from app.core.security import create_access_token
from app.core.security import hash_password
from app.db.session import async_session
from app.models.user import User


@pytest_asyncio.fixture
async def auth_client(client: AsyncClient):
    """Reuse the isolated application client without replacing global dependencies."""
    yield client


def make_headers(user_id: int = 1):
    token = create_access_token(subject=str(user_id))
    return {"Authorization": f"Bearer {token}"}


# --- 配置校验 ---

def test_config_validate_critical():
    """测试当 jwt_secret_key 为默认值时能检测到"""
    from app.config import Settings
    # 明确传入默认值来测试校验逻辑
    s = Settings(_env_file=None, jwt_secret_key="change-me-in-production")
    critical = s.validate_critical()
    assert "JWT_SECRET_KEY" in critical


def test_config_validate_optional():
    from app.config import Settings
    s = Settings(_env_file=None)
    optional = s.validate_optional()
    assert "DIFY_DEFAULT_BASE_URL" in optional
    assert "SEEDREAM_API_KEY" in optional


def test_production_requires_explicit_confirmation():
    from app.config import Settings

    settings = Settings(
        _env_file=None,
        app_env="production",
        deployment_environment="production",
        production_confirmation="",
        jwt_secret_key="production-test-secret",
        database_url="postgresql+asyncpg://ai_user:strong-password@postgres/app",
        xhs_worker_internal_token="worker-secret",
        storage_type="local",
    )

    assert "PRODUCTION_CONFIRMATION" in settings.validate_critical()


def test_test_environment_rejects_postgres():
    from app.config import Settings

    settings = Settings(
        _env_file=None,
        app_env="test",
        deployment_environment="test",
        jwt_secret_key="test-secret",
        database_url="postgresql+asyncpg://test:test@postgres/test",
    )

    assert "TEST_DATABASE_MUST_BE_SQLITE" in settings.validate_critical()


def test_environment_names_must_match():
    from app.config import Settings

    settings = Settings(
        _env_file=None,
        app_env="development",
        deployment_environment="production",
        jwt_secret_key="test-secret",
    )

    assert "APP_ENV_MATCHES_DEPLOYMENT_ENVIRONMENT" in settings.validate_critical()


# --- 分页校验 ---

@pytest.mark.asyncio
async def test_pagination_page_zero_rejected(auth_client):
    resp = await auth_client.get("/api/v1/templates?page=0")
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_pagination_negative_page(auth_client):
    resp = await auth_client.get("/api/v1/templates?page=-1")
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_pagination_limit_too_large(auth_client):
    resp = await auth_client.get("/api/v1/templates?limit=1000000")
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_pagination_limit_zero(auth_client):
    resp = await auth_client.get("/api/v1/templates?limit=0")
    assert resp.status_code == 422


# --- 全局异常处理 ---

@pytest.mark.asyncio
async def test_validation_error_format(auth_client):
    """测试验证错误返回统一格式"""
    async with async_session() as db:
        existing = await db.execute(select(User).where(User.username == "val_user"))
        if existing.scalar_one_or_none() is None:
            db.add(User(
                username="val_user",
                email="val@test.com",
                hashed_password=hash_password("password123"),
            ))
            await db.commit()
    login_resp = await auth_client.post("/api/v1/auth/login", json={
        "username": "val_user", "password": "password123",
    })
    headers = {"Authorization": f"Bearer {login_resp.json()['access_token']}"}

    resp = await auth_client.post("/api/v1/templates", json={
        "name": "",  # 违反 min_length
        "fabric_json": "{}",
        "category": "test",
    }, headers=headers)
    assert resp.status_code == 422
    data = resp.json()
    assert data["code"] == 422
    assert data["message"] == "参数验证失败"
    assert isinstance(data["data"], list)
