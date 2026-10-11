"""Browser-only sessions. Business requests never write activity timestamps."""

from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import re
import secrets
import uuid

from fastapi import HTTPException
from sqlalchemy import inspect, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.security import create_access_token
from app.models.auth_session import AuthSession
from app.models.user import User


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def digest(value: str) -> str:
    return hmac.new(settings.jwt_secret_key.encode(), value.encode(), hashlib.sha256).hexdigest()


def refresh_value(row: AuthSession) -> str:
    # Deterministic only for this rotation, so a lost response can be retried
    # with the same random request nonce without storing a bearer secret.
    secret = digest(f"browser-refresh:{row.id}:{row.generation}:{row.refresh_nonce}")
    return f"{row.id}.{row.generation}.{row.refresh_nonce}.{secret}"


def signed_refresh(cookie: str) -> bool:
    parts = cookie.split(".")
    if len(parts) != 4:
        return False
    sid, generation, nonce, signature = parts
    if not (re.fullmatch(r"[a-f0-9]{32}", sid) and re.fullmatch(r"[0-9]{1,10}", generation)
            and re.fullmatch(r"[a-f0-9]{32,64}", nonce)):
        return False
    expected = digest(f"browser-refresh:{sid}:{generation}:{nonce}")
    return hmac.compare_digest(expected, signature)


def session_error(code: str = "session_expired", status: int = 401) -> HTTPException:
    return HTTPException(status_code=status, detail=code)


def valid(row: AuthSession, user: User, now: datetime) -> bool:
    return bool(
        user.is_active and row.revoked_at is None and row.expires_at > now
        and row.last_active_at + timedelta(days=settings.auth_session_idle_days) > now
        and hmac.compare_digest(row.credential_digest, digest(user.hashed_password))
    )


def access_payload(row: AuthSession, now: datetime) -> dict:
    lifetime = min(
        timedelta(minutes=settings.auth_session_access_minutes),
        row.expires_at - now,
        row.last_active_at + timedelta(days=settings.auth_session_idle_days) - now,
    )
    return {"access_token": create_access_token(row.user_id, lifetime, session_id=row.id),
            "token_type": "bearer", "expires_in": max(0, int(lifetime.total_seconds()))}


async def create_session(db: AsyncSession, user: User) -> tuple[AuthSession, dict]:
    now = utcnow()
    row = AuthSession(id=uuid.uuid4().hex, user_id=user.id,
                      credential_digest=digest(user.hashed_password), refresh_digest="",
                      refresh_nonce=secrets.token_hex(24), generation=0, last_active_at=now,
                      expires_at=now + timedelta(days=settings.auth_session_absolute_days))
    row.refresh_digest = digest(refresh_value(row))
    db.add(row)
    await db.commit()
    return row, access_payload(row, now)


async def validate_session(db: AsyncSession, session_id: str, user: User) -> AuthSession:
    row = await db.get(AuthSession, session_id)
    if not row or row.user_id != user.id or not valid(row, user, utcnow()):
        raise session_error()
    return row


async def rotate_session(db: AsyncSession, cookie: str, nonce: str, *, attempt: int = 0) -> tuple[AuthSession, dict]:
    if attempt > 2:
        raise session_error("refresh_conflict", 409)
    sid = cookie.split(".", 1)[0]
    if not signed_refresh(cookie):
        raise session_error()
    row = await db.get(AuthSession, sid)
    user = await db.get(User, row.user_id) if row else None
    now = utcnow()
    if not row or not user or not valid(row, user, now):
        raise session_error()
    supplied = digest(cookie)
    current = hmac.compare_digest(supplied, row.refresh_digest)
    previous = bool(row.previous_digest and hmac.compare_digest(supplied, row.previous_digest))
    recent = bool(row.rotated_at and now - row.rotated_at < timedelta(seconds=30))
    if (current or previous) and recent and nonce == row.refresh_nonce:
        return row, access_payload(row, now)
    if previous or (not current and signed_refresh(cookie)):
        if recent:
            raise session_error("refresh_conflict", 409)
        await db.execute(update(AuthSession).where(AuthSession.id == sid).values(revoked_at=now))
        await db.commit()
        raise session_error("refresh_reuse")
    if not current:
        raise session_error()
    next_generation = row.generation + 1
    secret = digest(f"browser-refresh:{sid}:{next_generation}:{nonce}")
    next_digest = digest(f"{sid}.{next_generation}.{nonce}.{secret}")
    result = await db.execute(update(AuthSession).where(
        AuthSession.id == sid, AuthSession.refresh_digest == supplied,
        AuthSession.revoked_at.is_(None),
    ).values(previous_digest=supplied, refresh_digest=next_digest, generation=next_generation,
             refresh_nonce=nonce, rotated_at=now))
    if result.rowcount != 1:
        await db.rollback()
        # Read the winner: identical retries are safe across API processes.
        return await rotate_session(db, cookie, nonce, attempt=attempt + 1)
    await db.commit()
    await db.refresh(row)
    if not valid(row, user, utcnow()):
        raise session_error()
    return row, access_payload(row, now)


async def record_activity(db: AsyncSession, row: AuthSession) -> None:
    now = utcnow()
    if row.last_active_at > now - timedelta(seconds=60):
        return
    await db.execute(update(AuthSession).where(
        AuthSession.id == row.id, AuthSession.revoked_at.is_(None),
        AuthSession.last_active_at <= now - timedelta(seconds=60),
    ).values(last_active_at=now))
    await db.commit()


async def revoke_cookie(db: AsyncSession, cookie: str) -> None:
    sid = cookie.split(".", 1)[0]
    row = await db.get(AuthSession, sid) if len(sid) == 32 else None
    if row and signed_refresh(cookie):
        await db.execute(update(AuthSession).where(AuthSession.id == sid).values(revoked_at=utcnow()))
        await db.commit()


async def revoke_disabled_user(db: AsyncSession, user_id: int) -> None:
    # Admin changes also run during the flag-off migration window. An old DB
    # cannot contain browser sessions, so missing-table compatibility is safe.
    connection = await db.connection()
    exists = await connection.run_sync(lambda conn: inspect(conn).has_table("auth_sessions"))
    if exists:
        await db.execute(update(AuthSession).where(AuthSession.user_id == user_id,
                         AuthSession.revoked_at.is_(None)).values(revoked_at=utcnow()))
