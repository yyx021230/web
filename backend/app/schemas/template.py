from pydantic import BaseModel, Field
from typing import Optional


class TemplateCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255, description="模板名称")
    description: Optional[str] = Field(None, max_length=1000, description="描述")
    fabric_json: str = Field(..., description="Fabric.js JSON 数据", max_length=5_000_000)
    category: str = Field(..., max_length=100, description="分类")
    tags: list[str] = Field(default=[], description="标签")


class TemplateUpdate(BaseModel):
    name: Optional[str] = Field(None, max_length=255)
    description: Optional[str] = Field(None, max_length=1000)
    fabric_json: Optional[str] = Field(None, max_length=5_000_000)
    category: Optional[str] = Field(None, max_length=100)
    tags: Optional[list[str]] = None


class TemplateResponse(BaseModel):
    id: int
    name: str
    description: Optional[str]
    thumbnail: Optional[str]
    fabric_json: Optional[str] = None
    category: str
    tags: list[str]

    model_config = {"from_attributes": True}
