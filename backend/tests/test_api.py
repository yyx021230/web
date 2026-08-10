"""测试 API 路由"""

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import select

from app.config import settings
from app.core.security import hash_password
from app.models.user import User
from tests.conftest import make_auth_headers, session_factory


async def create_test_user(
    username: str,
    email: str,
    password: str = "password123",
    role: str = "viewer",
) -> User:
    async with session_factory() as db:
        existing = await db.execute(select(User).where(User.username == username))
        user = existing.scalar_one_or_none()
        if user is not None:
            return user
        user = User(
            username=username,
            email=email,
            hashed_password=hash_password(password),
            role=role,
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
        return user


async def register_and_login(client, username="testuser", email="test@example.com", password="password123"):
    """Create a test user directly and return API auth headers."""
    await create_test_user(username, email, password)
    login_resp = await client.post("/api/v1/auth/login", json={
        "username": username,
        "password": password,
    })
    token = login_resp.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


# --- 健康检查 ---

@pytest.mark.asyncio
async def test_health_check(client):
    resp = await client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["version"] == settings.app_version
    assert data["environment"] == "test"


@pytest.mark.asyncio
async def test_version_and_request_trace_headers(client):
    resp = await client.get("/version", headers={"X-Request-ID": "release-smoke-001"})
    assert resp.status_code == 200
    assert resp.headers["X-Request-ID"] == "release-smoke-001"
    assert float(resp.headers["X-Process-Time"]) >= 0
    assert resp.json() == {
        "version": settings.app_version,
        "commit": "unknown",
        "buildTime": "unknown",
        "environment": "test",
    }


# --- 认证 ---

@pytest.mark.asyncio
async def test_register(client):
    admin = await create_test_user("register_admin", "register-admin@example.com", role="admin")
    resp = await client.post("/api/v1/auth/register", json={
        "username": "testuser_api",
        "email": "test@example.com",
        "password": "password123",
    }, headers=make_auth_headers(admin.id))
    assert resp.status_code == 200
    data = resp.json()
    assert "access_token" in data
    assert data["token_type"] == "bearer"


@pytest.mark.asyncio
async def test_login_success(client):
    await create_test_user("login_test_user", "login@example.com")
    resp = await client.post("/api/v1/auth/login", json={
        "username": "login_test_user",
        "password": "password123",
    })
    assert resp.status_code == 200
    data = resp.json()
    assert "access_token" in data


@pytest.mark.asyncio
async def test_login_wrong_password(client):
    await create_test_user("wrong_pw_user", "wrongpw@example.com")
    resp = await client.post("/api/v1/auth/login", json={
        "username": "wrong_pw_user",
        "password": "wrongpassword",
    })
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_get_me_without_auth(client):
    resp = await client.get("/api/v1/auth/me")
    # HTTPBearer 未提供 token 返回 403，提供无效 token 返回 401
    assert resp.status_code in (401, 403)


@pytest.mark.asyncio
async def test_get_me_with_auth(client):
    headers = await register_and_login(client, "me_test_user", "me@example.com")
    resp = await client.get("/api/v1/auth/me", headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    # /me 直接返回 UserResponse（不包在 ApiResponse.data 里）
    assert data["username"] == "me_test_user"
    assert data["email"] == "me@example.com"


# --- 模板 ---

@pytest.mark.asyncio
async def test_get_templates(client):
    resp = await client.get("/api/v1/templates")
    assert resp.status_code == 200
    data = resp.json()
    assert data["code"] == 0
    assert "items" in data["data"]


@pytest.mark.asyncio
async def test_get_template_not_found(client):
    resp = await client.get("/api/v1/templates/99999")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_create_template(client):
    headers = await register_and_login(client, "tpl_user", "tpl@example.com")
    resp = await client.post("/api/v1/templates", json={
        "name": "测试模板",
        "description": "测试描述",
        "fabric_json": '{"objects":[]}',
        "category": "poster",
        "tags": ["tag1", "tag2"],
    }, headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["data"]["name"] == "测试模板"
    assert data["data"]["category"] == "poster"
    template_id = data["data"]["id"]

    resp = await client.get(f"/api/v1/templates/{template_id}")
    assert resp.status_code == 200
    assert resp.json()["data"]["name"] == "测试模板"


@pytest.mark.asyncio
async def test_delete_template(client):
    headers = await register_and_login(client, "del_tpl_user", "del_tpl@example.com")
    resp = await client.post("/api/v1/templates", json={
        "name": "删除测试模板",
        "description": "",
        "fabric_json": '{"objects":[]}',
        "category": "test",
    }, headers=headers)
    template_id = resp.json()["data"]["id"]

    resp = await client.delete(f"/api/v1/templates/{template_id}", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["message"] == "已删除"

    resp = await client.get(f"/api/v1/templates/{template_id}")
    assert resp.status_code == 404


# --- 项目 ---

@pytest.mark.asyncio
async def test_get_projects(client):
    headers = await register_and_login(client, "proj_user", "proj@example.com")
    resp = await client.get("/api/v1/projects", headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert "items" in data["data"]


@pytest.mark.asyncio
async def test_create_project(client):
    headers = await register_and_login(client, "proj2_user", "proj2@example.com")
    resp = await client.post("/api/v1/projects", json={
        "name": "测试项目",
    }, headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["data"]["name"] == "测试项目"
    project_id = data["data"]["id"]

    resp = await client.get(f"/api/v1/projects/{project_id}", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["data"]["name"] == "测试项目"


@pytest.mark.asyncio
async def test_update_project(client):
    headers = await register_and_login(client, "proj3_user", "proj3@example.com")
    resp = await client.post("/api/v1/projects", json={"name": "更新前"}, headers=headers)
    project_id = resp.json()["data"]["id"]

    resp = await client.put(f"/api/v1/projects/{project_id}", json={
        "name": "更新后",
        "status": "published",
    }, headers=headers)
    assert resp.status_code == 200
    assert resp.json()["data"]["name"] == "更新后"
    assert resp.json()["data"]["status"] == "published"


@pytest.mark.asyncio
async def test_delete_project(client):
    headers = await register_and_login(client, "proj4_user", "proj4@example.com")
    resp = await client.post("/api/v1/projects", json={"name": "删除测试项目"}, headers=headers)
    project_id = resp.json()["data"]["id"]

    resp = await client.delete(f"/api/v1/projects/{project_id}", headers=headers)
    assert resp.status_code == 200

    resp = await client.get(f"/api/v1/projects/{project_id}", headers=headers)
    assert resp.status_code == 404


# --- 素材 ---

@pytest.mark.asyncio
async def test_get_materials(client):
    headers = await register_and_login(client, "materials_user", "materials_user@example.com")
    resp = await client.get("/api/v1/materials", headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert "items" in data["data"]


@pytest.mark.asyncio
async def test_get_material_is_user_scoped(client):
    headers_a = await register_and_login(client, "material_owner", "material_owner@example.com")
    headers_b = await register_and_login(client, "material_other", "material_other@example.com")

    create_resp = await client.post("/api/v1/materials/design", json={
        "name": "用户私有草稿",
        "design_json": {"objects": []},
        "thumbnail": "data:image/png;base64,test",
        "width": 100,
        "height": 100,
    }, headers=headers_a)
    assert create_resp.status_code == 200
    material_id = create_resp.json()["data"]["id"]

    own_resp = await client.get(f"/api/v1/materials/{material_id}", headers=headers_a)
    assert own_resp.status_code == 200
    assert own_resp.json()["data"]["name"] == "用户私有草稿"

    other_resp = await client.get(f"/api/v1/materials/{material_id}", headers=headers_b)
    assert other_resp.status_code == 404


# --- Dify 工作流 ---

@pytest.mark.asyncio
async def test_list_workflows(client):
    headers = await register_and_login(client, "workflow_user", "workflow@example.com")
    resp = await client.get("/api/v1/workflows", headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["code"] == 0


# --- AI 生图 ---

@pytest.mark.asyncio
async def test_list_ai_models(client):
    resp = await client.get("/api/v1/ai-image/models")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data["data"], list)
    assert len(data["data"]) > 0
    assert data["data"][0]["id"] == "seedream"


@pytest.mark.asyncio
async def test_generate_ai_image_with_invalid_token_returns_401(client):
    resp = await client.post(
        "/api/v1/ai-image/generate",
        json={"prompt": "test", "model": "seedream"},
        headers={"Authorization": "Bearer invalid.token.value"},
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_generate_ai_image_without_token_returns_401(client):
    resp = await client.post(
        "/api/v1/ai-image/generate",
        json={"prompt": "test", "model": "seedream"},
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_cancel_local_ai_image_task_marks_cancelled(client):
    from sqlalchemy import select

    from app.db.session import async_session
    from app.models.ai_task import AITask
    from app.models.user import User
    from tests.conftest import make_auth_headers

    async with async_session() as db:
        db.add(User(id=1, username="cancel_user", email="cancel@example.com", hashed_password="x"))
        db.add(AITask(id=10, user_id=1, model_name="gptimage2", prompt="test", status="processing"))
        await db.commit()

    resp = await client.post(
        "/api/v1/ai-image/tasks/10/cancel?model=gptimage2",
        headers=make_auth_headers(1),
    )
    assert resp.status_code == 200
    assert resp.json()["message"] == "已取消"

    async with async_session() as db:
        result = await db.execute(select(AITask).where(AITask.id == 10))
        task = result.scalar_one_or_none()
        assert task is not None
        assert task.status == "cancelled"
        assert task.error == "已取消"
        assert task.finished_at is not None


# --- 未授权访问 ---

@pytest.mark.asyncio
async def test_unauthorized_project_access(client):
    resp = await client.get("/api/v1/projects")
    assert resp.status_code in (401, 403)


@pytest.mark.asyncio
async def test_unauthorized_template_create(client):
    resp = await client.post("/api/v1/templates", json={
        "name": "无权限创建",
        "fabric_json": '{"objects":[]}',
        "category": "test",
    })
    assert resp.status_code in (401, 403)


# --- 安全修复测试：所有权校验 ---

@pytest.mark.asyncio
async def test_template_ownership_update(client):
    """用户 B 不能修改用户 A 的模板"""
    # 用户 A 创建模板
    headers_a = await register_and_login(client, "owner_a", "owner_a@example.com")
    resp = await client.post("/api/v1/templates", json={
        "name": "用户A的模板",
        "fabric_json": '{"objects":[]}',
        "category": "test",
    }, headers=headers_a)
    template_id = resp.json()["data"]["id"]

    # 用户 B 尝试修改
    headers_b = await register_and_login(client, "attacker_b", "attacker_b@example.com")
    resp = await client.put(f"/api/v1/templates/{template_id}", json={
        "name": "被篡改的名字",
    }, headers=headers_b)
    # 应返回 404（服务层返回 None 时路由层抛出）
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_template_ownership_delete(client):
    """用户 B 不能删除用户 A 的模板"""
    # 用户 A 创建模板
    headers_a = await register_and_login(client, "owner_a2", "owner_a2@example.com")
    resp = await client.post("/api/v1/templates", json={
        "name": "用户A的模板2",
        "fabric_json": '{"objects":[]}',
        "category": "test",
    }, headers=headers_a)
    template_id = resp.json()["data"]["id"]

    # 用户 B 尝试删除
    headers_b = await register_and_login(client, "attacker_b2", "attacker_b2@example.com")
    resp = await client.delete(f"/api/v1/templates/{template_id}", headers=headers_b)
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_material_delete_requires_auth(client):
    """删除素材需要登录"""
    resp = await client.delete("/api/v1/materials/99999")
    assert resp.status_code in (401, 403)


@pytest.mark.asyncio
async def test_duplicate_user_returns_400(client):
    """重复注册返回 400 而非 500"""
    admin = await create_test_user("duplicate_admin", "duplicate-admin@example.com", role="admin")
    headers = make_auth_headers(admin.id)
    first = await client.post("/api/v1/auth/register", json={
        "username": "dup_user",
        "email": "dup@example.com",
        "password": "password123",
    }, headers=headers)
    assert first.status_code == 200
    resp = await client.post("/api/v1/auth/register", json={
        "username": "dup_user",
        "email": "dup2@example.com",
        "password": "password123",
    }, headers=headers)
    # 重复用户名返回 400（通过预检查或 IntegrityError handler）
    assert resp.status_code == 400
    data = resp.json()
    assert "detail" in data or data.get("code") == 400


@pytest.mark.asyncio
async def test_fabric_json_max_length(client):
    """fabric_json 超长时应被验证拒绝"""
    headers = await register_and_login(client, "limit_user", "limit@example.com")
    huge_json = "x" * 6_000_000  # 超过 5MB 限制
    resp = await client.post("/api/v1/templates", json={
        "name": "超大模板",
        "fabric_json": huge_json,
        "category": "test",
    }, headers=headers)
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_material_upload_requires_auth(client):
    """上传素材需要登录"""
    import io
    resp = await client.post(
        "/api/v1/materials/upload",
        files={"file": ("test.jpg", io.BytesIO(b"fake image data"), "image/jpeg")},
    )
    assert resp.status_code in (401, 403)


@pytest.mark.asyncio
async def test_save_ai_draft_persists_ai_meta(client):
    """保存 AI 草稿时应持久化 ai_meta（提示词/参考图/参数）"""
    headers = await register_and_login(client, "ai_draft_user", "ai_draft_user@example.com")
    resp = await client.post("/api/v1/materials/draft-ai", json={
        "name": "AI 草稿测试",
        "url": "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8Xw8AAoMBgQf3J7kAAAAASUVORK5CYII=",
        "width": 1536,
        "height": 2048,
        "ai_meta": {
            "prompt": "测试提示词",
            "ref_images": ["https://example.com/ref1.jpg"],
            "model": "GPT Image 2",
            "size": "1536×2048",
            "style": "写实",
            "quality": "high",
        },
    }, headers=headers)
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["name"] == "AI 草稿测试"
    assert data["ai_meta"]["prompt"] == "测试提示词"
    assert data["ai_meta"]["model"] == "GPT Image 2"

    list_resp = await client.get("/api/v1/materials?owner=true", headers=headers)
    assert list_resp.status_code == 200
    items = list_resp.json()["data"]["items"]
    saved = next((m for m in items if m["id"] == data["id"]), None)
    assert saved is not None
    assert saved["ai_meta"]["prompt"] == "测试提示词"


@pytest.mark.asyncio
async def test_project_create_with_fabric_json(client):
    """创建项目时可传入 fabric_json"""
    headers = await register_and_login(client, "pj_user5", "pj5@example.com")
    canvas = '{"objects":[{"type":"rect","left":10,"top":10}]}'
    resp = await client.post("/api/v1/projects", json={
        "name": "带画布的项目",
        "fabric_json": canvas,
    }, headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["data"]["name"] == "带画布的项目"
    project_id = data["data"]["id"]

    # 验证 fabric_json 已保存
    resp = await client.get(f"/api/v1/projects/{project_id}", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["data"]["fabric_json"] == canvas


@pytest.mark.asyncio
async def test_template_response_includes_fabric_json(client):
    """模板响应包含 fabric_json"""
    headers = await register_and_login(client, "fj_user", "fj@example.com")
    canvas = '{"objects":[{"type":"circle"}]}'
    resp = await client.post("/api/v1/templates", json={
        "name": "含画布模板",
        "fabric_json": canvas,
        "category": "test",
    }, headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["data"]["fabric_json"] == canvas

    # GET 也应包含 fabric_json
    tid = data["data"]["id"]
    resp = await client.get(f"/api/v1/templates/{tid}")
    assert resp.status_code == 200
    assert resp.json()["data"]["fabric_json"] == canvas


@pytest.mark.asyncio
async def test_dify_management_requires_auth(client):
    """Dify 工作流的创建和删除需要管理员登录。"""
    resp = await client.post("/api/v1/workflows", json={
        "app_name": "test",
        "app_type": "workflow",
        "base_url": "http://test.com",
        "api_key": "key-1234567890",
    })
    assert resp.status_code in (401, 403)

    resp = await client.delete("/api/v1/workflows/1")
    assert resp.status_code in (401, 403)
