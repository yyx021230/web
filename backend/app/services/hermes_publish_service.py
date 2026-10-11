"""Durable scheduling and fail-closed reconciliation for Phone Cloud publishing."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from sqlalchemy import func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.phone_cloud_publish import PhoneCloudPublisher, PublishAssets, PublishError, publish_evidence
from app.config import settings
from app.core.roles import has_role
from app.models.hermes_publish import HermesPublishAttempt, HermesPublishJob
from app.models.hermes_workflow import HermesWorkflowPost
from app.models.user import User
from app.models.user_xhs_env import UserXHSEnvironment
from app.models.xhs_environment import XHSEnvironment
from app.utils.timezone import cst_now_naive


LOCAL_PENDING = {"scheduled", "waiting_device"}
REMOTE_ACTIVE = {"queued", "running", "stalled", "cancel_requested"}
LOCKED_CONTENT = {"preparing", "submitting", "queued", "running", "stalled", "cancel_requested", "unknown", "submitted"}
MESSAGES = {
    "publish_account_unmapped": "云手机未配置该小红书ID",
    "publish_account_ambiguous": "该小红书ID对应多个手机槽位，请修正配置",
    "publish_account_identity_mismatch": "云手机目标账号已变化，停止发布，请核对小红书ID",
    "publish_conflict_rejected": "云手机拒绝发布请求，请核对冲突原因，不自动重试",
    "publish_evidence_conflict": "手机返回的身份或文案证据未通过核验，禁止重发，请人工核查",
    "publish_account_unverified": "尚未人工确认手机实际登录账号，暂不允许发布",
    "publish_device_busy": "手机正在执行其他任务，等待设备空闲",
    "publish_device_offline": "手机离线或自动化未就绪，等待恢复",
    "publish_permission_changed": "账号分配或用户权限已变化，请重新确认",
    "publish_version_changed": "审核版本、账号或内容已变化，原排期停止",
    "publish_schedule_expired": "已超过允许的排期延迟，请人工确认后重新排期",
    "publish_response_unknown": "提交结果未知，禁止自动重发，请核查原任务",
    "publish_task_missing": "原任务不在最近100条列表中，需要人工对账",
    "publish_remote_failed": "手机执行失败，可能已发生发布动作，请核查原任务",
    "publish_remote_expired": "手机任务超时，发布结果待人工核查",
    "publish_image_missing": "配图缺失或无法读取",
    "publish_image_origin_denied": "配图来源未授权，请配置可信图片来源",
    "publish_image_too_large": "配图超过云手机单张3MB限制，请先调整并重新审核",
    "publish_image_invalid": "配图格式无效，仅支持PNG、JPEG和WebP",
    "publish_configuration_invalid": "云手机发布配置不完整",
    "publish_api_unavailable": "暂时无法查询手机任务，保留原任务继续核查，不会重新发布",
    "publish_observation_timeout": "已超过状态等待预算，保留原任务并等待对账，禁止重发",
}


def snapshot_content(post: HermesWorkflowPost, xhs_id: str) -> dict:
    snapshot = {"title": post.title, "content": post.content, "image_url": post.image_url,
            "revision": int((post.source_detail or {}).get("revision", 1)),
            "reviewed_at": post.reviewed_at.isoformat() if post.reviewed_at else None,
            "reviewed_by": post.reviewed_by, "xhs_id": xhs_id}
    if (post.source_detail or {}).get('source_kind') == 'user_upload':
        from app.services.hermes_workflow_service import post_image_urls
        snapshot['image_urls'] = post_image_urls(post)
    return snapshot


def serialize_publish_job(job: HermesPublishJob) -> dict:
    return {"id": job.id, "post_id": job.post_id, "environment_id": job.environment_id,
            "status": job.status, "scheduled_at": job.scheduled_at.isoformat(),
            "remote_job_id": job.remote_job_id, "error_code": job.error_code, "message": job.message,
            "revision": job.snapshot.get("revision"), "title": job.snapshot.get("title"),
            "events": job.events or [], "updated_at": job.updated_at.isoformat() if job.updated_at else None,
            "can_cancel": job.status in LOCAL_PENDING | {"preparing", "submitting"} | REMOTE_ACTIVE}


def transition(job: HermesPublishJob, status: str, code: str | None = None) -> None:
    now = cst_now_naive()
    changed = job.status != status or job.error_code != code
    job.status, job.error_code = status, code
    job.message = MESSAGES.get(code, "发布异常，请检查配置或联系管理员") if code else None
    if changed:
        job.updated_at = now
        job.events = [*(job.events or []), {"status": status, "code": code, "at": now.isoformat()}][-50:]


async def mirror(db: AsyncSession, job: HermesPublishJob) -> None:
    await db.execute(update(HermesWorkflowPost).where(HermesWorkflowPost.id == job.post_id).values(
        publish_status=job.status, publish_external_id=job.remote_job_id,
    ))


async def lock_job(db: AsyncSession, job_id: int) -> HermesPublishJob | None:
    """Always lock post before job, matching schedule/review/edit transactions."""
    post_id = await db.scalar(select(HermesPublishJob.post_id).where(HermesPublishJob.id == job_id))
    if post_id is None:
        return None
    await db.execute(select(HermesWorkflowPost.id).where(HermesWorkflowPost.id == post_id).with_for_update())
    return await db.scalar(select(HermesPublishJob).where(HermesPublishJob.id == job_id).with_for_update())


class HermesPublishService:
    def __init__(self, db: AsyncSession, *, assets: PublishAssets | None = None):
        self.db = db
        self.assets = assets or PublishAssets()

    async def schedule(self, *, user: User, items: list[dict], is_admin=False) -> list[HermesWorkflowPost]:
        from app.services.hermes_workflow_service import HermesWorkflowService
        workflow = HermesWorkflowService(self.db)
        ids = [item["post_id"] for item in items]
        if len(set(ids)) != len(ids):
            raise HTTPException(400, "同一篇内容不能重复排期")
        posts = list((await self.db.scalars(select(HermesWorkflowPost).where(
            HermesWorkflowPost.id.in_(ids)).order_by(HermesWorkflowPost.id).with_for_update())).all())
        if len(posts) != len(ids):
            raise HTTPException(404, "部分待发布内容不存在")
        if not is_admin and any(post.owner_user_id != user.id for post in posts):
            raise HTTPException(403, "只能安排自己的内容")
        environments = {env.id: env for env in (list((await self.db.scalars(select(XHSEnvironment).where(
            XHSEnvironment.status == "active"))).all()) if is_admin else await workflow.assigned_environments(user.id))}
        target_ids = {item["environment_id"] for item in items}
        if not target_ids.issubset(environments):
            raise HTTPException(403, "发布账号必须是当前授权的账号")
        await self.db.execute(select(XHSEnvironment.id).where(XHSEnvironment.id.in_(target_ids))
                              .order_by(XHSEnvironment.id).with_for_update())
        existing = {job.post_id: job for job in (await self.db.scalars(select(HermesPublishJob).where(
            HermesPublishJob.post_id.in_(ids)).order_by(HermesPublishJob.id).with_for_update())).all()}
        by_id = {post.id: post for post in posts}
        normalized = []
        seen = set()
        for item in items:
            post = by_id[item["post_id"]]
            env = environments[item["environment_id"]]
            if post.status not in {"approved", "publish_ready"} or not post.hard_pass or not all([post.title, post.content, post.image_url, post.reviewed_at, post.reviewed_by, post.owner_user_id]):
                raise HTTPException(409, "只有已审核通过的完整图文可以排期")
            if env.id != post.environment_id:
                raise HTTPException(409, "目标账号属于审核内容，换账号须重新生产并审核")
            xhs_id = str(env.xhs_account_id or "").strip()
            if not xhs_id:
                raise HTTPException(409, "请先配置账号的小红书ID")
            if len(post.title.strip().encode("utf-16-le")) // 2 > 100 or len(post.content.strip().encode("utf-16-le")) // 2 > 2000:
                raise HTTPException(409, "标题或正文超过云手机接口限制，不能自动截断")
            try:
                when = datetime.fromisoformat(item["scheduled_at"].replace("Z", "+00:00"))
                if when.tzinfo:
                    when = when.astimezone(ZoneInfo("Asia/Shanghai")).replace(tzinfo=None)
            except ValueError:
                raise HTTPException(400, "发布时间格式无效") from None
            if when <= cst_now_naive():
                raise HTTPException(400, "发布时间必须晚于当前时间（北京时间）")
            if (env.id, when) in seen:
                raise HTTPException(409, "同一账号在该时间已有排期")
            seen.add((env.id, when))
            conflict = await self.db.scalar(select(HermesPublishJob.id).where(
                HermesPublishJob.environment_id == env.id, HermesPublishJob.scheduled_at == when,
                HermesPublishJob.status.in_(LOCAL_PENDING | LOCKED_CONTENT), HermesPublishJob.post_id.not_in(ids)).limit(1))
            if conflict:
                raise HTTPException(409, "同一账号在该时间已有排期")
            job = existing.get(post.id)
            snap = snapshot_content(post, xhs_id)
            # A lost save response may be replayed unchanged even though the post version advanced.
            if job and job.status in LOCAL_PENDING and job.scheduled_at == when and all(job.snapshot.get(k) == v for k, v in snap.items()):
                continue
            if job and job.status not in LOCAL_PENDING | {"cancelled", "failed"}:
                raise HTTPException(409, "该内容已经提交或结果待核验，不能重新排期")
            if not item.get("expected_version"):
                raise HTTPException(409, "请刷新并携带当前审核版本排期")
            await workflow.reserve_post(post, item["expected_version"])
            normalized.append((post, env, when, snap, job))
        for post, env, when, snap, job in normalized:
            try:
                from app.services.hermes_workflow_service import post_image_urls
                snap["images"] = await self.assets.freeze(post_image_urls(post))
            except PublishError as exc:
                raise HTTPException(409, MESSAGES.get(exc.code, "配图快照准备失败，请检查配置")) from None
            if job is None:
                job = HermesPublishJob(post_id=post.id, owner_user_id=post.owner_user_id,
                                       environment_id=env.id, requested_by=user.id, events=[])
                self.db.add(job)
            job.request_key = uuid.uuid4().hex
            job.requested_by, job.snapshot, job.scheduled_at = user.id, snap, when
            job.retry_at = job.lease_until = job.claim_token = None
            job.remote_job_id = job.device_id = job.app_slot = None
            transition(job, "scheduled")
            post.publish_status = "scheduled"
            post.publish_target_environment_id, post.scheduled_publish_at = env.id, when
            workflow.append_event(post, "schedule", user.id, "保存云手机发布排期")
        await self.db.commit()
        refreshed = {post.id: post for post in (await self.db.scalars(select(HermesWorkflowPost).where(
            HermesWorkflowPost.id.in_(ids)).execution_options(populate_existing=True))).all()}
        return [refreshed[post_id] for post_id in ids]

    async def list_jobs(self, user: User, *, is_admin=False, page=1, limit=40) -> dict:
        filters = [] if is_admin else [HermesPublishJob.owner_user_id == user.id]
        total = await self.db.scalar(select(func.count()).select_from(HermesPublishJob).where(*filters))
        jobs = (await self.db.scalars(select(HermesPublishJob).where(*filters).order_by(
            HermesPublishJob.id.desc()).offset((page - 1) * limit).limit(limit))).all()
        return {"items": [serialize_publish_job(job) for job in jobs], "total": total,
                "dispatch_enabled": settings.phone_cloud_publish_enabled}

    async def cancel(self, job_id: int, user: User, *, is_admin=False) -> dict:
        job = await lock_job(self.db, job_id)
        if job is None or (not is_admin and job.owner_user_id != user.id):
            raise HTTPException(404, "发布单不存在")
        if job.status in LOCAL_PENDING | {"preparing"}:
            transition(job, "cancelled")
            job.claim_token = None
        elif job.status in REMOTE_ACTIVE | {"submitting"}:
            transition(job, "cancel_requested")
        elif job.status not in {"cancelled", "cancel_requested"}:
            raise HTTPException(409, "该任务已结束或结果未知，不能保证取消或撤回")
        await mirror(self.db, job)
        await self.db.commit()
        return serialize_publish_job(job)

    async def guard_content_change(self, post_id: int) -> None:
        job = await self.db.scalar(select(HermesPublishJob).where(HermesPublishJob.post_id == post_id).with_for_update())
        if job and job.status in LOCKED_CONTENT:
            raise HTTPException(409, "内容已进入发布执行或待核验，请先处理发布单，不能修改审核版本")
        if job and job.status in LOCAL_PENDING:
            transition(job, "cancelled", "publish_version_changed")


class HermesPublishWorker:
    """Short DB transactions; remote work never holds a post/database lock."""

    def __init__(self, session_factory, publisher=None, assets=None):
        self.sessions = session_factory
        self.publisher = publisher or PhoneCloudPublisher()
        self.assets = assets or PublishAssets()

    async def tick(self) -> None:
        if not settings.phone_cloud_publish_enabled:
            return
        await self.recover()
        await self.poll()
        for _ in range(10):
            claimed = await self.claim()
            if not claimed:
                break
            await self.dispatch(*claimed)

    async def recover(self) -> None:
        async with self.sessions() as db:
            ids = list((await db.scalars(select(HermesPublishJob.id).where(
                HermesPublishJob.status.in_({"preparing", "submitting", "cancel_requested"}),
                HermesPublishJob.remote_job_id.is_(None), HermesPublishJob.lease_until < cst_now_naive())
                .order_by(HermesPublishJob.post_id))).all())
            for job_id in ids:
                job = await lock_job(db, job_id)
                if job.status not in {"preparing", "submitting", "cancel_requested"} or job.remote_job_id or not job.lease_until or job.lease_until >= cst_now_naive():
                    continue
                if job.status == "preparing":
                    transition(job, "scheduled")
                    job.claim_token = None
                else:
                    transition(job, "unknown", "publish_response_unknown")
                await mirror(db, job)
            await db.commit()

    async def claim(self) -> tuple[int, str] | None:
        now = cst_now_naive()
        async with self.sessions() as db:
            job = await db.scalar(select(HermesPublishJob).where(
                HermesPublishJob.status.in_(LOCAL_PENDING), HermesPublishJob.scheduled_at <= now,
                or_(HermesPublishJob.retry_at.is_(None), HermesPublishJob.retry_at <= now))
                .order_by(HermesPublishJob.scheduled_at, HermesPublishJob.id).limit(1).with_for_update(skip_locked=True))
            if not job:
                return None
            token = uuid.uuid4().hex
            won = await db.scalar(update(HermesPublishJob).where(
                HermesPublishJob.id == job.id, HermesPublishJob.status.in_(LOCAL_PENDING))
                .values(status="preparing", claim_token=token, lease_until=now + timedelta(minutes=2))
                .returning(HermesPublishJob.id))
            await db.commit()
            return (won, token) if won else None

    async def dispatch(self, job_id: int, token: str) -> None:
        try:
            async with self.sessions() as db:
                job = await db.get(HermesPublishJob, job_id)
                if not job or job.status != "preparing" or job.claim_token != token:
                    return
                snapshot = dict(job.snapshot)
                if cst_now_naive() > job.scheduled_at + timedelta(seconds=settings.phone_cloud_publish_max_lateness_seconds):
                    raise PublishError("publish_schedule_expired")
                verified = {v.strip() for v in settings.phone_cloud_publish_verified_xhs_ids.split(",") if v.strip()}
                if snapshot["xhs_id"] not in verified:
                    raise PublishError("publish_account_unverified")
            target = self.publisher.target(await self.publisher.devices(), snapshot["xhs_id"])
            images = await self.assets.data_urls(snapshot["images"])
            async with self.sessions() as db:
                # Same lock order as review/save: post -> job -> environment.
                post = await db.scalar(select(HermesWorkflowPost).where(HermesWorkflowPost.id == job.post_id).with_for_update())
                current = await lock_job(db, job_id)
                if not current or current.claim_token != token or current.status != "preparing":
                    return
                env = await db.scalar(select(XHSEnvironment).where(XHSEnvironment.id == current.environment_id).with_for_update())
                actor = await db.get(User, current.requested_by)
                owner = await db.get(User, current.owner_user_id)
                assigned = await db.scalar(select(UserXHSEnvironment.id).where(
                    UserXHSEnvironment.environment_id == current.environment_id, UserXHSEnvironment.user_id == current.owner_user_id))
                if not actor or not actor.is_active or not owner or not owner.is_active or not assigned or (actor.id != owner.id and not has_role(actor, "admin")):
                    raise PublishError("publish_permission_changed")
                if not env or env.status != "active" or not post or post.status not in {"approved", "publish_ready"} or not post.hard_pass or post.owner_user_id != current.owner_user_id or snapshot_content(post, str(env.xhs_account_id or "").strip()) != {k: v for k, v in snapshot.items() if k not in {"images", "publish_proof_required"}}:
                    raise PublishError("publish_version_changed")
                busy = await db.scalar(select(HermesPublishJob.id).where(
                    HermesPublishJob.id != job_id, HermesPublishJob.device_id == target["device_id"],
                    HermesPublishJob.status.in_(REMOTE_ACTIVE | {"submitting", "unknown"})).limit(1))
                if busy:
                    raise PublishError("publish_device_busy", retryable=True)
                current.device_id, current.app_slot = target["device_id"], target["app_slot"]
                transition(current, "submitting")
                current.lease_until = cst_now_naive() + timedelta(minutes=2)
                attempt = HermesPublishAttempt(job_id=job_id, request_key=current.request_key, status="submitting",
                                               evidence={"images": snapshot["images"], "device_id": current.device_id, "app_slot": current.app_slot})
                db.add(attempt)
                await mirror(db, current)
                await db.commit()
            remote_id = await self.publisher.create(target, snapshot, images)
            async with self.sessions() as db:
                current = await lock_job(db, job_id)
                if current.claim_token != token:
                    return
                current.remote_job_id = remote_id
                transition(current, "cancel_requested" if current.status == "cancel_requested" else "queued")
                await db.execute(update(HermesPublishAttempt).where(HermesPublishAttempt.request_key == current.request_key)
                                 .values(status="accepted", remote_job_id=remote_id))
                await mirror(db, current)
                await db.commit()
        except PublishError as exc:
            await self.finish_error(job_id, token, exc)
        except Exception:
            # No provider body, token, content, or URL enters public error/log records.
            await self.finish_error(job_id, token, PublishError("publish_internal_error", uncertain=True))

    async def finish_error(self, job_id: int, token: str, error: PublishError) -> None:
        async with self.sessions() as db:
            job = await lock_job(db, job_id)
            if not job or job.claim_token != token or job.status not in {"preparing", "submitting", "cancel_requested"}:
                return
            if job.status == "cancel_requested":
                transition(job, "unknown", "publish_response_unknown")
            elif error.uncertain:
                transition(job, "unknown", "publish_response_unknown")
            elif error.retryable:
                transition(job, "waiting_device", error.code)
                job.retry_at = cst_now_naive() + timedelta(seconds=30)
                # An explicit rejection was not accepted, so a future attempt is allowed.
                job.request_key = uuid.uuid4().hex
            else:
                transition(job, "failed", error.code)
            job.claim_token = None
            attempts = (await db.scalars(select(HermesPublishAttempt).where(
                HermesPublishAttempt.job_id == job.id, HermesPublishAttempt.status == "submitting"))).all()
            for attempt in attempts:
                attempt.status = job.status
                attempt.evidence = {**(attempt.evidence or {}), "code": error.code}
            await mirror(db, job)
            await db.commit()

    async def poll(self, *, job_id: int | None = None) -> None:
        async with self.sessions() as db:
            query = select(HermesPublishJob.id).where(
                or_(HermesPublishJob.status.in_(REMOTE_ACTIVE),
                    (HermesPublishJob.status == "unknown") &
                    HermesPublishJob.error_code.in_({"publish_observation_timeout", "publish_task_missing", "publish_evidence_conflict"}) &
                    (HermesPublishJob.updated_at > cst_now_naive() - timedelta(days=1))),
                HermesPublishJob.remote_job_id.is_not(None))
            if job_id is not None:
                query = query.where(HermesPublishJob.id == job_id)
            ids = list((await db.scalars(query.order_by(HermesPublishJob.id).limit(200))).all())
        if not ids:
            return
        try:
            tasks = {task.get("jobId"): task for task in await self.publisher.tasks()}
        except PublishError:
            for job_id in ids:
                async with self.sessions() as db:
                    job = await lock_job(db, job_id)
                    if not job or job.status not in REMOTE_ACTIVE:
                        continue
                    expired = job.lease_until and cst_now_naive() > job.lease_until + timedelta(
                        seconds=settings.phone_cloud_publish_max_observe_seconds)
                    status, code = ("unknown", "publish_observation_timeout") if expired else (job.status, "publish_api_unavailable")
                    if (job.status, job.error_code) != (status, code):
                        transition(job, status, code)
                        await mirror(db, job)
                        await db.commit()
            return
        for job_id in ids:
            async with self.sessions() as db:
                job = await lock_job(db, job_id)
                if not job or job.status not in REMOTE_ACTIVE | {"unknown"}:
                    continue
                before = (job.status, job.error_code, job.message)
                task = tasks.get(job.remote_job_id)
                proof = publish_evidence(task) if task else {}
                if not task:
                    transition(job, "unknown", "publish_task_missing")
                elif task.get("status") == "succeeded":
                    # Cloud status is authoritative; optional evidence is audit-only.
                    transition(job, "submitted")
                    job.message = "云手机返回发布成功"
                elif task.get("status") in {"failed", "expired", "cancelled"}:
                    if task["status"] == "cancelled":
                        transition(job, "cancelled")
                        job.message = "云手机任务已取消，已发生的发布动作不可撤回"
                    else:
                        transition(job, "failed", "publish_remote_expired" if task["status"] == "expired" else "publish_remote_failed")
                elif task.get("status") in {"queued", "running", "stalled"}:
                    expired = job.lease_until and cst_now_naive() > job.lease_until + timedelta(
                        seconds=settings.phone_cloud_publish_max_observe_seconds)
                    if expired:
                        transition(job, "unknown", "publish_observation_timeout")
                    elif job.status not in {"cancel_requested", "unknown"}:
                        transition(job, task["status"])
                else:
                    transition(job, "unknown", "publish_response_unknown")
                remote_id = job.remote_job_id if job.status == "cancel_requested" else None
                if before != (job.status, job.error_code, job.message) or proof:
                    await mirror(db, job)
                    attempts = (await db.scalars(select(HermesPublishAttempt).where(
                        HermesPublishAttempt.job_id == job.id, HermesPublishAttempt.remote_job_id == job.remote_job_id
                    ))).all()
                    for attempt in attempts:
                        attempt.status = job.status
                        if proof:
                            attempt.evidence = {**(attempt.evidence or {}), "remote_publish_proof": proof}
                    await db.commit()
            if remote_id:
                try:
                    await self.publisher.cancel(remote_id)
                except PublishError:
                    pass  # Keep observing the original task; cancellation is not withdrawal.
