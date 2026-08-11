"""End-to-end prompt library, moderation and bulk import contracts."""

import pytest

from app.db.session import async_session as session_factory
from app.models.user import User
from tests.conftest import make_auth_headers


async def _seed_prompt_users():
    async with session_factory() as db:
        db.add_all(
            [
                User(id=1, username="prompt-admin", email="prompt-admin@example.com", hashed_password="x", role="admin"),
                User(id=2, username="prompt-owner", email="prompt-owner@example.com", hashed_password="x", role="viewer"),
                User(id=3, username="prompt-other", email="prompt-other@example.com", hashed_password="x", role="viewer"),
            ]
        )
        await db.commit()


@pytest.mark.asyncio
async def test_prompt_community_crud_visibility_and_permissions(client):
    await _seed_prompt_users()
    owner = make_auth_headers(2)
    other = make_auth_headers(3)
    admin = make_auth_headers(1)

    empty = await client.post("/api/v1/prompts", headers=owner, json={"chinese": ""})
    assert empty.status_code == 400
    created = await client.post(
        "/api/v1/prompts",
        headers=owner,
        json={
            "name": "车型封面",
            "chinese": "生成一张车型封面",
            "english": "car cover",
            "category": "汽车",
            "param_type": "封面",
            "image_url": "/uploads/prompts/car.png",
            "ul_list": ["真实"],
            "sort_order": 2,
            "is_public": True,
        },
    )
    assert created.status_code == 200
    prompt_id = created.json()["data"]["id"]
    private = await client.post(
        "/api/v1/prompts",
        headers=owner,
        json={"chinese": "私有提示词", "category": "汽车", "is_public": False},
    )
    private_id = private.json()["data"]["id"]

    public_list = await client.get("/api/v1/prompts", headers=other, params={"keyword": "车型", "category": "汽车"})
    assert public_list.status_code == 200
    assert [item["id"] for item in public_list.json()["data"]["items"]] == [prompt_id]
    owner_list = await client.get("/api/v1/prompts", headers=owner, params={"owner": True})
    assert {item["id"] for item in owner_list.json()["data"]["items"]} == {prompt_id, private_id}
    admin_list = await client.get("/api/v1/prompts", headers=admin)
    assert admin_list.json()["data"]["total"] == 2
    categories = await client.get("/api/v1/prompts/categories", headers=other)
    assert categories.json()["data"]["categories"] == [{"name": "汽车", "count": 1}]

    forbidden = await client.put(f"/api/v1/prompts/{prompt_id}", headers=other, json={"name": "越权"})
    assert forbidden.status_code == 403
    invalid = await client.put(f"/api/v1/prompts/{prompt_id}", headers=owner, json={"chinese": ""})
    assert invalid.status_code == 400
    updated = await client.put(
        f"/api/v1/prompts/{prompt_id}",
        headers=owner,
        json={
            "category": "新能源",
            "chinese": "更新后的提示词",
            "english": "updated",
            "image_url": "",
            "param_type": "海报",
            "name": "更新名称",
            "is_public": False,
        },
    )
    assert updated.status_code == 200
    assert updated.json()["data"]["category"] == "新能源"
    # Non-admin owners cannot change visibility through update.
    assert updated.json()["data"]["is_public"] is True

    assert (await client.delete(f"/api/v1/prompts/{private_id}", headers=other)).status_code == 403
    assert (await client.delete(f"/api/v1/prompts/{private_id}", headers=owner)).status_code == 200
    assert (await client.delete("/api/v1/prompts/99999", headers=owner)).status_code == 404


