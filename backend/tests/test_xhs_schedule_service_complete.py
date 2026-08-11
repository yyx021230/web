"""Scheduling configuration and execution contracts."""

from datetime import date, datetime

import pytest

from app.db.session import async_session as session_factory
from app.models.xhs_report import XHSReportDaily
from app.models.xhs_schedule_run_log import XHSScheduleRunLog
from app.services import xhs_schedule_service as module
from app.services.xhs_schedule_service import (
    ACCOUNT_DATA_SYNC_TASK,
    AD_DATA_REFRESH_TASK,
    AD_REPORT_PUBLISH_TASK,
    XHSScheduleService,
    _build_even_runner_assignments,
    _default_task_definition,
    _distribute_limit,
    _execute_account_data_sync,
    _execute_ad_data_refresh,
    _execute_ad_report_publish,
    _format_publish_message,
    _is_due,
    _normalize_run_time,
    _normalize_task_config,
    _report_conversion_value,
    _report_metric_value,
    _resolve_ad_refresh_date_range,
    _scope_label,
    _scheduled_time_today,
    trigger_xhs_scheduled_task,
)


def test_schedule_configuration_normalization_and_helpers(monkeypatch):
    assert _normalize_run_time(" 7:05 ") == "07:05"
    with pytest.raises(ValueError, match="HH:MM"):
        _normalize_run_time("25:99")
    now = datetime(2026, 6, 1, 12, 34, 56)
    assert _scheduled_time_today("08:30", now) == datetime(2026, 6, 1, 8, 30)
    assert _default_task_definition(ACCOUNT_DATA_SYNC_TASK)["run_time"] == "19:00"
    assert _default_task_definition(AD_DATA_REFRESH_TASK)["run_time"] == "06:30"
    assert _default_task_definition(AD_REPORT_PUBLISH_TASK)["run_time"] == "18:30"
    with pytest.raises(ValueError, match="未知"):
        _default_task_definition("bad")

    account = _normalize_task_config(
        ACCOUNT_DATA_SYNC_TASK,
        {
            "target_scope": "bad",
            "target_user_ids": [2, 2, -1],
            "post_sync_runner_ids": [4, 3, 4],
            "post_sync_limit_per_env": 999,
            "detail_sync_mode": "bad",
            "detail_total_limit": 5000,
            "detail_limit_per_runner": 0,
            "detail_pause_min_seconds": 1000,
            "detail_pause_max_seconds": 1,
            "detail_max_post_age_days": 9999,
            "content_tag_ai_origin_type": "bad",
            "content_tag_status": "",
            "content_tag_concurrency": 99,
        },
    )
    assert account["target_scope"] == "all"
    assert account["target_user_ids"] == [2]
    assert account["post_sync_runner_ids"] == [3, 4]
    assert account["post_sync_limit_per_env"] == 60
    assert account["detail_sync_mode"] == "unpublished_only"
    assert account["detail_total_limit"] == 1000
    assert account["detail_pause_min_seconds"] == account["detail_pause_max_seconds"] == 900
    assert account["content_tag_ai_origin_type"] == "all"
    assert account["content_tag_concurrency"] == 50

    fixed = _normalize_task_config(
        AD_DATA_REFRESH_TASK,
        {"date_range_mode": "fixed", "start_date": "2026-06-01", "end_date": "2026-06-03", "report_types": ["simple", "bad"]},
    )
    assert fixed["report_types"] == ["simple"]
    assert _resolve_ad_refresh_date_range(fixed) == (date(2026, 6, 1), date(2026, 6, 3), 3)
    with pytest.raises(ValueError, match="合法"):
        _normalize_task_config(AD_DATA_REFRESH_TASK, {"date_range_mode": "fixed", "start_date": "bad", "end_date": "bad"})
    with pytest.raises(ValueError, match="开始日期"):
        _normalize_task_config(AD_DATA_REFRESH_TASK, {"date_range_mode": "fixed", "start_date": "2026-06-03", "end_date": "2026-06-01"})
    with pytest.raises(ValueError, match="366"):
        _normalize_task_config(AD_DATA_REFRESH_TASK, {"date_range_mode": "fixed", "start_date": "2025-01-01", "end_date": "2026-06-01"})

    publish = _normalize_task_config(
        AD_REPORT_PUBLISH_TASK,
        {"account_ids": " b, a\na ", "report_types": ["bad"], "message_title": ""},
    )
    assert publish["account_ids"] == ["a", "b"]
    assert publish["report_types"] == ["simple", "standard"]
    assert publish["message_title"] == "今日小红书零跑汇总数据"
    with pytest.raises(ValueError, match="未知"):
        _normalize_task_config("bad", {})

    assert _scope_label("owner_users", [], {"target_user_ids": [1, 2]}) == "指定负责人(2人)"
    assert _scope_label("environment_ids", [1], {}) == "指定账号(1个)"
    assert _scope_label("all", [], {}) == "全量"
    assert _build_even_runner_assignments([], [1]) == {}
    assert _build_even_runner_assignments([10, 20], [1, 2, 3]) == {10: [1, 3], 20: [2]}
    assert _distribute_limit(5, []) == []
    assert _distribute_limit(5, [1, 2]) == [(1, 3), (2, 2)]
    assert _report_metric_value({"a": "bad", "b": "1,234.5%"}, "a", "b") == 1234.5
    assert _report_metric_value({"x": float("nan")}, "x") == 0
    assert _report_conversion_value({"valid_leads": 3}) == 3
    assert "单个线索成本：2.50" in _format_publish_message(
        "日报", {"impression": 10, "click": 2, "conversion": 1, "fee": 2.5, "conversion_cost": 2.5}
    )

    monkeypatch.setattr(module, "cst_now_naive", lambda: datetime(2026, 6, 10, 10, 0))
    start, end, days = _resolve_ad_refresh_date_range({"days": 3})
    assert (start, end, days) == (date(2026, 6, 7), date(2026, 6, 9), 3)
    assert _is_due(False, "09:00", None) is False
    assert _is_due(True, "11:00", None) is False
    assert _is_due(True, "09:00", None) is True
    assert _is_due(True, "09:00", datetime(2026, 6, 10, 2, 0)) is False


