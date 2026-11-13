"""Import existing mobile snapshots; never submit a phone or browser task."""
from __future__ import annotations

from datetime import date, datetime, timedelta
import asyncio
import hashlib
import json
import re
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.phone_cloud_xhs_data import CloudDataError, PhoneCloudXHSDataClient
from app.config import settings
from app.models.xhs_account_note import XHSAccountNote
from app.models.xhs_cloud_import import XHSCloudImport
from app.models.xhs_environment import XHSEnvironment
from app.models.xhs_account import XHSAccount
from app.services.xhs_metric_provenance import record_metric
from app.utils.timezone import CST, UTC, utc_now_naive


def cloud_enabled() -> bool:
    return settings.xhs_creator_sync_source == "phone_cloud"


def parse_time(value: Any) -> datetime:
    try:
        at = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if at.tzinfo is None:
            raise ValueError
        return at.astimezone(UTC).replace(tzinfo=None)
    except (ValueError, TypeError):
        raise CloudDataError("cloud_data_invalid_timestamp") from None


def note_day(note: XHSAccountNote) -> date | None:
    return note.published_at.replace(tzinfo=UTC).astimezone(CST).date() if note.published_at else None


def title_key(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def verified_bindings() -> dict[str, dict]:
    try:
        raw = json.loads(settings.phone_cloud_xhs_verified_bindings)
        if not isinstance(raw, list):
            raise ValueError
        result, slots = {}, set()
        for binding in raw:
            if (not isinstance(binding, dict) or not isinstance(binding.get("xhs_id"), str)
                    or not binding["xhs_id"].strip() or not isinstance(binding.get("device_id"), str)
                    or not binding["device_id"].strip()
                    or binding.get("app_slot") not in {"app1", "app2"}):
                raise ValueError
            xid = binding["xhs_id"]
            slot = (binding["device_id"], binding["app_slot"])
            if xid in result or slot in slots:
                raise ValueError
            # Human verification is explicit and dated, not inferred from a configured name.
            parse_time(binding.get("verified_at"))
            result[xid] = binding
            slots.add(slot)
        return result
    except (ValueError, TypeError, KeyError):
        raise CloudDataError("cloud_data_invalid_verified_bindings") from None


class XHSCloudDataService:
    def __init__(self, db: AsyncSession):
        self.db = db

    @staticmethod
    def subject_values(subject: XHSEnvironment | XHSAccount) -> dict:
        return {"account_id": subject.id, "environment_id": None} if isinstance(subject, XHSAccount) else {
            "environment_id": subject.id, "account_id": None}

    @staticmethod
    def subject_condition(model, subject: XHSEnvironment | XHSAccount):
        values = XHSCloudDataService.subject_values(subject)
        return (model.account_id == values["account_id"]) if isinstance(subject, XHSAccount) else (
            (model.environment_id == subject.id) & model.account_id.is_(None))

    async def current_subject(self, subject, xhs_id):
        model = XHSAccount if isinstance(subject, XHSAccount) else XHSEnvironment
        current = await self.db.scalar(select(model).where(model.id == subject.id).with_for_update()
            .execution_options(populate_existing=True))
        if current is None or current.status != "active" or current.xhs_account_id != xhs_id:
            raise CloudDataError("cloud_data_account_changed")
        if model is XHSEnvironment:
            duplicate = await self.db.scalar(select(model.id).where(model.xhs_account_id == xhs_id,
                model.status == "active", model.id != current.id).limit(1))
            if duplicate:
                raise CloudDataError("cloud_data_ambiguous_account")
        return current

    async def sync(self, envs: list[XHSEnvironment] | list[XHSAccount], *, progress_callback=None, cancel_check=None) -> dict:
        result = {"synced_accounts": 0, "created_notes": 0, "updated_notes": 0,
                  "metric_synced_notes": 0, "total_notes": 0, "failed_accounts": [], "source": "phone_cloud"}
        ids = {str(env.xhs_account_id or "").strip() for env in envs}
        client = PhoneCloudXHSDataClient(settings.phone_cloud_xhs_data_base_url,
            settings.phone_cloud_xhs_data_client_id, settings.phone_cloud_xhs_data_secret,
            http_origins=settings.phone_cloud_xhs_data_http_origins)
        bindings = verified_bindings()
        # Release the caller's read transaction before remote pagination.
        model = XHSAccount if envs and isinstance(envs[0], XHSAccount) else XHSEnvironment
        subject_key = "account_id" if model is XHSAccount else "environment_id"
        if any(not isinstance(env, model) for env in envs):
            raise CloudDataError("cloud_data_mixed_subjects")
        env_ids = [int(env.id) for env in envs]
        account_names = {int(env.id): env.account_name for env in envs}
        await self.db.commit()
        try:
            async with asyncio.timeout(180):
                observations = await client.latest_items(ids - {""})
        except TimeoutError:
            raise CloudDataError("cloud_data_query_budget_exhausted") from None
        for index, env_id in enumerate(env_ids, 1):
            if cancel_check and cancel_check():
                from app.services.xhs_service import SyncJobCancelled
                raise SyncJobCancelled("同步已取消，已保留此前导入结果")
            env = await self.db.get(model, env_id, populate_existing=True)
            account_name = env.account_name if env is not None else account_names[env_id]
            error = None
            try:
                if env is None or env.status != "active":
                    raise CloudDataError("cloud_data_account_changed")
                xid = str(env.xhs_account_id or "").strip()
                if not xid or xid not in bindings:
                    raise CloudDataError("cloud_data_identity_not_verified")
                if model is XHSEnvironment:
                    await self.current_subject(env, xid)
                if xid not in observations:
                    raise CloudDataError("cloud_data_no_recent_observation")
                run_id, item = observations[xid]
                outcome = await self.import_item(env, run_id, item, bindings[xid])
                if outcome.get("error"):
                    raise CloudDataError(outcome["error"])
                result["synced_accounts"] += 1
                for key in ("created_notes", "updated_notes", "metric_synced_notes"):
                    result[key] += outcome.get(key, 0)
            except CloudDataError as exc:
                error = str(exc)
                result["failed_accounts"].append({subject_key: env_id, "account_name": account_name,
                                                  "error": error})
            finally:
                await self.db.commit()
            if progress_callback:
                from app.services.xhs_service import XHSService
                await XHSService._emit_progress(progress_callback, {"phase": "account_engagement_failed" if error else "account_engagement_completed",
                    subject_key: env_id, "account_name": account_name, "account_index": index,
                    "account_total": len(env_ids), "current": index, "total": len(env_ids),
                    "percent": int(index * 100 / len(env_ids)), "error": error,
                    "detail": error or f"{account_name} 云手机结果已入库", **result})
        note_scope = XHSAccountNote.account_id.in_(env_ids) if model is XHSAccount else (
            XHSAccountNote.environment_id.in_(env_ids) & XHSAccountNote.account_id.is_(None))
        result["total_notes"] = int(await self.db.scalar(select(func.count()).select_from(XHSAccountNote).where(note_scope)) or 0)
        return result

    def validate_item(self, env: XHSEnvironment, item: dict, binding: dict) -> tuple[datetime, list[dict]]:
        if item.get("status") != "succeeded":
            state = item.get("status") if item.get("status") in {"failed", "skipped"} else "invalid_status"
            raise CloudDataError("cloud_data_upstream_" + state)
        data = item.get("data")
        if (item.get("identitySource") != "platform_binding_snapshot" or not isinstance(data, dict)
                or item.get("xhsId") != env.xhs_account_id or item.get("xhsId") != binding["xhs_id"]
                or item.get("deviceId") != binding["device_id"] or item.get("appSlot") != binding["app_slot"]
                or data.get("app_slot") != binding["app_slot"] or data.get("account_bound") is not True):
            raise CloudDataError("cloud_data_identity_mismatch")
        if (data.get("schema_version") != 3 or data.get("window_days") != 30
                or data.get("source") != "xhs_creator_center_works_analysis_list"
                or data.get("complete") is not True
                or data.get("stop_reason") not in {"list_end_visible", "older_than_window_visible"}):
            raise CloudDataError("cloud_data_incomplete_or_unsupported")
        events = data.get("recovery_events") or []
        if (not isinstance(events, list) or "collection_integrity:verified_two_pass" not in events
                or any("configured_id_mismatch" in str(event) or "account_changed" in str(event) for event in events)):
            raise CloudDataError("cloud_data_account_or_integrity_unproven")
        captured = parse_time(data.get("captured_at"))
        now = utc_now_naive()
        if captured > now + timedelta(minutes=5) or captured < now - timedelta(hours=settings.phone_cloud_xhs_data_max_age_hours):
            raise CloudDataError("cloud_data_stale_or_future_snapshot")
        if parse_time(binding["verified_at"]) > captured:
            raise CloudDataError("cloud_data_snapshot_predates_identity_verification")
        try:
            start, end = date.fromisoformat(data["window_start_date"]), date.fromisoformat(data["window_end_date"])
        except (ValueError, KeyError, TypeError):
            raise CloudDataError("cloud_data_invalid_window") from None
        if end - start != timedelta(days=29) or end != captured.replace(tzinfo=UTC).astimezone(CST).date():
            raise CloudDataError("cloud_data_invalid_window")
        rows = data.get("notes")
        if not isinstance(rows, list) or len(rows) > 1000:
            raise CloudDataError("cloud_data_invalid_notes")
        identities = set()
        for row in rows:
            if not isinstance(row, dict) or not isinstance(row.get("title"), str) or not row["title"].strip():
                raise CloudDataError("cloud_data_invalid_note")
            try:
                day = date.fromisoformat(row["published_date"])
            except (ValueError, KeyError, TypeError):
                raise CloudDataError("cloud_data_invalid_note_date") from None
            if not start <= day <= end or len(row["title"]) >= 180 or row.get("note_id") is not None:
                raise CloudDataError("cloud_data_ambiguous_or_invalid_note")
            identity = (title_key(row["title"]), day)
            if identity in identities:
                raise CloudDataError("cloud_data_duplicate_title_date")
            identities.add(identity)
            for field in ("list_view_count", "list_like_count", "list_comment_count"):
                value = row.get(field)
                if value is not None and (type(value) is not int or not 0 <= value <= 2_147_483_647):
                    raise CloudDataError("cloud_data_invalid_metric")
        return captured, rows

    async def import_item(self, env: XHSEnvironment | XHSAccount, run_id: str, item: dict, binding: dict) -> dict:
        """Atomic apply and receipt; failed snapshots remain auditable, not numeric zero."""
        if not re.fullmatch(r"[a-f0-9]{64}", run_id) or not re.fullmatch(r"\d{1,32}", str(item.get("itemId", ""))):
            raise CloudDataError("cloud_data_invalid_observation_identity")
        if item.get("status") in {"queued", "submitting", "running", "unknown"}:
            raise CloudDataError("cloud_data_upstream_pending")
        raw = json.dumps(item, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        if len(raw.encode()) > 2_000_000:
            raise CloudDataError("cloud_data_item_too_large")
        payload_hash = hashlib.sha256(raw.encode()).hexdigest()
        key = (XHSCloudImport.client_id == settings.phone_cloud_xhs_data_client_id,
               XHSCloudImport.run_id == run_id, XHSCloudImport.item_id == str(item["itemId"]))
        existing = await self.db.scalar(select(XHSCloudImport).where(*key).with_for_update())
        if existing:
            if (any(getattr(existing, key) != value for key, value in self.subject_values(env).items())
                    or existing.payload_hash != payload_hash):
                raise CloudDataError("cloud_data_observation_conflict")
            if existing.status == "applied":
                current = await self.current_subject(env, item.get("xhsId"))
                self.validate_item(current, item, binding)
                return {"created_notes": 0, "updated_notes": 0, "metric_synced_notes": 0, "duplicate": True}
            receipt = existing
        else:
            receipt = XHSCloudImport(client_id=settings.phone_cloud_xhs_data_client_id,
                run_id=run_id, item_id=str(item["itemId"]), **self.subject_values(env),
                payload_hash=payload_hash, payload=item, status="received")
            try:
                async with self.db.begin_nested():
                    self.db.add(receipt)
                    await self.db.flush()
            except IntegrityError:
                raise CloudDataError("cloud_data_import_busy_retry") from None
        try:
            captured, rows = self.validate_item(env, item, binding)
            receipt.captured_at = captured
            env = await self.current_subject(env, item.get("xhsId"))
            newer = await self.db.scalar(select(XHSCloudImport.id).where(
                self.subject_condition(XHSCloudImport, env), XHSCloudImport.status == "applied",
                XHSCloudImport.captured_at > captured).limit(1))
            if newer:
                raise CloudDataError("cloud_data_superseded_snapshot")
            async with self.db.begin_nested():
                outcome = await self._apply_rows(env, rows, captured, item["data"].get("warnings") or [])
                receipt.status, receipt.error_code = "applied", None
                receipt.applied_at, receipt.result = utc_now_naive(), outcome
                await self.db.flush()
        except CloudDataError as exc:
            receipt.status, receipt.error_code = "quarantined", str(exc)
            outcome = {"error": str(exc)}
        except Exception:
            # The nested transaction has rolled back; retain the source for offline replay.
            receipt.status, receipt.error_code = "quarantined", "cloud_data_apply_failed"
            outcome = {"error": "cloud_data_apply_failed"}
        await self.db.commit()
        if receipt.status == "applied":
            from app.services.xhs_service import _INSIGHTS_DASHBOARD_CACHE
            _INSIGHTS_DASHBOARD_CACHE.clear()
        return outcome

    async def _apply_rows(self, env: XHSEnvironment | XHSAccount, rows: list[dict], captured: datetime, warnings: list) -> dict:
        notes = list((await self.db.scalars(select(XHSAccountNote).where(
            self.subject_condition(XHSAccountNote, env)).with_for_update()
            .execution_options(populate_existing=True))).all())
        snapshot_titles = {(title_key(r["title"]), date.fromisoformat(r["published_date"])) for r in rows}
        outcome = {"created_notes": 0, "updated_notes": 0, "metric_synced_notes": 0}
        precision = "approximate" if "list_metric_units_are_displayed_approximations" in warnings else "displayed"
        for row in rows:
            day, title = date.fromisoformat(row["published_date"]), title_key(row["title"])
            candidates = [n for n in notes if title_key(n.title) == title and note_day(n) == day]
            if len(candidates) > 1:
                raise CloudDataError("cloud_data_ambiguous_existing_note")
            if candidates:
                note = candidates[0]
                outcome["updated_notes"] += 1
            else:
                if any(note_day(n) == day and (title_key(n.title), day) not in snapshot_titles for n in notes):
                    raise CloudDataError("cloud_data_possible_title_change")
                note = XHSAccountNote(**self.subject_values(env), account_name=env.account_name,
                    title=row["title"], identity_status="creator_only", identity_match_method="cloud_title_date",
                    identity_match_confidence=0.6, creator_identity_key=hashlib.sha256(
                        f"phone_cloud|{day}|{title}".encode()).hexdigest(),
                    published_at=datetime.combine(day, datetime.min.time(), CST).astimezone(UTC).replace(tzinfo=None),
                    published_at_precision="date", metric_sources={}, status="active", sort_index=len(notes),
                    first_synced_at=captured)
                self.db.add(note)
                notes.append(note)
                outcome["created_notes"] += 1
            legacy = note.metric_sources is None and note.creator_synced_at is not None
            sources = dict(note.metric_sources or {})
            if legacy:
                for field in ("view_count", "liked_count", "comment_count", "collected_count", "share_count",
                              "exposure_count", "cover_click_rate"):
                    sources[field] = {"source": "creator_export", "captured_at": note.creator_synced_at.isoformat(), "precision": "legacy"}
            note.metric_sources = sources
            applied_metric = False
            for source, field in (("list_view_count", "view_count"), ("list_like_count", "liked_count"),
                                  ("list_comment_count", "comment_count")):
                value = row.get(source)
                previous = sources.get(field) or {}
                previous_at = datetime.fromisoformat(previous["captured_at"]) if previous.get("captured_at") else None
                if value is not None and (previous_at is None or captured > previous_at):
                    setattr(note, field, value)
                    record_metric(note, field, "phone_cloud", captured, precision=precision)
                    applied_metric = True
            note.creator_first_seen_at = note.creator_first_seen_at or captured
            note.creator_last_seen_at = max(note.creator_last_seen_at or captured, captured)
            note.creator_synced_at = max(note.creator_synced_at or captured, captured)
            note.updated_at = utc_now_naive()
            outcome["metric_synced_notes"] += int(applied_metric)
        await self.db.flush()
        return outcome
