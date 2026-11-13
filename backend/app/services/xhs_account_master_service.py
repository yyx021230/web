"""Reviewed master imports and independent account visibility; no browser operations."""

from __future__ import annotations

import csv
from datetime import timedelta
import hashlib
import io
import json
import re
from types import SimpleNamespace
import unicodedata
import uuid
from urllib.parse import urlparse

from sqlalchemy import column, func, inspect, or_, select, table, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.roles import (
    ROLE_ADMIN,
    ROLE_BRAND_LEAD,
    ROLE_XHS_LEAD,
    get_user_roles,
    has_role,
)
from app.models.user import User, UserRole
from app.models.xhs_account import (
    XHSAccount,
    XHSAccountHistoryLink,
    XHSAccountMasterImport,
)
from app.models.xhs_account_note import XHSAccountNote
from app.models.xhs_environment import XHSEnvironment
from app.utils.timezone import utc_now_naive


MASTER_SOURCE = (
    "https://ncisb4cgbz.feishu.cn/sheets/AXNmsJ5g3hMQLBtimnPcTLR9nfg?sheet=Q07GJB"
)
TYPES = {
    "企业专业号": "enterprise_professional",
    "企业员工号": "enterprise_employee",
    "个人号": "personal",
}
DEPARTMENTS = {"小红书部": "xhs", "品牌部": "brand", "私域中心": "private"}
FIELDS = {
    "xhs_account_id": "小红书ID号（请勿动）",
    "account_name": "小红书账号名称",
    "account_type": "账号类型（请勿动）",
    "owner_label": "使用人",
    "department": "归属部门",
    "login_phone_number": "注册手机号（请勿动）",
    "sim_device_label": "注册手机编号（请勿动）",
    "login_device_label": "账号登录手机编号",
}
ACCOUNT_FIELDS = (
    "xhs_account_id",
    "account_name",
    "owner_user_id",
    "department",
    "account_type",
    "status",
    "owner_label",
    "login_phone_number",
    "sim_device_label",
    "login_device_label",
    "source_row",
    "source_hash",
)
# Explicit corrections confirmed by the account owner on 2026-11-13; never infer aliases from nicknames.
CONFIRMED_ID_CORRECTIONS = {
    "94546474724": "63025106935",
    "94558682071": "63082245293",
    "63017276905": "6301727690",
}


class MasterError(ValueError):
    """Bounded errors never contain raw CSV, contact data or upstream responses."""


def valid_profile_url(value: str) -> bool:
    try:
        parsed = urlparse(value)
        return bool(parsed.scheme == "https" and parsed.hostname in {"www.xiaohongshu.com","xiaohongshu.com"}
                and not parsed.username and not parsed.password and not parsed.port and not parsed.fragment
                and re.fullmatch(r"/user/profile/[A-Za-z0-9]+/?",parsed.path))
    except ValueError:
        return False


def normalized(value: str) -> str:
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", value or ""))


def digest(value) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False, default=str).encode()
    ).hexdigest()


