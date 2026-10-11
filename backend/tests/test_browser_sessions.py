from __future__ import annotations

import asyncio
from datetime import timedelta, timezone

import pytest
import pytest_asyncio
from jose import jwt
from sqlalchemy import select, update

from app.config import settings
from app.core.security import create_access_token, decode_access_token, hash_password
from app.models.auth_session import AuthSession
from app.models.user import User
from app.services import auth_session_service as sessions
from tests.conftest import session_factory, test_engine

pytestmark = pytest.mark.asyncio
HEADERS = {"Origin": "http://localhost:3000", "X-Session-Request": "1"}
PREFIX = "/api/v1/auth/session"
CREDENTIALS = {"username": "session_user", "password": "password123"}


@pytest_asyncio.fixture
async def browser(client, monkeypatch):
    monkeypatch.setattr(settings, "auth_browser_sessions_enabled", True)
    async with session_factory() as db:
        user = User(username=CREDENTIALS["username"], email="session@example.com",
                    hashed_password=hash_password(CREDENTIALS["password"]), role="viewer")
        db.add(user)
        await db.commit()
    return client


async def login(browser):
    response = await browser.post(f"{PREFIX}/login", headers=HEADERS, json=CREDENTIALS)
    assert response.status_code == 200, response.text
    token = response.json()["access_token"]
    cookie = response.cookies["creative_refresh"]
    return token, cookie, decode_access_token(token)["sid"]


def cookie_headers(cookie, token=None, origin=None):
    return {**HEADERS, "Cookie": f"creative_refresh={cookie}",
            **({"Authorization": f"Bearer {token}"} if token else {}),
            **({"Origin": origin} if origin else {})}


async def refresh(browser, cookie, nonce="a" * 32):
    return await browser.post(f"{PREFIX}/refresh", headers=cookie_headers(cookie), json={"request_id": nonce})


async def change(sid, **values):
    async with session_factory() as db:
        await db.execute(update(AuthSession).where(AuthSession.id == sid).values(**values))
        await db.commit()


async def row_for(sid):
    async with session_factory() as db:
        return await db.get(AuthSession, sid)


async def test_browser_login_cookie_and_token(browser):
    token, cookie, sid = await login(browser)
    payload = decode_access_token(token)
    assert payload["sid"] == sid
    assert payload["exp"] <= sessions.utcnow().replace(tzinfo=timezone.utc).timestamp() + 1810
    row = await row_for(sid)
    assert row.refresh_digest != cookie and len(row.refresh_digest) == 64
    assert row.expires_at - row.last_active_at == timedelta(days=30)
    assert (await browser.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})).status_code == 200


async def test_cookie_attributes_and_no_cache(browser):
    response = await browser.post(f"{PREFIX}/login", headers=HEADERS, json=CREDENTIALS)
    header = response.headers["set-cookie"]
    assert "HttpOnly" in header and "SameSite=strict" in header
    assert "Path=/api/auth-session" in header and "Domain=" not in header
    assert response.headers["cache-control"] == "no-store"


async def test_https_uses_secure_cookie(browser, monkeypatch):
    monkeypatch.setattr(settings, "auth_session_origins", ["https://app.example.com"])
    response = await browser.post(f"{PREFIX}/login", headers={**HEADERS, "Origin": "https://app.example.com"}, json=CREDENTIALS)
    assert response.status_code == 200
    assert "Secure" in response.headers["set-cookie"]


@pytest.mark.parametrize("headers", [{}, {"Origin": "http://localhost:3000"},
                                    {**HEADERS, "Origin": "https://evil.example"},
                                    {**HEADERS, "Origin": "null"}])
async def test_cross_site_and_missing_proof_rejected(browser, headers):
    assert (await browser.post(f"{PREFIX}/login", headers=headers, json=CREDENTIALS)).status_code == 403


async def test_public_http_rejected_even_if_allowed_origin(browser, monkeypatch):
    monkeypatch.setattr(settings, "auth_session_origins", ["http://public.example"])
    response = await browser.post(f"{PREFIX}/login", headers={**HEADERS, "Origin": "http://public.example"}, json=CREDENTIALS)
    assert response.status_code == 403 and response.json()["detail"] == "session_https_required"


async def test_disabled_flag_preserves_legacy_contract(browser, monkeypatch):
    monkeypatch.setattr(settings, "auth_browser_sessions_enabled", False)
    assert (await browser.get(f"{PREFIX}/policy")).json() == {"enabled": False}
    assert (await browser.post(f"{PREFIX}/login", headers=HEADERS, json=CREDENTIALS)).status_code == 503
    result = await browser.post("/api/v1/auth/login", json=CREDENTIALS)
    assert result.status_code == 200 and set(result.json()) == {"access_token", "token_type"}
    assert "sid" not in decode_access_token(result.json()["access_token"])
    assert "set-cookie" not in result.headers


