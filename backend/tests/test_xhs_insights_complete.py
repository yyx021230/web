"""Coverage and contract tests for the XHS operations dashboard aggregation."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.db.session import async_session
from app.models.user import User
from app.models.xhs_account_note import XHSAccountNote
from app.models.xhs_environment import XHSEnvironment
from app.services import xhs_service as module
from app.services.xhs_service import XHSService


def _note(
    note_id: int,
    *,
    environment_id: int,
    account: str,
    title: str,
    published_at: datetime,
    views: object = 0,
    likes: object = 0,
    comments: object = 0,
    collects: object = 0,
    shares: object = 0,
    owner_id: int | None = None,
    owner: str = "",
    role: str | None = None,
    promoted: bool = False,
    image_urls: list[str] | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=note_id,
        environment_id=environment_id,
        account_name=account,
        profile_nickname=account,
        feed_id=f"feed-{note_id}",
        post_url=f"https://xhs.test/{note_id}",
        title=title,
        content=f"{title} 正文 #购车攻略[话题]#",
        cover_image_url="" if image_urls else f"https://img.test/{note_id}.jpg",
        image_urls=image_urls or [],
        view_count=views,
        liked_count=likes,
        comment_count=comments,
        collected_count=collects,
        share_count=shares,
        published_at=published_at,
        created_at=published_at,
        updated_at=published_at,
        owner_user_id=owner_id,
        owner_username=owner,
        owner_role=role,
        is_promoted=promoted,
        has_paid_report=False,
        has_creative_report=False,
    )


def test_insights_scalar_role_time_and_vehicle_helpers_cover_edges():
    invalid = SimpleNamespace(value="bad", nan=float("nan"), account_name="", profile_nickname="")
    assert XHSService._insights_note_number(invalid, "missing") == 0
    assert XHSService._insights_note_number(invalid, "value") == 0
    assert XHSService._insights_note_number(invalid, "nan") == 0
    assert XHSService._insights_note_account_name(invalid) == "未命名账号"
    assert XHSService._insights_note_account_key(invalid) == "未命名账号"
    assert XHSService._insights_note_date(invalid) is None
    assert XHSService._insights_round(1.236, 2) == 1.24
    assert XHSService._insights_ratio(5, 0) == 0

    curve = [(0, 0), (10, 5), (20, 10)]
    assert XHSService._insights_score_curve(5, curve) == 2.5
    assert XHSService._insights_score_curve(-1, curve) == 0
    assert XHSService._insights_score_curve(25, curve) == 10
    assert XHSService._insights_score_curve(1, []) == 0
    assert XHSService._insights_score_curve(1, [(0, 1), (0, 2)]) == 2

    role_labels = {
        "xhs_lead": "小红书部门负责人",
        "xhs_ops": "小红书运营",
        "buyer": "投手",
        "xhs_buyer": "投手",
        "brand_lead": "品牌责任人",
        "brand_ops": "品牌运营",
        "admin": "管理员",
        "viewer": "未分配",
    }
    for role, label in role_labels.items():
        assert XHSService._insights_owner_role_label(role) == label
    assert XHSService._insights_is_reportable_owner("xhs_ops") is True
    assert XHSService._insights_is_reportable_owner("viewer") is False
    assert XHSService._insights_owner_role(["viewer", "brand_lead"]) == "brand_lead"

    day_key, day_label = XHSService._insights_trend_bucket(
        datetime(2026, 6, 2),
        date(2026, 6, 1),
        date(2026, 6, 30),
    )
    assert (day_key, day_label) == ("2026-06-02", "06/02")
    week_key, week_label = XHSService._insights_trend_bucket(
        datetime(2026, 6, 10),
        date(2026, 5, 1),
        date(2026, 6, 30),
    )
    assert week_key.startswith("week-")
    assert "~" in week_label

    XHSService.set_vehicle_catalog_entries(
        [
            {"brand": "零跑汽车", "model": "零跑C10"},
            {"brand": "比亚迪", "model": "海豹06 DM-i"},
            {"brand": "零跑汽车", "model": "零跑C10"},
            {"brand": "", "model": "无效"},
        ]
    )
    assert len(XHSService._vehicle_catalog()) == 2
    assert XHSService._vehicle_normalize("\ufeff 零跑-C10 ") == "零跑c10"
    assert XHSService._vehicle_useful_key("汽车") is False
    assert XHSService._vehicle_useful_key("C10") is True
    assert XHSService._vehicle_short_ambiguous("4") is True
    assert XHSService._vehicle_short_ambiguous("c9") is True
    assert XHSService._vehicle_short_ambiguous("c10") is True
    assert XHSService._vehicle_short_ambiguous("leapc10") is False

    zero = SimpleNamespace(title="", content="")
    assert XHSService._vehicle_match(zero)["brand"] == "未识别品牌"
    matched = SimpleNamespace(title="零跑C10新车体验", content="价格很有诚意")
    result = XHSService._vehicle_match(matched)
    assert result["brand"] == "零跑汽车"
    assert result["model"] == "零跑C10"
    brand_only = SimpleNamespace(title="比亚迪购车政策", content="没有具体车型")
    assert XHSService._vehicle_match(brand_only)["brand"] == "比亚迪"
    unknown = SimpleNamespace(title="完全无关内容", content="生活记录")
    assert XHSService._vehicle_match(unknown)["brand"] == "未识别品牌"


def test_build_insights_dashboard_aggregates_real_business_dimensions():
    module._INSIGHTS_DASHBOARD_CACHE.clear()
    XHSService.set_vehicle_catalog_entries(
        [
            {"brand": "零跑汽车", "model": "零跑C10"},
            {"brand": "比亚迪", "model": "海豹06"},
        ]
    )
    start = date(2026, 6, 1)
    end = date(2026, 6, 30)
    base = datetime(2026, 6, 1, 10)
    notes = [
        _note(1, environment_id=11, account="账号A", title="零跑C10首测", published_at=base, views=6000, likes=80, comments=35, collects=20, shares=5, owner_id=1, owner="运营甲", role="xhs_ops", promoted=True),
        _note(2, environment_id=11, account="账号A", title="零跑C10价格", published_at=base + timedelta(days=1), views=5000, likes=60, comments=32, collects=15, shares=4, owner_id=1, owner="运营甲", role="xhs_ops"),
        _note(3, environment_id=11, account="账号A", title="零跑C10日常", published_at=base + timedelta(days=2), views=50, likes=1, comments=1, collects=0, shares=0, owner_id=1, owner="运营甲", role="xhs_ops", image_urls=["https://img.test/fallback.jpg"]),
        _note(4, environment_id=22, account="账号B", title="海豹06购车建议", published_at=base + timedelta(days=3), views=700, likes=10, comments=4, collects=3, shares=1, owner_id=2, owner="品牌乙", role="brand_lead"),
        _note(5, environment_id=33, account="账号C", title="低效样本一", published_at=base + timedelta(days=4), views=20, likes=0, comments=0, owner_id=3, owner="投手丙", role="xhs_buyer"),
        _note(6, environment_id=33, account="账号C", title="低效样本二", published_at=base + timedelta(days=5), views=30, likes=0, comments=0, owner_id=3, owner="投手丙", role="xhs_buyer"),
        _note(7, environment_id=33, account="账号C", title="低效样本三", published_at=base + timedelta(days=6), views=40, likes=0, comments=0, owner_id=3, owner="投手丙", role="xhs_buyer"),
        _note(8, environment_id=44, account="账号D", title="没有指标", published_at=base + timedelta(days=7), views="bad", likes=float("nan"), comments=0),
    ]

    dashboard = XHSService.build_insights_dashboard(notes, start_date=start, end_date=end)
    metrics = dashboard["metrics"]
    assert metrics["activeAccounts"] == 4
    assert metrics["totalPosts"] == 8
    assert metrics["totalViews"] == 11840
    assert metrics["qualityCount"] == 2
    assert metrics["lowQualityCount"] == 5
    assert len(dashboard["trend"]) == 8
    assert len(dashboard["postRankings"]) == 8
    assert dashboard["postRankings"][0]["title"] == "零跑C10首测"

    accounts = {row["accountName"]: row for row in dashboard["accountSummaries"]}
    assert accounts["账号A"]["status"] == "主推"
    assert accounts["账号B"]["status"] == "修正"
    assert accounts["账号C"]["status"] == "观察"
    assert accounts["账号D"]["status"] == "补样本"
    assert accounts["账号D"]["missingInteractionMetrics"] is False

    operators = {row["ownerName"]: row for row in dashboard["operatorRows"]}
    assert set(operators) == {"运营甲", "品牌乙"}
    assert operators["运营甲"]["accountCount"] == 1
    assert operators["运营甲"]["paidPosts"] == 1
    assert operators["运营甲"]["organicPosts"] == 2
    assert operators["运营甲"]["paidRatio"] == pytest.approx(1 / 3)

    brands = {row["brand"]: row for row in dashboard["carTypeStats"]}
    assert brands["零跑汽车"]["posts"] == 3
    assert brands["比亚迪"]["posts"] == 1
    assert brands["未识别品牌"]["posts"] == 4

    # A repeated request with the same source signature must reuse the cached snapshot.
    assert XHSService.build_insights_dashboard(notes, start_date=start, end_date=end) is dashboard

    weekly = XHSService.build_insights_dashboard(
        notes,
        start_date=date(2026, 5, 1),
        end_date=end,
    )
    assert weekly["trend"][0]["label"].count("~") == 1
    assert XHSService._build_insights_car_type_stats([])[0]["name"] == "暂无样本"


@pytest.mark.asyncio
async def test_list_account_notes_for_insights_filters_and_attaches_metadata(client):
    _ = client
    published = datetime(2026, 6, 10, 12)
    async with async_session() as db:
        user = User(id=10, username="insights", email="insights@test.local", hashed_password="x", role="xhs_ops")
        env = XHSEnvironment(id=301, shop_id="shop-301", account_name="运营账号", status="active")
        db.add_all([user, env])
        await db.flush()
        db.add_all(
            [
                XHSAccountNote(
                    environment_id=301,
                    account_name="运营账号",
                    profile_nickname="运营账号",
                    feed_id="inside",
                    title="范围内",
                    status="active",
                    view_count=100,
                    published_at=published,
                ),
                XHSAccountNote(
                    environment_id=301,
                    account_name="运营账号",
                    profile_nickname="运营账号",
                    feed_id="outside",
                    title="范围外",
                    status="offline",
                    view_count=200,
                    published_at=published - timedelta(days=60),
                ),
            ]
        )
        await db.commit()

    async with async_session() as db:
        service = XHSService(db)
        service.list_environments = AsyncMock(return_value=[XHSEnvironment(id=301)])
        service._attach_environment_owners = AsyncMock()
        service._attach_paid_report_flags = AsyncMock()
        user = User(id=10, username="insights", role="xhs_ops")
        items, total, accounts = await service.list_account_notes_for_insights(
            user,
            start_date=date(2026, 6, 1),
            end_date=date(2026, 6, 30),
            limit=100,
        )
        assert total == 1
        assert accounts == 1
        assert [item.feed_id for item in items] == ["inside"]
        service._attach_environment_owners.assert_awaited_once()
        service._attach_paid_report_flags.assert_awaited_once_with(
            items,
            start_date=date(2026, 6, 1),
            end_date=date(2026, 6, 30),
            resolve_from_reports=False,
        )

        service.list_environments = AsyncMock(return_value=[])
        assert await service.list_account_notes_for_insights(user) == ([], 0, 0)
