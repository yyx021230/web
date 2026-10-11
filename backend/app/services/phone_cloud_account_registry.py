"""Register verified cloud-phone identities without inventing YunDeng IDs."""
from __future__ import annotations

from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.roles import has_role
from app.models.user import User
from app.models.user_xhs_env import UserXHSEnvironment
from app.models.xhs_environment import PHONE_CLOUD_ACCOUNT_PREFIX, XHSEnvironment


async def register_verified_account(
    db: AsyncSession, *, operator: User, owner: User, xhs_id: str, name: str,
) -> XHSEnvironment:
    """Caller verifies the live phone mapping; conflicts never steal ownership."""
    # Role collections must be loaded explicitly before synchronous permission checks.
    await db.refresh(operator, attribute_names=["is_active", "role", "role_assignments"])
    await db.refresh(owner, attribute_names=["is_active"])
    if not operator.is_active or not has_role(operator, "admin") or not owner.is_active:
        raise ValueError("Active administrator and owner required")
    xhs_id, name = xhs_id.strip(), name.strip()
    if not xhs_id.isascii() or not xhs_id.isdigit() or not 5 <= len(xhs_id) <= 40 or not name or len(name) > 200:
        raise ValueError("Invalid cloud-phone account identity")
    shop_id = PHONE_CLOUD_ACCOUNT_PREFIX + xhs_id

    async def find_existing():
        rows = list((await db.scalars(select(XHSEnvironment).where(or_(
            XHSEnvironment.xhs_account_id == xhs_id, XHSEnvironment.shop_id == shop_id,
        )).with_for_update())).all())
        if len(rows) > 1:
            raise ValueError("Conflicting existing account identities")
        if rows and (rows[0].xhs_account_id != xhs_id or rows[0].status != "active"):
            raise ValueError("Existing account requires explicit reconciliation")
        return rows[0] if rows else None

    env = await find_existing()
    if env is None:
        try:
            async with db.begin_nested():
                env = XHSEnvironment(shop_id=shop_id, account_name=name, xhs_account_id=xhs_id,
                                     status="active", department="xhs", is_sync_runner=False,
                                     group_name="云手机", labels="phone-cloud")
                db.add(env)
                await db.flush()
        except IntegrityError:
            env = await find_existing()
            if env is None:
                raise
    assignment = await db.scalar(select(UserXHSEnvironment).where(
        UserXHSEnvironment.environment_id == env.id).with_for_update())
    if assignment and assignment.user_id != owner.id:
        raise ValueError("Account already belongs to another user")
    if assignment is None:
        db.add(UserXHSEnvironment(user_id=owner.id, environment_id=env.id))
        await db.flush()
    return env
