"""Profile-stat ingestion, ownership and aggregation contracts."""

from datetime import date

import pytest
from sqlalchemy import select

from app.config import settings
from app.db.session import async_session as session_factory
from app.models.user import User
from app.models.user_xhs_env import UserXHSEnvironment
from app.models.xhs_environment import XHSEnvironment
from app.models.xhs_report import XHSProfileStatDaily
from app.services import xhs_profile_stat_service as module
from app.services.xhs_profile_stat_service import (
    XHSProfileStatService,
    _date_range,
    _profile_owner_role,
    _to_int,
    _to_rate,
    display_profile_account_name,
    extract_profile_url_id,
    extract_youju_profile_id,
    get_youju_account_identifier,
    normalize_profile_account_id,
    normalize_profile_account_name,
)


def test_profile_stat_normalizers_and_date_ranges():
    assert normalize_profile_account_name(" 【小红书】 测试 账号 ") == "测试账号"
    assert display_profile_account_name("【小红书】测试") == "测试"
    assert normalize_profile_account_id(" AbC ") == "abc"
    assert get_youju_account_identifier(None) == ""
    assert get_youju_account_identifier({"account_id_with_id": "new", "wx_app_id": "old"}) == "new"
    assert get_youju_account_identifier({"wx_app_id": "legacy"}) == "legacy"
    assert extract_youju_profile_id("【小红书】昵称(AbC-12)") == "abc-12"
    assert extract_youju_profile_id("missing") == ""
    assert extract_profile_url_id("https://www.xiaohongshu.com/user/profile/ABC_12?x=1") == "abc_12"
    assert extract_profile_url_id("http://[") == ""
    assert _profile_owner_role(["viewer", "xhs_ops"]) == "xhs_ops"
    assert _to_int("1,234.6") == 1235
    assert _to_int("bad") == 0
    assert _to_rate("12.5%") == 0.125
    assert _to_rate("12.5") == 0.125
    assert _to_rate("0.5") == 0.5
    assert _to_rate(None) == 0
    assert _date_range("2026-06-03", "2026-06-01") == (date(2026, 6, 1), date(2026, 6, 3))


def test_profile_stat_payload_mapping_and_rates():
    payload = {
        "account_id_with_id": "【小红书】账号(P1)",
        "subscribe": "1,000",
        "info": "10",
        "user_info.ad_info.advertiser_id=null": 20,
        "user_info.ad_info.advertiser_id": 30,
        "chat+user_info.ad_info.advertiser_id=null": 8,
        "{小红书广告总开口}-{特殊自然来源数}": 6,
        "phone+user_info.ad_info.advertiser_id=null": 4,
        "user_info.ad_info.campaign_id=-1+phone": 2,
        "{小红书广告}-{特殊自然来源数}": 3,
        "{总访问数}-{评论用户数}": 50,
        "{客资数}-{评论留资数}": 7,
        "tag_小红书评论": 5,
        "tag_小红书评论+phone": 1,
        "user_info.ad_info.advertiser_id+phone": 9,
        "({自然来源客资数}+{特殊自然来源数})/{自然来源开口数}": "75%",
        "({小红书广告}-{特殊自然来源数})/{广告开口数}": "50%",
        "{评论留资数}/{评论用户数}": "20%",
        "({客资数}-{评论留资数})/({总访问数}-{评论用户数})": "14%",
    }
    row = XHSProfileStatService._row_from_payload(date(2026, 6, 1), payload)
    assert row["channel_account_name"] == "账号(P1)"
    assert (row["total_visits"], row["natural_leads"], row["special_natural_leads"], row["ad_leads"]) == (
        1000,
        4,
        2,
        3,
    )
    assert row["natural_opening_conversion_rate"] == 0.75
    assert XHSProfileStatService._derived_rates(row) == {
        "natural_opening_conversion_rate": 0.75,
        "ad_opening_conversion_rate": 0.5,
        "comment_lead_rate": 0.2,
        "private_lead_rate": 0.14,
    }
    assert all(value == 0 for value in XHSProfileStatService._derived_rates({}).values())


class _Response:
    def __init__(self, status_code=200, body=None, text=""):
        self.status_code = status_code
        self._body = body or {}
        self.text = text

    def json(self):
        return self._body


class _HTTPClient:
    response = _Response()
    calls = []

    def __init__(self, **kwargs):
        self.kwargs = kwargs

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None

    async def get(self, url, params):
        self.calls.append((url, params, self.kwargs))
        return self.response


@pytest.mark.asyncio
async def test_fetch_day_success_and_error_contracts(client, monkeypatch):
    service = XHSProfileStatService(None)  # type: ignore[arg-type]
    monkeypatch.setattr(settings, "xhs_profile_stat_app_id", "app")
    monkeypatch.setattr(settings, "xhs_profile_stat_secret", "secret")
    monkeypatch.setattr(module.httpx, "AsyncClient", _HTTPClient)

    _HTTPClient.response = _Response(
        body={
            "msg": "success",
            "data": {
                "data": [
                    {"account_id_with_id": "【小红书】保留(P1)", "subscribe": "2"},
                    {"account_id_with_id": "其他平台", "subscribe": "9"},
                ]
            },
        }
    )
    rows = await service.fetch_day(date(2026, 6, 1))
    assert len(rows) == 1 and rows[0]["total_visits"] == 2
    assert _HTTPClient.calls[-1][1]["start_time"] == "2026-06-01 00:00:00"

    _HTTPClient.response = _Response(status_code=503, text="upstream down")
    with pytest.raises(RuntimeError, match="HTTP 503"):
        await service.fetch_day(date(2026, 6, 1))

    _HTTPClient.response = _Response(body={"msg": "denied", "data": None})
    with pytest.raises(RuntimeError, match="denied"):
        await service.fetch_day(date(2026, 6, 1))

    monkeypatch.setattr(settings, "xhs_profile_stat_secret", "")
    with pytest.raises(RuntimeError, match="未配置"):
        await service.fetch_day(date(2026, 6, 1))


