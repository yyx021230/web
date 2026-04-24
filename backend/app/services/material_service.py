"""素材管理服务"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from app.models.material import Material
from app.adapters.storage import storage


class MaterialService:
    """素材服务"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_list(
        self, page: int = 1, limit: int = 20, category: str | None = None,
    ) -> tuple[list[Material], int]:
        """获取素材列表（分页）"""
        conditions = [Material.deleted_at.is_(None)]
        if category:
            conditions.append(Material.category == category)

        count_stmt = select(func.count(Material.id)).where(*conditions)
        total_result = await self.db.execute(count_stmt)
        total = total_result.scalar() or 0

        items_stmt = (
            select(Material)
            .where(*conditions)
            .order_by(Material.created_at.desc())
            .offset((page - 1) * limit)
            .limit(limit)
        )
        items_result = await self.db.execute(items_stmt)
        items = list(items_result.scalars().all())
        return items, total

    async def create(
        self,
        name: str,
        material_type: str,
        url: str,
        width: int | None = None,
        height: int | None = None,
        category: str | None = None,
        tags: list | None = None,
        user_id: int | None = None,
    ) -> Material:
        """创建素材记录"""
        material = Material(
            name=name,
            type=material_type,
            url=url,
            width=width,
            height=height,
            category=category,
            tags=tags or [],
            created_by=user_id,
        )
        self.db.add(material)
        await self.db.commit()
        await self.db.refresh(material)
        return material

    async def delete(self, material_id: int, user_id: int | None = None) -> bool:
        """软删除素材（含存储文件，仅 owner 可删）"""
        result = await self.db.execute(
            select(Material).where(
                Material.id == material_id,
                Material.deleted_at.is_(None),
            )
        )
        material = result.scalar_one_or_none()
        if not material:
            return False

        # 所有权校验
        if material.created_by is not None and user_id is not None:
            if material.created_by != user_id:
                return False  # 非 owner 无权

        # 删除存储文件
        try:
            await storage.delete(material.url)
        except Exception:
            pass  # 存储删除失败不影响数据库删除

        material.deleted_at = func.now()
        await self.db.commit()
        return True