@pytest.mark.asyncio
async def test_prompt_reporting_resolution_and_audit_history(client):
    await _seed_prompt_users()
    owner = make_auth_headers(2)
    reporter = make_auth_headers(3)
    admin = make_auth_headers(1)
    created = await client.post(
        "/api/v1/prompts",
        headers=owner,
        json={"name": "待举报", "chinese": "内容", "category": "举报测试", "image_url": "/x.png"},
    )
    prompt_id = created.json()["data"]["id"]

    reasons = await client.get("/api/v1/prompts/report-reasons", headers=reporter)
    assert "违规内容" in reasons.json()["data"]["reasons"]
    assert (await client.post(f"/api/v1/prompts/{prompt_id}/report", headers=reporter, json={"reason": "不存在"})).status_code == 400
    report = await client.post(
        f"/api/v1/prompts/{prompt_id}/report",
        headers=reporter,
        json={"reason": "低质重复", "details": "重复内容"},
    )
    assert report.status_code == 200
    assert (await client.post(f"/api/v1/prompts/{prompt_id}/report", headers=reporter, json={})).status_code == 400
    assert (await client.post("/api/v1/prompts/99999/report", headers=reporter, json={})).status_code == 404

    mine = await client.get("/api/v1/prompts/my-reports", headers=reporter, params={"status": "pending"})
    assert mine.json()["data"]["total"] == 1
    report_id = mine.json()["data"]["items"][0]["id"]
    listed = await client.get("/api/v1/admin/prompts/reports", headers=admin, params={"status": "pending"})
    assert listed.json()["data"]["total"] == 1
    stats = await client.get("/api/v1/admin/prompts/reports/stats", headers=admin)
    assert stats.json()["data"]["pending"] == 1
    assert (await client.post(f"/api/v1/admin/prompts/reports/{report_id}/resolve", headers=admin, json={"action": "bad"})).status_code == 400
    resolved = await client.post(
        f"/api/v1/admin/prompts/reports/{report_id}/resolve",
        headers=admin,
        json={"action": "hide", "note": "确认隐藏"},
    )
    assert resolved.status_code == 200
    assert (await client.post(f"/api/v1/admin/prompts/reports/{report_id}/resolve", headers=admin, json={"action": "reject"})).status_code == 400

    audit = await client.get(
        "/api/v1/admin/prompts/audit-logs",
        headers=admin,
        params={"action": "hide", "operator_name": "prompt-admin"},
    )
    assert audit.json()["data"]["total"] == 1
    after = await client.get("/api/v1/admin/prompts/reports/stats", headers=admin)
    assert after.json()["data"]["resolved"] == 1

    second = await client.post(
        "/api/v1/prompts",
        headers=owner,
        json={"name": "第二条", "chinese": "内容2", "category": "举报测试", "image_url": "/y.png"},
    )
    second_id = second.json()["data"]["id"]
    await client.post(f"/api/v1/prompts/{second_id}/report", headers=reporter, json={"reason": "其他"})
    pending = await client.get("/api/v1/prompts/my-reports", headers=reporter, params={"status": "pending"})
    second_report_id = pending.json()["data"]["items"][0]["id"]
    assert (await client.post("/api/v1/admin/prompts/reports/batch-resolve", headers=admin, json={"report_ids": []})).status_code == 400
    batch = await client.post(
        "/api/v1/admin/prompts/reports/batch-resolve",
        headers=admin,
        json={"report_ids": [second_report_id], "action": "reject", "note": "不成立"},
    )
    assert batch.status_code == 200 and batch.json()["data"]["processed"] == 1


