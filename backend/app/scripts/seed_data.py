"""初始化管理员账号及角色，不再填充已下线的编辑器素材。"""

from __future__ import annotations

import asyncio
import os
import sys

# 确保使用 SQLite 本地数据库（如果未配置 DATABASE_URL）
if "DATABASE_URL" not in os.environ:
    os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///./dev.db"

from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy import func, or_, select

from app.db.base import Base
from app.models.user import User, UserRole
from app.core.roles import ROLE_ADMIN, set_user_roles
from app.core.security import hash_password


def get_local_session():
    """为本地种子脚本创建数据库会话"""
    db_url = os.environ.get("DATABASE_URL", "sqlite+aiosqlite:///./dev.db")
    # SQLite 需要不同的连接参数
    if db_url.startswith("sqlite"):
        engine = create_async_engine(db_url, echo=False)
    else:
        engine = create_async_engine(db_url, echo=False, pool_size=5)
    return async_sessionmaker(engine, expire_on_commit=False)


def _required_seed_admin_credentials() -> tuple[str, str, str]:
    username = os.getenv("SEED_ADMIN_USERNAME", "").strip()
    email = os.getenv("SEED_ADMIN_EMAIL", "").strip().lower()
    password = os.getenv("SEED_ADMIN_PASSWORD", "")
    if not username or not email or not password:
        raise RuntimeError(
            "缺少 SEED_ADMIN_USERNAME / SEED_ADMIN_EMAIL / SEED_ADMIN_PASSWORD，"
            "拒绝创建默认管理员"
        )
    return username, email, password


async def _ensure_seed_admin(db: AsyncSession) -> tuple[User, bool]:
    admin = (
        await db.execute(
            select(User)
            .outerjoin(UserRole, UserRole.user_id == User.id)
            .where(or_(User.role == ROLE_ADMIN, UserRole.role == ROLE_ADMIN))
            .order_by(User.id.asc())
            .limit(1)
        )
    ).scalars().first()
    if admin is not None:
        assigned_roles = list(
            (
                await db.execute(
                    select(UserRole.role).where(UserRole.user_id == admin.id)
                )
            ).scalars()
        )
        await set_user_roles(db, admin, [*assigned_roles, ROLE_ADMIN])
        return admin, False

    username, email, password = _required_seed_admin_credentials()
    conflict = (
        await db.execute(
            select(User).where(
                or_(User.username == username, func.lower(User.email) == email)
            )
        )
    ).scalar_one_or_none()
    if conflict is not None:
        raise RuntimeError("种子管理员用户名或邮箱已被非管理员账户占用")

    admin = User(
        username=username,
        email=email,
        hashed_password=hash_password(password),
        is_active=True,
    )
    db.add(admin)
    await db.flush()
    await set_user_roles(db, admin, [ROLE_ADMIN])
    return admin, True


async def seed():
    """初始化管理员；历史模板、素材和用户记录均不清空。"""
    local_session = get_local_session()
    async with local_session() as db:
        if "--reset" in sys.argv:
            raise RuntimeError("编辑器已下线，不再支持 --reset；不会清空历史数据")
        async with db.bind.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        admin, created = await _ensure_seed_admin(db)
        await db.commit()
        action = "创建" if created else "确认"
        print(f"已{action}管理员: {admin.username}")


if __name__ == "__main__":
    asyncio.run(seed())
