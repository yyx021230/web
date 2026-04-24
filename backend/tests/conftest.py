"""测试配置和 fixture - 使用 SQLite 替代 PostgreSQL"""

import os

# 在导入任何 app 模块前设置环境变量
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///./test_ai_creative.db"
os.environ["STORAGE_TYPE"] = "local"
os.environ["STORAGE_PATH"] = "./test_uploads"
os.environ["JWT_SECRET_KEY"] = "test-secret-key-for-testing"

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker

from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.core.security import create_access_token

# 测试专用 SQLite 引擎
test_engine = create_async_engine(
    "sqlite+aiosqlite:///./test_ai_creative.db",
    echo=False,
)
test_session_factory = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)


async def override_get_db():
    async with test_session_factory() as session:
        yield session


app.dependency_overrides[get_db] = override_get_db


@pytest_asyncio.fixture
async def client():
    # 创建测试表
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    # 清理
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


def make_auth_headers(user_id: int = 1) -> dict:
    token = create_access_token(subject=str(user_id))
    return {"Authorization": f"Bearer {token}"}
