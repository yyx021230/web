from __future__ import annotations
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, or_, func

from app.db.session import get_db
from app.models.user import User
from app.schemas.auth import LoginRequest, RegisterRequest, TokenResponse, UserResponse
from app.core.security import hash_password, verify_password, create_access_token
from app.core.deps import get_current_user, require_admin

router = APIRouter()


@router.post("/login", response_model=TokenResponse)
async def login(req: LoginRequest, db: AsyncSession = Depends(get_db)):
    """用户登录"""
    login_value = (req.username or "").strip()
    if not login_value:
        raise HTTPException(status_code=400, detail="用户名或邮箱不能为空")

    result = await db.execute(
        select(User).where(
            or_(
                User.username == login_value,
                func.lower(User.email) == login_value.lower(),
            )
        )
    )
    user = result.scalar_one_or_none()

    if not user or not verify_password(req.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="用户名或密码错误")

    if not user.is_active:
        raise HTTPException(status_code=403, detail="账户已禁用")

    token = create_access_token(subject=str(user.id))
    return TokenResponse(access_token=token)


@router.post("/register", response_model=TokenResponse)
async def register(
    req: RegisterRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """用户注册（仅管理员可用）"""
    # 检查用户名是否已存在
    result = await db.execute(select(User).where(User.username == req.username))
    if result.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="用户名已存在")

    # 检查邮箱是否已存在
    normalized_email = req.email.lower()
    result = await db.execute(select(User).where(func.lower(User.email) == normalized_email))
    if result.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="邮箱已存在")

    user = User(
        username=req.username,
        email=normalized_email,
        hashed_password=hash_password(req.password),
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)

    token = create_access_token(subject=str(user.id))
    return TokenResponse(access_token=token)


@router.get("/me", response_model=UserResponse)
async def get_current_user_info(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取当前用户信息"""
    return UserResponse.model_validate(current_user)