@pytest.mark.parametrize("field", ["last_active_at", "expires_at", "revoked_at"])
async def test_expiry_and_revocation_block_access_and_refresh(browser, field):
    token, cookie, sid = await login(browser)
    value = sessions.utcnow() - timedelta(days=3) if field == "last_active_at" else sessions.utcnow() - timedelta(seconds=1)
    await change(sid, **{field: value})
    assert (await refresh(browser, cookie)).status_code == 401
    assert (await browser.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})).status_code == 401


async def test_polling_and_refresh_do_not_extend_idle(browser):
    token, cookie, sid = await login(browser)
    before = sessions.utcnow() - timedelta(days=2)
    await change(sid, last_active_at=before)
    for _ in range(3):
        assert (await browser.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})).status_code == 200
    assert (await refresh(browser, cookie)).status_code == 200
    assert (await row_for(sid)).last_active_at == before


async def test_foreground_activity_is_coalesced(browser):
    token, cookie, sid = await login(browser)
    await change(sid, last_active_at=sessions.utcnow() - timedelta(minutes=10))
    response = await browser.post(f"{PREFIX}/activity", headers=cookie_headers(cookie, token))
    assert response.status_code == 200
    first = (await row_for(sid)).last_active_at
    assert sessions.utcnow() - first < timedelta(seconds=2)
    assert (await browser.post(f"{PREFIX}/activity", headers=cookie_headers(cookie, token))).status_code == 200
    assert (await row_for(sid)).last_active_at == first


async def test_rotation_and_lost_response_idempotency(browser):
    _, old_cookie, sid = await login(browser)
    first = await refresh(browser, old_cookie)
    assert first.status_code == 200
    new_cookie = first.cookies["creative_refresh"]
    assert new_cookie != old_cookie
    for cookie in [old_cookie, new_cookie]:
        retry = await refresh(browser, cookie)
        assert retry.status_code == 200 and retry.cookies["creative_refresh"] == new_cookie
    assert (await row_for(sid)).generation == 1


async def test_different_tab_conflict_cannot_issue_token(browser):
    _, cookie, _ = await login(browser)
    assert (await refresh(browser, cookie)).status_code == 200
    conflict = await refresh(browser, cookie, "b" * 32)
    assert conflict.status_code == 409 and "access_token" not in conflict.json()


async def test_old_refresh_reuse_revokes_session(browser):
    token, cookie, sid = await login(browser)
    assert (await refresh(browser, cookie)).status_code == 200
    await change(sid, rotated_at=sessions.utcnow() - timedelta(seconds=31))
    assert (await refresh(browser, cookie, "b" * 32)).status_code == 401
    assert (await row_for(sid)).revoked_at
    assert (await browser.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})).status_code == 401


async def test_concurrent_rotation_one_generation(browser):
    _, cookie, sid = await login(browser)
    responses = await asyncio.gather(*(refresh(browser, cookie) for _ in range(10)))
    assert all(response.status_code == 200 for response in responses)
    assert len({response.cookies["creative_refresh"] for response in responses}) == 1
    assert (await row_for(sid)).generation == 1


async def test_logout_revokes_access_and_refresh(browser):
    token, cookie, sid = await login(browser)
    result = await browser.post(f"{PREFIX}/logout", headers=cookie_headers(cookie))
    assert result.status_code == 200 and "Max-Age=0" in result.headers["set-cookie"]
    assert (await row_for(sid)).revoked_at
    assert (await refresh(browser, cookie)).status_code == 401
    assert (await browser.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})).status_code == 401


async def test_devices_independent_and_logout_all(browser):
    token, cookie, sid = await login(browser)
    # A new browser with no cookie leaves the first device's session alone.
    token2, cookie2, sid2 = await login(browser)
    assert sid != sid2 and not (await row_for(sid)).revoked_at
    await browser.post(f"{PREFIX}/logout", headers=cookie_headers(cookie2))
    assert (await refresh(browser, cookie)).status_code == 200
    result = await browser.post(f"{PREFIX}/logout-all", headers=cookie_headers(cookie, token))
    assert result.status_code == 200
    assert (await row_for(sid)).revoked_at and (await row_for(sid2)).revoked_at


