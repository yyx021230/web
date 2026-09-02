"""Scheduling configuration and execution contracts."""

from datetime import date, datetime, timedelta

import pytest

from app.db.session import async_session as session_factory
from app.models.xhs_environment import XHSEnvironment
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
    _partition_creator_sync_targets,
    _report_conversion_value,
    _report_metric_value,
    _resolve_ad_refresh_date_range,
    _resolve_target_environment_ids,
    _scope_label,
    _scheduled_time_today,
    due_xhs_schedule_task_keys,
    trigger_xhs_scheduled_task,
)


@pytest.mark.asyncio
async def test_account_schedule_excludes_sync_runners_and_incomplete_accounts(client):
    async with session_factory() as db:
        complete = XHSEnvironment(
            shop_id="creator-complete",
            account_name="配置完整账号",
            xhs_account_id="123456789",
            login_phone_number="+86 190-6712-5562",
            xhs_account_type="enterprise_professional",
            is_sync_runner=False,
            status="active",
        )
        legacy_runner = XHSEnvironment(
            shop_id="legacy-test-runner",
            account_name="测试2",
            is_sync_runner=False,
            status="active",
        )
        incomplete = XHSEnvironment(
            shop_id="creator-incomplete",
            account_name="配置缺失账号",
            xhs_account_id="",
            login_phone_number="",
            xhs_account_type="enterprise_employee",
            is_sync_runner=False,
            status="active",
        )
        db.add_all([complete, legacy_runner, incomplete])
        await db.commit()
        await db.refresh(complete)
        await db.refresh(legacy_runner)
        await db.refresh(incomplete)

        resolved = await _resolve_target_environment_ids(
            db,
            {
                "target_scope": "environment_ids",
                "target_environment_ids": [complete.id, legacy_runner.id, incomplete.id],
            },
        )
        eligible, skipped, names = await _partition_creator_sync_targets(db, resolved)

    assert int(legacy_runner.id) not in resolved
    assert eligible == [int(complete.id)]
    assert names[int(complete.id)] == "配置完整账号"
    assert len(skipped) == 1
    assert skipped[0]["environment_id"] == int(incomplete.id)
    assert "小红书ID" in skipped[0]["reason"]
    assert "登录手机号" in skipped[0]["reason"]


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
            "yundeng_sync_concurrency": 99,
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
    assert account["yundeng_sync_concurrency"] == 5
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


@pytest.mark.asyncio
async def test_due_schedule_reconciles_stale_running_logs(client):
    async with session_factory() as db:
        service = XHSScheduleService(db)
        row = await service.get_row(AD_DATA_REFRESH_TASK)
        row.last_status = "running"
        stale = XHSScheduleRunLog(
            task_key=AD_DATA_REFRESH_TASK,
            source="schedule",
            status="running",
            message="任务执行中",
            started_at=datetime.utcnow() - timedelta(hours=13),
        )
        db.add(stale)
        await db.commit()

        await due_xhs_schedule_task_keys(db)
        await db.refresh(stale)
        await db.refresh(row)

        assert stale.status == "failed"
        assert stale.finished_at is not None
        assert row.last_status == "failed"


class _FakeXHSService:
    observed_calls: list[str] = []

    def __init__(self, _session):
        self.calls = []

    async def refresh_report_token_statuses(self):
        self.calls.append(("refresh_tokens", {}))
        return {
            "configured_accounts": 2,
            "valid_accounts": [
                {"account_id": "a", "account_name": "账户A"},
                {"account_id": "b", "account_name": "账户B"},
            ],
            "failed_accounts": [],
            "transient_errors": [],
        }

    async def sync_account_notes(self, **kwargs):
        self.observed_calls.append("posts")
        self.calls.append(("posts", kwargs))
        return {
            "synced_accounts": 2,
            "created_notes": 0,
            "updated_notes": 4,
            "deferred_homepage_notes": 3,
        }

    async def sync_account_note_engagements(self, **kwargs):
        self.observed_calls.append("engagement")
        self.calls.append(("engagement", kwargs))
        return {"synced_accounts": 2, "metric_synced_notes": 5}

    async def sync_existing_account_note_stats(self, **kwargs):
        self.observed_calls.append("detail")
        self.calls.append(("detail", kwargs))
        return {"synced_notes": 2, "failed_notes": 1}

    async def refresh_jg_report_cache(self, **kwargs):
        self.calls.append(("report", kwargs))
        if kwargs["report_type"] == "creative":
            return {
                "updated_accounts": 1,
                "attempted_accounts": 2,
                "updated_rows": 2,
                "changed_rows": 1,
                "errors": ["one"],
            }
        return {
            "updated_accounts": 2,
            "attempted_accounts": 2,
            "updated_rows": 3,
            "changed_rows": 2,
            "errors": [],
        }

    async def finalize_jg_report_refresh(self, **kwargs):
        self.calls.append(("finalize_reports", kwargs))
        return {"promoted": {}, "aggregates": {}, "errors": []}