@pytest.mark.asyncio
async def test_prompt_admin_crud_import_cleanup_and_csv_import(client):
    await _seed_prompt_users()
    admin = make_auth_headers(1)
    owner = make_auth_headers(2)
    invalid_category = await client.post("/api/v1/admin/prompts/categories", headers=admin, json={"name": ""})
    assert invalid_category.status_code == 400
    category = await client.post(
        "/api/v1/admin/prompts/categories",
        headers=admin,
        json={"name": "管理分类", "start_intro": "intro", "sort_order": 3},
    )
    category_id = category.json()["data"]["id"]
    assert (await client.get("/api/v1/admin/prompts/categories", headers=admin, params={"search": "管理"})).json()["data"]["total"] == 1
    assert (await client.put(f"/api/v1/admin/prompts/categories/{category_id}", headers=admin, json={"name": "管理分类2", "sort_order": 4})).status_code == 200

    invalid_example = await client.post("/api/v1/admin/prompts/examples", headers=admin, json={})
    assert invalid_example.status_code == 400
    example = await client.post(
        "/api/v1/admin/prompts/examples",
        headers=admin,
        json={
            "category_id": category_id,
            "param_type": "海报",
            "name": "管理员示例",
            "chinese_example": "中文",
            "english_example": "English",
            "image_url": "/admin.png",
            "ul_list": ["A"],
            "is_public": True,
        },
    )
    example_id = example.json()["data"]["id"]
    examples = await client.get(
        "/api/v1/admin/prompts/examples",
        headers=admin,
        params={"category_id": category_id, "param_type": "海报", "search": "管理员"},
    )
    assert examples.json()["data"]["total"] == 1
    assert (await client.put(f"/api/v1/admin/prompts/examples/{example_id}", headers=admin, json={"is_public": False, "name": "隐藏示例"})).status_code == 200
    overview = await client.get("/api/v1/admin/prompts/overview", headers=admin)
    assert overview.status_code == 200
    assert (await client.delete("/api/v1/admin/prompts/examples/99999", headers=admin)).status_code == 404
    assert (await client.delete(f"/api/v1/admin/prompts/examples/{example_id}", headers=admin)).status_code == 200

    bulk = await client.post(
        "/api/v1/admin/prompts/import",
        headers=admin,
        json={
            "categories": [
                {
                    "id": 9,
                    "name": "批量分类",
                    "params": [
                        {
                            "type": "通用",
                            "ulList": ["技巧"],
                            "examples": [
                                {"image": 1, "imageUrl": "/bulk.png", "name": "批量示例", "chineseExample": "批量中文", "englishExample": "bulk"}
                            ],
                        }
                    ],
                }
            ]
        },
    )
    assert bulk.status_code == 200 and bulk.json()["data"]["imported_examples"] == 1
    duplicate = await client.post("/api/v1/admin/prompts/import", headers=admin, json=bulk.request.content and {
        "categories": [{"name": "批量分类", "params": [{"type": "通用", "examples": [{"chineseExample": "批量中文"}]}]}]
    })
    assert duplicate.status_code == 200 and duplicate.json()["data"]["imported_examples"] == 0

    csv_bytes = "标题,中文提示词,英文提示词,分类,图片URL,参数类型\n成功,CSV中文,csv,CSV分类,/csv.png,封面\n失败,缺图,,CSV分类,,封面\n".encode()
    imported = await client.post(
        "/api/v1/prompts/import",
        headers=owner,
        files={"file": ("prompts.csv", csv_bytes, "text/csv")},
    )
    assert imported.status_code == 200
    assert imported.json()["data"]["imported_count"] == 1
    assert imported.json()["data"]["failed_count"] == 1
    assert (await client.post("/api/v1/prompts/import", headers=owner, files={"file": ("bad.txt", b"x", "text/plain")})).status_code == 400

    no_image = await client.post(
        "/api/v1/prompts",
        headers=owner,
        json={"name": "无图", "chinese": "待清理", "category": "清理"},
    )
    assert no_image.status_code == 200
    cleanup = await client.post("/api/v1/admin/prompts/cleanup-no-image", headers=admin)
    assert cleanup.status_code == 200 and cleanup.json()["data"]["deleted_count"] >= 1
    assert (await client.post("/api/v1/admin/prompts/cleanup-no-image", headers=admin)).json()["data"]["deleted_count"] == 0
    assert (await client.delete(f"/api/v1/admin/prompts/categories/{category_id}", headers=admin)).status_code == 200
