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


@pytest.mark.asyncio
async def test_report_refresh_resiliently_splits_timeout_ranges(client, monkeypatch):
    calls: list[tuple[str, str]] = []

    async def fetch_token(_account_id: str) -> str:
        return "token"

    async def fetch_rows(**kwargs):
        start = str(kwargs["start_date"])
        end = str(kwargs["end_date"])
        calls.append((start, end))
        if start != end:
            raise RuntimeError("noteOfflineReportApi timeout, rpc server")
        return [{"time": start, "campaign_id": f"campaign-{start}", "fee": 1}], 1

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

    async with async_session() as db:
        db.add(XHSReportToken(account_id="resilient-1", account_name="韧性账户", token_status="成功"))
        await db.commit()
        result = await XHSService(db).refresh_jg_report_cache(
            "standard_note",
            start_date="2026-08-01",
            end_date="2026-08-03",
            resilient=True,
            defer_post_processing=True,
        )

    assert result["updated_accounts"] == 1
    assert result["updated_rows"] == 3
    assert result["changed_rows"] == 3
    assert result["errors"] == []
    assert ("2026-08-01", "2026-08-03") in calls
    assert {item for item in calls if item[0] == item[1]} == {
        ("2026-08-01", "2026-08-01"),
        ("2026-08-02", "2026-08-02"),
        ("2026-08-03", "2026-08-03"),
    }


@pytest.mark.asyncio
async def test_scheduled_report_refresh_preserves_existing_rows_on_empty_response(client, monkeypatch):
    async def fetch_token(_account_id: str) -> str:
        return "token"

    async def fetch_rows(**_kwargs):
        return [], 0

    monkeypatch.setattr(XHSService, "_fetch_report_token", lambda self, account_id: fetch_token(account_id))
    monkeypatch.setattr(XHSService, "_fetch_report_rows", lambda self, **kwargs: fetch_rows(**kwargs))

    async with async_session() as db:
        db.add(XHSReportToken(account_id="empty-guard", account_name="空响应保护", token_status="成功"))
        db.add(
            XHSReportDaily(
                report_type="creative",
                account_id="empty-guard",
                account_name="空响应保护",
                report_date=date(2026, 8, 16),
                campaign_id="existing",
                payload={"time": "2026-08-16", "creative_id": "existing", "fee": 1},
            )
        )
        await db.commit()
        result = await XHSService(db).refresh_jg_report_cache(
            "creative",
            start_date="2026-08-16",
            end_date="2026-08-16",
            preserve_existing_on_empty=True,
            defer_post_processing=True,
        )
        existing = (
            await db.execute(
                select(XHSReportDaily).where(XHSReportDaily.account_id == "empty-guard")
            )
        ).scalar_one_or_none()

    assert existing is not None
    assert result["updated_accounts"] == 0
    assert result["changed_rows"] == 0
    assert len(result["preserved_empty_accounts"]) == 1
    assert "已保留 1 行现有数据" in result["errors"][0]


@pytest.mark.asyncio
async def test_report_timeout_does_not_overwrite_valid_token_status(client, monkeypatch):
    async def fetch_token(_account_id: str) -> str:
        return "token"

    async def fetch_rows(**_kwargs):
        raise RuntimeError("noteOfflineReportApi timeout, rpc server")

    monkeypatch.setattr(XHSService, "_fetch_report_token", lambda self, account_id: fetch_token(account_id))
    monkeypatch.setattr(XHSService, "_fetch_report_rows", lambda self, **kwargs: fetch_rows(**kwargs))

    async with async_session() as db:
        db.add(XHSReportToken(account_id="timeout-token", account_name="超时账户", token_status="成功"))
        await db.commit()
        result = await XHSService(db).refresh_jg_report_cache(
            "standard_note",
            start_date="2026-08-16",
            end_date="2026-08-16",
            defer_post_processing=True,
        )
        token_row = (
            await db.execute(
                select(XHSReportToken).where(XHSReportToken.account_id == "timeout-token")
            )
        ).scalar_one_or_none()

    assert result["updated_accounts"] == 0
    assert len(result["failed_accounts"]) == 1
    assert token_row is not None
    assert token_row.token_status == "成功"


