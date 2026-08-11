from __future__ import annotations

import pytest

from app.api.v1 import xhs as module
from app.db.session import async_session
from app.models.user import User
from app.services.vehicle_catalog_service import VehicleCatalogService
from app.services.xhs_ad_dashboard_service import XHSAdDashboardService
from app.services.xhs_profile_stat_service import XHSProfileStatService
from app.services.xhs_service import XHSService
from tests.conftest import make_auth_headers


async def _seed_users():
    async with async_session() as db:
        users = [
            User(id=1, username="admin", email="admin@example.com", hashed_password="x", role="admin"),
            User(id=2, username="buyer", email="buyer@example.com", hashed_password="x", role="buyer"),
            User(id=3, username="viewer", email="viewer@example.com", hashed_password="x", role="viewer"),
            User(id=4, username="operator", email="operator@example.com", hashed_password="x", role="xhs_ops"),
            User(id=5, username="lead", email="lead@example.com", hashed_password="x", role="xhs_lead"),
            User(id=6, username="brand", email="brand@example.com", hashed_password="x", role="brand_lead"),
        ]
        db.add_all(users)
        await db.commit()
    return users


def test_xhs_report_export_and_scope_helpers():
    assert module._split_csv(None) == []
    assert module._split_csv(" 1, 2 ,,3 ") == ["1", "2", "3"]
    assert module._export_ai_origin_value({"account_note_matched": False}) == "未找到"
    assert module._export_ai_origin_value({"account_note_matched": True}) == "未设置"
    assert module._export_ai_origin_value({"account_note_matched": True, "ai_origin_type": "text_ai"}) == "仅文案 AI"
    assert module._export_value({}, "fee") == 0
    assert module._export_value({"name": None}, "name") is None

    admin = User(id=1, username="a", email="a@x", hashed_password="x", role="admin")
    buyer = User(id=2, username="b", email="b@x", hashed_password="x", role="buyer")
    operator = User(id=3, username="o", email="o@x", hashed_password="x", role="xhs_ops")
    viewer = User(id=4, username="v", email="v@x", hashed_password="x", role="viewer")
    assert module._resolve_xhs_ad_dashboard_viewer_scope(admin, 8) == ("all", 8)
    assert module._resolve_xhs_ad_dashboard_viewer_scope(buyer, None) == ("buyer:self:2", 2)
    with pytest.raises(module.HTTPException):
        module._resolve_xhs_ad_dashboard_viewer_scope(buyer, 99)
    assert module._resolve_xhs_ad_dashboard_viewer_scope(viewer, None) == ("denied", None)
    assert module._resolve_xhs_insights_owner_scope(admin) == (None, None)
    assert module._resolve_xhs_insights_owner_scope(operator) == (None, {3})
    with pytest.raises(module.HTTPException):
        module._require_xhs_ad_dashboard_access(viewer)
    with pytest.raises(module.HTTPException):
        module._require_xhs_insights_access(viewer)


@pytest.mark.asyncio
async def test_xhs_report_endpoints_forward_all_types(client, monkeypatch):
    users = await _seed_users()
    headers = make_auth_headers(users[0].id)
    calls = []

    async def report(self, **kwargs):
        calls.append(kwargs)
        return {
            "report_type": kwargs["report_type"],
            "start_date": "2026-08-01",
            "end_date": "2026-08-10",
            "account_id": kwargs.get("account_id"),
            "account_name": kwargs.get("account_name"),
            "total_accounts": 1,
            "total_rows": 1,
            "page": kwargs.get("page", 1),
            "limit": kwargs.get("limit", 20),
            "items": [{"fee": 12}],
            "rows": [{"fee": 12}],
        }

    monkeypatch.setattr(XHSService, "get_jg_report_cached", report)
    paths = ["simple", "standard", "simple-note", "standard-note", "creative"]
    expected_types = ["simple", "standard", "simple_note", "standard_note", "creative"]
    for path, expected in zip(paths, expected_types):
        response = await client.get(
            f"/api/v1/xhs/report/{path}?account_id=10&account_name=广告户&start_date=2026-08-01&end_date=2026-08-10&page=2&limit=5&ai_origin_filter=text_ai",
            headers=headers,
        )
        assert response.status_code == 200
        assert response.json()["data"]["report_type"] == expected
    assert [call["report_type"] for call in calls] == expected_types
    assert calls[-1]["creative_ai_filter"] == "text_ai"

    async def compare(self, **kwargs):
        return {
            "report_type": "creative",
            "start_date": "2026-08-01",
            "end_date": "2026-08-10",
            "account_id": kwargs.get("account_id"),
            "account_name": kwargs.get("account_name"),
            "tags": [{"key": "all_ai"}],
            "granularities": {"day": {"periods": []}},
        }

    async def accounts(self):
        return [{"account_id": "10", "account_name": "广告户"}]

    monkeypatch.setattr(XHSService, "get_creative_report_ai_compare", compare)
    monkeypatch.setattr(XHSService, "list_report_accounts", accounts)
    compared = await client.get("/api/v1/xhs/report/creative/compare?account_id=10", headers=headers)
    assert compared.json()["data"]["tags"][0]["key"] == "all_ai"
    listed = await client.get("/api/v1/xhs/report/accounts", headers=headers)
    assert listed.json()["data"][0]["account_id"] == "10"