@pytest.mark.asyncio
async def test_execute_account_data_sync_all_steps(client, monkeypatch):
    _FakeXHSService.observed_calls = []
    monkeypatch.setattr(module, "XHSService", _FakeXHSService)
    monkeypatch.setattr(module, "_resolve_target_environment_ids", lambda *_args, **_kwargs: None)

    async def resolve_ids(*_args, **_kwargs):
        return [101, 102]

    async def load_admin(_db):
        return object()

    async def partition_targets(_db, environment_ids):
        assert environment_ids == [101, 102]
        return [101, 102], [], {101: "账号101", 102: "账号102"}

    async def tag_batch(*_args, **_kwargs):
        return {"tagged_count": 2, "matched_count": 3}

    monkeypatch.setattr(module, "_resolve_target_environment_ids", resolve_ids)
    monkeypatch.setattr(module, "_load_system_admin_user", load_admin)
    monkeypatch.setattr(module, "_partition_creator_sync_targets", partition_targets)
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
        assert "补齐 4 条" in result
        assert "待创作者中心建档 3 条" in result
        assert "创作者中心首轮成功 2/2" in result
        assert "未同步策略" in result
        assert "内容打标 2/3" in result
        assert _FakeXHSService.observed_calls[:2] == ["engagement", "posts"]
        assert all(call == "detail" for call in _FakeXHSService.observed_calls[2:])

        empty = await _execute_account_data_sync(db, {"post_sync_enabled": False})
        assert empty == "未启用任何账户同步步骤"
        with pytest.raises(ValueError, match="主页帖子同步"):
            await _execute_account_data_sync(db, {"post_sync_enabled": True, "post_sync_runner_ids": []})
        with pytest.raises(ValueError, match="未同步策略"):
            await _execute_account_data_sync(db, {"post_sync_enabled": False, "detail_sync_enabled": True, "detail_runner_ids": []})


