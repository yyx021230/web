"""测试 API 路由"""

import pytest
import pytest_asyncio
from httpx import AsyncClient


async def register_and_login(client, username="testuser", email="test@example.com", password="password123"):
    """注册并返回 auth headers"""
    resp = await client.post("/api/v1/auth/register", json={
        "username": username,
        "email": email,
        "password": password,
    })
    if resp.status_code == 200:
        token = resp.json()["access_token"]
    else:
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


# --- 认证 ---

@pytest.mark.asyncio
async def test_register(client):
    resp = await client.post("/api/v1/auth/register", json={
        "username": "testuser_api",
        "email": "test@example.com",
        "password": "password123",
    })
    assert resp.status_code in (200, 400)
    if resp.status_code == 200:
        data = resp.json()
        assert "access_token" in data
        assert data["token_type"] == "bearer"


@pytest.mark.asyncio
async def test_login_success(client):
    await client.post("/api/v1/auth/register", json={
        "username": "login_test_user",
        "email": "login@example.com",
        "password": "password123",
    })
    resp = await client.post("/api/v1/auth/login", json={
        "username": "login_test_user",
        "password": "password123",
    })
    assert resp.status_code == 200
    data = resp.json()
    assert "access_token" in data


@pytest.mark.asyncio
async def test_login_wrong_password(client):
    await client.post("/api/v1/auth/register", json={
        "username": "wrong_pw_user",
        "email": "wrongpw@example.com",
        "password": "password123",
    })
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
    resp = await client.get("/api/v1/materials")
    assert resp.status_code == 200
    data = resp.json()
    assert "items" in data["data"]


# --- Dify 工作流 ---

@pytest.mark.asyncio
async def test_list_workflows(client):
    resp = await client.get("/api/v1/workflows")
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
    await client.post("/api/v1/auth/register", json={
        "username": "dup_user",
        "email": "dup@example.com",
        "password": "password123",
    })
    resp = await client.post("/api/v1/auth/register", json={
        "username": "dup_user",
        "email": "dup2@example.com",
        "password": "password123",
    })
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
    """Dify 实例/工作流的创建和删除需要登录"""
    # 创建实例
    resp = await client.post("/api/v1/workflows/instances", json={
        "name": "test",
        "base_url": "http://test.com",
        "api_key": "key-1234567890",
    })
    assert resp.status_code in (401, 403)

    # 删除实例
    resp = await client.delete("/api/v1/workflows/instances/1")
    assert resp.status_code in (401, 403)

    # 创建工作流
    resp = await client.post("/api/v1/workflows", json={
        "instance_id": 1,
        "app_id": "app1",
        "app_name": "test",
        "app_type": "workflow",
    })
    assert resp.status_code in (401, 403)