@pytest.mark.asyncio
async def test_upsert_sync_and_backfill_retry_skip(client, monkeypatch):
    day1 = date(2026, 6, 1)
    day2 = date(2026, 6, 2)
    async with session_factory() as db:
        service = XHSProfileStatService(db)
        base = XHSProfileStatService._row_from_payload(day1, {"account_id_with_id": "【小红书】账号", "info": 1})
        assert await service.upsert_rows([base]) == 1
        changed = {**base, "leads": 9}
        assert await service.upsert_rows([changed]) == 1
        saved = (await db.execute(select(XHSProfileStatDaily))).scalar_one()
        assert saved.leads == 9

        async def fetch_day(target):
            return [XHSProfileStatService._row_from_payload(target, {"account_id_with_id": "【小红书】新增"})]

        monkeypatch.setattr(service, "fetch_day", fetch_day)
        assert await service.sync_day(day2) == {"date": "2026-06-02", "rows": 1, "updated": 1}

        attempts = 0

        async def flaky_sync(target):
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise RuntimeError("temporary")
            return {"date": target.isoformat(), "rows": 1, "updated": 1}

        monkeypatch.setattr(service, "sync_day", flaky_sync)
        result = await service.backfill(
            start_date=day1,
            end_date=date(2026, 6, 3),
            delay_seconds=0,
            skip_existing=True,
            max_retries=1,
        )
        assert result["days"] == 3
        assert result["updated_days"] == 1
        assert len([item for item in result["results"] if item.get("skipped")]) == 2
        assert result["errors"] == []

        async def always_fail(_target):
            raise RuntimeError("permanent")

        monkeypatch.setattr(service, "sync_day", always_fail)
        failed = await service.backfill(
            start_date=date(2026, 6, 4),
            end_date=date(2026, 6, 5),
            delay_seconds=0,
            skip_existing=False,
            limit_days=1,
            max_retries=0,
        )
        assert failed["updated_days"] == 0
        assert failed["errors"] == [{"date": "2026-06-04", "error": "permanent"}]


@pytest.mark.asyncio
async def test_owner_rows_uses_stable_profile_id_and_current_assignments(client):
    async with session_factory() as db:
        owner = User(
            id=10,
            username="owner",
            display_name="运营甲",
            email="owner@example.com",
            hashed_password="x",
            role="xhs_ops",
        )
        ignored = User(
            id=11,
            username="viewer",
            email="viewer-owner@example.com",
            hashed_password="x",
            role="viewer",
        )
        env = XHSEnvironment(
            id=100,
            shop_id="shop-100",
            account_name="账号新名称",
            profile_url="https://www.xiaohongshu.com/user/profile/P100",
            status="active",
        )
        ignored_env = XHSEnvironment(id=101, shop_id="shop-101", account_name="忽略", status="inactive")
        db.add_all([owner, ignored, env, ignored_env])
        await db.flush()
        db.add_all(
            [
                UserXHSEnvironment(user_id=10, environment_id=100),
                UserXHSEnvironment(user_id=11, environment_id=101),
                XHSProfileStatDaily(
                    stat_date=date(2026, 6, 1),
                    channel_account_name="历史昵称(P100)",
                    channel_account_key="历史昵称(p100)",
                    total_visits=100,
                    leads=10,
                    natural_openings=8,
                    natural_leads=4,
                    special_natural_leads=2,
                    ad_openings=6,
                    ad_leads=3,
                    comment_users=5,
                    comment_leads=1,
                    direct_private_count=10,
                    private_leads=2,
                    payload={"account_id_with_id": "【小红书】历史昵称(P100)"},
                ),
                XHSProfileStatDaily(
                    stat_date=date(2026, 6, 1),
                    channel_account_name="未知账户",
                    channel_account_key="未知账户",
                    leads=99,
                    payload={"account_id_with_id": "【小红书】未知(P999)"},
                ),
            ]
        )
        await db.commit()

        payload = await XHSProfileStatService(db).owner_rows(
            start_date="2026-06-01",
            end_date="2026-06-01",
        )
        assert payload["owner_rows"][0]["owner_name"] == "运营甲"
        assert payload["owner_rows"][0]["leads"] == 10
        assert payload["owner_rows"][0]["natural_opening_conversion_rate"] == 0.75
        assert payload["unmatched_accounts"] == ["未知账户"]
        assert payload["assignment_summary"] == {
            "assigned_owner_count": 1,
            "assigned_account_count": 1,
            "assigned_active_account_count": 1,
            "covered_owner_count": 1,
            "covered_account_count": 1,
            "unmatched_profile_account_count": 1,
        }

        restricted = await XHSProfileStatService(db).owner_rows(
            start_date="2026-06-01",
            end_date="2026-06-01",
            allowed_owner_ids={999},
        )
        assert restricted["owner_rows"] == []
        assert sorted(restricted["unmatched_accounts"]) == ["历史昵称(P100)", "未知账户"]