@pytest.mark.asyncio
async def test_creator_schedule_retries_only_first_pass_failures(client, monkeypatch):
    class RetryingCreatorService:
        target_batches: list[list[int]] = []

        def __init__(self, _session):
            pass

        async def sync_account_note_engagements(self, **kwargs):
            target_ids = list(kwargs["target_environment_ids"])
            self.target_batches.append(target_ids)
            if len(self.target_batches) == 1:
                return {
                    "synced_accounts": 1,
                    "created_notes": 2,
                    "updated_notes": 3,
                    "failed_accounts": [
                        {"environment_id": 102, "account_name": "账号102", "error": "首轮失败"},
                    ],
                }
            return {
                "synced_accounts": 1,
                "created_notes": 1,
                "updated_notes": 4,
            }

    async def resolve_ids(*_args, **_kwargs):
        return [101, 102, 103]

    async def partition_targets(_db, environment_ids):
        assert environment_ids == [101, 102, 103]
        return (
            [101, 102],
            [{"environment_id": 103, "account_name": "配置缺失账号", "reason": "未配置完整：登录手机号"}],
            {101: "账号101", 102: "账号102", 103: "配置缺失账号"},
        )

    async def load_admin(_db):
        return object()

    RetryingCreatorService.target_batches = []
    monkeypatch.setattr(module, "XHSService", RetryingCreatorService)
    monkeypatch.setattr(module, "_resolve_target_environment_ids", resolve_ids)
    monkeypatch.setattr(module, "_partition_creator_sync_targets", partition_targets)
    monkeypatch.setattr(module, "_load_system_admin_user", load_admin)

    async with session_factory() as db:
        result = await _execute_account_data_sync(
            db,
            {
                "post_sync_enabled": False,
                "engagement_sync_enabled": True,
                "yundeng_sync_concurrency": 5,
            },
        )

    assert RetryingCreatorService.target_batches == [[101, 102], [102]]
    assert "首轮成功 1/2" in result
    assert "失败重试成功 1/1" in result
    assert "最终失败 0" in result
    assert "配置不全跳过 1" in result
    assert "新增 3 条，更新 7 条" in result


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
        assert "成功 3/4 个账户报表组合" in message
        assert "读取 5 行，实际变更 3 行，异常 1 条" in message
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
async def test_ad_refresh_rebuilds_aggregates_even_when_raw_rows_are_unchanged(client, monkeypatch):
    class UnchangedReportService:
        finalize_calls: list[dict] = []

        def __init__(self, _session):
            pass

        async def refresh_report_token_statuses(self):
            return {
                "configured_accounts": 1,
                "valid_accounts": [{"account_id": "a", "account_name": "账户A"}],
                "failed_accounts": [],
                "transient_errors": [],
            }

        async def refresh_jg_report_cache(self, **kwargs):
            return {
                "updated_accounts": 1,
                "attempted_accounts": 1,
                "updated_rows": 1,
                "changed_rows": 0,
                "errors": [],
            }

        async def finalize_jg_report_refresh(self, **kwargs):
            self.finalize_calls.append(kwargs)
            return {"promoted": {}, "aggregates": {}, "errors": []}

    UnchangedReportService.finalize_calls = []
    monkeypatch.setattr(module, "XHSService", UnchangedReportService)
    async with session_factory() as db:
        message = await _execute_ad_data_refresh(
            db,
            {
                "date_range_mode": "fixed",
                "start_date": "2026-06-01",
                "end_date": "2026-06-01",
                "report_types": ["simple"],
            },
        )

    assert "数据一致性验收通过" in message
    assert len(UnchangedReportService.finalize_calls) == 1
    assert UnchangedReportService.finalize_calls[0]["report_types"] == ["simple"]


@pytest.mark.asyncio
async def test_schedule_claim_is_persisted_before_long_task_starts(client, monkeypatch):
    observed_last_run_at: list[datetime | None] = []

    async with session_factory() as db:
        await XHSScheduleService(db).update_setting(
            AD_DATA_REFRESH_TASK,
            enabled=True,
            run_time="06:30",
            config={
                "date_range_mode": "fixed",
                "start_date": "2026-06-01",
                "end_date": "2026-06-01",
                "report_types": ["simple"],
            },
        )

    async def inspect_durable_claim(_session, _config, *, history_run_id=None):
        async with session_factory() as verification_db:
            row = await XHSScheduleService(verification_db).get_row(AD_DATA_REFRESH_TASK)
            observed_last_run_at.append(row.last_run_at)
        return "刷新完成，数据一致性验收通过"

    monkeypatch.setattr(module, "_execute_ad_data_refresh", inspect_durable_claim)
    await module._run_task(AD_DATA_REFRESH_TASK, "schedule", session_factory)

    assert len(observed_last_run_at) == 1
    assert observed_last_run_at[0] is not None


@pytest.mark.asyncio
async def test_consistency_check_ignores_reports_not_selected_for_refresh(client):
    async with session_factory() as db:
        db.add(
            XHSReportDaily(
                report_type="creative",
                account_id="creative-only",
                account_name="不在本次范围",
                report_date=date(2026, 6, 1),
                campaign_id="creative-1",
                payload={"time": "2026-06-01", "creative_id": "creative-1"},
            )
        )
        await db.commit()
        result = await module._validate_ad_refresh_consistency(
            db,
            start_d=date(2026, 6, 1),
            end_d=date(2026, 6, 1),
            report_types=["simple"],
        )

    assert result["errors"] == []


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
