from pydantic import BaseModel, Field, EmailStr
from typing import Optional
from datetime import datetime


class LoginRequest(BaseModel):
    username: str = Field(..., min_length=3, max_length=50, description="用户名")
    password: str = Field(..., min_length=6, max_length=100, description="密码")


class RegisterRequest(BaseModel):
    username: str = Field(..., min_length=3, max_length=50, description="用户名")
    display_name: Optional[str] = Field(default=None, max_length=80, description="展示名")
    email: EmailStr = Field(..., min_length=5, max_length=255, description="邮箱")
    password: str = Field(..., min_length=6, max_length=100, description="密码")


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserResponse(BaseModel):
    id: int
    username: str
    display_name: Optional[str] = None
    email: str
    avatar: Optional[str] = None
    is_active: bool
    role: str
    roles: list[str] = Field(default_factory=list)
    created_at: Optional[datetime] = None

    model_config = {"from_attributes": True}
