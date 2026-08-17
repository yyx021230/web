from __future__ import annotations

from datetime import date
from unittest.mock import AsyncMock

import pytest

from app.services.xhs_ad_dashboard_service import (
    XHSAdDashboardService,
    _brand,
    _clean_content_tag,
    _creative_tag,
    _date_range,
    _note_id,
    _normalize_brand_candidate,
    _percent,
    _previous_range,
    _row_note_content_tag,
    _snapshot_account_ids,
    _strip_brand_noise,
    _to_float,
    _valid_content_tag,
    invalidate_ad_dashboard_caches,
)


@pytest.fixture
def dashboard_rows() -> list[dict]:
    return [
        {
            "time": "2026-08-01",
            "account_id": "account-a",
            "account_name": "上海炎创-A",
            "report_type": "simple_note",
            "fee": "100.00",
            "impression": "1,000",
            "click": 100,
            "like": 10,
            "collect": 5,
            "comment": 3,
            "share": 2,
            "follow": 1,
            "message_consult": 20,
            "initiative_message": 10,
            "msg_leads_num": 5,
            "note_id": "note-1",
            "note_title": "地区团购价格公布",
            "brand": "#比亚迪",
            "ai_origin_type": "manual",
        },
        {
            "time": "2026-08-01",
            "account_id": "account-a",
            "account_name": "上海炎创-A",
            "report_type": "standard_note",
            "fee": 50,
            "impression": 500,
            "click": 50,
            "interaction": 30,
            "message_consult": 5,
            "msg_chat_user_cnt": 5,
            "valid_leads": 2,
            "note_id": "note-1",
            "note_title": "地区团购价格公布",
            "brand_name": "比亚迪汽车",
            "creative_tag": "价格海报",
        },
        {
            "time": "2026-08-02",
            "account_id": "account-b",
            "account_name": "上海炎创-B",
            "report_type": "creative",
            "fee": 200,
            "impression": 2000,
            "click": 100,
            "interaction": 40,
            "message_consult": 30,
            "initiative_message": 20,
            "conversion": 10,
            "note_id": "note-2",
            "note_title": "零跑 C10 实测",
            "campaign_name": "🔴5.28零跑汽车#复投",
            "creativity_name": "车型测评#话题",
        },
    ]


@pytest.fixture
def note_tags() -> dict[str, dict[str, str]]:
    return {
        "note-1": {"primary": "价格优惠", "secondary": "地区团购"},
        "note-2": {"primary": "车型测评", "secondary": ""},
    }


def test_dashboard_normalizers_cover_dirty_external_values():
    catalog = ("比亚迪", "零跑汽车", "理想汽车")

    assert _to_float("1,234.5%") == 1234.5
    assert _to_float(None) == 0
    assert _to_float("not-a-number") == 0
    assert _percent(1, 4) == 25
    assert _strip_brand_noise("🔴5.28 零跑汽车 #复投") == "零跑汽车#复投"
    assert _normalize_brand_candidate("测试/比亚迪汽车", catalog) == "比亚迪"
    assert _brand({"campaign_name": "🔴5.28零跑汽车#复投"}, catalog) == (
        "零跑汽车"
    )
    assert _brand({"campaign_name": "上海炎创-云特曼懂车老油条-2"}, ("曼",)) == "未知"
    assert _brand({"brand": "曼"}, ("曼",)) == "曼"
    assert _brand({}, catalog) == "未知"
    assert _creative_tag({"ai_origin_type": "image_ai"}) == "图生图"
    assert _creative_tag({"creativity_name": "车型测评#话题"}) == "车型测评"
    assert _creative_tag({}) == "未标记"
    assert _note_id({"feed_id": 123}) == "123"

    assert _clean_content_tag("#车型测评【话题】#") == "车型测评"
    assert _valid_content_tag("车型测评") is True
    assert _valid_content_tag("1234") is False
    assert _valid_content_tag("#话题") is False
    assert _row_note_content_tag(
        {"note_id": "note-1"},
        {"note-1": {"primary": "价格优惠", "secondary": ""}},
        level="secondary",
    ) == ["未打二级标签"]
    assert _row_note_content_tag(
        {"note_id": "note-1"},
        {"note-1": {"primary": "价格优惠", "secondary": "地区"}},
        primary_tag="其他",
    ) == []

    assert _date_range("2026-08-03", "2026-08-01") == (
        date(2026, 8, 1),
        date(2026, 8, 3),
    )
    assert _previous_range(date(2026, 8, 3), date(2026, 8, 5)) == (
        date(2026, 7, 31),
        date(2026, 8, 2),
    )
    assert _snapshot_account_ids([" b ", "", "a", "a"]) == ["a", "a", "b"]


