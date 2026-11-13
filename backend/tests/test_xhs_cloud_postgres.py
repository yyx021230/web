"""Opt-in real PostgreSQL transaction tests against a disposable local database."""
from __future__ import annotations

import asyncio
from datetime import datetime
import os
import uuid

import pytest
from sqlalchemy import func, select
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.adapters.phone_cloud_xhs_data import CloudDataError
from app.config import settings
from app.models.xhs_cloud_import import XHSCloudImport
from app.models.xhs_account_note import XHSAccountNote
from app.models.xhs_environment import XHSEnvironment
from app.services.xhs_cloud_data_service import XHSCloudDataService
from app.services.xhs_service import XHSService
import app.services.xhs_cloud_data_service as cloud


@pytest.mark.asyncio
async def test_postgres_concurrent_idempotency_and_retained_failed_apply(monkeypatch):
    dsn = os.environ.get("XHS_CLOUD_TEST_POSTGRES_URL")
    if not dsn:
        pytest.skip("requires an explicitly provisioned disposable local PostgreSQL database")
    url = make_url(dsn)
    assert url.host == "127.0.0.1" and url.database.startswith("xhs_cloud_test_"), "Refuse non-test database"
    engine = create_async_engine(dsn)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    now = datetime(2026, 11, 12, 4)
    suffix = uuid.uuid4().hex
    run_a, run_b = uuid.uuid4().hex * 2, uuid.uuid4().hex * 2
    monkeypatch.setattr(cloud, "utc_now_naive", lambda: now)
    monkeypatch.setattr(settings, "phone_cloud_xhs_data_client_id", "pg-test-client")
    binding = {"xhs_id": "pg-test-account-" + suffix, "device_id": "pg-test-phone", "app_slot": "app1",
               "verified_at": "2026-11-01T00:00:00Z"}
    payload = {"itemId": "0", "status": "succeeded", "xhsId": binding["xhs_id"],
               "deviceId": binding["device_id"], "appSlot": "app1", "identitySource": "platform_binding_snapshot",
               "data": {"schema_version": 3, "source": "xhs_creator_center_works_analysis_list", "window_days": 30,
                        "window_start_date": "2026-10-14", "window_end_date": "2026-11-12",
                        "captured_at": "2026-11-12T04:00:00Z", "app_slot": "app1", "account_bound": True,
                        "complete": True, "stop_reason": "list_end_visible", "warnings": [],
                        "recovery_events": ["collection_integrity:verified_two_pass"],
                        "notes": [{"title": "Car guide", "published_date": "2026-11-12", "note_id": None,
                                   "list_view_count": 100, "list_like_count": 5, "list_comment_count": 0}]}}
    try:
        async with sessions() as db:
            env = XHSEnvironment(shop_id="pg-cloud-" + suffix, account_name="PG test", status="active",
                                 xhs_account_id=binding["xhs_id"])
            db.add(env)
            await db.commit()
            env_id = env.id
        async def apply(run_id):
            async with sessions() as db:
                env = await db.get(XHSEnvironment, env_id)
                try:
                    return await XHSCloudDataService(db).import_item(env, run_id, payload, binding)
                except CloudDataError as exc:
                    return {"error": str(exc)}
        results = await asyncio.gather(apply(run_a), apply(run_a))
        assert sum(r.get("created_notes", 0) for r in results) == 1
        assert all(r.get("error") in {None, "cloud_data_import_busy_retry"} for r in results)
        async with sessions() as db:
            assert await db.scalar(select(func.count()).select_from(XHSAccountNote).where(
                XHSAccountNote.environment_id == env_id)) == 1
            assert await db.scalar(select(func.count()).select_from(XHSCloudImport).where(
                XHSCloudImport.environment_id == env_id)) == 1
        original = XHSCloudDataService._apply_rows
        async def fail_after_mutation(self, env, rows, captured, warnings):
            note = await self.db.scalar(select(XHSAccountNote).where(XHSAccountNote.environment_id == env.id))
            note.content = "must roll back"
            await self.db.flush()
            raise RuntimeError("simulated apply failure")
        monkeypatch.setattr(XHSCloudDataService, "_apply_rows", fail_after_mutation)
        outcome = await apply(run_b)
        assert outcome["error"] == "cloud_data_apply_failed"
        async with sessions() as db:
            note = await db.scalar(select(XHSAccountNote).where(XHSAccountNote.environment_id == env_id))
            assert note.content is None
            receipt = await db.scalar(select(XHSCloudImport).where(XHSCloudImport.run_id == run_b))
            assert receipt.status == "quarantined" and receipt.payload == payload
        monkeypatch.setattr(XHSCloudDataService, "_apply_rows", original)
        assert (await apply(run_b))["updated_notes"] == 1

        # A manual workbook and mobile snapshot may both be the first source for a post.
        async with sessions() as db:
            env = XHSEnvironment(shop_id="pg-mixed-" + suffix, account_name="PG mixed", status="active",
                                 xhs_account_id="pg-mixed-account-" + suffix)
            db.add(env)
            await db.commit()
            env_id = env.id
        binding = {**binding, "xhs_id": env.xhs_account_id}
        payload = {**payload, "xhsId": binding["xhs_id"]}
        async def manual():
            async with sessions() as db:
                env = await db.get(XHSEnvironment, env_id)
                result = await XHSService(db)._import_creator_note_stats_rows(env, [{
                    "title": "Car guide", "published_at": datetime(2026, 11, 12, 10),
                    "source_row_index": 2, "view_count": 200, "collect_count": 9}])
                await db.commit()
                return result
        results = await asyncio.gather(apply(uuid.uuid4().hex * 2), manual())
        assert sum(r.get("created_notes", 0) for r in results) == 1
        async with sessions() as db:
            assert await db.scalar(select(func.count()).select_from(XHSAccountNote).where(
                XHSAccountNote.environment_id == env_id)) == 1
            note = await db.scalar(select(XHSAccountNote).where(XHSAccountNote.environment_id == env_id))
            assert note.collected_count == 9 and note.published_at_precision == "second"
    finally:
        await engine.dispose()
