from __future__ import annotations

import uuid
import hashlib
import json
from difflib import SequenceMatcher
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo
from typing import Any

from fastapi import HTTPException
from sqlalchemy import String, case, func, or_, select, update
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.hermes_workflow import (
    HermesWorkerState,
    HermesWorkflowPost,
    HermesWorkflowRun,
    HermesWorkflowSchedule,
)
from app.models.user import User
from app.models.user_xhs_env import UserXHSEnvironment
from app.models.xhs_environment import XHSEnvironment
from app.utils.timezone import cst_now_naive
from app.services.hermes_policy_service import policy_summaries


ACTIVE_GENERATION_STATUSES = {"queued", "claimed", "running", "generating"}
REVIEWABLE_STATUSES = {"review_pending", "approved", "rejected", "publish_ready"}
GENERATED_STATUSES = REVIEWABLE_STATUSES | {"published"}


def post_version(post: HermesWorkflowPost) -> str:
    payload = [post.title, post.content, post.image_url, post.status, post.review_comment,
               _iso(post.reviewed_at), post.publish_status, _iso(post.scheduled_publish_at),
               post.publish_target_environment_id, (post.source_detail or {}).get('revision', 1)]
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False).encode()).hexdigest()[:24]


def post_counts(posts: list[HermesWorkflowPost]) -> dict[str, int]:
    return {
        'total': len(posts),
        'generated': sum(p.status in GENERATED_STATUSES for p in posts),
        'approved': sum(p.status in {'approved', 'publish_ready', 'published'} for p in posts),
        'rejected': sum(p.status == 'rejected' for p in posts),
        'failed': sum(p.status == 'generation_failed' for p in posts),
        'pending_review': sum(p.status == 'review_pending' for p in posts),
        'active': sum(p.status in ACTIVE_GENERATION_STATUSES for p in posts),
    }


def aggregate_status(posts: list[HermesWorkflowPost], fallback: str = 'queued') -> str:
    states = {p.status for p in posts}
    if not states:
        return fallback
    if states == {'queued'}:
        return 'queued'
    if states & ACTIVE_GENERATION_STATUSES:
        return 'running'
    if 'generation_failed' in states:
        return 'partial_failed' if states & GENERATED_STATUSES else 'failed'
    if 'rejected' in states:
        return 'changes_requested'
    if states == {'published'}:
        return 'published'
    if states == {'cancelled'}:
        return 'cancelled'
    if states <= {'approved', 'publish_ready', 'published'}:
        return 'approved'
    return 'review_pending'


def _iso(value: datetime | date | None) -> str | None:
    return value.isoformat() if value is not None else None


def text_change(before: str | None, after: str) -> dict[str, Any]:
    """Persist server-computed exact changes, not a user-authored change claim."""
    old = before or ''
    segments = []
    for op, i, j, a, b in SequenceMatcher(None, old, after, autojunk=False).get_opcodes():
        if op == 'equal':
            segments.append({'kind': 'equal', 'text': old[i:j]})
        else:
            if i != j:
                segments.append({'kind': 'removed', 'text': old[i:j]})
            if a != b:
                segments.append({'kind': 'added', 'text': after[a:b]})
    return {'before': old, 'after': after, 'segments': segments}


def serialize_post(post: HermesWorkflowPost) -> dict[str, Any]:
    return {
        "id": post.id,
        "run_id": post.run_id,
        "environment_id": post.environment_id,
        "owner_user_id": post.owner_user_id,
        "slot": post.slot,
        "account_name": post.account_name,
        "vehicle_model": post.vehicle_model,
        "case_id": post.case_id,
        "status": post.status,
        "title": post.title,
        "content": post.content,
        "image_url": post.image_url,
        "hard_pass": bool(post.hard_pass),
        "version": post_version(post),
        "revision": int((post.source_detail or {}).get('revision', 1)),
        "source_detail": post.source_detail or {},
        "review_comment": post.review_comment,
        "reviewed_by": post.reviewed_by,
        "reviewed_at": _iso(post.reviewed_at),
        "publish_status": post.publish_status,
        "publish_external_id": post.publish_external_id,
        "published_at": _iso(post.published_at),
        "publish_target_environment_id": post.publish_target_environment_id,
        "scheduled_publish_at": _iso(post.scheduled_publish_at),
        "created_at": _iso(post.created_at),
        "updated_at": _iso(post.updated_at),
    }


def serialize_run(run: HermesWorkflowRun, *, include_posts: bool = False) -> dict[str, Any]:
    counts = post_counts(list(run.posts))
    parameters = dict(run.parameters or {})
    if not include_posts:
        parameters.pop('policy_snapshot', None)
    payload = {
        "id": run.id,
        "run_key": run.run_key,
        "source": run.source,
        "workflow_mode": getattr(run, 'workflow_mode', 'single' if run.source == 'manual' else 'batch'),
        "status": aggregate_status(list(run.posts), run.status),
        "name": parameters.get('name') or f"图文创作 · #{run.id}",
        "requested_by": run.requested_by,
        "schedule_id": run.schedule_id,
        "scheduled_for": _iso(run.scheduled_for),
        "parameters": parameters,
        "total_posts": counts['total'],
        "generated_posts": counts['generated'],
        "approved_posts": counts['approved'],
        "rejected_posts": counts['rejected'],
        "failed_posts": counts['failed'],
        "pending_review_posts": counts['pending_review'],
        "accounts": sorted({p.account_name for p in run.posts}),
        "vehicles": sorted({p.vehicle_model for p in run.posts}),
        "worker_id": run.worker_id,
        "error": run.error,
        "publish_requested_at": _iso(run.publish_requested_at),
        "started_at": _iso(run.started_at),
        "finished_at": _iso(run.finished_at),
        "created_at": _iso(run.created_at),
        "updated_at": _iso(run.updated_at),
    }
    if include_posts:
        payload["posts"] = [serialize_post(post) for post in sorted(run.posts, key=lambda row: (row.environment_id, row.slot))]
    return payload


