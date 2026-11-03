"""Scheduled exclusions must not remove accounts or affect manual backfills."""

from datetime import date
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from app.db.session import async_session as session_factory
from app.models.xhs_report import XHSReportDaily, XHSReportToken
from app.services import xhs_schedule_service as schedule
from app.services.xhs_service import XHSService


@pytest.mark.parametrize("invalid", [None, "123", {}, [True], [""], ["abc"], [-1], [0], [1.5], ["１２３"]])
def test_invalid_exclusions_fail_closed(invalid):
    with pytest.raises(ValueError, match="ID"):
        schedule._normalize_task_config(schedule.AD_DATA_REFRESH_TASK, {"excluded_account_ids": invalid})


def test_exclusions_normalize_and_default():
    assert schedule._normalize_task_config(schedule.AD_DATA_REFRESH_TASK, {})["excluded_account_ids"] == []
    assert schedule._normalize_task_config(schedule.AD_DATA_REFRESH_TASK, {
        "excluded_account_ids": [" 123 ", 456, "123"],
    })["excluded_account_ids"] == ["123", "456"]


@pytest.mark.asyncio
async def test_legacy_settings_save_preserves_exclusions_and_explicit_empty_clears(client):
    async with session_factory() as db:
        service = schedule.XHSScheduleService(db)
        await service.update_setting(schedule.AD_DATA_REFRESH_TASK, enabled=False, run_time="06:30",
                                     config={"excluded_account_ids": ["123"]})
        await service.update_setting(schedule.AD_DATA_REFRESH_TASK, enabled=False, run_time="07:30",
                                     config={"days": 7})
        row = await service.get_row(schedule.AD_DATA_REFRESH_TASK)
        assert row.config["excluded_account_ids"] == ["123"]
        assert row.config["days"] == 7
        await service.update_setting(schedule.AD_DATA_REFRESH_TASK, enabled=False, run_time="07:30",
                                     config={"excluded_account_ids": []})
        assert row.config["excluded_account_ids"] == []


@pytest.mark.asyncio
async def test_scheduler_skips_tokens_and_all_five_reports_preserves_history_and_manual_access(client, monkeypatch):
    token_calls = []
    report_calls = []

    async def fetch_token(self, account_id):
        token_calls.append(account_id)
        return "mock-refreshed-token"

    async def fetch_rows(self, **kwargs):
        report_calls.append((kwargs["advertiser_id"], kwargs["api_path"]))
        return [], {}

    monkeypatch.setattr(XHSService, "_fetch_report_token", fetch_token)
    monkeypatch.setattr(XHSService, "_fetch_report_rows_resilient", fetch_rows)
    monkeypatch.setattr(XHSService, "finalize_jg_report_refresh", AsyncMock(return_value={"errors": []}))
    monkeypatch.setattr(schedule, "_validate_ad_refresh_consistency", AsyncMock(return_value={"errors": []}))
    for name in ("mark_report_refresh_running_safely", "record_report_refresh_result_safely", "finish_report_refresh_run_safely"):
        monkeypatch.setattr(schedule, name, AsyncMock())

    async with session_factory() as db:
        excluded = ["10176598", "10176597", "11336738", "11692529"]
        for i, account_id in enumerate([*excluded, "999999"]):
            db.add(XHSReportToken(account_id=account_id, account_name=f"test-{i}", token="mock-original",
                                  token_status="成功" if i % 2 == 0 else "失败", token_message="original"))
        for account_id in excluded:
            for report_type in schedule.AD_REPORT_TYPES:
                db.add(XHSReportDaily(account_id=account_id, account_name="retained", report_type=report_type,
                                      report_date=date(2026, 11, 2), campaign_id="old", payload={"fee": "12.34"}))
        await db.commit()
        before = list((await db.execute(select(XHSReportDaily))).scalars())
        before_values = [(r.id, r.payload.copy(), r.updated_at) for r in before]
        message = await schedule._execute_ad_data_refresh(db, {
            "excluded_account_ids": excluded, "date_range_mode": "fixed",
            "start_date": "2026-11-02", "end_date": "2026-11-02",
        })
        assert token_calls == ["999999"]
        assert len(report_calls) == 5
        assert {account_id for account_id, _ in report_calls} == {"999999"}
        assert len({path for _, path in report_calls}) == 5
        assert "按配置排除 4 个" in message
        assert "异常" not in message
        for i, account_id in enumerate(excluded):
            row = (await db.execute(select(XHSReportToken).where(XHSReportToken.account_id == account_id))).scalar_one()
            assert row.token == "mock-original"
            assert row.token_status == ("成功" if i % 2 == 0 else "失败")
            assert row.token_message == "original"
        db.expire_all()
        after = list((await db.execute(select(XHSReportDaily))).scalars())
        assert [(r.id, r.payload, r.updated_at) for r in after] == before_values

        # Explicit manual refresh does not inherit the scheduler-only exclusions.
        result = await XHSService(db).refresh_jg_report_cache(
            "simple", account_id=excluded[0], start_date="2026-11-02", end_date="2026-11-02",
            resilient=True, preserve_existing_on_empty=True, defer_post_processing=True,
        )
        assert result["attempted_accounts"] == 1
        assert token_calls[-1] == excluded[0]
        assert report_calls[-1][0] == excluded[0]


@pytest.mark.asyncio
async def test_excluding_all_accounts_never_calls_upstream(client, monkeypatch):
    fetch_token = AsyncMock(side_effect=AssertionError("excluded account reached upstream"))
    monkeypatch.setattr(XHSService, "_fetch_report_token", fetch_token)
    async with session_factory() as db:
        db.add(XHSReportToken(account_id="123", account_name="retained", token_status="成功"))
        await db.commit()
        service = XHSService(db)
        assert (await service.refresh_report_token_statuses(exclude_account_ids=["123"]))["configured_accounts"] == 0
        for report_type in schedule.AD_REPORT_TYPES:
            result = await service.refresh_jg_report_cache(report_type, start_date="2026-11-02", end_date="2026-11-02",
                                                          exclude_account_ids=["123"], defer_post_processing=True)
            assert result["attempted_accounts"] == 0
            assert not result["errors"]
        fetch_token.assert_not_called()
