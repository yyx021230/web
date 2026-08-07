from __future__ import annotations

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User, UserRole

ROLE_ADMIN = "admin"
ROLE_XHS_LEAD = "xhs_lead"
ROLE_XHS_OPS = "xhs_ops"
ROLE_BUYER = "buyer"
ROLE_BRAND_LEAD = "brand_lead"
ROLE_BRAND_OPS = "brand_ops"
ROLE_VIEWER = "viewer"
LEGACY_ROLE_ALIASES = {
    "xhs_buyer": ROLE_BUYER,
}

VALID_USER_ROLES = {
    ROLE_ADMIN,
    ROLE_XHS_LEAD,
    ROLE_XHS_OPS,
    ROLE_BUYER,
    ROLE_BRAND_LEAD,
    ROLE_BRAND_OPS,
    ROLE_VIEWER,
}
ROLE_PRIORITY = [
    ROLE_ADMIN,
    ROLE_XHS_LEAD,
    ROLE_BRAND_LEAD,
    ROLE_XHS_OPS,
    ROLE_BRAND_OPS,
    ROLE_BUYER,
    ROLE_VIEWER,
]


def normalize_roles(raw_roles: object, fallback: str | None = ROLE_VIEWER) -> list[str]:
    if isinstance(raw_roles, str):
        values = [raw_roles]
    elif isinstance(raw_roles, (list, tuple, set)):
        values = [str(item) for item in raw_roles]
    else:
        values = []
    roles = []
    for value in values:
        role = LEGACY_ROLE_ALIASES.get(str(value or "").strip(), str(value or "").strip())
        if role and role not in roles:
            roles.append(role)
    if not roles and fallback:
        roles = [fallback]
    return sorted(roles, key=lambda role: ROLE_PRIORITY.index(role) if role in ROLE_PRIORITY else len(ROLE_PRIORITY))


def validate_roles(roles: list[str]) -> None:
    invalid = [role for role in roles if role not in VALID_USER_ROLES]
    if invalid:
        raise ValueError(f"无效的角色: {', '.join(invalid)}")


def get_user_roles(user: User | None) -> list[str]:
    if not user:
        return []
    assignments = getattr(user, "role_assignments", None) or []
    roles = [str(item.role) for item in assignments if str(item.role or "").strip()]
    return normalize_roles(roles, fallback=user.role or ROLE_VIEWER)


def get_primary_role(roles: list[str]) -> str:
    normalized = normalize_roles(roles)
    return normalized[0] if normalized else ROLE_VIEWER


def has_role(user: User | None, *roles: str) -> bool:
    current = set(get_user_roles(user))
    return any(role in current for role in roles)


async def set_user_roles(db: AsyncSession, user: User, roles: list[str]) -> list[str]:
    normalized = normalize_roles(roles)
    validate_roles(normalized)
    await db.execute(delete(UserRole).where(UserRole.user_id == user.id))
    for role in normalized:
        db.add(UserRole(user_id=user.id, role=role))
    user.role = get_primary_role(normalized)
    return normalized


async def load_roles_for_users(db: AsyncSession, user_ids: list[int]) -> dict[int, list[str]]:
    if not user_ids:
        return {}
    result = await db.execute(select(UserRole.user_id, UserRole.role).where(UserRole.user_id.in_(user_ids)))
    roles_by_user: dict[int, list[str]] = {}
    for user_id, role in result.all():
        roles_by_user.setdefault(int(user_id), []).append(str(role))
    return {user_id: normalize_roles(roles) for user_id, roles in roles_by_user.items()}