@pytest.mark.asyncio
async def test_scheduled_report_refresh_skips_known_invalid_tokens(client, monkeypatch):
    fetched_accounts: list[str] = []

    async def fetch_token(account_id: str) -> str:
        fetched_accounts.append(account_id)
        return "token"

    async def fetch_rows(**_kwargs):
        return [], 0

    monkeypatch.setattr(XHSService, "_fetch_report_token", lambda self, account_id: fetch_token(account_id))
    monkeypatch.setattr(XHSService, "_fetch_report_rows", lambda self, **kwargs: fetch_rows(**kwargs))

    async with async_session() as db:
        db.add_all(
            [
                XHSReportToken(account_id="valid-token", account_name="有效账户", token_status="成功"),
                XHSReportToken(account_id="invalid-token", account_name="无效账户", token_status="失败"),
            ]
        )
        await db.commit()
        result = await XHSService(db).refresh_jg_report_cache(
            "simple",
            start_date="2026-08-16",
            end_date="2026-08-16",
            successful_tokens_only=True,
            defer_post_processing=True,
        )

    assert fetched_accounts == ["valid-token"]
    assert result["configured_accounts"] == 2
    assert result["attempted_accounts"] == 1
    assert [item["account_id"] for item in result["skipped_token_accounts"]] == ["invalid-token"]


@pytest.mark.asyncio
async def test_token_preflight_recovers_an_account_previously_marked_failed(client, monkeypatch):
    async def fetch_token(account_id: str) -> str:
        assert account_id == "recovered-token"
        return "fresh-token"

    monkeypatch.setattr(XHSService, "_fetch_report_token", lambda self, account_id: fetch_token(account_id))
    async with async_session() as db:
        db.add(
            XHSReportToken(
                account_id="recovered-token",
                account_name="已恢复账户",
                token="old-token",
                token_status="失败",
                token_message="旧授权失败",
            )
        )
        await db.commit()
        result = await XHSService(db).refresh_report_token_statuses()
        token_row = (
            await db.execute(
                select(XHSReportToken).where(XHSReportToken.account_id == "recovered-token")
            )
        ).scalar_one()

    assert result["configured_accounts"] == 1
    assert len(result["valid_accounts"]) == 1
    assert result["failed_accounts"] == []
    assert token_row.token == "fresh-token"
    assert token_row.token_status == "成功"
    assert token_row.token_message is None


@pytest.mark.asyncio
async def test_scheduled_reports_reuse_token_from_preflight(client, monkeypatch):
    token_fetch_calls: list[str] = []

    async def fetch_token(account_id: str) -> str:
        token_fetch_calls.append(account_id)
        return "unexpected-token"

    async def fetch_rows(**kwargs):
        assert kwargs["token"] == "cached-token"
        return [], 0

    monkeypatch.setattr(XHSService, "_fetch_report_token", lambda self, account_id: fetch_token(account_id))
    monkeypatch.setattr(XHSService, "_fetch_report_rows", lambda self, **kwargs: fetch_rows(**kwargs))
    async with async_session() as db:
        db.add(
            XHSReportToken(
                account_id="cached-token-account",
                account_name="缓存 Token 账户",
                token="cached-token",
                token_status="成功",
            )
        )
        await db.commit()
        result = await XHSService(db).refresh_jg_report_cache(
            "simple",
            start_date="2026-08-16",
            end_date="2026-08-16",
            successful_tokens_only=True,
            use_cached_tokens=True,
            defer_post_processing=True,
        )

    assert token_fetch_calls == []
    assert result["attempted_accounts"] == 1
    assert result["updated_accounts"] == 1