def test_dashboard_core_metrics_and_rankings(dashboard_rows, note_tags):
    service = XHSAdDashboardService(None)  # type: ignore[arg-type]
    assignments = {
        "account-a": {
            "buyer_user_id": 7,
            "buyer_display_name": "小赵",
            "buyer_username": "buyer-7",
            "account_name": "上海炎创-A",
        }
    }

    totals = service._totals(dashboard_rows)
    assert totals == {
        "fee": 350.0,
        "impression": 3500,
        "click": 250,
        "ctr": 7.14,
        "avg_click_cost": 1.4,
        "message_consult": 55,
        "openings": 35,
        "interaction": 91,
        "interaction_rate": 36.4,
        "opening_cost": 10.0,
        "conversion": 17,
        "conversion_rate": 6.8,
        "conversion_cost": 20.59,
        "comment": 3,
    }
    kpis = service._kpis(totals, {**totals, "fee": 300, "conversion": 10})
    assert len(kpis) == 12
    assert kpis[0]["delta"] == 50
    assert next(item for item in kpis if item["key"] == "conversion")[
        "delta"
    ] == 7

    owner_rows = service._owner_rows(dashboard_rows, assignments)
    assert [item["owner_name"] for item in owner_rows] == ["未分配", "小赵"]
    assigned = next(item for item in owner_rows if item["owner_name"] == "小赵")
    assert assigned["account_count"] == 1
    assert assigned["fee"] == 150
    assert assigned["conversion"] == 7
    account_rows = service._account_rows(dashboard_rows, assignments)
    assert [item["owner_name"] for item in account_rows] == [
        "上海炎创-B",
        "上海炎创-A",
    ]

    funnel = service._funnel(dashboard_rows)
    assert [item["label"] for item in funnel] == [
        "曝光",
        "点击",
        "咨询",
        "开口",
        "转化",
    ]
    assert funnel[0]["overall_rate"] == 100
    assert funnel[-1]["value"] == 17

    trend = service._trend(dashboard_rows, date(2026, 8, 1), date(2026, 8, 3))
    assert [item["fee"] for item in trend] == [150.0, 200.0, 0.0]
    assert trend[2]["conversion"] == 0

    brands = service._brand_rows(dashboard_rows, ("比亚迪", "零跑汽车"))
    assert [(item["brand"], item["fee"]) for item in brands] == [
        ("零跑汽车", 200.0),
        ("比亚迪", 150.0),
    ]
    assert brands[0]["conversion_cost"] == 20

    note_rows = service._note_rows(
        dashboard_rows,
        {"note-1": "专业号甲", "note-2": "专业号乙"},
    )
    assert [item["note_id"] for item in note_rows] == ["note-2", "note-1"]
    assert note_rows[1]["report_types"] == ["简单投笔记报表", "标准投笔记报表"]
    assert note_rows[1]["xhs_account_name"] == "专业号甲"

    top_notes = service._top_notes(
        dashboard_rows,
        {"note-1": "专业号甲", "note-2": "专业号乙"},
    )
    assert top_notes["conversion"]["note_id"] == "note-2"
    assert top_notes["impression"]["score"] > 0

    summary = service._ai_summary(totals, owner_rows, brands)
    assert summary["title"] == "投流数据摘要"
    assert "未分配" in summary["summary"]
    assert len(summary["actions"]) == 3