@pytest.mark.asyncio
async def test_ad_dashboard_modules_access_scopes_refresh_and_exports(client, monkeypatch):
    users = await _seed_users()
    admin_headers = make_auth_headers(users[0].id)
    buyer_headers = make_auth_headers(users[1].id)
    viewer_headers = make_auth_headers(users[2].id)
    calls = []

    async def dashboard(self, **kwargs):
        calls.append(kwargs)
        return {
            "start_date": "2026-08-01",
            "end_date": "2026-08-10",
            "brand_rows": [
                {
                    "brand": "零跑",
                    "fee": 100,
                    "impression": 1000,
                    "click": 100,
                    "ctr": 10,
                    "avg_click_cost": 1,
                    "conversion": 5,
                    "conversion_cost": 20,
                    "interaction": 30,
                }
            ],
            "note_rows": [
                {
                    "note_id": "n1",
                    "note_title": "帖子",
                    "account_name": "广告户",
                    "xhs_account_name": "专业号",
                    "report_types": ["简单投", "标准投"],
                    "fee": 100,
                }
            ],
        }

    async def tags(self, **kwargs):
        calls.append(kwargs)
        return {"level": kwargs["level"], "rows": [{"tag": "行情"}]}

    monkeypatch.setattr(XHSAdDashboardService, "dashboard", dashboard)
    monkeypatch.setattr(XHSAdDashboardService, "content_tag_modules", tags)
    denied = await client.get("/api/v1/xhs/ad-dashboard", headers=viewer_headers)
    assert denied.status_code == 403
    buyer_denied = await client.get("/api/v1/xhs/ad-dashboard?buyer_user_id=1", headers=buyer_headers)
    assert buyer_denied.status_code == 403
    buyer = await client.get(
        "/api/v1/xhs/ad-dashboard?account_ids=1,2&xhs_account_ids=x1,x2&include_content_tags=false",
        headers=buyer_headers,
    )
    assert buyer.status_code == 200
    assert calls[-1]["buyer_user_id"] == users[1].id
    assert calls[-1]["account_ids"] == ["1", "2"]
    assert calls[-1]["viewer_scope"] == f"buyer:self:{users[1].id}"

    content_tags = await client.get(
        "/api/v1/xhs/ad-dashboard/content-tags?level=secondary&primary_tag=行情",
        headers=admin_headers,
    )
    assert content_tags.json()["data"]["level"] == "secondary"
    refreshed = await client.post(
        "/api/v1/xhs/ad-dashboard/cache/refresh?include_content_tags=false",
        headers=admin_headers,
    )
    assert refreshed.json()["data"]["status"] == "refreshed"
    assert calls[-1]["force_refresh"] is True

    for table, title in (("brand", "xhs_ad_brand"), ("note", "xhs_ad_note")):
        exported = await client.get(f"/api/v1/xhs/ad-dashboard/export?table={table}", headers=admin_headers)
        assert exported.status_code == 200
        assert title in exported.headers["content-disposition"]
        assert len(exported.content) > 100


@pytest.mark.asyncio
async def test_profile_owner_and_empty_insights_endpoints(client, monkeypatch):
    users = await _seed_users()
    admin_headers = make_auth_headers(users[0].id)
    operator_headers = make_auth_headers(users[3].id)
    viewer_headers = make_auth_headers(users[2].id)
    received = []

    async def owners(self, **kwargs):
        received.append(kwargs)
        return [{"owner": "负责人", "natural_leads": 2}]

    monkeypatch.setattr(XHSProfileStatService, "owner_rows", owners)
    assert (await client.get("/api/v1/xhs/profile-stat/owners", headers=viewer_headers)).status_code == 403
    owner_response = await client.get(
        "/api/v1/xhs/profile-stat/owners?start_date=2026-08-01&end_date=2026-08-10",
        headers=operator_headers,
    )
    assert owner_response.status_code == 200
    assert received[-1]["allowed_owner_ids"] == {users[3].id}

    async def list_notes(self, user, **kwargs):
        return [], 0, 0

    monkeypatch.setattr(XHSService, "list_account_notes", list_notes)
    monkeypatch.setattr(XHSService, "list_account_notes_for_insights", list_notes)
    monkeypatch.setattr(XHSService, "build_insights_dashboard", lambda *args, **kwargs: {"kpis": {"notes": 0}})
    monkeypatch.setattr(VehicleCatalogService, "match_entries", pytest.fail)
    listed = await client.get(
        "/api/v1/xhs/account-notes?page=2&limit=5&keyword=零跑&status=active",
        headers=admin_headers,
    )
    assert listed.json()["data"]["total"] == 0
    insights = await client.get(
        "/api/v1/xhs/account-notes/insights?start_date=2026-08-01&end_date=2026-08-01&include_items=false",
        headers=admin_headers,
    )
    assert insights.status_code == 200
    assert insights.json()["data"]["dashboard"]["kpis"]["notes"] == 0


@pytest.mark.asyncio
async def test_report_export_and_token_import(client, monkeypatch):
    users = await _seed_users()
    headers = make_auth_headers(users[0].id)

    async def report(self, **kwargs):
        return {
            "start_date": "2026-08-01",
            "end_date": "2026-08-10",
            "rows": [
                {
                    "time": "2026-08-10",
                    "campaign_name": "计划",
                    "campaign_id": "p1",
                    "ai_origin_type": "image_ai",
                    "account_note_matched": True,
                    "fee": None,
                }
            ],
        }

    async def import_tokens(self, file_path):
        return {"imported": 2, "path": file_path}

    monkeypatch.setattr(XHSService, "get_jg_report_cached", report)
    monkeypatch.setattr(XHSService, "import_report_tokens_from_xls", import_tokens)
    for report_type in ("simple", "standard", "simple_note", "standard_note", "creative"):
        exported = await client.get(f"/api/v1/xhs/report/export?report_type={report_type}", headers=headers)
        assert exported.status_code == 200
        assert f"xhs_{report_type}_all" in exported.headers["content-disposition"]
    imported = await client.post("/api/v1/xhs/report/import-tokens?file_path=/tmp/tokens.xls", headers=headers)
    assert imported.json()["data"]["imported"] == 2
