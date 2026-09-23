from __future__ import annotations

import importlib.util
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.db.session import async_session
from app.models.xhs_environment import XHSEnvironment


SCRIPT_PATH = (
    Path(__file__).resolve().parents[2]
    / "scripts"
    / "windows"
    / "sync_xhs_creator_center.py"
)
SPEC = importlib.util.spec_from_file_location("windows_creator_center_sync", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


@pytest.mark.asyncio
async def test_resolves_test2_and_unique_business_account_by_xhs_id(client):
    async with async_session() as db:
        db.add_all(
            [
                XHSEnvironment(
                    id=901,
                    shop_id="runner-test2",
                    account_name="\u6d4b\u8bd52",
                    status="active",
                    is_sync_runner=True,
                ),
                XHSEnvironment(
                    id=902,
                    shop_id="business-902",
                    account_name="business-account",
                    xhs_account_id="red-902",
                    status="inactive",
                    is_sync_runner=False,
                ),
            ]
        )
        await db.commit()

        runner = await MODULE.resolve_runner(db, "\u6d4b\u8bd52")
        target = await MODULE.resolve_target(
            db,
            {"xhs_account_id": "red-902", "account_name": "nickname"},
        )

        assert runner.id == 901
        assert target.id == 902


@pytest.mark.asyncio
async def test_runner_must_be_explicitly_marked(client):
    async with async_session() as db:
        db.add(
            XHSEnvironment(
                id=903,
                shop_id="not-a-runner",
                account_name="\u6d4b\u8bd52",
                status="active",
                is_sync_runner=False,
            )
        )
        await db.commit()

        with pytest.raises(RuntimeError, match="not marked as a sync runner"):
            await MODULE.resolve_runner(db, "\u6d4b\u8bd52")


@pytest.mark.asyncio
async def test_auto_mapping_rejects_duplicate_business_accounts(client):
    async with async_session() as db:
        db.add_all(
            [
                XHSEnvironment(
                    id=904,
                    shop_id="duplicate-1",
                    account_name="duplicate-one",
                    xhs_account_id="same-red-id",
                    status="active",
                    is_sync_runner=False,
                ),
                XHSEnvironment(
                    id=905,
                    shop_id="duplicate-2",
                    account_name="duplicate-two",
                    xhs_account_id="same-red-id",
                    status="inactive",
                    is_sync_runner=False,
                ),
            ]
        )
        await db.commit()

        with pytest.raises(RuntimeError, match="maps to multiple business accounts"):
            await MODULE.resolve_target(
                db,
                {"xhs_account_id": "same-red-id", "account_name": "nickname"},
            )


@pytest.mark.asyncio
async def test_explicit_target_rejects_logged_in_identity_mismatch(client):
    async with async_session() as db:
        db.add(
            XHSEnvironment(
                id=906,
                shop_id="wrong-target",
                account_name="wrong-account",
                xhs_account_id="expected-red-id",
                status="active",
                is_sync_runner=False,
            )
        )
        await db.commit()

        with pytest.raises(RuntimeError, match="wrong account"):
            await MODULE.resolve_target(
                db,
                {"xhs_account_id": "actual-red-id", "account_name": "nickname"},
                target_environment_id=906,
            )


@pytest.mark.asyncio
async def test_full_run_imports_into_business_account_not_runner(client, monkeypatch):
    async with async_session() as db:
        db.add_all(
            [
                XHSEnvironment(
                    id=907,
                    shop_id="runner-full-run",
                    account_name="\u6d4b\u8bd52",
                    status="active",
                    is_sync_runner=True,
                ),
                XHSEnvironment(
                    id=908,
                    shop_id="business-full-run",
                    account_name="verified-business-account",
                    xhs_account_id="verified-red-id",
                    status="active",
                    is_sync_runner=False,
                ),
            ]
        )
        await db.commit()

    calls: dict[str, object] = {}

    @asynccontextmanager
    async def fake_lease(environment_id, operation):
        calls["lease"] = (environment_id, operation)
        yield SimpleNamespace(distributed=True, queue_wait_seconds=0.01)

    async def fake_acquire(service, preferred_environment_id, *, allow_fallback):
        runner = await service.get_environment(preferred_environment_id)
        return runner, "ws://browser/devtools/browser/test"

    async def fake_allocate(_service):
        return 18099

    async def fake_start(_service, ws_url, port):
        calls["start"] = (ws_url, port)
        return 4321

    async def fake_ready(_service, api_base=None, timeout=15):
        calls["ready"] = (api_base, timeout)

    async def fake_login(_service, api_base, *, probe=False):
        return {"is_logged_in": True}

    async def fake_identity(_service, api_base):
        return {
            "xhs_account_id": "verified-red-id",
            "account_name": "verified-nickname",
        }

    async def fake_download(_service, api_base):
        return b"workbook"

    def fake_parse(_service, content):
        return [{"title": "note-one"}]

    async def fake_import(_service, target, rows):
        calls["import_target_id"] = int(target.id)
        calls["import_rows"] = rows
        return {
            "created_notes": 1,
            "updated_notes": 0,
            "ambiguous_notes": 0,
            "metric_synced_notes": 1,
            "total_notes": 1,
        }

    async def fake_stop_mcp(_service, pid):
        calls["stopped_mcp"] = pid

    async def fake_stop_browser(_service, shop_id):
        calls["stopped_browser"] = shop_id

    monkeypatch.setattr(MODULE.yundeng_sync_coordinator, "lease", fake_lease)
    monkeypatch.setattr(MODULE.XHSService, "_acquire_ready_sync_browser_ws_with_fallback", fake_acquire)
    monkeypatch.setattr(MODULE.XHSService, "_allocate_free_port", fake_allocate)
    monkeypatch.setattr(MODULE.XHSService, "_start_mcp", fake_start)
    monkeypatch.setattr(MODULE.XHSService, "_wait_mcp_ready", fake_ready)
    monkeypatch.setattr(MODULE.XHSService, "_get_mcp_login_status", fake_login)
    monkeypatch.setattr(MODULE.XHSService, "_get_mcp_current_profile_identity", fake_identity)
    monkeypatch.setattr(MODULE.XHSService, "_download_creator_stats_excel", fake_download)
    monkeypatch.setattr(MODULE.XHSService, "_parse_creator_stats_excel", fake_parse)
    monkeypatch.setattr(MODULE.XHSService, "_import_creator_note_stats_rows", fake_import)
    monkeypatch.setattr(MODULE.XHSService, "_stop_mcp", fake_stop_mcp)
    monkeypatch.setattr(MODULE.XHSService, "_stop_browser", fake_stop_browser)

    result = await MODULE.run(
        SimpleNamespace(
            runner_name="\u6d4b\u8bd52",
            target_environment_id=None,
            target_account_name=None,
            identity_only=False,
            export_only=False,
            export_directory="/unused",
            keep_browser_open=False,
        )
    )

    assert result["success"] is True
    assert result["exported_rows"] == 1
    assert calls["lease"] == (907, "standalone_creator_center")
    assert calls["import_target_id"] == 908
    assert calls["stopped_mcp"] == 4321
    assert calls["stopped_browser"] == "runner-full-run"


@pytest.mark.asyncio
async def test_identity_only_reports_unmapped_login_without_writing(client, monkeypatch):
    async with async_session() as db:
        db.add(
            XHSEnvironment(
                id=909,
                shop_id="runner-unmapped",
                account_name="\u6d4b\u8bd52",
                status="active",
                is_sync_runner=True,
            )
        )
        await db.commit()

    calls: dict[str, object] = {}

    @asynccontextmanager
    async def fake_lease(environment_id, operation):
        yield SimpleNamespace(distributed=True, queue_wait_seconds=0.0)

    async def fake_acquire(service, preferred_environment_id, *, allow_fallback):
        runner = await service.get_environment(preferred_environment_id)
        return runner, "ws://browser/devtools/browser/unmapped"

    async def fake_allocate(_service):
        return 18100

    async def fake_start(_service, ws_url, port):
        return 4322

    async def fake_noop(*_args, **_kwargs):
        return None

    async def fake_login(_service, api_base, *, probe=False):
        return {"is_logged_in": True}

    async def fake_identity(_service, api_base):
        return {
            "xhs_account_id": "unmapped-red-id",
            "account_name": "unmapped-nickname",
        }

    async def fake_stop_mcp(_service, pid):
        calls["stopped_mcp"] = pid

    async def fake_stop_browser(_service, shop_id):
        calls["stopped_browser"] = shop_id

    monkeypatch.setattr(MODULE.yundeng_sync_coordinator, "lease", fake_lease)
    monkeypatch.setattr(MODULE.XHSService, "_acquire_ready_sync_browser_ws_with_fallback", fake_acquire)
    monkeypatch.setattr(MODULE.XHSService, "_allocate_free_port", fake_allocate)
    monkeypatch.setattr(MODULE.XHSService, "_start_mcp", fake_start)
    monkeypatch.setattr(MODULE.XHSService, "_wait_mcp_ready", fake_noop)
    monkeypatch.setattr(MODULE.XHSService, "_get_mcp_login_status", fake_login)
    monkeypatch.setattr(MODULE.XHSService, "_get_mcp_current_profile_identity", fake_identity)
    monkeypatch.setattr(MODULE.XHSService, "_stop_mcp", fake_stop_mcp)
    monkeypatch.setattr(MODULE.XHSService, "_stop_browser", fake_stop_browser)

    result = await MODULE.run(
        SimpleNamespace(
            runner_name="\u6d4b\u8bd52",
            target_environment_id=None,
            target_account_name=None,
            identity_only=True,
            export_only=False,
            export_directory="/unused",
            keep_browser_open=False,
        )
    )

    assert result["success"] is True
    assert result["mapping_verified"] is False
    assert result["database_changed"] is False
    assert result["logged_in_identity"]["account_name"] == "unmapped-nickname"
    assert calls["stopped_mcp"] == 4322
    assert calls["stopped_browser"] == "runner-unmapped"


@pytest.mark.asyncio
async def test_export_only_saves_workbook_without_target_or_database_import(
    client,
    monkeypatch,
    tmp_path,
):
    async with async_session() as db:
        db.add(
            XHSEnvironment(
                id=910,
                shop_id="runner-export-only",
                account_name="\u6d4b\u8bd52",
                status="active",
                is_sync_runner=True,
            )
        )
        await db.commit()

    calls: dict[str, object] = {}

    @asynccontextmanager
    async def fake_lease(environment_id, operation):
        yield SimpleNamespace(distributed=True, queue_wait_seconds=0.0)

    async def fake_acquire(service, preferred_environment_id, *, allow_fallback):
        runner = await service.get_environment(preferred_environment_id)
        return runner, "ws://browser/devtools/browser/export-only"

    async def fake_allocate(_service):
        return 18101

    async def fake_start(_service, ws_url, port):
        return 4323

    async def fake_noop(*_args, **_kwargs):
        return None

    async def fake_login(_service, api_base, *, probe=False):
        return {"is_logged_in": True}

    async def fake_identity(_service, api_base):
        return {
            "xhs_account_id": "export-red-id",
            "account_name": "export-nickname",
        }

    async def fake_download(_service, api_base):
        return b"valid-workbook-content"

    def fake_parse(_service, content):
        return [{"title": "exported-note"}]

    async def fail_import(*_args, **_kwargs):
        raise AssertionError("export-only must not call the database importer")

    async def fake_stop_mcp(_service, pid):
        calls["stopped_mcp"] = pid

    async def fake_stop_browser(_service, shop_id):
        calls["stopped_browser"] = shop_id

    monkeypatch.setattr(MODULE.yundeng_sync_coordinator, "lease", fake_lease)
    monkeypatch.setattr(MODULE.XHSService, "_acquire_ready_sync_browser_ws_with_fallback", fake_acquire)
    monkeypatch.setattr(MODULE.XHSService, "_allocate_free_port", fake_allocate)
    monkeypatch.setattr(MODULE.XHSService, "_start_mcp", fake_start)
    monkeypatch.setattr(MODULE.XHSService, "_wait_mcp_ready", fake_noop)
    monkeypatch.setattr(MODULE.XHSService, "_get_mcp_login_status", fake_login)
    monkeypatch.setattr(MODULE.XHSService, "_get_mcp_current_profile_identity", fake_identity)
    monkeypatch.setattr(MODULE.XHSService, "_download_creator_stats_excel", fake_download)
    monkeypatch.setattr(MODULE.XHSService, "_parse_creator_stats_excel", fake_parse)
    monkeypatch.setattr(MODULE.XHSService, "_import_creator_note_stats_rows", fail_import)
    monkeypatch.setattr(MODULE.XHSService, "_stop_mcp", fake_stop_mcp)
    monkeypatch.setattr(MODULE.XHSService, "_stop_browser", fake_stop_browser)

    result = await MODULE.run(
        SimpleNamespace(
            runner_name="\u6d4b\u8bd52",
            target_environment_id=None,
            target_account_name=None,
            identity_only=False,
            export_only=True,
            export_directory=str(tmp_path),
            keep_browser_open=False,
        )
    )

    saved_path = Path(result["saved_path"])
    assert result["success"] is True
    assert result["database_changed"] is False
    assert result["exported_rows"] == 1
    assert saved_path.read_bytes() == b"valid-workbook-content"
    assert calls["stopped_mcp"] == 4323
    assert calls["stopped_browser"] == "runner-export-only"
