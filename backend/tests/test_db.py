"""测试数据库连接和模型"""

import asyncio
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from app.db.base import Base
from app.models import User, Template, Material, Project, AITask, DifyWorkflowConfig, DifyRunLog


# 使用 SQLite 异步引擎进行测试
SQLITE_URL = "sqlite+aiosqlite:///./test_ai_creative.db"


@pytest_asyncio.fixture
async def test_engine():
    engine = create_async_engine(SQLITE_URL, echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    # 清理
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest_asyncio.fixture
async def test_db(test_engine):
    async_session = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)
    async with async_session() as session:
        yield session


# --- 模型创建测试 ---

@pytest.mark.asyncio
async def test_create_user(test_db: AsyncSession):
    user = User(
        username="testuser",
        email="test@test.com",
        hashed_password="hashed",
    )
    test_db.add(user)
    await test_db.commit()
    await test_db.refresh(user)
    assert user.id is not None
    assert user.username == "testuser"
    assert user.is_active is True


@pytest.mark.asyncio
async def test_create_template(test_db: AsyncSession):
    tpl = Template(
        name="测试模板",
        fabric_json='{"objects":[]}',
        category="poster",
        tags=["tag1"],
    )
    test_db.add(tpl)
    await test_db.commit()
    await test_db.refresh(tpl)
    assert tpl.id is not None
    assert tpl.category == "poster"


@pytest.mark.asyncio
async def test_create_project(test_db: AsyncSession):
    project = Project(
        user_id=1,
        name="测试项目",
        status="draft",
    )
    test_db.add(project)
    await test_db.commit()
    await test_db.refresh(project)
    assert project.id is not None
    assert project.status == "draft"


@pytest.mark.asyncio
async def test_create_material(test_db: AsyncSession):
    material = Material(
        name="素材图片",
        type="image",
        url="/uploads/test.png",
        width=800,
        height=600,
    )
    test_db.add(material)
    await test_db.commit()
    await test_db.refresh(material)
    assert material.id is not None
    assert material.width == 800


@pytest.mark.asyncio
async def test_create_ai_task(test_db: AsyncSession):
    task = AITask(
        user_id=1,
        model_name="seedream",
        prompt="a beautiful sunset",
        status="pending",
    )
    test_db.add(task)
    await test_db.commit()
    await test_db.refresh(task)
    assert task.id is not None
    assert task.status == "pending"


@pytest.mark.asyncio
async def test_create_dify_workflow_config(test_db: AsyncSession):
    workflow = DifyWorkflowConfig(
        app_name="测试 Dify",
        app_type="workflow",
        base_url="http://localhost:8080",
        api_key="test-key",
    )
    test_db.add(workflow)
    await test_db.commit()
    await test_db.refresh(workflow)
    assert workflow.id is not None
    assert workflow.is_enabled is True


@pytest.mark.asyncio
async def test_dify_run_log(test_db: AsyncSession):
    log = DifyRunLog(
        workflow_id=1,
        user_id=1,
        inputs={"prompt": "hello"},
        outputs={"response": "world"},
        status="succeeded",
    )
    test_db.add(log)
    await test_db.commit()
    await test_db.refresh(log)
    assert log.id is not None
    assert log.status == "succeeded"
