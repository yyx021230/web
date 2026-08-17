from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy import select

from app.db.session import async_session
from app.models.xhs_report import XHSReportDaily, XHSReportToken
from app.services.xhs_service import XHSService


@pytest.mark.asyncio
async def test_report_refresh_only_rewrites_changed_rows(client, monkeypatch):
    source_rows = [{"time": "2026-08-16", "campaign_id": "c1", "fee": 1}]
    aggregate_calls: list[str] = []

    async def fetch_token(_account_id: str) -> str:
        return "token"

    async def fetch_rows(**_kwargs):
        return list(source_rows), len(source_rows)

    async def refresh_aggregates(**kwargs):
        aggregate_calls.append(str(kwargs["report_type"]))
        return {"account": 1}

    async def backfill(**_kwargs):
        return {"updated": 0}

    monkeypatch.setattr(XHSService, "_fetch_report_token", lambda self, account_id: fetch_token(account_id))
    monkeypatch.setattr(XHSService, "_fetch_report_rows", lambda self, **kwargs: fetch_rows(**kwargs))
    monkeypatch.setattr(
        XHSService,
        "_normalize_jg_report_row",
        lambda self, _report_type, row, **_kwargs: dict(row),
    )
    monkeypatch.setattr(
        XHSService,
        "_report_row_campaign_key",
        lambda self, _report_type, payload: str(payload["campaign_id"]),
    )
    monkeypatch.setattr(XHSService, "refresh_xhs_ad_aggregates", lambda self, **kwargs: refresh_aggregates(**kwargs))
    monkeypatch.setattr(XHSService, "backfill_promoted_flags_from_reports", lambda self, **kwargs: backfill(**kwargs))

    async with async_session() as db:
        db.add(XHSReportToken(account_id="a1", account_name="账户一"))
        await db.commit()
        service = XHSService(db)

        first = await service.refresh_jg_report_cache(
            "simple",
            start_date="2026-08-16",
            end_date="2026-08-16",
        )
        second = await service.refresh_jg_report_cache(
            "simple",
            start_date="2026-08-16",
            end_date="2026-08-16",
        )

        assert first["updated_rows"] == 1
        assert first["changed_rows"] == 1
        assert second["updated_rows"] == 1
        assert second["changed_rows"] == 0
        assert aggregate_calls == ["simple"]

        source_rows[0] = {"time": "2026-08-16", "campaign_id": "c1", "fee": 2}
        changed = await service.refresh_jg_report_cache(
            "simple",
            start_date="2026-08-16",
            end_date="2026-08-16",
        )
        assert changed["changed_rows"] == 1

        source_rows.clear()
        emptied = await service.refresh_jg_report_cache(
            "simple",
            start_date="2026-08-16",
            end_date="2026-08-16",
        )
        assert emptied["updated_rows"] == 0
        assert emptied["changed_rows"] == 1
        assert (
            await db.execute(
                select(XHSReportDaily).where(
                    XHSReportDaily.account_id == "a1",
                    XHSReportDaily.report_date == date(2026, 8, 16),
                )
            )
        ).scalar_one_or_none() is None