def parse_master_csv(content: bytes) -> tuple[list[dict], list[dict]]:
    if not content or len(content) > 2_000_000:
        raise MasterError("master_file_size_invalid")
    try:
        reader = csv.reader(io.StringIO(content.decode("utf-8-sig")), strict=True)
        raw = list(reader)
    except (UnicodeError, csv.Error):
        raise MasterError("master_csv_invalid_utf8") from None
    if len(raw) > 2010 or any(len(row) > 100 for row in raw):
        raise MasterError("master_csv_limits_exceeded")
    required = {normalized(label) for label in FIELDS.values()}
    headers = None
    for index, row in enumerate(raw[:10]):
        labels = [normalized(v) for v in row]
        if required.issubset(labels):
            if any(labels.count(label) != 1 for label in required):
                raise MasterError("master_duplicate_headers")
            headers = {
                key: labels.index(normalized(label)) for key, label in FIELDS.items()
            }
            break
    if headers is None:
        raise MasterError("master_headers_missing")
    rows, skipped = [], []
    for number, cells in enumerate(raw[index + 1 :], index + 2):
        row = {
            key: (cells[col].strip() if col < len(cells) else "")
            for key, col in headers.items()
        }
        if not any(
            row[key] for key in ("xhs_account_id", "account_name", "account_type")
        ):
            continue
        if row["xhs_account_id"] in {"", "-", "/"}:
            skipped.append({"row": number, "reason": "missing_or_placeholder_id"})
            continue
        if not re.fullmatch(r"\d{1,32}", row["xhs_account_id"]):
            raise MasterError(f"master_id_invalid_row_{number}")
        if (
            any(len(value) > 255 for value in row.values())
            or len(row["account_name"]) > 200
            or any(
                len(row[key]) > 100
                for key in ("sim_device_label", "login_device_label")
            )
        ):
            raise MasterError(f"master_field_too_long_row_{number}")
        phone = re.sub(r"[\s+()-]", "", row["login_phone_number"])
        if len(phone) == 13 and phone.startswith("86"):
            phone = phone[2:]
        if phone and not re.fullmatch(r"1\d{10}", phone):
            raise MasterError(f"master_phone_invalid_row_{number}")
        row.update(source_row=number, login_phone_number=phone or None)
        rows.append(row)
    if not rows:
        raise MasterError("master_has_no_accounts")
    ids = [r["xhs_account_id"] for r in rows]
    if len(ids) != len(set(ids)):
        raise MasterError("master_duplicate_account_id")
    return rows, skipped


def serialize_account(account: XHSAccount, *, owner_name: str | None = None) -> dict:
    return {
        "id": account.id,
        "xhs_account_id": account.xhs_account_id,
        "account_name": account.account_name,
        "owner_user_id": account.owner_user_id,
        "owner_name": owner_name,
        "department": account.department,
        "account_type": account.account_type,
        "status": account.status,
        "revision": account.revision,
        "source_row": account.source_row,
        "profile_url": account.profile_url,
        "homepage_sync_eligible": account.status == "active" and bool(account.profile_url),
    }


