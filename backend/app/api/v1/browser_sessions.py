"""Opt-in browser authentication, never used by worker/provider credentials."""

from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.deps import get_current_user, require_admin
from app.core.security import decode_access_token
from app.db.session import get_db
from app.models.auth_session import AuthSession
from app.models.user import User
from app.schemas.auth import LoginRequest
from app.services.auth_session_service import (
    create_session, record_activity, refresh_value, revoke_cookie, rotate_session,
    utcnow, validate_session,
)

router = APIRouter()
COOKIE_NAME = "creative_refresh"
COOKIE_PATH = "/api/auth-session"


class RefreshRequest(BaseModel):
    request_id: str = Field(pattern=r"^[a-f0-9]{32,64}$", description="刷新请求的随机幂等标识")


def transport_allowed(origin: str) -> bool:
    parsed = urlsplit(origin)
    return parsed.scheme == "https" or (
        parsed.scheme == "http" and parsed.hostname in {"localhost", "127.0.0.1", "::1"}
    )


def require_browser(request: Request, response: Response) -> str:
    response.headers["Cache-Control"] = "no-store"
    if not settings.auth_browser_sessions_enabled:
        raise HTTPException(503, "browser_sessions_disabled")
    origin = request.headers.get("origin", "")
    if (origin not in settings.auth_session_origins
            or request.headers.get("x-session-request") != "1"):
        raise HTTPException(403, "session_origin_rejected")
    if not transport_allowed(origin):
        raise HTTPException(403, "session_https_required")
    return origin


def set_refresh_cookie(response: Response, row: AuthSession, origin: str) -> None:
    response.set_cookie(COOKIE_NAME, refresh_value(row), httponly=True,
                        secure=urlsplit(origin).scheme == "https", samesite="strict",
                        path=COOKIE_PATH, max_age=max(0, int((row.expires_at - utcnow()).total_seconds())))


@router.get("/session/policy")
async def session_policy(response: Response):
    """Public rollout flag; does not disclose credentials or create a session."""
    response.headers["Cache-Control"] = "no-store"
    return {"enabled": settings.auth_browser_sessions_enabled}


@router.post("/session/login")
async def browser_login(req: LoginRequest, request: Request, response: Response,
                        origin: str = Depends(require_browser), db: AsyncSession = Depends(get_db)):
    """Authenticate a browser and create a bounded, revocable session."""
    from app.api.v1.auth import authenticate
    user = await authenticate(req, db)
    # Replace this browser's prior session, not sessions on other devices.
    await revoke_cookie(db, request.cookies.get(COOKIE_NAME, ""))
    row, payload = await create_session(db, user)
    set_refresh_cookie(response, row, origin)
    return payload


@router.post("/session/refresh")
async def browser_refresh(req: RefreshRequest, request: Request, response: Response,
                          origin: str = Depends(require_browser), db: AsyncSession = Depends(get_db)):
    """Rotate a refresh token, without counting polling as human activity."""
    row, payload = await rotate_session(db, request.cookies.get(COOKIE_NAME, ""), req.request_id)
    set_refresh_cookie(response, row, origin)
    return payload


@router.post("/session/activity")
async def browser_activity(request: Request, origin: str = Depends(require_browser),
                           db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    """Coalesce explicit foreground activity; normal API requests do not touch it."""
    token = request.headers.get("authorization", "").removeprefix("Bearer ")
    sid = decode_access_token(token).get("sid")
    if not sid:
        raise HTTPException(400, "browser_session_required")
    row = await validate_session(db, sid, user)
    await record_activity(db, row)
    return {"ok": True}


@router.post("/session/logout")
async def browser_logout(request: Request, response: Response, origin: str = Depends(require_browser),
                         db: AsyncSession = Depends(get_db)):
    """Revoke even an expired access session, using its HttpOnly refresh cookie."""
    await revoke_cookie(db, request.cookies.get(COOKIE_NAME, ""))
    response.delete_cookie(COOKIE_NAME, path=COOKIE_PATH, secure=urlsplit(origin).scheme == "https",
                           httponly=True, samesite="strict")
    return {"ok": True}


@router.post("/session/logout-all")
async def browser_logout_all(origin: str = Depends(require_browser),
                            db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    """Revoke this user's browser sessions only; legacy API tokens are separate."""
    await db.execute(update(AuthSession).where(AuthSession.user_id == user.id,
                    AuthSession.revoked_at.is_(None)).values(revoked_at=utcnow()))
    await db.commit()
    return {"ok": True}


@router.post("/session/revoke-user/{user_id}")
async def revoke_user_sessions(user_id: int, db: AsyncSession = Depends(get_db),
                               admin: User = Depends(require_admin)):
    """Administrator revocation, authenticated by bearer, not ambient cookies."""
    if not settings.auth_browser_sessions_enabled:
        raise HTTPException(503, "browser_sessions_disabled")
    result = await db.execute(update(AuthSession).where(AuthSession.user_id == user_id,
                    AuthSession.revoked_at.is_(None)).values(revoked_at=utcnow()))
    await db.commit()
    return {"revoked": result.rowcount}
