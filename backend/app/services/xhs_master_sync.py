"""Canonical account scheduling; browser IDs are execution resources, never account IDs."""

from __future__ import annotations

import asyncio
import re
import uuid

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.db import session as db_session
from app.models.xhs_account import XHSAccount
from app.models.xhs_account_note import XHSAccountNote
from app.models.xhs_account_sync_run import XHSAccountSyncRun, XHSAccountSyncRunItem
from app.schemas.xhs_account_master import MasterSyncRequest
from app.services.xhs_master_data import master_enabled, require_master
from app.utils.timezone import utc_now_naive


class XHSMasterSync:
    def __init__(self, db):
        self.db = db

    async def targets(self, request: MasterSyncRequest):
        if not master_enabled():
            raise ValueError("飞书主名单模式未启用")
        await require_master(self.db)
        stmt = (
            select(XHSAccount)
            .where(
                XHSAccount.status == "active",
                XHSAccount.department.in_(("xhs", "brand")),
            )
            .order_by(XHSAccount.id)
        )
        if request.account_ids is not None:
            if not request.account_ids or len(set(request.account_ids)) != len(
                request.account_ids
            ):
                raise ValueError("请选择不重复的有效主名单账号")
            stmt = stmt.where(XHSAccount.id.in_(request.account_ids))
        accounts = list((await self.db.scalars(stmt)).all())
        if request.account_ids is not None and len(accounts) != len(
            request.account_ids
        ):
            raise ValueError("部分账号不在有效主名单中，请刷新名单")
        if request.kind != "engagement" and accounts:
            await self.runners(request.runner_ids)
        if request.runner_assignments:
            selected = {a.id for a in accounts}
            assigned = [
                i for values in request.runner_assignments.values() for i in values
            ]
            if (
                set(request.runner_assignments) - {str(r) for r in request.runner_ids}
                or len(set(assigned)) != len(assigned)
                or set(assigned) != selected
            ):
                raise ValueError("采集环境分配必须完整且不重复地覆盖所选主名单账号")
        if request.target_note_ids is not None:
            ids = list(
                (
                    await self.db.scalars(
                        select(XHSAccountNote.id).where(
                            XHSAccountNote.account_id.in_([a.id for a in accounts]),
                            XHSAccountNote.id.in_(request.target_note_ids),
                        )
                    )
                ).all()
            )
            if set(ids) != set(request.target_note_ids):
                raise ValueError("所选帖子不属于有效主名单账号")
        return accounts

    async def runners(self, ids):
        from app.services.xhs_service import XHSService

        allowed = {
            e.id: e for e in await XHSService(self.db).list_sync_runner_environments()
        }
        if not ids or len(ids) != len(set(ids)) or set(ids) - set(allowed):
            raise ValueError("请选择有效的测试采集环境，不可使用业务账号作为环境")
        return [allowed[i] for i in ids]

    async def prepare(
        self, request, *, user_id=None, source="manual", parent_run_id=None
    ):
        accounts = await self.targets(request)
        run = XHSAccountSyncRun(
            job_id="master-" + uuid.uuid4().hex,
            sync_kind=request.kind,
            source=source,
            requested_by_user_id=user_id,
            parent_run_id=parent_run_id,
            request_config={
                "identity_source": "feishu",
                **request.model_dump(),
                "account_ids": [a.id for a in accounts],
            },
            status="queued",
            message="等待主名单同步",
        )
        self.db.add(run)
        await self.db.flush()
        for account in accounts:
            self.db.add(
                XHSAccountSyncRunItem(
                    run_id=run.id,
                    account_id=account.id,
                    account_name=account.account_name,
                    status="queued",
                )
            )
        await self.db.commit()
        return run

    async def execute(self, run_id, *, cancel_check=None, progress_callback=None):
        from app.services.xhs_cloud_data_service import XHSCloudDataService
        from app.services.xhs_service import XHSService, SyncJobCancelled

        run = await self.db.get(XHSAccountSyncRun, run_id)
        request = MasterSyncRequest.model_validate(
            {k: v for k, v in run.request_config.items() if k != "identity_source"}
        )
        try:
            accounts = await self.targets(request)
        except ValueError as exc:
            await self.db.rollback()
            for aid in request.account_ids or []:
                await self.finish_item(
                    run_id, aid, {"error": self.safe_error(exc)}, {}, pending_only=True
                )
            return await self.finalize(run_id)
        account_ids = [a.id for a in accounts]
        detail_ids = {}
        if request.kind == "details":
            service = XHSService(self.db)
            all_ids = list(
                (
                    await self.db.scalars(
                        select(XHSAccountNote.id).where(
                            XHSAccountNote.account_id.in_(account_ids),
                            *(
                                [XHSAccountNote.id.in_(request.target_note_ids)]
                                if request.target_note_ids is not None
                                else []
                            ),
                        )
                    )
                ).all()
            )
            if all_ids:
                selected, _, _ = await service._prepare_account_note_detail_sync_notes(
                    environment_id=None,
                    target_note_ids=all_ids,
                    sync_mode=request.sync_mode,
                    sync_limit=request.sync_limit,
                    max_post_age_days=request.max_post_age_days,
                    persona=service._build_sync_session_persona(),
                )
                for note in selected:
                    detail_ids.setdefault(note.account_id, []).append(note.id)
        run.status = "running"
        run.started_at = utc_now_naive()
        await self.db.commit()
        try:
            if request.kind == "engagement":
                previous_counts = {}

                async def cloud_progress(patch):
                    aid = patch.get("account_id")
                    if aid and patch.get("phase") in {
                        "account_engagement_completed",
                        "account_engagement_failed",
                    }:
                        counts = {
                            key: int(patch.get(key) or 0)
                            for key in (
                                "created_notes",
                                "updated_notes",
                                "metric_synced_notes",
                            )
                        }
                        delta = {
                            key: value - previous_counts.get(key, 0)
                            for key, value in counts.items()
                        }
                        previous_counts.update(counts)
                        await self.finish_item(
                            run_id,
                            aid,
                            {"error": patch["error"]} if patch.get("error") else None,
                            delta,
                        )
                    if progress_callback:
                        await XHSService._emit_progress(progress_callback, patch)

                result = await XHSCloudDataService(self.db).sync(
                    accounts,
                    progress_callback=cloud_progress,
                    cancel_check=cancel_check,
                )
                failures = {
                    int(f["account_id"]): f for f in result.get("failed_accounts", [])
                }
                for aid in account_ids:
                    await self.finish_item(
                        run_id, aid, failures.get(aid), {}, pending_only=True
                    )
            else:
                groups = {r: [] for r in request.runner_ids}
                if request.runner_assignments:
                    groups = {
                        int(r): values
                        for r, values in request.runner_assignments.items()
                    }
                else:
                    for index, aid in enumerate(account_ids):
                        groups[
                            request.runner_ids[index % len(request.runner_ids)]
                        ].append(aid)
                await self.db.commit()
                semaphore = asyncio.Semaphore(request.concurrency)

                async def group(runner_id, ids):
                    async with semaphore:
                        for aid in ids:
                            if cancel_check and cancel_check():
                                return
                            async with db_session.async_session() as session:
                                worker = XHSMasterSync(session)
                                item = await session.scalar(
                                    select(XHSAccountSyncRunItem).where(
                                        XHSAccountSyncRunItem.run_id == run_id,
                                        XHSAccountSyncRunItem.account_id == aid,
                                    )
                                )
                                item.status = "running"
                                item.started_at = utc_now_naive()
                                await session.commit()
                                try:
                                    account = await session.get(XHSAccount, aid)
                                    if account is None or account.status != "active":
                                        raise ValueError("账号已移出有效主名单")
                                    if request.kind == "posts":
                                        result = await worker.homepage(
                                            account,
                                            runner_id,
                                            request,
                                            progress_callback=progress_callback,
                                            cancel_check=cancel_check,
                                        )
                                    else:
                                        notes = detail_ids.get(aid, [])
                                        # An empty exact selection must not fall back to all notes.
                                        result = (
                                            await worker.details(
                                                account,
                                                runner_id,
                                                notes,
                                                request,
                                                progress_callback=progress_callback,
                                                cancel_check=cancel_check,
                                            )
                                            if notes
                                            else {"synced_notes": 0}
                                        )
                                        if result.get("failed_notes"):
                                            await worker.finish_item(
                                                run_id,
                                                aid,
                                                {"error": "部分帖子补充失败"},
                                                result,
                                            )
                                            continue
                                    await worker.finish_item(run_id, aid, None, result)
                                except SyncJobCancelled:
                                    await session.rollback()
                                    return
                                except Exception as exc:
                                    await session.rollback()
                                    await worker.finish_item(
                                        run_id,
                                        aid,
                                        {"error": worker.safe_error(exc)},
                                        {},
                                    )

                await asyncio.gather(
                    *(group(r, ids) for r, ids in groups.items() if ids),
                    return_exceptions=True,
                )
        except SyncJobCancelled:
            pass
        except Exception as exc:
            await self.db.rollback()
            for aid in account_ids:
                await self.finish_item(
                    run_id, aid, {"error": self.safe_error(exc)}, {}, pending_only=True
                )
        summary = await self.finalize(
            run_id, cancelled=bool(cancel_check and cancel_check())
        )
        if request.kind == "engagement" and "result" in locals():
            summary.update(
                {
                    k: result[k]
                    for k in (
                        "created_notes",
                        "updated_notes",
                        "metric_synced_notes",
                        "total_notes",
                    )
                    if k in result
                }
            )
        return summary

    @staticmethod
    def safe_error(exc):
        # Raw worker/HTTP exceptions may contain signed profile URLs or credentials.
        safe_messages = {
            "未配置有效的独立主页链接，未启动采集环境",
            "主名单账号已变化，请按最新名单重新同步",
            "主页公开号与主名单不一致或无法确认，未写入任何帖子",
            "账号已移出有效主名单",
            "部分账号不在有效主名单中，请刷新名单",
            "飞书主名单尚未完整初始化，请管理员先确认导入完整名单",
            "主名单账号版本或主页链接无效",
            "主名单账号版本已变化",
            "详情目标不属于所选主名单账号",
        }
        if str(exc) in safe_messages or re.fullmatch(
            r"cloud_data_[a-z0-9_]+", str(exc)
        ):
            return str(exc)[:180]
        return f"{type(exc).__name__}: 主名单同步失败，请查看对应采集阶段日志"

    async def finish_item(
        self, run_id, account_id, failure, result, *, pending_only=False
    ):
        item = await self.db.scalar(
            select(XHSAccountSyncRunItem)
            .where(
                XHSAccountSyncRunItem.run_id == run_id,
                XHSAccountSyncRunItem.account_id == account_id,
            )
            .execution_options(populate_existing=True)
        )
        if pending_only and item.status not in ("queued", "running"):
            return
        item.status = "failed" if failure else "succeeded"
        item.error = str(failure.get("error") or "采集失败")[:180] if failure else None
        item.message = item.error or "同步完成"
        item.result = {
            k: v
            for k, v in result.items()
            if k
            in {
                "created_notes",
                "updated_notes",
                "synced_notes",
                "failed_notes",
                "failed_note_ids",
                "total_notes",
                "metric_synced_notes",
                "matched_notes",
                "skipped_notes",
                "deferred_homepage_notes",
            }
        }
        item.finished_at = utc_now_naive()
        await self.db.commit()

    async def finalize(self, run_id, *, cancelled=False):
        run = await self.db.scalar(
            select(XHSAccountSyncRun)
            .where(XHSAccountSyncRun.id == run_id)
            .options(selectinload(XHSAccountSyncRun.items))
            .execution_options(populate_existing=True)
        )
        for item in run.items:
            if item.status in ("queued", "running"):
                item.status = "cancelled" if cancelled else "failed"
                item.error = "任务已取消" if cancelled else "任务中断，未完成同步"
                item.finished_at = utc_now_naive()
        failed = [
            {
                "account_id": i.account_id,
                "account_name": i.account_name,
                "error": i.error,
            }
            for i in run.items
            if i.status == "failed"
        ]
        succeeded = sum(i.status == "succeeded" for i in run.items)
        run.status = (
            "cancelled"
            if cancelled
            else (
                "partial_failed"
                if failed and succeeded
                else "failed"
                if failed
                else "succeeded"
            )
        )
        run.message = f"成功 {succeeded}/{len(run.items)} 个账号，失败 {len(failed)} 个"
        run.finished_at = utc_now_naive()
        await self.db.commit()
        return {
            **{
                key: sum(int((item.result or {}).get(key) or 0) for item in run.items)
                for key in (
                    "created_notes",
                    "updated_notes",
                    "metric_synced_notes",
                    "total_notes",
                    "synced_notes",
                    "failed_notes",
                    "matched_notes",
                    "skipped_notes",
                    "deferred_homepage_notes",
                )
            },
            "synced_accounts": succeeded,
            "failed_accounts": failed,
            "status": run.status,
            "message": run.message,
        }

    async def homepage(self, account, runner_id, request, **callbacks):
        from app.services.xhs_service import XHSService
        from app.services.xhs_account_master_service import valid_profile_url

        if not valid_profile_url(account.profile_url or ""):
            raise ValueError("未配置有效的独立主页链接，未启动采集环境")
        service = XHSService(self.db)
        if service._should_delegate_browser_ops():
            return await service._call_worker_api(
                "POST",
                "/api/v1/xhs/accounts/internal/homepage",
                json={
                    "account_id": account.id,
                    "expected_revision": account.revision,
                    "runner_id": runner_id,
                    "limit": request.limit_per_account,
                    "homepage_sync_mode": request.homepage_sync_mode,
                },
                timeout=900,
            )
        return await self.homepage_local(
            account.id,
            account.revision,
            runner_id,
            request.limit_per_account,
            request.homepage_sync_mode,
            **callbacks,
        )

    async def details(self, account, runner_id, notes, request, **callbacks):
        from app.services.xhs_service import XHSService
        from app.schemas.xhs_account_master import MasterDetailWorkerRequest

        body = MasterDetailWorkerRequest(
            account_id=account.id,
            expected_revision=account.revision,
            runner_id=runner_id,
            note_ids=notes,
            sync_limit_per_runner=request.sync_limit_per_runner,
            pause_seconds_min=request.pause_seconds_min,
            pause_seconds_max=request.pause_seconds_max,
        )
        service = XHSService(self.db)
        if service._should_delegate_browser_ops():
            return await service._call_worker_api(
                "POST",
                "/api/v1/xhs/accounts/internal/details",
                json=body.model_dump(),
                timeout=900,
            )
        return await self.details_local(body, **callbacks)

    async def details_local(self, body, **callbacks):
        from app.services.xhs_service import XHSService

        await require_master(self.db)
        await self.runners([body.runner_id])
        account = await self.db.get(XHSAccount, body.account_id, populate_existing=True)
        if (
            account is None
            or account.status != "active"
            or account.revision != body.expected_revision
        ):
            raise ValueError("主名单账号版本已变化")
        ids = list(
            (
                await self.db.scalars(
                    select(XHSAccountNote.id).where(
                        XHSAccountNote.account_id == account.id,
                        XHSAccountNote.id.in_(body.note_ids),
                    )
                )
            ).all()
        )
        if set(ids) != set(body.note_ids):
            raise ValueError("详情目标不属于所选主名单账号")
        service = XHSService(self.db)
        if service._should_delegate_browser_ops():
            raise ValueError("接收详情任务的Worker必须启用本地浏览器执行")
        return await service.sync_existing_account_note_stats(
            target_note_ids=ids,
            scrape_environment_ids=[body.runner_id],
            sync_mode="all",
            sync_limit=len(ids),
            sync_limit_per_runner=body.sync_limit_per_runner,
            pause_seconds_min=body.pause_seconds_min,
            pause_seconds_max=body.pause_seconds_max,
            concurrency=1,
            **callbacks,
        )

    async def homepage_local(
        self, account_id, revision, runner_id, limit, mode, **callbacks
    ):
        from app.services.xhs_service import XHSService
        from app.services.xhs_account_master_service import valid_profile_url

        await require_master(self.db)
        account = await self.db.get(XHSAccount, account_id, populate_existing=True)
        runners = await self.runners([runner_id])
        if (
            account is None
            or account.status != "active"
            or account.revision != revision
            or not valid_profile_url(account.profile_url or "")
        ):
            raise ValueError("主名单账号版本或主页链接无效")
        service = XHSService(self.db)
        return await service._sync_account_notes_for_environment_locked(
            account,
            scrape_env=runners[0],
            limit=limit,
            persona=service._build_sync_session_persona(),
            runner_envs=runners,
            homepage_sync_mode=mode,
            **callbacks,
        )

    async def retry_request(self, run):
        if run.status in ("queued", "running"):
            raise ValueError("任务仍在运行，不能重复下发")
        ids = [i.account_id for i in run.items if i.status == "failed" and i.account_id]
        if not ids:
            raise ValueError("没有可重跑的失败账号")
        config = {k: v for k, v in run.request_config.items() if k != "identity_source"}
        config["account_ids"] = ids
        if config.get("runner_assignments"):
            config["runner_assignments"] = {
                r: [i for i in values if i in ids]
                for r, values in config["runner_assignments"].items()
                if any(i in ids for i in values)
            }
        if run.sync_kind == "details":
            failed_notes = [
                n
                for i in run.items
                if i.status == "failed"
                for n in (i.result or {}).get("failed_note_ids", [])
            ]
            if not failed_notes:
                raise ValueError(
                    "未记录失败帖子ID，请手动选择后重试，避免重复采集成功帖子"
                )
            config.update(
                target_note_ids=failed_notes,
                sync_mode="all",
                sync_limit=len(failed_notes),
            )
        return MasterSyncRequest.model_validate(config)
