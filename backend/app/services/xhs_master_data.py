"""Canonical account reads and legacy API compatibility, without browser identities."""

from datetime import date, datetime, time, timedelta
from types import SimpleNamespace

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import settings
from app.models.user import User
from app.models.xhs_account import XHSAccount, XHSAccountMasterImport
from app.models.xhs_account_note import XHSAccountNote
from app.models.xhs_account_note_browse_event import XHSAccountNoteBrowseEvent
from app.services.xhs_account_master_service import XHSAccountMasterService, digest
from app.utils.timezone import CST, UTC


def master_enabled() -> bool:
    return settings.xhs_account_master_enabled


async def master_ready(db: AsyncSession) -> bool:
    return bool(
        await db.scalar(
            select(XHSAccountMasterImport.id)
            .where(
                XHSAccountMasterImport.status == "applied",
                XHSAccountMasterImport.result["authoritative_roster"]
                .as_boolean()
                .is_(True),
            )
            .limit(1)
        )
    )


async def require_master(db: AsyncSession) -> None:
    if not await master_ready(db):
        raise ValueError("飞书主名单尚未完整初始化，请管理员先确认导入完整名单")


def account_scope(user: User):
    return select(XHSAccount.id).where(
        XHSAccountMasterService.visibility(user), XHSAccount.status != "archived"
    )


def note_scope(user: User):
    return XHSAccountNote.account_id.in_(account_scope(user))


def account_owner_role(department: str, roles: list[str]) -> str:
    from app.core.roles import ROLE_BRAND_LEAD, ROLE_XHS_LEAD

    if department == "brand":
        return "brand_lead" if ROLE_BRAND_LEAD in roles else "brand_ops"
    return "xhs_lead" if ROLE_XHS_LEAD in roles else "xhs_ops"


class XHSMasterData:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def query(
        self,
        user: User,
        *,
        page=1,
        limit=20,
        account_id=None,
        keyword=None,
        ai_origin_type=None,
        status=None,
        start_date: date | None = None,
        end_date: date | None = None,
        insights=False,
    ):
        await require_master(self.db)
        conditions = [note_scope(user)]
        if account_id is not None:
            conditions.append(XHSAccountNote.account_id == account_id)
        if status and status != "all":
            conditions.append(XHSAccountNote.status == status)
        if ai_origin_type and ai_origin_type != "all":
            conditions.append(
                or_(
                    XHSAccountNote.ai_origin_type.is_(None),
                    XHSAccountNote.ai_origin_type == "",
                )
                if ai_origin_type == "__unset__"
                else XHSAccountNote.ai_origin_type == ai_origin_type
            )
        if keyword and keyword.strip():
            pattern = f"%{keyword.strip()}%"
            conditions.append(
                or_(
                    XHSAccountNote.title.ilike(pattern),
                    XHSAccountNote.feed_id.ilike(pattern),
                    XHSAccountNote.red_id.ilike(pattern),
                )
            )
        if (
            start_date
            and end_date
            and (end_date < start_date or (end_date - start_date).days > 366)
        ):
            raise ValueError("账号数据日期范围无效")
        if start_date:
            conditions.append(
                XHSAccountNote.published_at
                >= datetime.combine(start_date, time.min, CST)
                .astimezone(UTC)
                .replace(tzinfo=None)
            )
        if end_date:
            conditions.append(
                XHSAccountNote.published_at
                < datetime.combine(end_date + timedelta(days=1), time.min, CST)
                .astimezone(UTC)
                .replace(tzinfo=None)
            )
        total = int(
            await self.db.scalar(
                select(func.count()).select_from(XHSAccountNote).where(*conditions)
            )
            or 0
        )
        count = int(
            await self.db.scalar(
                select(func.count(func.distinct(XHSAccountNote.account_id))).where(
                    *conditions
                )
            )
            or 0
        )
        notes = list(
            (
                await self.db.scalars(
                    select(XHSAccountNote)
                    .where(*conditions)
                    .options(selectinload(XHSAccountNote.assigned_runner_environment))
                    .order_by(
                        XHSAccountNote.published_at.desc().nullslast(),
                        XHSAccountNote.id.desc(),
                    )
                    .offset((page - 1) * limit)
                    .limit(limit)
                )
            ).all()
        )
        from app.services.xhs_service import XHSService

        await XHSService(self.db)._attach_paid_report_flags(
            notes, start_date=start_date, end_date=end_date, resolve_from_reports=False
        )
        if notes and not insights:
            today = datetime.now(CST).date()
            day_start = (
                datetime.combine(today, time.min, CST)
                .astimezone(UTC)
                .replace(tzinfo=None)
            )
            counts = dict(
                (
                    await self.db.execute(
                        select(
                            XHSAccountNoteBrowseEvent.note_id,
                            func.count(XHSAccountNoteBrowseEvent.id),
                        )
                        .where(
                            XHSAccountNoteBrowseEvent.note_id.in_(
                                [n.id for n in notes]
                            ),
                            XHSAccountNoteBrowseEvent.created_at >= day_start,
                            XHSAccountNoteBrowseEvent.created_at
                            < day_start + timedelta(days=1),
                        )
                        .group_by(XHSAccountNoteBrowseEvent.note_id)
                    )
                ).all()
            )
            for note in notes:
                note.today_browse_count = int(counts.get(note.id, 0))
        projected = await self.project(notes, user=user)
        return projected, total, count

    async def project(
        self, notes: list[XHSAccountNote], *, user: User | None = None
    ) -> list[SimpleNamespace]:
        from app.core.roles import get_user_roles

        rows = (
            await self.db.execute(
                select(XHSAccount, User)
                .options(selectinload(User.role_assignments))
                .outerjoin(User, User.id == XHSAccount.owner_user_id)
                .where(XHSAccount.id.in_({n.account_id for n in notes}))
                .where(
                    XHSAccount.id.in_(account_scope(user)) if user is not None else True
                )
                .execution_options(populate_existing=True)
            )
        ).all()
        accounts = {a.id: (a, u) for a, u in rows}
        result = []
        for note in notes:
            if note.account_id not in accounts:
                continue
            account, owner = accounts[note.account_id]
            values = {
                column.name: getattr(note, column.name)
                for column in XHSAccountNote.__table__.columns
            }
            values.update(
                account_name=account.account_name,
                profile_nickname=account.account_name,
                red_id=account.xhs_account_id,
                account_department=account.department,
                master_revision=account.revision,
                owner_user_id=account.owner_user_id,
                owner_username=(owner.display_name or owner.username)
                if owner
                else None,
                owner_role=account_owner_role(account.department, get_user_roles(owner))
                if owner
                else "unassigned",
                assigned_runner_account_name=note.assigned_runner_account_name,
            )
            for field in ("has_paid_report", "has_creative_report"):
                values[field] = getattr(note, field, False)
            values["today_browse_count"] = getattr(note, "today_browse_count", 0)
            if note.published_at:
                values["insights_published_at"] = (
                    note.published_at.replace(tzinfo=UTC)
                    .astimezone(CST)
                    .replace(tzinfo=None)
                )
            result.append(SimpleNamespace(**values))
        return result

    @staticmethod
    def dashboard(items, *, start_date=None, end_date=None):
        from app.services.xhs_service import XHSService

        namespace = digest(
            sorted(
                {
                    (n.account_id, n.master_revision, n.account_name, n.owner_user_id)
                    for n in items
                }
            )
        )
        return XHSService.build_insights_dashboard(
            items,
            start_date=start_date,
            end_date=end_date,
            cache_namespace="master-cutover:" + namespace,
        )