def test_dashboard_content_tags_and_period_comparisons(dashboard_rows, note_tags):
    service = XHSAdDashboardService(None)  # type: ignore[arg-type]
    assignments = {
        "account-a": {
            "buyer_user_id": 7,
            "buyer_display_name": "小赵",
            "buyer_username": "buyer-7",
        },
        "account-b": {
            "buyer_user_id": 8,
            "buyer_display_name": "小林",
            "buyer_username": "buyer-8",
        },
    }

    quadrant, creative_tags, children = service._content_tag_tree_payload(
        dashboard_rows,
        note_tags,
    )
    assert {point["tag"] for point in quadrant["points"]} == {
        "价格优惠",
        "车型测评",
    }
    assert [item["tag"] for item in creative_tags] == ["车型测评", "价格优惠"]
    assert children["价格优惠"]["creative_tags"][0]["tag"] == "地区团购"
    assert children["车型测评"]["creative_tags"][0]["tag"] == (
        "未打二级标签"
    )

    aggregate_rows = [
        {
            "primary_content_tag": "价格优惠",
            "secondary_content_tag": "地区团购",
            "fee": 150,
            "conversion": 7,
            "click": 150,
            "interaction": 51,
            "row_count": 2,
        },
        {
            "primary_content_tag": "车型测评",
            "secondary_content_tag": "",
            "fee": 200,
            "conversion": 10,
            "click": 100,
            "interaction": 40,
            "row_count": 1,
        },
    ]
    agg_quadrant, agg_tags, agg_children = (
        service._content_tag_tree_payload_from_aggregate_rows(aggregate_rows)
    )
    assert agg_quadrant == quadrant
    assert agg_tags == creative_tags
    assert set(agg_children) == set(children)

    secondary_quadrant, secondary_tags = (
        service._content_tag_payload_from_aggregate_rows(
            aggregate_rows,
            level="secondary",
            primary_tag="价格优惠",
        )
    )
    assert secondary_quadrant["points"][0]["tag"] == "地区团购"
    assert secondary_tags[0]["conversion"] == 7

    previous_rows = [
        {
            **dashboard_rows[0],
            "fee": 80,
            "click": 80,
            "initiative_message": 8,
            "msg_leads_num": 4,
        }
    ]
    comparisons = service._comparison_rows(
        dashboard_rows,
        previous_rows,
        assignments,
    )
    assert [item["owner_name"] for item in comparisons] == ["小林", "小赵"]
    xiao_zhao = next(item for item in comparisons if item["owner_name"] == "小赵")
    assert xiao_zhao["fee_delta"] == 70
    assert xiao_zhao["conversion_delta"] == 3
    assert "opening_rate_delta" in xiao_zhao

    metadata = {
        "note-1": {
            "primary": "价格优惠",
            "secondary": "地区团购",
            "owner_name": "专业号甲",
        },
        "note-2": {
            "primary": "车型测评",
            "secondary": "",
            "owner_name": "专业号乙",
        },
    }
    assert service._content_tag_map_from_metadata(metadata)["note-1"] == {
        "primary": "价格优惠",
        "secondary": "地区团购",
    }
    assert service._note_owner_map_from_metadata(metadata) == {
        "note-1": "专业号甲",
        "note-2": "专业号乙",
    }


@pytest.mark.asyncio
async def test_dashboard_orchestration_filters_and_uses_aggregates(monkeypatch):
    invalidate_ad_dashboard_caches()
    service = XHSAdDashboardService(None)  # type: ignore[arg-type]
    assignments = {
        "account-a": {
            "buyer_user_id": 7,
            "buyer_display_name": "小赵",
            "buyer_username": "buyer-7",
        },
        "account-b": {
            "buyer_user_id": 8,
            "buyer_display_name": "小林",
            "buyer_username": "buyer-8",
        },
    }
    mappings = {
        "account-a": {
            "xhs_account_id": "xhs-a",
            "xhs_account_name": "专业号甲",
            "xhs_owner_name": "运营甲",
        },
        "account-b": {
            "xhs_account_id": "xhs-b",
            "xhs_account_name": "专业号乙",
            "xhs_owner_name": "运营乙",
        },
    }
    current = [{
        "report_type": "simple",
        "report_date": "2026-08-01",
        "account_id": "account-a",
        "account_name": "广告账户甲",
        "fee": 100,
        "impression": 1000,
        "click": 100,
        "message_consult": 20,
        "initiative_message": 10,
        "msg_leads_num": 5,
        "interaction": 30,
    }]
    previous = [{
        **current[0],
        "report_date": "2026-07-31",
        "fee": 80,
        "msg_leads_num": 4,
    }]

    monkeypatch.setattr(service, "_assignments", AsyncMock(return_value=assignments))
    monkeypatch.setattr(service, "_professional_mappings", AsyncMock(return_value=mappings))
    monkeypatch.setattr(service, "_assignment_revision", AsyncMock(return_value={"row_count": 2}))
    monkeypatch.setattr(service, "_report_revision", AsyncMock(return_value={"row_count": 2}))
    monkeypatch.setattr(service, "_load_snapshot", AsyncMock(return_value=None))
    monkeypatch.setattr(service, "_save_snapshot", AsyncMock())

    async def aggregate_accounts(_types, start, _end, account_ids):
        assert account_ids == ["account-a"]
        return current if start == date(2026, 8, 1) else previous

    monkeypatch.setattr(service, "_aggregate_account_rows", aggregate_accounts)
    monkeypatch.setattr(service, "_aggregate_brand_rows", AsyncMock(return_value=[{
        "brand": "比亚迪",
        "fee": 100,
        "conversion": 5,
    }]))
    monkeypatch.setattr(service, "content_tag_modules", AsyncMock(return_value={
        "quadrant": {"avg_x": 20, "avg_y": 5, "points": []},
        "creative_tags": [{"tag": "车型测评", "conversion": 5}],
        "top_notes": {"conversion": None},
        "note_rows": [],
    }))
    monkeypatch.setattr(service, "_account_options_for_buyer", AsyncMock(return_value=[{
        "account_id": "account-a",
        "account_name": "广告账户甲",
    }]))
    monkeypatch.setattr(service, "_professional_options", AsyncMock(return_value=[{
        "xhs_account_id": "xhs-a",
        "xhs_account_name": "专业号甲",
    }]))
    monkeypatch.setattr(service, "buyer_options", AsyncMock(return_value=[{
        "user_id": 7,
        "display_name": "小赵",
    }]))

    payload = await service.dashboard(
        start_date="2026-08-01",
        end_date="2026-08-01",
        account_ids=["account-a", "account-b"],
        xhs_account_ids=["xhs-a"],
        buyer_user_id=7,
        viewer_scope="buyer:self:7",
        force_refresh=True,
    )

    assert payload["data_source"] == "aggregate"
    assert payload["filters"]["account_ids"] == ["account-a"]
    assert payload["filters"]["xhs_account_ids"] == ["xhs-a"]
    assert payload["summary"]["fee"] == 100
    assert payload["owner_rows"][0]["owner_name"] == "广告账户甲"
    assert payload["creative_tags"][0]["tag"] == "车型测评"
    assert payload["comparison_rows"][0]["fee_delta"] == 20
    service._save_snapshot.assert_awaited_once()