@pytest.mark.asyncio
async def test_schedule_settings_and_logs_round_trip(client):
    async with session_factory() as db:
        service = XHSScheduleService(db)
        settings_rows = await service.list_settings()
        assert [row["task_key"] for row in settings_rows] == [
            ACCOUNT_DATA_SYNC_TASK,
            AD_DATA_REFRESH_TASK,
            AD_REPORT_PUBLISH_TASK,
        ]
        assert await service.list_settings()  # existing rows path
        with pytest.raises(ValueError, match="不支持"):
            await service.get_row("bad")
        updated = await service.update_setting(
            AD_DATA_REFRESH_TASK,
            enabled=True,
            run_time="08:15",
            config={"days": 7},
        )
        assert updated["enabled"] is True and updated["run_time"] == "08:15"

        db.add(XHSScheduleRunLog(task_key=AD_DATA_REFRESH_TASK, source="manual", status="succeeded", message="ok"))
        await db.commit()
        logs = await service.list_run_logs(task_key=AD_DATA_REFRESH_TASK, limit=999)
        assert len(logs) == 1
        assert logs[0]["source"] == "manual"


class _FakeXHSService:
    def __init__(self, _session):
        self.calls = []

    async def sync_account_notes(self, **kwargs):
        self.calls.append(("posts", kwargs))
        return {"synced_accounts": 2, "created_notes": 3, "updated_notes": 4}

    async def sync_account_note_engagements(self, **kwargs):
        self.calls.append(("engagement", kwargs))
        return {"synced_accounts": 2, "metric_synced_notes": 5}

    async def sync_existing_account_note_stats(self, **kwargs):
        self.calls.append(("detail", kwargs))
        return {"synced_notes": 2, "failed_notes": 1}

    async def refresh_jg_report_cache(self, **kwargs):
        self.calls.append(("report", kwargs))
        if kwargs["report_type"] == "creative":
            return {"updated_accounts": 1, "updated_rows": 2, "errors": ["one"]}
        return {"updated_accounts": 2, "updated_rows": 3, "errors": []}


@pytest.mark.asyncio
async def test_execute_account_data_sync_all_steps(client, monkeypatch):
    monkeypatch.setattr(module, "XHSService", _FakeXHSService)
    monkeypatch.setattr(module, "_resolve_target_environment_ids", lambda *_args, **_kwargs: None)

    async def resolve_ids(*_args, **_kwargs):
        return [101, 102]

    async def load_admin(_db):
        return object()

    async def tag_batch(*_args, **_kwargs):
        return {"tagged_count": 2, "matched_count": 3}

    monkeypatch.setattr(module, "_resolve_target_environment_ids", resolve_ids)
    monkeypatch.setattr(module, "_load_system_admin_user", load_admin)
    monkeypatch.setattr(module, "_run_content_tag_batch", tag_batch)

    async with session_factory() as db:
        result = await _execute_account_data_sync(
            db,
            {
                "target_scope": "environment_ids",
                "target_environment_ids": [101, 102],
                "post_sync_enabled": True,
                "post_sync_runner_ids": [1, 2],
                "engagement_sync_enabled": True,
                "detail_sync_enabled": True,
                "detail_runner_ids": [1, 2],
                "detail_total_limit": 3,
                "content_tag_enabled": True,
            },
        )
        assert "主页帖子" in result
        assert "创作中心互动" in result
        assert "未同步策略" in result
        assert "内容打标 2/3" in result

        empty = await _execute_account_data_sync(db, {"post_sync_enabled": False})
        assert empty == "未启用任何账户同步步骤"
        with pytest.raises(ValueError, match="主页帖子同步"):
            await _execute_account_data_sync(db, {"post_sync_enabled": True, "post_sync_runner_ids": []})
        with pytest.raises(ValueError, match="未同步策略"):
            await _execute_account_data_sync(db, {"post_sync_enabled": False, "detail_sync_enabled": True, "detail_runner_ids": []})


