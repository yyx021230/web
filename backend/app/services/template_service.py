"""模板管理服务"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from app.models.template import Template
from app.schemas.template import TemplateCreate, TemplateUpdate


class TemplateService:
    """模板服务"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_list(
        self, page: int = 1, limit: int = 20, category: str | None = None,
    ) -> tuple[list[Template], int]:
        """获取模板列表（分页）"""
        conditions = [Template.is_public == True, Template.deleted_at.is_(None)]
        if category:
            conditions.append(Template.category == category)

        # 高效 count
        count_stmt = select(func.count(Template.id)).where(*conditions)
        total_result = await self.db.execute(count_stmt)
        total = total_result.scalar() or 0

        # 分页
        items_stmt = (
            select(Template)
            .where(*conditions)
            .order_by(Template.created_at.desc())
            .offset((page - 1) * limit)
            .limit(limit)
        )
        items_result = await self.db.execute(items_stmt)
        items = list(items_result.scalars().all())
        return items, total

    async def get_by_id(self, template_id: int) -> Template | None:
        """根据 ID 获取模板"""
        result = await self.db.execute(
            select(Template).where(
                Template.id == template_id,
                Template.deleted_at.is_(None),
            )
        )
        return result.scalar_one_or_none()

    async def create(self, req: TemplateCreate, user_id: int | None = None) -> Template:
        """创建模板"""
        template = Template(
            name=req.name,
            description=req.description,
            fabric_json=req.fabric_json,
            category=req.category,
            tags=req.tags or [],
            created_by=user_id,
        )
        self.db.add(template)
        await self.db.commit()
        await self.db.refresh(template)
        return template

    async def update(
        self, template_id: int, req: TemplateUpdate, user_id: int | None = None,
    ) -> Template | None:
        """更新模板（仅 owner 可修改）"""
        template = await self.get_by_id(template_id)
        if not template:
            return None
        # 所有权校验
        if template.created_by is not None and user_id is not None:
            if template.created_by != user_id:
                return None  # 非 owner 无权

        update_data = req.model_dump(exclude_unset=True)
        for key, value in update_data.items():
            setattr(template, key, value)

        await self.db.commit()
        await self.db.refresh(template)
        return template

    async def delete(self, template_id: int, user_id: int | None = None) -> bool:
        """软删除模板（仅 owner 可删）"""
        template = await self.get_by_id(template_id)
        if not template:
            return False
        # 所有权校验
        if template.created_by is not None and user_id is not None:
            if template.created_by != user_id:
                return False  # 非 owner 无权
        template.deleted_at = func.now()
        await self.db.commit()
        return True
