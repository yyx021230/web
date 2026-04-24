from __future__ import annotations
from pydantic import BaseModel, Field
from typing import Generic, TypeVar, Optional, List

T = TypeVar("T")

MAX_PAGE_LIMIT = 100


class ApiResponse(BaseModel, Generic[T]):
    code: int = 0
    message: str = "success"
    data: Optional[T] = None


class PaginationParams(BaseModel):
    page: int = Field(default=1, ge=1, description="页码")
    limit: int = Field(default=20, ge=1, le=MAX_PAGE_LIMIT, description="每页数量")


class PaginatedResponse(BaseModel, Generic[T]):
    items: List[T]
    total: int
    page: int
    limit: int