def serialize_schedule(schedule: HermesWorkflowSchedule) -> dict[str, Any]:
    return {
        "id": schedule.id,
        "name": schedule.name,
        "enabled": bool(schedule.enabled),
        "run_time": schedule.run_time,
        "timezone": schedule.timezone,
        "posts_per_account": schedule.posts_per_account,
        "accounts": schedule.accounts or [],
        "instruction": schedule.instruction,
        "last_enqueued_for": _iso(schedule.last_enqueued_for),
        "last_run_id": schedule.last_run_id,
        "created_at": _iso(schedule.created_at),
        "updated_at": _iso(schedule.updated_at),
    }


class HermesWorkflowService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def assigned_environments(self, user_id: int) -> list[XHSEnvironment]:
        result = await self.db.execute(
            select(XHSEnvironment)
            .join(UserXHSEnvironment, UserXHSEnvironment.environment_id == XHSEnvironment.id)
            .where(
                UserXHSEnvironment.user_id == user_id,
                XHSEnvironment.status == "active",
            )
            .order_by(XHSEnvironment.account_name.asc())
        )
        return list(result.scalars().all())

    async def get_or_create_schedule(self, *, created_by: int | None = None) -> HermesWorkflowSchedule:
        schedule = (
            await self.db.execute(
                select(HermesWorkflowSchedule).where(HermesWorkflowSchedule.name == "Hermes 每日 8×5")
            )
        ).scalar_one_or_none()
        if schedule is None:
            try:
                async with self.db.begin_nested():
                    schedule = HermesWorkflowSchedule(
                        name="Hermes 每日 8×5",
                        enabled=False,
                        run_time="09:00",
                        posts_per_account=5,
                        accounts=[],
                        created_by=created_by,
                    )
                    self.db.add(schedule)
                    await self.db.flush()
            except IntegrityError:
                # Two freshly-started API workers can bootstrap the admin page
                # at the same time. The unique name is the authority; reuse the
                # row won by the other transaction instead of returning a 400.
                schedule = (
                    await self.db.execute(
                        select(HermesWorkflowSchedule).where(
                            HermesWorkflowSchedule.name == "Hermes 每日 8×5"
                        )
                    )
                ).scalar_one()
        return schedule

    async def validate_accounts(
        self,
        account_inputs: list[dict[str, Any]],
        *,
        owner_user_id: int | None = None,
    ) -> list[dict[str, Any]]:
        environment_ids = [int(item["environment_id"]) for item in account_inputs]
        if not environment_ids or len(environment_ids) != len(set(environment_ids)):
            raise HTTPException(status_code=400, detail="至少选择一个不重复的账号")
        result = await self.db.execute(
            select(XHSEnvironment).where(
                XHSEnvironment.id.in_(environment_ids),
                XHSEnvironment.status == "active",
            )
        )
        environments = {row.id: row for row in result.scalars().all()}
        if set(environments) != set(environment_ids):
            raise HTTPException(status_code=400, detail="所选账号不存在或已停用")
        owner_rows = await self.db.execute(
            select(UserXHSEnvironment.environment_id, UserXHSEnvironment.user_id).where(
                UserXHSEnvironment.environment_id.in_(environment_ids)
            )
        )
        owners = {int(environment_id): int(user_id) for environment_id, user_id in owner_rows.all()}
        if owner_user_id is not None:
            forbidden = [env_id for env_id in environment_ids if owners.get(env_id) != owner_user_id]
            if forbidden:
                raise HTTPException(status_code=403, detail="只能向自己负责的账号下发任务")

        normalized: list[dict[str, Any]] = []
        for item in account_inputs:
            environment_id = int(item["environment_id"])
            environment = environments[environment_id]
            normalized.append({
                "environment_id": environment_id,
                "account_name": environment.account_name,
                "owner_user_id": owners.get(environment_id),
                "vehicle_model": str(item.get("vehicle_model") or "").strip(),
                "case_id": str(item.get("case_id") or "").strip() or None,
            })
        return normalized

    async def create_run(
        self,
        *,
        source: str,
        requested_by: int | None,
        accounts: list[dict[str, Any]],
        posts_per_account: int,
        instruction: str | None = None,
        schedule_id: int | None = None,
        scheduled_for: date | None = None,
        name: str | None = None,
        copy_type: str | None = None,
        image_type: str | None = None,
        commit: bool = True,
    ) -> HermesWorkflowRun:
        account_plans: list[dict[str, Any]] = []
        from app.services.hermes_reference_types import validate_type, COPY_TYPES, IMAGE_TYPES, TAXONOMY_VERSION
        try:
            validate_type('copy', copy_type)
            validate_type('image', image_type)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        for account in accounts:
            post_count = int(account.get("post_count") or posts_per_account)
            if post_count < 1 or post_count > 5:
                raise HTTPException(status_code=400, detail="每个账号只能生成 1—5 篇")
            configured_models = [
                str(value).strip()
                for value in account.get("vehicle_models") or []
                if str(value).strip()
            ]
            if not configured_models:
                configured_models = [str(account.get("vehicle_model") or "").strip()]
            if not configured_models[0]:
                raise HTTPException(status_code=400, detail="生产车型不能为空")
            vehicle_models = [configured_models[index % len(configured_models)] for index in range(post_count)]
            account_plans.append({
                **account,
                "post_count": post_count,
                "vehicle_models": vehicle_models,
            })
        total_posts = sum(int(account["post_count"]) for account in account_plans)
        if total_posts > 40:
            raise HTTPException(status_code=400, detail="单次任务最多生成40篇")
        model_names = {model for account in account_plans for model in account['vehicle_models']}
        snapshots = [p for p in policy_summaries() if p['vehicle_model'] in model_names]
        if image_type in {'多配置报价单', 'quote_table'} and any(
            not any(p['vehicle_model'] == model and p.get('allow_multi_config_quote') and p.get('quote_rows') for p in snapshots)
            for model in model_names
        ):
            raise HTTPException(status_code=400, detail='所选车型缺少完整配置价格，不能下发多配置报价单任务')
        run = HermesWorkflowRun(
            run_key=f"hermes-{uuid.uuid4().hex[:20]}",
            source=source,
            status="queued",
            requested_by=requested_by,
            schedule_id=schedule_id,
            scheduled_for=scheduled_for,
            parameters={
                "accounts": account_plans,
                "posts_per_account": posts_per_account,
                "instruction": (instruction or "").strip(),
                "name": (name or '').strip() or f"{' · '.join(sorted(model_names))} · {total_posts}篇",
                "copy_type": copy_type,
                "image_type": image_type,
                "selection_contract": {
                    "version": TAXONOMY_VERSION,
                    "mode": "typed" if copy_type or image_type else "portfolio",
                    "copy_label": next((d['name'] for d in COPY_TYPES if d['id'] == copy_type), copy_type),
                    "image_label": next((d['name'] for d in IMAGE_TYPES if d['id'] == image_type), image_type),
                    "rule": "所选类型内挑选母版；文案与图片独立选型，不以随机回退替代指定类型",
                },
                "policy_snapshot": snapshots,
                "policy_snapshot_at": _iso(cst_now_naive()),
                "policy_fingerprint": hashlib.sha256(json.dumps(snapshots, sort_keys=True, ensure_ascii=False).encode()).hexdigest(),
            },
            total_posts=total_posts,
        )
        self.db.add(run)
        await self.db.flush()
        for account in account_plans:
            for slot, vehicle_model in enumerate(account["vehicle_models"], start=1):
                self.db.add(HermesWorkflowPost(
                    run_id=run.id,
                    environment_id=int(account["environment_id"]),
                    owner_user_id=account.get("owner_user_id"),
                    slot=slot,
                    account_name=str(account["account_name"]),
                    vehicle_model=str(vehicle_model),
                    case_id=account.get("case_id"),
                    status="queued",
                ))
        if commit:
            await self.db.commit()
        else:
            await self.db.flush()
        return await self.get_run(run.id)

    async def publish_candidates(
        self, user_id: int | None, *, page: int = 1, limit: int = 40,
        search: str | None = None, environment_id: int | None = None, planned: bool | None = None,
    ) -> tuple[list[HermesWorkflowPost], int]:
        filters = [HermesWorkflowPost.status.in_(["approved", "publish_ready"])]
        if user_id is not None:
            filters.append(HermesWorkflowPost.owner_user_id == user_id)
        if environment_id is not None:
            filters.append(HermesWorkflowPost.environment_id == environment_id)
        if search:
            filters.append(or_(
                HermesWorkflowPost.title.contains(search, autoescape=True),
                HermesWorkflowPost.account_name.contains(search, autoescape=True),
                HermesWorkflowPost.vehicle_model.contains(search, autoescape=True),
            ))
        if planned is not None:
            filters.append(HermesWorkflowPost.publish_status == 'scheduled' if planned else or_(
                HermesWorkflowPost.publish_status != 'scheduled', HermesWorkflowPost.publish_status.is_(None)))
        total = int((await self.db.execute(select(func.count()).select_from(HermesWorkflowPost).where(*filters))).scalar() or 0)
        result = await self.db.execute(select(HermesWorkflowPost).where(*filters)
            .order_by(HermesWorkflowPost.reviewed_at.desc(), HermesWorkflowPost.id.desc())
            .offset((page - 1) * limit).limit(limit))
        return list(result.scalars().all()), total

    async def save_publish_plan(
        self,
        *,
        user: User,
        items: list[dict[str, Any]],
        is_admin: bool = False,
    ) -> list[HermesWorkflowPost]:
        post_ids = [int(item["post_id"]) for item in items]
        if len(post_ids) != len(set(post_ids)):
            raise HTTPException(status_code=400, detail="同一篇内容不能重复排期")
        posts = list((await self.db.execute(
            select(HermesWorkflowPost).where(HermesWorkflowPost.id.in_(post_ids)).order_by(HermesWorkflowPost.id).with_for_update()
        )).scalars().all())
        post_map = {post.id: post for post in posts}
        if set(post_map) != set(post_ids):
            raise HTTPException(status_code=404, detail="部分待发布内容不存在")
        if not is_admin and any(post.owner_user_id != user.id for post in posts):
            raise HTTPException(status_code=403, detail="只能安排自己负责账号的内容")
        if any(post.status not in {"approved", "publish_ready"} for post in posts):
            raise HTTPException(status_code=409, detail="只有审核通过的内容可以进入发布计划")

        if any(not p.hard_pass or not p.title or not p.content or not p.image_url for p in posts):
            raise HTTPException(status_code=409, detail='内容或配图不完整，不能排期')
        environments = {row.id: row for row in (
            list((await self.db.execute(select(XHSEnvironment).where(XHSEnvironment.status == 'active'))).scalars().all())
            if is_admin else await self.assigned_environments(user.id)
        )}
        target_ids = {int(item["environment_id"]) for item in items}
        if not target_ids.issubset(environments):
            raise HTTPException(status_code=403, detail="发布账号必须是自己负责的账号")
        # Serialize schedules per target account, including different posts.
        await self.db.execute(select(XHSEnvironment.id).where(XHSEnvironment.id.in_(target_ids)).order_by(XHSEnvironment.id).with_for_update())

        affected_run_ids: set[int] = set()
        for item in items:
            post = post_map[int(item["post_id"])]
            await self.reserve_post(post, item.get('expected_version'))
            environment = environments[int(item["environment_id"])]
            try:
                scheduled_at = datetime.fromisoformat(str(item["scheduled_at"]).replace("Z", "+00:00"))
            except ValueError as exc:
                raise HTTPException(status_code=400, detail="发布时间格式无效") from exc
            if scheduled_at.tzinfo is not None:
                scheduled_at = scheduled_at.astimezone(ZoneInfo('Asia/Shanghai')).replace(tzinfo=None)
            if scheduled_at <= cst_now_naive():
                raise HTTPException(status_code=400, detail='发布时间必须晚于当前时间（北京时间）')
            conflict = await self.db.scalar(select(HermesWorkflowPost.id).where(
                HermesWorkflowPost.publish_target_environment_id == environment.id,
                HermesWorkflowPost.scheduled_publish_at == scheduled_at,
                HermesWorkflowPost.publish_status == 'scheduled',
                HermesWorkflowPost.id.not_in(post_ids),
            ).limit(1))
            if conflict or any(other.get('_time') == scheduled_at and other['environment_id'] == environment.id for other in items if other is not item):
                raise HTTPException(status_code=409, detail='同一账号在该时间已有排期，请调整时间')
            item['_time'] = scheduled_at
            self.append_event(post, 'schedule', user.id, '保存发布计划（未执行发布）')
            post.publish_target_environment_id = environment.id
            post.scheduled_publish_at = scheduled_at
            post.status = "approved"
            post.publish_status = "scheduled"
            affected_run_ids.add(post.run_id)

        for run_id in affected_run_ids:
            await self.recalculate(await self.get_run(run_id))
        await self.db.commit()
        return [post_map[post_id] for post_id in post_ids]

    @staticmethod
    def history_modes():
        """Classify by the original entry point, not post count or selected types.

        Legacy regenerations inherit their root task's module without rewriting
        history. IDs increase along the lineage, bounding malformed/cyclic data.
        """
        table = HermesWorkflowRun.__table__
        modes = select(
            table.c.id.label('run_id'),
            case((table.c.source == 'manual', 'single'), else_='batch').label('mode'),
        ).where(table.c.source != 'regeneration').cte('hermes_history_modes', recursive=True)
        child = table.alias('history_child')
        return modes.union_all(select(child.c.id, modes.c.mode).join(
            modes, child.c.parameters['regeneration']['run_id'].as_integer() == modes.c.run_id,
        ).where(child.c.source == 'regeneration', child.c.id > modes.c.run_id))

    async def get_run(self, run_id: int, *, lock: bool = False) -> HermesWorkflowRun:
        statement = (select(HermesWorkflowRun).options(selectinload(HermesWorkflowRun.posts))
                     .where(HermesWorkflowRun.id == run_id))
        if lock:
            statement = statement.with_for_update()
        run = (await self.db.execute(statement)).scalar_one_or_none()
        if run is None:
            raise HTTPException(status_code=404, detail="任务不存在")
        if run.source == 'regeneration':
            modes = self.history_modes()
            run.workflow_mode = await self.db.scalar(select(modes.c.mode).where(modes.c.run_id == run.id)) or 'batch'
        return run

    async def list_runs(
        self,
        *,
        user_id: int | None,
        status: str | None,
        page: int,
        limit: int,
        search: str | None = None,
        source: str | None = None,
        workflow_mode: str | None = None,
        environment_id: int | None = None,
        date_from: date | None = None,
        date_to: date | None = None,
    ) -> tuple[list[HermesWorkflowRun], int]:
        conditions = []
        modes = self.history_modes()
        mode = func.coalesce(modes.c.mode, 'batch')
        if workflow_mode:
            if workflow_mode not in {'batch', 'single'}:
                raise HTTPException(status_code=400, detail='不支持的创作模块')
            conditions.append(mode == workflow_mode)
        visible_posts = select(HermesWorkflowPost.run_id)
        if user_id is not None:
            visible_posts = visible_posts.where(HermesWorkflowPost.owner_user_id == user_id)
        if status:
            post_states = {
                'running': ACTIVE_GENERATION_STATUSES, 'review_pending': {'review_pending'},
                'approved': {'approved', 'publish_ready', 'published'},
                'failed': {'generation_failed'}, 'changes_requested': {'rejected'},
                'cancelled': {'cancelled'},
            }.get(status)
            conditions.append(HermesWorkflowRun.id.in_(visible_posts.where(HermesWorkflowPost.status.in_(post_states))) if post_states else HermesWorkflowRun.status == status)
        if search:
            term = f"%{search.strip()}%"
            conditions.append(or_(
                HermesWorkflowRun.run_key.ilike(term),
                HermesWorkflowRun.parameters['name'].as_string().ilike(term),
                HermesWorkflowRun.id.in_(visible_posts.where(or_(
                    HermesWorkflowPost.account_name.ilike(term), HermesWorkflowPost.vehicle_model.ilike(term),
                    HermesWorkflowPost.title.ilike(term),
                ))),
            ))
        if source:
            conditions.append(HermesWorkflowRun.source == source)
        if environment_id is not None:
            conditions.append(HermesWorkflowRun.id.in_(visible_posts.where(HermesWorkflowPost.environment_id == environment_id)))
        if date_from:
            conditions.append(HermesWorkflowRun.created_at >= datetime.combine(date_from, datetime.min.time()))
        if date_to:
            conditions.append(HermesWorkflowRun.created_at < datetime.combine(date_to + timedelta(days=1), datetime.min.time()))
        if user_id is not None:
            visible_run_ids = select(HermesWorkflowPost.run_id).where(HermesWorkflowPost.owner_user_id == user_id)
            conditions.append(or_(
                HermesWorkflowRun.requested_by == user_id,
                HermesWorkflowRun.id.in_(visible_run_ids),
            ))
        count = int((await self.db.scalar(
            select(func.count(HermesWorkflowRun.id)).outerjoin(modes, modes.c.run_id == HermesWorkflowRun.id).where(*conditions)
        )) or 0)
        rows = await self.db.execute(
            select(HermesWorkflowRun, mode)
            .outerjoin(modes, modes.c.run_id == HermesWorkflowRun.id)
            .options(selectinload(HermesWorkflowRun.posts).defer(HermesWorkflowPost.source_detail).defer(HermesWorkflowPost.content))
            .where(*conditions)
            .order_by(HermesWorkflowRun.created_at.desc(), HermesWorkflowRun.id.desc())
            .offset((page - 1) * limit)
            .limit(limit)
        )
        result = []
        for run, run_mode in rows.all():
            run.workflow_mode = run_mode
            result.append(run)
        return result, count

    async def user_run(self, run_id: int, user_id: int) -> HermesWorkflowRun:
        run = await self.get_run(run_id)
        if run.requested_by == user_id or any(post.owner_user_id == user_id for post in run.posts):
            return run
        raise HTTPException(status_code=403, detail="无权查看该任务")

    async def review_post(
        self,
        *,
        post_id: int,
        reviewer: User,
        action: str,
        comment: str | None,
        is_admin: bool,
        expected_version: str | None = None,
        regenerate: bool = False,
    ) -> HermesWorkflowRun:
        post = await self.db.scalar(select(HermesWorkflowPost).where(HermesWorkflowPost.id == post_id).with_for_update())
        if post is None:
            raise HTTPException(status_code=404, detail="帖子不存在")
        if not is_admin and post.owner_user_id != reviewer.id:
            raise HTTPException(status_code=403, detail="只能审核自己负责账号的帖子")
        if post.status not in REVIEWABLE_STATUSES:
            raise HTTPException(status_code=409, detail="帖子尚未生成完成，当前不能审核")
        if action not in {'approve', 'reject'} or (regenerate and (action != 'reject' or not expected_version)):
            raise HTTPException(status_code=400, detail='重新生成仅用于不通过操作，且必须提供当前版本')
        await self.reserve_post(post, expected_version)
        if action == 'approve' and (not post.hard_pass or not post.title or not post.content or not post.image_url):
            raise HTTPException(status_code=409, detail='图文不完整或存在硬错误，不能通过审核')
        if action == 'reject' and not (comment or '').strip():
            raise HTTPException(status_code=400, detail='请填写具体修改意见')
        if regenerate:
            previous_id = (post.source_detail or {}).get('latest_regeneration', {}).get('run_id')
            previous = await self.db.get(HermesWorkflowRun, previous_id) if previous_id else None
            if previous and previous.status in ACTIVE_GENERATION_STATUSES:
                raise HTTPException(status_code=409, detail=f'这一篇已有重生任务 #{previous.id} 正在排队或生产，请勿重复提交')
        self.append_event(post, action, reviewer.id, comment, actor_name=reviewer.display_name or reviewer.username)
        if action == 'reject':
            self.clear_publish_plan(post)
        post.status = "approved" if action == "approve" else "rejected"
        post.review_comment = (comment or "").strip() or None
        post.reviewed_by = reviewer.id
        post.reviewed_at = cst_now_naive()
        run = await self.get_run(post.run_id)
        if regenerate:
            await self.queue_post_regeneration(post, run, reviewer, (comment or '').strip(), is_admin=is_admin)
        await self.recalculate(run)
        await self.db.commit()
        return await self.get_run(run.id)

    async def queue_post_regeneration(self, post: HermesWorkflowPost, original: HermesWorkflowRun,
                                      reviewer: User, reason: str, *, is_admin: bool) -> None:
        """Enqueue exactly one new post in the same transaction as its rejection."""
        accounts = await self.validate_accounts([{'environment_id': post.environment_id, 'vehicle_model': post.vehicle_model}],
                                                owner_user_id=None if is_admin else reviewer.id)
        if not accounts[0].get('owner_user_id'):
            raise HTTPException(status_code=409, detail='账号需先分配负责人，才能重新生成')
        params = original.parameters or {}
        # Do not recursively append previous retry prompts through a regeneration chain.
        original_instruction = (params.get('regeneration') or {}).get('original_instruction', params.get('instruction') or '')
        context = {'title': post.title, 'content': post.content}
        instruction = (
            f"原创作偏好：{original_instruction or '无'}\n"
            f"用户审核不通过，要求重新生成这一篇图文。具体原因：{reason}\n"
            "请针对审核指出的问题调整；保持本次账号、车型与图文类型，事实仍只取当前政策和车型资料。"
            "以下旧稿只是被退回的问题上下文，不能作为政策、价格、参数依据，也不要直接重复旧稿：\n"
            f"{json.dumps(context, ensure_ascii=False)}"
        )
        regenerated = await self.create_run(
            source='regeneration', requested_by=reviewer.id, accounts=accounts, posts_per_account=1,
            instruction=instruction, name=f'{post.vehicle_model} · 单篇重生',
            copy_type=params.get('copy_type'), image_type=params.get('image_type'), commit=False,
        )
        lineage = {'post_id': post.id, 'run_id': original.id, 'revision': int((post.source_detail or {}).get('revision', 1)),
                   'reason': reason, 'requested_by': reviewer.id, 'requested_at': _iso(cst_now_naive()),
                   'original_instruction': original_instruction}
        regenerated.parameters = {**regenerated.parameters, 'regeneration': lineage}
        for child in regenerated.posts:
            child.source_detail = {'regenerated_from': lineage}
        self.append_event(post, 'regenerate', reviewer.id, reason, actor_name=reviewer.display_name or reviewer.username,
                          details={'regenerated_run_id': regenerated.id})
        post.source_detail = {**post.source_detail, 'latest_regeneration': {'run_id': regenerated.id, 'revision': lineage['revision']}}

    @staticmethod
    def check_version(post: HermesWorkflowPost, expected: str | None) -> None:
        if expected and expected != post_version(post):
            raise HTTPException(status_code=409, detail='这篇内容已发生变化，请刷新后再操作')

    async def reserve_post(self, post: HermesWorkflowPost, expected: str | None) -> None:
        """Optimistic write reservation also works on SQLite (which ignores FOR UPDATE)."""
        self.check_version(post, expected)
        previous = post.updated_at
        now = cst_now_naive()
        stamp_matches = HermesWorkflowPost.updated_at == previous if previous is not None else HermesWorkflowPost.updated_at.is_(None)
        if previous is not None and previous.microsecond == 0:
            # SQLite CURRENT_TIMESTAMP legacy rows omit the fractional suffix.
            stamp_matches = or_(stamp_matches, HermesWorkflowPost.updated_at.cast(String) == previous.isoformat(sep=' ', timespec='seconds'))
        try:
            result = await self.db.execute(update(HermesWorkflowPost).where(
                HermesWorkflowPost.id == post.id,
                stamp_matches,
            ).values(updated_at=now))
        except OperationalError as exc:
            if 'locked' not in str(exc).lower():
                raise
            raise HTTPException(status_code=409, detail='内容正在被其他操作更新，请刷新后重试') from exc
        if result.rowcount != 1:
            raise HTTPException(status_code=409, detail='内容已被其他操作更新，请刷新后重试')

    @staticmethod
    def clear_publish_plan(post: HermesWorkflowPost) -> None:
        post.publish_status = 'not_requested'
        post.publish_target_environment_id = None
        post.scheduled_publish_at = None

    @staticmethod
    def append_event(post: HermesWorkflowPost, action: str, user_id: int, comment: str | None,
                     *, actor_name: str | None = None, details: dict[str, Any] | None = None) -> None:
        detail = dict(post.source_detail or {})
        event = {
            'action': action, 'user_id': user_id, 'at': _iso(cst_now_naive()),
            'comment': comment or '', 'revision': int(detail.get('revision', 1)),
            'before_status': post.status,
            'user_name': actor_name,
            **(details or {}),
        }
        if action == 'edit':
            event.update({'title': post.title, 'content': post.content, 'image_url': post.image_url})
            detail['revision'] = int(detail.get('revision', 1)) + 1
        detail['events'] = [*(detail.get('events') or []), event]
        post.source_detail = detail

    async def edit_post(self, post_id: int, user: User, *, title: str, content: str,
                        comment: str, expected_version: str, is_admin: bool = False) -> HermesWorkflowPost:
        post = await self.db.scalar(select(HermesWorkflowPost).where(HermesWorkflowPost.id == post_id).with_for_update())
        if post is None:
            raise HTTPException(status_code=404, detail='帖子不存在')
        if not is_admin and post.owner_user_id != user.id:
            raise HTTPException(status_code=403, detail='只能修改自己负责账号的帖子')
        if post.status not in REVIEWABLE_STATUSES:
            raise HTTPException(status_code=409, detail='只能编辑已生成且未发布的内容')
        self.check_version(post, expected_version)
        changes = {field: text_change(getattr(post, field), value) for field, value in [('title', title), ('content', content)] if getattr(post, field) != value}
        if not changes:
            raise HTTPException(status_code=400, detail='标题和正文没有改动，无需保存新版本')
        await self.reserve_post(post, expected_version)
        self.append_event(post, 'edit', user.id, comment, actor_name=user.display_name or user.username,
                          details={'changes': changes, 'result_revision': int((post.source_detail or {}).get('revision', 1)) + 1,
                                   'after_title': title, 'after_content': content})
        post.title, post.content = title, content
        post.status = 'review_pending'
        post.review_comment = comment
        post.reviewed_at = None
        post.reviewed_by = None
        # Manual edits are explicitly unreviewed; the existing image/OCR result
        # is retained, never presented as a fresh machine validation of the edit.
        post.source_detail = {**post.source_detail, 'manual_edit_requires_review': True}
        self.clear_publish_plan(post)
        await self.recalculate(await self.get_run(post.run_id))
        await self.db.commit()
        return post

    async def cancel_queued(self, run_id: int, user: User, *, is_admin: bool = False) -> HermesWorkflowRun:
        run = await self.db.scalar(select(HermesWorkflowRun).where(HermesWorkflowRun.id == run_id).with_for_update())
        if run is None:
            raise HTTPException(status_code=404, detail='任务不存在')
        if not is_admin and (run.requested_by != user.id or any(p.owner_user_id != user.id for p in run.posts)):
            raise HTTPException(status_code=403, detail='只能取消自己下发的完整任务')
        if run.status != 'queued':
            raise HTTPException(status_code=409, detail='任务已经开始执行，不能以取消排队的方式中断')
        for post in run.posts:
            post.status = 'cancelled'
        run.status = 'cancelled'
        run.finished_at = cst_now_naive()
        run.updated_at = cst_now_naive()
        await self.db.commit()
        return await self.get_run(run.id)

    async def recalculate(self, run: HermesWorkflowRun) -> None:
        posts = list(run.posts)
        run.total_posts = len(posts)
        run.generated_posts = sum(post.status in GENERATED_STATUSES for post in posts)
        run.approved_posts = sum(post.status in {"approved", "publish_ready", "published"} for post in posts)
        run.rejected_posts = sum(post.status == "rejected" for post in posts)
        run.status = aggregate_status(posts, run.status)
        if run.worker_id and run.finished_at is None and run.status not in {'queued', 'cancelled'}:
            run.status = 'running'  # Keep the producer lease until its final acknowledgement.
        run.updated_at = cst_now_naive()

    async def claim_next(self, worker_id: str) -> HermesWorkflowRun | None:
        # A crashed external Worker must not leave a run stuck forever. A run is
        # reclaimable only when both its start time and its worker heartbeat are
        # stale, which avoids stealing a long-running but healthy image batch.
        now = cst_now_naive()
        stale_cutoff = now - timedelta(minutes=10)
        stale_runs = list((await self.db.execute(
            select(HermesWorkflowRun).where(
                HermesWorkflowRun.status == "running",
                HermesWorkflowRun.started_at < stale_cutoff,
            )
        )).scalars().all())
        if stale_runs:
            stale_worker_ids = {str(row.worker_id) for row in stale_runs if row.worker_id}
            worker_rows = list((await self.db.execute(
                select(HermesWorkerState).where(HermesWorkerState.worker_id.in_(stale_worker_ids))
            )).scalars().all()) if stale_worker_ids else []
            live_workers = {
                row.worker_id for row in worker_rows if row.last_seen_at and row.last_seen_at >= stale_cutoff
            }
            recovered = False
            for stale_run in stale_runs:
                if stale_run.worker_id and stale_run.worker_id in live_workers:
                    continue
                stale_run.status = "queued"
                stale_run.worker_id = None
                stale_run.started_at = None
                for post in stale_run.posts:
                    if post.status in ACTIVE_GENERATION_STATUSES:
                        post.status = "queued"
                recovered = True
            if recovered:
                await self.db.commit()

        statement = (
            select(HermesWorkflowRun)
            .options(selectinload(HermesWorkflowRun.posts))
            .where(HermesWorkflowRun.status == "queued")
            .order_by(HermesWorkflowRun.created_at.asc(), HermesWorkflowRun.id.asc())
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        run = (await self.db.execute(statement)).scalar_one_or_none()
        if run is None:
            return None
        now = cst_now_naive()
        run.status = "running"
        run.worker_id = worker_id
        run.started_at = now
        for post in run.posts:
            if post.status in ACTIVE_GENERATION_STATUSES:
                post.status = "generating"
        await self.db.commit()
        return await self.get_run(run.id)

    async def heartbeat_worker(
        self,
        *,
        worker_id: str,
        status: str,
        current_run_id: int | None,
        capabilities: dict[str, Any] | None = None,
    ) -> HermesWorkerState:
        worker = (
            await self.db.execute(
                select(HermesWorkerState).where(HermesWorkerState.worker_id == worker_id)
            )
        ).scalar_one_or_none()
        if worker is None:
            worker = HermesWorkerState(worker_id=worker_id)
            self.db.add(worker)
        worker.status = status
        worker.current_run_id = current_run_id
        if capabilities is not None:
            worker.capabilities = capabilities
        worker.last_seen_at = cst_now_naive()
        await self.db.commit()
        await self.db.refresh(worker)
        return worker

    async def ingest_generated_post(self, run: HermesWorkflowRun, post: HermesWorkflowPost,
                                    item: dict[str, Any], *, require_ready: bool = False) -> None:
        title = str(item.get("title") or "").strip() or None
        content = str(item.get("content") or "").strip() or None
        image_url = str(item.get("image_url") or item.get("local_image") or "").strip() or None
        delivered_model = str(item.get('vehicle_model') or post.vehicle_model)
        errors = []
        if delivered_model != post.vehicle_model:
            errors.append(f'交付车型 {delivered_model} 与任务车型 {post.vehicle_model} 不一致')
        if not title or not content or not image_url or not image_url.startswith(('http://', 'https://', '/api/', '/uploads/')):
            errors.append('交付缺少标题、正文或可访问配图')
        hard_pass = item.get("hard_pass") is True and not errors
        if require_ready and not hard_pass:
            raise HTTPException(status_code=400, detail='；'.join(errors) or '逐篇交付必须通过完整图文检查')
        source_detail = {key: item[key] for key in (
            "mother_copy_id", "mother_title", "mother_content", "selected_prompt_id",
            "selected_prompt_original", "selected_prompt_image", "image_template_type",
            "image_text_blocks", "slot_mappings", "adapted_prompt", "scene_change",
            "vehicle_image", "image_task_id", "ocr_lines", "ocr_config_comparison", "copy_validation",
            "account_history", "account_repetition", "stage_timings",
        ) if item.get(key) is not None}
        if errors:
            source_detail['error'] = '；'.join(errors)
        if (run.parameters or {}).get('regeneration'):
            source_detail['regenerated_from'] = run.parameters['regeneration']
        # Conditional update makes first delivery win, including concurrent
        # retries. Never overwrite a post already exposed for review or editing.
        await self.db.execute(
            update(HermesWorkflowPost).where(
                HermesWorkflowPost.id == post.id,
                HermesWorkflowPost.status.in_(ACTIVE_GENERATION_STATUSES | {'generation_failed'}),
            ).values(title=title, content=content, image_url=image_url,
                     case_id=str(item.get("case_id") or post.case_id or "").strip() or None,
                     hard_pass=bool(hard_pass), source_detail=source_detail,
                     status="review_pending" if hard_pass else "generation_failed")
            .execution_options(synchronize_session=False)
        )
        await self.db.refresh(post)

    async def progress_run(self, run_id: int, delivery: dict[str, Any], *, worker_id: str) -> HermesWorkflowRun:
        run = await self.get_run(run_id, lock=True)
        if run.worker_id != worker_id:
            raise HTTPException(status_code=409, detail="任务已被其他 Worker 接管")
        if run.finished_at is not None:
            return run  # A late partial snapshot cannot reopen a terminal run.
        if run.status != 'running':
            raise HTTPException(status_code=409, detail="任务不在生产中")
        indexed = {(post.environment_id, post.slot): post for post in run.posts}
        seen = set()
        for item in delivery.get('posts') or []:
            if not isinstance(item, dict):
                raise HTTPException(status_code=400, detail="逐篇交付格式错误")
            try:
                key = (int(item.get('account_id') or 0), int(item.get('slot') or 0))
            except (ValueError, TypeError):
                raise HTTPException(status_code=400, detail="逐篇交付账号或篇序号错误")
            if key not in indexed or key in seen:
                raise HTTPException(status_code=400, detail="逐篇交付包含非本任务帖子或重复篇序号")
            seen.add(key)
            post = indexed[key]
            if post.status in GENERATED_STATUSES:
                continue
            await self.ingest_generated_post(run, post, item, require_ready=True)
        await self.recalculate(run)
        # No finished_at, failure marking for missing siblings, or worker idle
        # heartbeat here. The producer is still running the remaining posts.
        await self.db.commit()
        return await self.get_run(run.id)

    async def complete_run(
        self,
        run_id: int,
        delivery: dict[str, Any],
        *,
        worker_id: str,
    ) -> HermesWorkflowRun:
        run = await self.get_run(run_id, lock=True)
        if run.worker_id == worker_id and run.finished_at is not None and run.output_manifest:
            # Idempotent repeats return immediately, but allow the same worker
            # to monotonically replace a partial/failed manifest with a later
            # fully recovered delivery (for example after switching the one
            # image template whose upstream request failed).
            previous_ready = bool((run.output_manifest or {}).get("production_ready"))
            incoming_ready = bool(delivery.get("production_ready"))
            if previous_ready or not incoming_ready:
                return run
        if run.worker_id != worker_id or run.status not in {"running", "failed", "partial_failed"}:
            raise HTTPException(status_code=409, detail="任务已被其他 Worker 接管或不再运行")
        indexed = {
            (int(item.get("account_id") or 0), int(item.get("slot") or 0)): item
            for item in delivery.get("posts") or []
            if isinstance(item, dict)
        }
        for post in run.posts:
            if post.status in GENERATED_STATUSES or (post.source_detail or {}).get('manual_edit_requires_review'):
                continue  # A delayed worker callback must not overwrite reviewed/edited content.
            item = indexed.get((post.environment_id, post.slot))
            if item is None:
                post.status = "generation_failed"
                post.source_detail = {**(post.source_detail or {}), "error": "Hermes 交付清单缺少该帖子"}
                continue
            await self.ingest_generated_post(run, post, item)
        run.output_manifest = {**delivery, 'production_ready': all(p.hard_pass and p.status in GENERATED_STATUSES for p in run.posts)}
        run.finished_at = cst_now_naive()
        run.error = None if delivery.get("production_ready") else str(delivery.get("error") or "部分内容未通过硬校验")
        await self.recalculate(run)
        if any(p.status == 'generation_failed' for p in run.posts):
            run.error = run.error or '部分内容交付不完整或车型不一致'
        await self.db.commit()
        return await self.get_run(run.id)

    async def fail_run(self, run_id: int, error: str, *, worker_id: str) -> HermesWorkflowRun:
        run = await self.get_run(run_id)
        if run.worker_id == worker_id and run.status == "failed" and run.finished_at is not None:
            return run
        if run.worker_id != worker_id or run.status != "running":
            raise HTTPException(status_code=409, detail="任务已被其他 Worker 接管或不再运行")
        run.status = "failed"
        run.error = error
        run.finished_at = cst_now_naive()
        for post in run.posts:
            if post.status in ACTIVE_GENERATION_STATUSES:
                post.status = "generation_failed"
        await self.recalculate(run)
        await self.db.commit()
        return await self.get_run(run.id)

    async def prepare_publish(self, run_id: int) -> tuple[HermesWorkflowRun, dict[str, Any]]:
        run = await self.get_run(run_id)
        candidates = [p for p in run.posts if p.status in {'approved', 'publish_ready'} and p.hard_pass and p.title and p.content and p.image_url]
        if not candidates:
            raise HTTPException(status_code=409, detail="没有已审核通过的完整图文")
        now = cst_now_naive()
        manifest = {
            "adapter": "reserved",
            "executed": False,
            "message": "发布接口待接入，当前仅生成发布清单",
            "posts": [
                {
                    "post_id": post.id,
                    "environment_id": post.publish_target_environment_id or post.environment_id,
                    "scheduled_at": _iso(post.scheduled_publish_at),
                    "version": post_version(post),
                    "title": post.title,
                    "content": post.content,
                    "image_urls": [post.image_url] if post.image_url else [],
                }
                for post in candidates
            ],
        }
        # Export is a draft only. Approval and saved scheduling are unchanged.
        run.publish_requested_at = now
        run.output_manifest = {**(run.output_manifest or {}), "publish_manifest": manifest}
        await self.recalculate(run)
        await self.db.commit()
        return await self.get_run(run.id), manifest

    async def update_schedule(
        self,
        *,
        schedule: HermesWorkflowSchedule,
        enabled: bool,
        run_time: str,
        posts_per_account: int,
        accounts: list[dict[str, Any]],
        instruction: str | None,
    ) -> HermesWorkflowSchedule:
        if enabled and (len(accounts) != 8 or posts_per_account != 5):
            raise HTTPException(status_code=400, detail="正式定时任务必须配置8个账号、每个账号5篇")
        if enabled and any(not account.get("owner_user_id") for account in accounts):
            raise HTTPException(status_code=400, detail="定时任务中的8个账号都必须先分配负责人")
        schedule.enabled = enabled
        schedule.run_time = run_time
        schedule.posts_per_account = posts_per_account
        schedule.accounts = accounts
        schedule.instruction = (instruction or "").strip() or None
        await self.db.commit()
        await self.db.refresh(schedule)
        return schedule

    async def enqueue_schedule(
        self,
        schedule: HermesWorkflowSchedule,
        *,
        for_date: date,
        requested_by: int | None,
    ) -> HermesWorkflowRun:
        existing = (
            await self.db.execute(
                select(HermesWorkflowRun).where(
                    HermesWorkflowRun.schedule_id == schedule.id,
                    HermesWorkflowRun.scheduled_for == for_date,
                    HermesWorkflowRun.source == "schedule",
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            return await self.get_run(existing.id)
        accounts = await self.validate_accounts(list(schedule.accounts or []))
        run = await self.create_run(
            source="schedule",
            requested_by=requested_by,
            accounts=accounts,
            posts_per_account=int(schedule.posts_per_account or 5),
            instruction=schedule.instruction,
            schedule_id=schedule.id,
            scheduled_for=for_date,
        )
        schedule.last_enqueued_for = for_date
        schedule.last_run_id = run.id
        await self.db.commit()
        return run


async def enqueue_due_hermes_runs(db: AsyncSession, *, now: datetime | None = None) -> list[int]:
    current = now or cst_now_naive()
    rows = await db.execute(
        select(HermesWorkflowSchedule).where(HermesWorkflowSchedule.enabled.is_(True))
    )
    created: list[int] = []
    service = HermesWorkflowService(db)
    for schedule in rows.scalars().all():
        try:
            hour, minute = map(int, str(schedule.run_time or "09:00").split(":"))
        except (TypeError, ValueError):
            continue
        if current.time() < current.replace(hour=hour, minute=minute, second=0, microsecond=0).time():
            continue
        if schedule.last_enqueued_for == current.date():
            continue
        run = await service.enqueue_schedule(schedule, for_date=current.date(), requested_by=schedule.created_by)
        created.append(run.id)
    return created