@pytest.mark.asyncio
async def test_ad_refresh_records_success_and_failure(client, monkeypatch):
    monkeypatch.setattr(module, "XHSService", _FakeXHSService)
    events = []

    async def record(*args, **kwargs):
        events.append((args, kwargs))

    monkeypatch.setattr(module, "mark_report_refresh_running_safely", record)
    monkeypatch.setattr(module, "record_report_refresh_result_safely", record)
    monkeypatch.setattr(module, "finish_report_refresh_run_safely", record)
    async with session_factory() as db:
        message = await _execute_ad_data_refresh(
            db,
            {"date_range_mode": "fixed", "start_date": "2026-06-01", "end_date": "2026-06-01", "report_types": ["simple", "creative"]},
            history_run_id=9,
        )
        assert "更新 3 个账户、5 行，异常 1 条" in message
        assert events

    class _Failing(_FakeXHSService):
        async def refresh_jg_report_cache(self, **_kwargs):
            raise RuntimeError("refresh failed")

    monkeypatch.setattr(module, "XHSService", _Failing)
    async with session_factory() as db:
        with pytest.raises(RuntimeError, match="refresh failed"):
            await _execute_ad_data_refresh(
                db,
                {"date_range_mode": "fixed", "start_date": "2026-06-01", "end_date": "2026-06-01", "report_types": ["simple"]},
                history_run_id=10,
            )


@pytest.mark.asyncio
async def test_ad_report_publish_aggregates_and_zero_fills(client, monkeypatch):
    sent = []

    async def send(url, text):
        sent.append((url, text))

    async def refresh(*_args, **_kwargs):
        return "补刷完成"

    monkeypatch.setattr(module, "_send_feishu_robot_message", send)
    monkeypatch.setattr(module, "_execute_ad_data_refresh", refresh)
    monkeypatch.setattr(module, "cst_now_naive", lambda: datetime(2026, 6, 1, 18, 0))
    async with session_factory() as db:
        db.add_all(
            [
                XHSReportDaily(
                    report_type="simple",
                    account_id="a",
                    account_name="A",
                    report_date=date(2026, 6, 1),
                    campaign_id="1",
                    payload={"fee": "25.5", "impression": 100, "click": 20, "valid_leads": 2},
                ),
                XHSReportDaily(
                    report_type="standard",
                    account_id="a",
                    account_name="A",
                    report_date=date(2026, 6, 1),
                    campaign_id="2",
                    payload="not-json",
                ),
            ]
        )
        await db.commit()
        message = await _execute_ad_report_publish(
            db,
            {"webhook_url": "https://example.test/hook", "account_ids": ["a", "missing"], "refresh_before_send": True},
        )
        assert "账户 1/2 个" in message and "1 个账户当天无日报数据" in message and "补刷完成" in message
        assert "单个线索成本：12.75" in sent[0][1]
        with pytest.raises(ValueError, match="webhook"):
            await _execute_ad_report_publish(db, {"account_ids": ["a"]})
        with pytest.raises(ValueError, match="广告账户"):
            await _execute_ad_report_publish(db, {"webhook_url": "x"})


@pytest.mark.asyncio
async def test_trigger_rejects_duplicate_and_schedules_once(monkeypatch):
    scheduled = []

    def create_task(coro):
        scheduled.append(coro)
        coro.close()
        return object()

    monkeypatch.setattr(module.asyncio, "create_task", create_task)
    with pytest.raises(ValueError, match="不支持"):
        await trigger_xhs_scheduled_task("bad")
    module._RUNNING_TASK_KEYS.add(AD_DATA_REFRESH_TASK)
    try:
        assert await trigger_xhs_scheduled_task(AD_DATA_REFRESH_TASK) is False
    finally:
        module._RUNNING_TASK_KEYS.clear()
    assert await trigger_xhs_scheduled_task(AD_DATA_REFRESH_TASK) is True
    assert len(scheduled) == 1