@pytest.mark.asyncio
async def test_dashboard_snapshot_short_circuits_expensive_queries(monkeypatch):
    invalidate_ad_dashboard_caches()
    service = XHSAdDashboardService(None)  # type: ignore[arg-type]
    snapshot = {"data_source": "snapshot", "summary": {"fee": 321}}
    monkeypatch.setattr(service, "_assignments", AsyncMock(return_value={}))
    monkeypatch.setattr(service, "_professional_mappings", AsyncMock(return_value={}))
    monkeypatch.setattr(service, "_assignment_revision", AsyncMock(return_value={}))
    monkeypatch.setattr(service, "_report_revision", AsyncMock(return_value={}))
    monkeypatch.setattr(service, "_load_snapshot", AsyncMock(return_value=snapshot))
    aggregate = AsyncMock(side_effect=AssertionError("snapshot hit must skip aggregation"))
    monkeypatch.setattr(service, "_aggregate_account_rows", aggregate)

    result = await service.dashboard(
        start_date="2026-08-01",
        end_date="2026-08-01",
    )

    assert result == snapshot
    aggregate.assert_not_awaited()


@pytest.mark.asyncio
async def test_content_tag_modules_aggregate_primary_and_secondary(monkeypatch):
    invalidate_ad_dashboard_caches()
    service = XHSAdDashboardService(None)  # type: ignore[arg-type]
    mappings = {
        "account-a": {
            "xhs_account_id": "xhs-a",
            "xhs_account_name": "专业号甲",
        }
    }
    tag_rows = [{
        "primary_content_tag": "价格优惠",
        "secondary_content_tag": "地区团购",
        "fee": 100,
        "impression": 1000,
        "click": 100,
        "conversion": 5,
        "interaction": 30,
        "row_count": 1,
    }]
    note_rows = [{
        "report_type": "simple_note",
        "report_date": "2026-08-01",
        "account_id": "account-a",
        "account_name": "广告账户甲",
        "xhs_account_name": "专业号甲",
        "note_id": "note-1",
        "note_title": "地区团购",
        "primary_content_tag": "价格优惠",
        "secondary_content_tag": "地区团购",
        "fee": 100,
        "impression": 1000,
        "click": 100,
        "initiative_message": 10,
        "msg_leads_num": 5,
        "interaction": 30,
    }]
    monkeypatch.setattr(service, "_assignments", AsyncMock(return_value={}))
    monkeypatch.setattr(service, "_professional_mappings", AsyncMock(return_value=mappings))
    monkeypatch.setattr(service, "_assignment_revision", AsyncMock(return_value={}))
    monkeypatch.setattr(service, "_report_revision", AsyncMock(return_value={}))
    monkeypatch.setattr(service, "_save_snapshot", AsyncMock())
    monkeypatch.setattr(service, "_aggregate_content_tag_rows", AsyncMock(return_value=tag_rows))
    monkeypatch.setattr(service, "_aggregate_note_rows", AsyncMock(return_value=note_rows))

    primary = await service.content_tag_modules(
        start_date="2026-08-01",
        end_date="2026-08-01",
        xhs_account_ids=["xhs-a"],
        force_refresh=True,
    )
    secondary = await service.content_tag_modules(
        start_date="2026-08-01",
        end_date="2026-08-01",
        xhs_account_ids=["xhs-a"],
        primary_tag="#价格优惠【话题】#",
        force_refresh=True,
    )

    assert primary["data_source"] == "aggregate"
    assert primary["content_tag_level"] == "primary"
    assert primary["content_tag_children"]["价格优惠"]["creative_tags"][0]["tag"] == "地区团购"
    assert primary["top_notes"]["conversion"]["note_id"] == "note-1"
    assert secondary["content_tag_level"] == "secondary"
    assert secondary["content_tag_primary"] == "价格优惠"
    assert secondary["quadrant"]["points"][0]["tag"] == "地区团购"
