"""测试配置和 fixture - 使用 SQLite 替代 PostgreSQL"""
# ruff: noqa: E402

import os
import asyncio
import tempfile
from pathlib import Path

# 在导入任何 app 模块前设置环境变量
TEST_DATABASE_PATH = Path(tempfile.gettempdir()) / f"ztqc-web-test-{os.getpid()}.db"
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{TEST_DATABASE_PATH}"
os.environ["STORAGE_TYPE"] = "local"
os.environ["STORAGE_PATH"] = "./test_uploads"
os.environ["HERMES_REFERENCE_SNAPSHOT_PATH"] = ""
os.environ["JWT_SECRET_KEY"] = "test-secret-key-for-testing"
os.environ["APP_ENV"] = "test"
os.environ["DEPLOYMENT_ENVIRONMENT"] = "test"
os.environ["REMOVE_AI_WATERMARKS_ENABLED"] = "false"

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.db.base import Base
from app.db.session import async_session as session_factory
from app.db.session import engine as test_engine
from app.db.session import get_db
from app.main import app
from app.core.security import create_access_token
from app.services.request_queue import image_generation_queue, xhs_publish_queue


@pytest_asyncio.fixture(autouse=True)
async def reset_global_request_queues():
    queues = (image_generation_queue, xhs_publish_queue)
    for queue in queues:
        queue._min_interval = 0.0
        queue._last_processed_at = 0.0
        queue._queue.clear()
    yield
    for queue in queues:
        workers = list(queue._workers)
        for worker in workers:
            worker.cancel()
        if workers:
            await asyncio.gather(*workers, return_exceptions=True)
        queue._workers.clear()
        queue._queue.clear()
        queue._processing_count = 0
        queue._stats.pending = 0
        queue._stats.processing = False

async def override_get_db():
    async with session_factory() as session:
        yield session


@pytest.fixture(scope="session", autouse=True)
def cleanup_test_database():
    yield
    for suffix in ("", "-wal", "-shm"):
        try:
            Path(f"{TEST_DATABASE_PATH}{suffix}").unlink()
        except FileNotFoundError:
            pass


@pytest_asyncio.fixture
async def client():
    # 创建测试表
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)

    previous_override = app.dependency_overrides.get(get_db)
    app.dependency_overrides[get_db] = override_get_db
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac
    finally:
        if previous_override is None:
            app.dependency_overrides.pop(get_db, None)
        else:
            app.dependency_overrides[get_db] = previous_override
        async with test_engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)


def make_auth_headers(user_id: int = 1) -> dict:
    token = create_access_token(subject=str(user_id))
    return {"Authorization": f"Bearer {token}"}
