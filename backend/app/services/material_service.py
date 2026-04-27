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

    async def get_by_id(self, material_id: int) -> Material | None:
        """根据 ID 获取素材"""
        result = await self.db.execute(
            select(Material).where(
                Material.id == material_id,
                Material.deleted_at.is_(None),
            )
        )
        return result.scalar_one_or_none()

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

    async def create_design(
        self,
        name: str,
        design_json: dict | None = None,
        thumbnail: str | None = None,
        width: int | None = None,
        height: int | None = None,
        user_id: int | None = None,
    ) -> Material:
        """创建编辑器设计稿素材

        - design_json: 完整的 Fabric JSON，包含所有图层/位置/样式关系
        - thumbnail: 设计缩略图（base64 或 URL），用于草稿箱预览
        """
        material = Material(
            name=name,
            type="design",
            url=thumbnail,  # 缩略图放在 url 字段
            width=width,
            height=height,
            category="editor-design",
            tags=[],
            design_json=design_json,
            created_by=user_id,
        )
        self.db.add(material)
        await self.db.commit()
        await self.db.refresh(material)
        return material

    async def update_design(
        self,
        material_id: int,
        name: str | None = None,
        design_json: dict | None = None,
        thumbnail: str | None = None,
        width: int | None = None,
        height: int | None = None,
        user_id: int | None = None,
    ) -> Material | None:
        """更新已有的设计稿（覆盖）"""
        result = await self.db.execute(
            select(Material).where(
                Material.id == material_id,
                Material.deleted_at.is_(None),
            )
        )
        material = result.scalar_one_or_none()
        if not material:
            return None

        # 所有权校验
        if material.created_by is not None and user_id is not None:
            if material.created_by != user_id:
                return None

        if name is not None:
            material.name = name
        if design_json is not None:
            material.design_json = design_json
        if thumbnail is not None:
            material.url = thumbnail
        if width is not None:
            material.width = width
        if height is not None:
            material.height = height

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

        # 删除存储文件（仅图片类素材）
        if material.url and not material.url.startswith("data:"):
            try:
                await storage.delete(material.url)
            except Exception:
                pass

        material.deleted_at = func.now()
        await self.db.commit()
        return True

    async def delete_all(self, user_id: int | None = None) -> int:
        """软删除所有素材（当前用户）"""
        conditions = [Material.deleted_at.is_(None)]
        if user_id is not None:
            conditions.append(Material.created_by == user_id)

        result = await self.db.execute(
            select(Material).where(*conditions)
        )
        materials = list(result.scalars().all())
        count = len(materials)

        # 删除存储文件
        for m in materials:
            if m.url and not m.url.startswith("data:"):
                try:
                    await storage.delete(m.url)
                except Exception:
                    pass
            m.deleted_at = func.now()

        await self.db.commit()
        return count