@pytest.mark.parametrize("mutation", ["password", "disabled", "deleted"])
async def test_user_changes_invalidate_session(browser, mutation):
    token, cookie, sid = await login(browser)
    async with session_factory() as db:
        user = (await db.execute(select(User).where(User.username == CREDENTIALS["username"]))).scalar_one()
        if mutation == "password":
            user.hashed_password = hash_password("changed_password")
        elif mutation == "disabled":
            user.is_active = False
        else:
            await db.delete(user)
        await db.commit()
    assert (await refresh(browser, cookie)).status_code == 401
    assert (await browser.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})).status_code in (401, 403)


@pytest.mark.parametrize("cookie", ["", "invalid", "0" * 32 + ".wrong"])
async def test_malformed_refresh_rejected(browser, cookie):
    assert (await refresh(browser, cookie)).status_code == 401


async def test_invalid_nonce_and_session_claim(browser):
    _, cookie, sid = await login(browser)
    assert (await refresh(browser, cookie, "invalid")).status_code == 422
    token = jwt.encode({"sub": "1", "sid": 2}, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)
    assert (await browser.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})).status_code == 401
    legacy = create_access_token("1")
    assert (await browser.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {legacy}"})).status_code == 200


async def test_expired_session_cannot_be_revived_by_activity(browser):
    token, cookie, sid = await login(browser)
    before = sessions.utcnow() - timedelta(days=3, seconds=1)
    await change(sid, last_active_at=before)
    assert (await browser.post(f"{PREFIX}/activity", headers=cookie_headers(cookie, token))).status_code == 401
    assert (await row_for(sid)).last_active_at == before


async def test_older_than_previous_refresh_cannot_bypass_reuse_detection(browser):
    _, old_cookie, sid = await login(browser)
    first = await refresh(browser, old_cookie)
    assert first.status_code == 200
    second = await refresh(browser, first.cookies["creative_refresh"], "b" * 32)
    assert second.status_code == 200
    await change(sid, rotated_at=sessions.utcnow() - timedelta(seconds=31))
    assert (await refresh(browser, old_cookie, "c" * 32)).status_code == 401
    assert (await row_for(sid)).revoked_at


async def test_admin_revokes_only_target_users_browser_sessions(browser):
    token, cookie, sid = await login(browser)
    denied = await browser.post(f"{PREFIX}/revoke-user/1", headers={"Authorization": f"Bearer {token}"})
    assert denied.status_code == 403 and not (await row_for(sid)).revoked_at
    async with session_factory() as db:
        admin = User(username="session_admin", email="session-admin@example.com", role="admin",
                     hashed_password=hash_password("password123"))
        db.add(admin)
        await db.commit()
        admin_id = admin.id
    accepted = await browser.post(f"{PREFIX}/revoke-user/1", headers={"Authorization": f"Bearer {create_access_token(admin_id)}"})
    assert accepted.status_code == 200 and accepted.json() == {"revoked": 1}
    assert (await refresh(browser, cookie)).status_code == 401


async def test_disable_then_reenable_does_not_restore_an_old_session(browser, monkeypatch):
    _, cookie, sid = await login(browser)
    async with session_factory() as db:
        admin = User(username="session_admin", email="session-admin@example.com", role="admin",
                     hashed_password=hash_password("password123"))
        db.add(admin)
        await db.commit()
        headers = {"Authorization": f"Bearer {create_access_token(admin.id)}"}
    # Revocation also works while rollout is off, not only during flag-on use.
    monkeypatch.setattr(settings, "auth_browser_sessions_enabled", False)
    assert (await browser.patch("/api/v1/admin/users/1/active", headers=headers, json={"is_active": False})).status_code == 200
    assert (await row_for(sid)).revoked_at
    assert (await browser.patch("/api/v1/admin/users/1/active", headers=headers, json={"is_active": True})).status_code == 200
    monkeypatch.setattr(settings, "auth_browser_sessions_enabled", True)
    assert (await refresh(browser, cookie)).status_code == 401


async def test_legacy_database_without_session_table_can_still_disable_users(browser, monkeypatch):
    monkeypatch.setattr(settings, "auth_browser_sessions_enabled", False)
    async with session_factory() as db:
        admin = User(username="session_admin", email="session-admin@example.com", role="admin",
                     hashed_password=hash_password("password123"))
        db.add(admin)
        await db.commit()
        headers = {"Authorization": f"Bearer {create_access_token(admin.id)}"}
    async with test_engine.begin() as connection:
        await connection.run_sync(AuthSession.__table__.drop)
    result = await browser.patch("/api/v1/admin/users/1/active", headers=headers, json={"is_active": False})
    assert result.status_code == 200