class XHSAccountMasterService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def update_profile(self, account_id: int, profile_url: str, expected_revision: int) -> dict:
        if not valid_profile_url(profile_url):
            raise MasterError("master_profile_invalid")
        account=await self.db.scalar(select(XHSAccount).where(XHSAccount.id==account_id)
            .with_for_update().execution_options(populate_existing=True))
        if account is None or account.revision!=expected_revision or account.status=="archived":
            raise MasterError("master_profile_stale")
        account.profile_url=profile_url
        account.revision+=1
        await self.db.commit()
        return {"id":account.id,"revision":account.revision}

    async def baseline(self) -> str:
        accounts = (
            (
                await self.db.execute(
                    select(XHSAccount)
                    .order_by(XHSAccount.id)
                    .execution_options(populate_existing=True)
                )
            )
            .scalars()
            .all()
        )
        users = (
            await self.db.execute(
                select(User.id, User.display_name, User.is_active, User.role).order_by(
                    User.id
                )
            )
        ).all()
        roles = (
            await self.db.execute(
                select(UserRole.user_id, UserRole.role).order_by(
                    UserRole.user_id, UserRole.role
                )
            )
        ).all()
        return digest(
            {
                "accounts": [
                    {
                        **{key: getattr(a, key) for key in (*ACCOUNT_FIELDS,"profile_url")},
                        "id": a.id,
                        "revision": a.revision,
                    }
                    for a in accounts
                ],
                "users": [list(r) for r in users],
                "roles": [list(r) for r in roles],
            }
        )

    @staticmethod
    def resolve_row(row: dict, users: list[User], source_hash: str) -> dict:
        label = normalized(row["owner_label"])
        candidates = []
        for user in users:
            name = normalized(user.display_name or "")
            if name and (
                label == name
                or (
                    label.startswith(name)
                    and label[len(name) : len(name) + 1] in "(-/、：:"
                )
            ):
                candidates.append(user)
        owner = (
            candidates[0] if len(candidates) == 1 and candidates[0].is_active else None
        )
        department = DEPARTMENTS.get(row["department"], "unresolved")
        account_type = TYPES.get(row["account_type"], "unresolved")
        errors = []
        if not row["account_name"]:
            errors.append("name_missing")
        if owner is None:
            errors.append("owner_unresolved")
        if department == "unresolved":
            errors.append("department_unresolved")
        if account_type == "unresolved":
            errors.append("account_type_unresolved")
        cancelled = "已注销" in row["account_name"]
        status = "retired" if cancelled else "needs_review" if errors else "active"
        return {
            "values": {
                **{
                    key: row[key]
                    for key in (
                        "xhs_account_id",
                        "owner_label",
                        "login_phone_number",
                        "sim_device_label",
                        "login_device_label",
                        "source_row",
                    )
                },
                "account_name": row["account_name"]
                or f"待补昵称({row['xhs_account_id']})",
                "owner_user_id": owner.id if owner else None,
                "department": department,
                "account_type": account_type,
                "status": status,
                "source_hash": source_hash,
            },
            "warnings": errors,
        }

    async def preview(self, content: bytes, administrator: User) -> dict:
        if not has_role(administrator, ROLE_ADMIN):
            raise MasterError("master_admin_required")
        rows, skipped = parse_master_csv(content)
        skipped.extend(
            {"row": row["source_row"], "reason": "private_department_excluded"}
            for row in rows
            if row["department"] == "私域中心"
        )
        rows = [row for row in rows if row["department"] != "私域中心"]
        source_hash = hashlib.sha256(content).hexdigest()
        users = list((await self.db.scalars(select(User).order_by(User.id))).all())
        user_names = {user.id: user.display_name or user.username for user in users}
        old = {
            a.xhs_account_id: a
            for a in (await self.db.scalars(select(XHSAccount))).all()
        }
        plan = [self.resolve_row(row, users, source_hash) for row in rows]
        retirement = await self.retirement_snapshot(
            {row["xhs_account_id"] for row in rows}
        )
        for item in plan:
            item["history"] = await self.history_snapshot(
                item["values"]["xhs_account_id"]
            )
        receipt = XHSAccountMasterImport(
            id=uuid.uuid4().hex,
            requested_by=administrator.id,
            source_hash=source_hash,
            baseline_hash=await self.baseline(),
            payload={"rows": plan, "skipped": skipped, "retirement": retirement},
            status="preview",
            expires_at=utc_now_naive() + timedelta(minutes=30),
        )
        self.db.add(receipt)
        await self.db.commit()
        public = []
        for item in plan:
            values = item["values"]
            existing = old.get(values["xhs_account_id"])
            changed = [
                key
                for key in ACCOUNT_FIELDS
                if existing is None or getattr(existing, key) != values[key]
            ]
            public.append(
                {
                    "row": values["source_row"],
                    "xhs_account_id": values["xhs_account_id"],
                    "account_name": values["account_name"],
                    "owner_user_id": values["owner_user_id"],
                    "owner_name": user_names.get(values["owner_user_id"]),
                    "department": values["department"],
                    "status": values["status"],
                    "operation": "update" if existing else "create",
                    "changed_fields": changed,
                    "warnings": item["warnings"],
                    "history_notes": len(item["history"]),
                    "confirmed_old_id": CONFIRMED_ID_CORRECTIONS.get(
                        values["xhs_account_id"]
                    ),
                }
            )
        return {
            "preview_id": receipt.id,
            "source_hash": source_hash,
            "source_url": MASTER_SOURCE,
            "expires_at": receipt.expires_at.isoformat(),
            "rows": public,
            "skipped": skipped,
            "unlisted_accounts": [
                {key: value for key, value in item.items() if key != "fingerprint"}
                for item in retirement
            ],
        }

    async def apply(
        self,
        preview_id: str,
        source_hash: str,
        rows: list[int],
        administrator: User,
        *,
        include_history: bool = False,
        replace_all: bool = False,
    ) -> dict:
        if not has_role(administrator, ROLE_ADMIN):
            raise MasterError("master_admin_required")
        if not rows or len(rows) != len(set(rows)):
            raise MasterError("master_explicit_unique_rows_required")
        if self.db.get_bind().dialect.name == "postgresql":
            await self.db.execute(text("SET LOCAL lock_timeout='1500ms'"))
            if not await self.db.scalar(
                select(func.pg_try_advisory_xact_lock(734219682))
            ):
                raise MasterError("master_import_busy")
        receipt = await self.db.scalar(
            select(XHSAccountMasterImport)
            .where(XHSAccountMasterImport.id == preview_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if (
            receipt is None
            or receipt.requested_by != administrator.id
            or receipt.source_hash != source_hash
        ):
            raise MasterError("master_preview_not_found")
        request_hash = digest(
            {
                "rows": sorted(rows),
                "include_history": include_history,
                "replace_all": replace_all,
            }
        )
        if receipt.status == "applied":
            if receipt.result.get("request_hash") != request_hash:
                raise MasterError("master_replay_scope_changed")
            return dict(receipt.result)
        if receipt.status != "preview" or receipt.expires_at < utc_now_naive():
            raise MasterError("master_preview_expired")
        result = await self.db.execute(
            update(XHSAccountMasterImport)
            .where(
                XHSAccountMasterImport.id == receipt.id,
                XHSAccountMasterImport.status == "preview",
            )
            .values(status="applying")
        )
        if result.rowcount != 1 or receipt.baseline_hash != await self.baseline():
            raise MasterError("master_preview_stale")
        selected = [
            item
            for item in receipt.payload["rows"]
            if item["values"]["source_row"] in rows
        ]
        if len(selected) != len(rows):
            raise MasterError("master_selected_rows_invalid")
        if any(i["values"]["department"] == "private" for i in selected):
            raise MasterError("master_private_department_excluded")
        source_ids = {
            item["values"]["xhs_account_id"] for item in receipt.payload["rows"]
        }
        if replace_all:
            if len(selected) != len(receipt.payload["rows"]):
                raise MasterError("master_full_sheet_selection_required")
            # Lock every existing identity in a consistent order before reading references.
            await self.db.scalars(
                select(XHSAccount)
                .order_by(XHSAccount.id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
            if receipt.baseline_hash != await self.baseline():
                raise MasterError("master_preview_stale")
            retirement = await self.retirement_snapshot(source_ids)
            if receipt.payload.get("retirement") != retirement:
                raise MasterError("master_retirement_changed_preview_again")
        if include_history:
            # Match the cloud importer lock order: account, then historical notes.
            await self.db.scalars(
                select(XHSAccount)
                .where(
                    XHSAccount.xhs_account_id.in_(
                        [item["values"]["xhs_account_id"] for item in selected]
                    )
                )
                .order_by(XHSAccount.id)
                .with_for_update()
            )
            for item in selected:
                if item["history"] != await self.history_snapshot(
                    item["values"]["xhs_account_id"], lock=True
                ):
                    raise MasterError("master_history_changed_preview_again")
        created, updated, linked, conflicts = 0, 0, 0, []
        for item in selected:
            values = item["values"]
            account = await self.db.scalar(
                select(XHSAccount)
                .where(XHSAccount.xhs_account_id == values["xhs_account_id"])
                .with_for_update()
                .execution_options(populate_existing=True)
            )
            if account is None:
                account = XHSAccount(**values, revision=1)
                self.db.add(account)
                created += 1
            else:
                for key in ACCOUNT_FIELDS:
                    if key != "xhs_account_id":
                        setattr(account, key, values[key])
                account.revision += 1
                updated += 1
            await self.db.flush()
            accepted_ids = {
                account.xhs_account_id,
                CONFIRMED_ID_CORRECTIONS.get(account.xhs_account_id),
            } - {None}
            legacy_rows = (
                await self.db.execute(
                    select(XHSEnvironment.id, XHSEnvironment.xhs_account_id).where(
                        XHSEnvironment.xhs_account_id.in_(accepted_ids),
                        XHSEnvironment.is_sync_runner.is_(False),
                    )
                )
            ).all()
            for legacy_id, legacy_xid in legacy_rows:
                exists = await self.db.scalar(
                    select(XHSAccountHistoryLink.id).where(
                        XHSAccountHistoryLink.account_id == account.id,
                        XHSAccountHistoryLink.environment_id == legacy_id,
                    )
                )
                if not exists:
                    self.db.add(
                        XHSAccountHistoryLink(
                            account_id=account.id,
                            environment_id=legacy_id,
                            xhs_id_snapshot=legacy_xid,
                            status="pending",
                        )
                    )
            if include_history:
                if not account.profile_url:
                    urls = list((await self.db.scalars(select(XHSEnvironment.profile_url).where(
                        XHSEnvironment.id.in_([row[0] for row in legacy_rows]),
                        XHSEnvironment.profile_url.is_not(None)))).all())
                    valid = [url for url in urls if valid_profile_url(url)]
                    if len({urlparse(url).path.rstrip('/') for url in valid}) == 1:
                        account.profile_url = valid[0]
                outcome = await self.attribute_snapshot(
                    account, item["history"], administrator.id
                )
                linked += outcome["linked"]
                conflicts.extend(outcome["conflicts"])
        removed, archived = [], []
        if replace_all:
            for item in retirement:
                account = await self.db.get(XHSAccount, item["id"])
                if item["action"] == "delete_empty":
                    await self.db.delete(account)
                    removed.append(item["id"])
                elif account.status != "archived":
                    account.status = "archived"
                    account.revision += 1
                    archived.append(item["id"])
        receipt.status = "applied"
        receipt.result = {
            "created": created,
            "updated": updated,
            "selected": len(selected),
            "request_hash": request_hash,
            "history_notes_moved": linked,
            "history_conflicts": conflicts,
            "unlisted_accounts_deleted": len(removed),
            "unlisted_accounts_archived": len(archived),
            "authoritative_roster": replace_all,
            "removed_account_ids": removed,
            "archived_account_ids": archived,
        }
        await self.db.commit()
        return dict(receipt.result)

    async def retirement_snapshot(self, source_ids: set[str]) -> list[dict]:
        accounts = list(
            (
                await self.db.scalars(
                    select(XHSAccount)
                    .where(XHSAccount.xhs_account_id.not_in(source_ids))
                    .order_by(XHSAccount.id)
                )
            ).all()
        )
        if not accounts:
            return []
        connection = await self.db.connection()

        def foreign_keys(sync):
            inspector = inspect(sync)
            result = set()
            for name in inspector.get_table_names():
                for fk in inspector.get_foreign_keys(name):
                    if fk["referred_table"] != "xhs_accounts":
                        continue
                    if len(fk["constrained_columns"]) != 1 or fk[
                        "referred_columns"
                    ] != ["id"]:
                        raise MasterError("master_unsupported_reference_schema")
                    result.add((name, fk["constrained_columns"][0]))
            return sorted(result)

        references = await connection.run_sync(foreign_keys)
        counts = {account.id: {} for account in accounts}
        for name, field in references:
            target = table(name, column(field))
            rows = (
                await self.db.execute(
                    select(target.c[field], func.count())
                    .where(target.c[field].in_(counts))
                    .group_by(target.c[field])
                )
            ).all()
            for identity, count in rows:
                counts[identity][f"{name}.{field}"] = int(count)
        return [
            {
                "id": account.id,
                "xhs_account_id": account.xhs_account_id,
                "account_name": account.account_name,
                "references": counts[account.id],
                "action": "archive_history" if counts[account.id] else "delete_empty",
                "fingerprint": digest(
                    {
                        "id": account.id,
                        "revision": account.revision,
                        "references": counts[account.id],
                    }
                ),
            }
            for account in accounts
        ]

    async def history_snapshot(self, xhs_id: str, *, lock: bool = False) -> list[dict]:
        accepted_ids = {xhs_id, CONFIRMED_ID_CORRECTIONS.get(xhs_id)} - {None}
        env_query = (
            select(XHSEnvironment)
            .where(
                XHSEnvironment.xhs_account_id.in_(accepted_ids),
                XHSEnvironment.is_sync_runner.is_(False),
            )
            .order_by(XHSEnvironment.id)
        )
        if lock:
            env_query = env_query.with_for_update().execution_options(
                populate_existing=True
            )
        envs = list((await self.db.scalars(env_query)).all())
        query = (
            select(XHSAccountNote)
            .where(XHSAccountNote.environment_id.in_([env.id for env in envs]))
            .order_by(XHSAccountNote.id)
            .limit(100_001)
        )
        if lock:
            query = query.with_for_update().execution_options(populate_existing=True)
        notes = list((await self.db.scalars(query)).all())
        if len(notes) > 100_000:
            raise MasterError("master_history_too_large_review_in_batches")
        return [
            {
                "id": note.id,
                "environment_id": note.environment_id,
                "fingerprint": digest(
                    {
                        column.name: getattr(note, column.name)
                        for column in XHSAccountNote.__table__.columns
                    }
                ),
            }
            for note in notes
        ]

    async def attribute_snapshot(
        self, account: XHSAccount, snapshot: list[dict], reviewer: int
    ) -> dict:
        existing = list(
            (
                await self.db.scalars(
                    select(XHSAccountNote)
                    .where(XHSAccountNote.account_id == account.id)
                    .with_for_update()
                )
            ).all()
        )
        feeds = {n.feed_id for n in existing if n.feed_id}
        keys = {n.creator_identity_key for n in existing if n.creator_identity_key}
        accepted = {
            account.xhs_account_id,
            CONFIRMED_ID_CORRECTIONS.get(account.xhs_account_id),
        } - {None}
        linked, conflicts = 0, []
        for item in snapshot:
            note = await self.db.get(XHSAccountNote, item["id"])
            if note.account_id == account.id:
                continue
            reason = None
            if note.account_id is not None or (
                note.red_id and note.red_id not in accepted
            ):
                reason = "different_account_identity"
            elif (note.feed_id and note.feed_id in feeds) or (
                note.creator_identity_key and note.creator_identity_key in keys
            ):
                reason = "duplicate_identity_retained"
            if reason:
                conflicts.append(
                    {"note_id": note.id, "account_id": account.id, "reason": reason}
                )
                continue
            note.account_id = account.id
            linked += 1
            if note.feed_id:
                feeds.add(note.feed_id)
            if note.creator_identity_key:
                keys.add(note.creator_identity_key)
        await self.db.flush()
        return {"linked": linked, "conflicts": conflicts}

    @staticmethod
    def visibility(user: User):
        if has_role(user, ROLE_ADMIN):
            return True
        clauses = [XHSAccount.owner_user_id == user.id]
        roles = get_user_roles(user)
        if ROLE_XHS_LEAD in roles:
            clauses.append(XHSAccount.department == "xhs")
        if ROLE_BRAND_LEAD in roles:
            clauses.append(XHSAccount.department == "brand")
        return (
            (XHSAccount.department.in_(("xhs", "brand")))
            & (XHSAccount.status.in_(("active", "retired")))
            & or_(*clauses)
        )

    async def accounts(self, user: User) -> list[dict]:
        rows = (
            await self.db.execute(
                select(XHSAccount, User.display_name)
                .outerjoin(User, User.id == XHSAccount.owner_user_id)
                .where(self.visibility(user))
                .order_by(XHSAccount.account_name, XHSAccount.id)
            )
        ).all()
        return [serialize_account(account, owner_name=name) for account, name in rows]

    async def notes(
        self,
        user: User,
        *,
        account_id: int | None = None,
        skip: int = 0,
        limit: int = 50,
    ):
        allowed = select(XHSAccount.id).where(self.visibility(user))
        if account_id is not None:
            allowed = allowed.where(XHSAccount.id == account_id)
        condition = XHSAccountNote.account_id.in_(allowed)
        count = int(
            await self.db.scalar(
                select(func.count()).select_from(XHSAccountNote).where(condition)
            )
            or 0
        )
        notes = list(
            (
                await self.db.scalars(
                    select(XHSAccountNote)
                    .where(condition)
                    .order_by(
                        XHSAccountNote.published_at.desc(), XHSAccountNote.id.desc()
                    )
                    .offset(skip)
                    .limit(limit)
                )
            ).all()
        )
        return notes, count

    async def confirm_history(
        self,
        account_id: int,
        environment_id: int,
        note_ids: list[int],
        expected_revision: int,
        administrator: User,
    ) -> dict:
        if (
            not has_role(administrator, ROLE_ADMIN)
            or not note_ids
            or len(note_ids) > 500
            or len(note_ids) != len(set(note_ids))
        ):
            raise MasterError("master_explicit_history_review_required")
        account = await self.db.scalar(
            select(XHSAccount).where(XHSAccount.id == account_id).with_for_update()
        )
        if account is None or account.revision != expected_revision:
            raise MasterError("master_account_revision_changed")
        notes = list(
            (
                await self.db.scalars(
                    select(XHSAccountNote)
                    .where(XHSAccountNote.id.in_(note_ids))
                    .order_by(XHSAccountNote.id)
                    .with_for_update()
                    .execution_options(populate_existing=True)
                )
            ).all()
        )
        if len(notes) != len(note_ids) or any(
            n.environment_id != environment_id or n.account_id not in (None, account_id)
            for n in notes
        ):
            raise MasterError("master_history_subject_conflict")
        link = await self.db.scalar(
            select(XHSAccountHistoryLink).where(
                XHSAccountHistoryLink.account_id == account_id,
                XHSAccountHistoryLink.environment_id == environment_id,
            )
        )
        if link is None:
            raise MasterError("master_history_link_not_found")
        for note in notes:
            note.account_id = account_id
        # A reviewed subset never authorizes future notes from a reused environment.
        link.status, link.reviewed_by, link.reviewed_at = (
            "reviewed_subset",
            administrator.id,
            utc_now_naive(),
        )
        await self.db.commit()
        return {
            "account_id": account_id,
            "linked_notes": len(notes),
            "legacy_environment_unchanged": True,
        }

    async def insights(self, user: User, start_date=None, end_date=None) -> dict:
        from datetime import datetime, time, timezone
        from app.services.xhs_service import XHSService
        from app.utils.timezone import CST

        conditions = [
            XHSAccountNote.account_id.in_(
                select(XHSAccount.id).where(self.visibility(user))
            )
        ]
        if start_date:
            conditions.append(
                XHSAccountNote.published_at
                >= datetime.combine(start_date, time.min, CST)
                .astimezone(timezone.utc)
                .replace(tzinfo=None)
            )
        if end_date:
            conditions.append(
                XHSAccountNote.published_at
                < datetime.combine(end_date + timedelta(days=1), time.min, CST)
                .astimezone(timezone.utc)
                .replace(tzinfo=None)
            )
        from sqlalchemy.orm import selectinload

        rows = (
            await self.db.execute(
                select(XHSAccountNote, XHSAccount, User)
                .options(selectinload(User.role_assignments))
                .join(XHSAccount, XHSAccount.id == XHSAccountNote.account_id)
                .outerjoin(User, User.id == XHSAccount.owner_user_id)
                .where(*conditions)
                .order_by(XHSAccountNote.id)
            )
        ).all()
        projected = []
        for note, account, owner in rows:
            values = {
                col.name: getattr(note, col.name)
                for col in XHSAccountNote.__table__.columns
            }
            for key in ("published_at", "created_at", "updated_at"):
                if values[key] is not None:
                    values[key] = (
                        values[key]
                        .replace(tzinfo=timezone.utc)
                        .astimezone(CST)
                        .replace(tzinfo=None)
                    )
            values.update(
                environment_id=f"account:{account.id}",
                account_name=account.account_name,
                profile_nickname=account.account_name,
                owner_user_id=owner.id if owner else None,
                owner_username=(owner.display_name or owner.username)
                if owner
                else None,
                owner_display_name=owner.display_name if owner else None,
                owner_role=XHSService._insights_owner_role(get_user_roles(owner))
                if owner
                else None,
            )
            projected.append(SimpleNamespace(**values))
        return XHSService.build_insights_dashboard(
            projected,
            start_date=start_date,
            end_date=end_date,
            cache_namespace="account-master:"
            + digest(
                sorted(
                    {
                        (account.id, account.revision, account.account_name)
                        for _, account, _ in rows
                    }
                )
            ),
        )
