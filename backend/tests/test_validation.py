"""测试安全校验"""

import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from app.core.security import create_access_token


@pytest_asyncio.fixture
async def auth_client():
    """已认证客户端"""
    from app.db.base import Base
    from app.db.session import get_db
    from app.main import app
    from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
    import os
    os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///./test_validation.db"
    os.environ["STORAGE_TYPE"] = "local"
    os.environ["STORAGE_PATH"] = "./test_uploads"
    os.environ["JWT_SECRET_KEY"] = "test"

    from app.config import get_settings
    get_settings.cache_clear()

    engine = create_async_engine("sqlite+aiosqlite:///./test_validation.db")
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async def override_get_db():
        async with factory() as s:
            yield s

    app.dependency_overrides[get_db] = override_get_db

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


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
    # 先注册用户
    await auth_client.post("/api/v1/auth/register", json={
        "username": "val_user", "email": "val@test.com", "password": "password123",
    })
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
