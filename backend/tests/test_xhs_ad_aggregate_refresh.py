"""Materialized advertising aggregate refresh contracts."""

from datetime import date

import pytest
from sqlalchemy import func, select

from app.db.session import async_session as session_factory
from app.models.xhs_report import (
    XHSAdStatsDailyAccount,
    XHSAdStatsDailyBrand,
    XHSAdStatsDailyBuyer,
    XHSAdStatsDailyContentTag,
    XHSAdStatsDailyNote,
    XHSReportDaily,
)
from app.services import xhs_service as module
from app.services.xhs_service import XHSService


class _Catalog:
    def __init__(self, _db):
        pass

    async def brands(self):
        return ["零跑汽车", "比亚迪"]


@pytest.mark.asyncio
async def test_refresh_summary_aggregates_accounts_buyers_and_brands(client, monkeypatch):
    monkeypatch.setattr(module, "VehicleCatalogService", _Catalog)
    day = date(2026, 6, 1)
    async with session_factory() as db:
        db.add_all(
            [
                XHSReportDaily(
                    report_type="simple",
                    account_id="a1",
                    account_name="广告账户一",
                    report_date=day,
                    campaign_id="c1",
                    payload={
                        "fee": "10.5",
                        "impression": "100",
                        "click": "20",
                        "message_consult": "4",
                        "initiative_message": "3",
                        "msg_leads_num": "2",
                        "like": "2",
                        "collect": "1",
                        "comment": "1",
                        "share": "1",
                        "campaign_name": "零跑汽车#价格政策",
                    },
                ),
                XHSReportDaily(
                    report_type="simple",
                    account_id="a1",
                    account_name="广告账户一",
                    report_date=day,
                    campaign_id="c2",
                    payload={
                        "fee": 9.5,
                        "impression": 50,
                        "click": 10,
                        "msg_leads_num": 1,
                        "campaign_name": "零跑汽车#车型介绍",
                    },
                ),
                XHSReportDaily(
                    report_type="simple",
                    account_id="a2",
                    account_name="广告账户二",
                    report_date=day,
                    campaign_id="c3",
                    payload={"fee": 5, "impression": 20, "click": 2, "campaign_name": "比亚迪#优惠"},
                ),
            ]
        )
        await db.commit()
        service = XHSService(db)

        async def assignments():
            return {
                "a1": {"buyer_user_id": 7, "buyer_name": "投手甲", "account_name": "广告账户一"},
                "a2": {"buyer_user_id": 7, "buyer_name": "投手甲", "account_name": "广告账户二"},
            }

        monkeypatch.setattr(service, "_xhs_ad_buyer_assignments", assignments)
        result = await service.refresh_xhs_ad_aggregates(report_type="simple", start_date=day, end_date=day)
        assert result == {"account": 2, "buyer": 1, "brand": 2, "note": 0, "content_tag": 0}

        accounts = (await db.execute(select(XHSAdStatsDailyAccount).order_by(XHSAdStatsDailyAccount.account_id))).scalars().all()
        assert len(accounts) == 2
        assert accounts[0].fee == 20
        assert accounts[0].impression == 150
        assert accounts[0].conversion == 3
        buyers = (await db.execute(select(XHSAdStatsDailyBuyer))).scalars().all()
        assert len(buyers) == 1 and buyers[0].account_count == 2 and buyers[0].buyer_name == "投手甲"
        brands = (await db.execute(select(XHSAdStatsDailyBrand).order_by(XHSAdStatsDailyBrand.brand))).scalars().all()
        assert {row.brand for row in brands} == {"比亚迪", "零跑汽车"}

        # Account-scoped refresh must not rebuild the cross-account buyer table.
        scoped = await service.refresh_xhs_ad_aggregates(
            report_type="simple", start_date=day, end_date=day, account_id="a1"
        )
        assert scoped["account"] == 1 and scoped["buyer"] == 0
        assert (await db.scalar(select(func.count(XHSAdStatsDailyBuyer.id)))) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("report_type", ["simple_note", "standard_note", "creative"])
async def test_refresh_note_and_content_tag_aggregates(client, monkeypatch, report_type):
    monkeypatch.setattr(module, "VehicleCatalogService", _Catalog)
    day = date(2026, 6, 2)
    async with session_factory() as db:
        db.add_all(
            [
                XHSReportDaily(
                    report_type=report_type,
                    account_id="a1",
                    account_name="广告账户一",
                    report_date=day,
                    campaign_id="row1",
                    payload={
                        "note_material": "note-1",
                        "note_id": "note-1",
                        "note_title": "零跑 C10 降价",
                        "fee": 10,
                        "impression": 100,
                        "click": 20,
                        "message_consult": 4,
                        "initiative_message": 3,
                        "msg_leads_num": 2,
                        "interaction": 5,
                    },
                ),
                XHSReportDaily(
                    report_type=report_type,
                    account_id="a1",
                    account_name="广告账户一",
                    report_date=day,
                    campaign_id="row2",
                    payload={
                        "note_material": "note-1",
                        "note_id": "note-1",
                        "note_title": "零跑 C10 降价",
                        "fee": 5,
                        "click": 5,
                        "msg_leads_num": 1,
                    },
                ),
                XHSReportDaily(
                    report_type=report_type,
                    account_id="a1",
                    account_name="广告账户一",
                    report_date=day,
                    campaign_id="missing-note",
                    payload={"fee": 99},
                ),
            ]
        )
        await db.commit()
        service = XHSService(db)

        async def assignments():
            return {"a1": {"buyer_user_id": 8, "buyer_name": "投手乙"}}

        async def metadata(note_ids):
            assert note_ids == {"note-1"}
            return {
                "note-1": {
                    "primary": "价格政策",
                    "secondary": "",
                    "owner_name": "专业号甲",
                }
            }

        monkeypatch.setattr(service, "_xhs_ad_buyer_assignments", assignments)
        monkeypatch.setattr(service, "_xhs_ad_note_metadata", metadata)
        result = await service.refresh_xhs_ad_aggregates(
            report_type=report_type,
            start_date=day,
            end_date=day,
        )
        assert result["note"] == 1 and result["content_tag"] == 1
        note = (await db.execute(select(XHSAdStatsDailyNote))).scalar_one()
        assert note.fee == 15 and note.conversion == 3 and note.row_count == 2
        assert note.xhs_account_name == "专业号甲"
        tag = (await db.execute(select(XHSAdStatsDailyContentTag))).scalar_one()
        assert tag.primary_content_tag == "价格政策"
        assert tag.secondary_content_tag == "未打二级标签"


@pytest.mark.asyncio
async def test_refresh_aggregates_rejects_unknown_report_without_writes(client):
    async with session_factory() as db:
        result = await XHSService(db).refresh_xhs_ad_aggregates(
            report_type="unknown",
            start_date=date(2026, 6, 1),
            end_date=date(2026, 6, 2),
        )
        assert result == {"account": 0, "buyer": 0, "brand": 0, "note": 0, "content_tag": 0}
