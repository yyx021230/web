"""文案库管理服务"""

from __future__ import annotations

import re
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from app.models.copywriting import Copywriting


class CopywritingService:
    """文案库服务"""

    def __init__(self, db: AsyncSession):
        self.db = db

    @staticmethod
    def _extract_tags(content: str) -> list[str]:
        """从内容中提取 #标签"""
        tags = re.findall(r'#([^\s#]+)', content)
        return list(set(tags))

    @staticmethod
    def _extract_category(title: str, content: str) -> str | None:
        """从标题/内容提取品牌分类"""
        brands = [
            "比亚迪", "零跑", "大众", "沃尔沃", "哈弗", "吉利", "领克", "五菱",
            "丰田", "宝马", "奔驰", "本田", "特斯拉", "小鹏", "理想", "蔚来",
            "福特", "现代", "起亚", "马自达", "别克", "雪佛兰", "日产", "奥迪",
        ]
        text = (title or "") + " " + (content or "")
        for brand in brands:
            if brand in text:
                return brand
        return None

    async def get_list(
        self, page: int = 1, limit: int = 20, category: str | None = None,
        keyword: str | None = None, user_id: int | None = None,
    ) -> tuple[list[Copywriting], int]:
        """获取文案列表（分页）"""
        conditions = [Copywriting.deleted_at.is_(None)]
        if category:
            conditions.append(Copywriting.category == category)
        if keyword:
            kw = f"%{keyword}%"
            conditions.append(
                Copywriting.title.ilike(kw) | Copywriting.content.ilike(kw)
            )
        if user_id is not None:
            conditions.append(Copywriting.created_by == user_id)

        count_stmt = select(func.count(Copywriting.id)).where(*conditions)
        total_result = await self.db.execute(count_stmt)
        total = total_result.scalar() or 0

        items_stmt = (
            select(Copywriting)
            .where(*conditions)
            .order_by(Copywriting.created_at.desc())
            .offset((page - 1) * limit)
            .limit(limit)
        )
        items_result = await self.db.execute(items_stmt)
        items = list(items_result.scalars().all())
        return items, total

    async def get_by_id(self, item_id: int) -> Copywriting | None:
        """根据 ID 获取"""
        result = await self.db.execute(
            select(Copywriting).where(
                Copywriting.id == item_id,
                Copywriting.deleted_at.is_(None),
            )
        )
        return result.scalar_one_or_none()

    async def create(
        self, title: str, content: str, user_id: int | None = None,
    ) -> Copywriting:
        """创建文案"""
        tags = self._extract_tags(content)
        category = self._extract_category(title, content)
        item = Copywriting(
            title=title, content=content, tags=tags, category=category,
            created_by=user_id,
        )
        self.db.add(item)
        await self.db.commit()
        await self.db.refresh(item)
        return item

    async def update(
        self, item_id: int, title: str | None = None, content: str | None = None,
        user_id: int | None = None,
    ) -> Copywriting | None:
        """更新文案"""
        result = await self.db.execute(
            select(Copywriting).where(
                Copywriting.id == item_id,
                Copywriting.deleted_at.is_(None),
            )
        )
        item = result.scalar_one_or_none()
        if not item:
            return None
        if item.created_by is not None and user_id is not None:
            if item.created_by != user_id:
                return None

        if title is not None:
            item.title = title
        if content is not None:
            item.content = content
            item.tags = self._extract_tags(content)
            item.category = self._extract_category(item.title, content)

        await self.db.commit()
        await self.db.refresh(item)
        return item

    async def delete(self, item_id: int, user_id: int | None = None) -> bool:
        """软删除"""
        result = await self.db.execute(
            select(Copywriting).where(
                Copywriting.id == item_id,
                Copywriting.deleted_at.is_(None),
            )
        )
        item = result.scalar_one_or_none()
        if not item:
            return False
        if item.created_by is not None and user_id is not None:
            if item.created_by != user_id:
                return False
        item.deleted_at = func.now()
        await self.db.commit()
        return True

    async def bulk_import(
        self, rows: list[dict], user_id: int | None = None,
    ) -> int:
        """批量导入文案"""
        items = []
        for row in rows:
            title = row.get("title", "").strip()
            content = row.get("content", "").strip()
            if not title or not content:
                continue
            tags = self._extract_tags(content)
            category = self._extract_category(title, content)
            item = Copywriting(
                title=title, content=content, tags=tags, category=category,
                created_by=user_id,
            )
            items.append(item)
        if items:
            self.db.add_all(items)
            await self.db.commit()
        return len(items)

    async def get_categories(self) -> list[dict]:
        """获取所有分类及其数量"""
        result = await self.db.execute(
            select(Copywriting.category, func.count(Copywriting.id))
            .where(
                Copywriting.deleted_at.is_(None),
                Copywriting.category.isnot(None),
            )
            .group_by(Copywriting.category)
            .order_by(Copywriting.category)
        )
        return [{"name": r[0], "count": r[1]} for r in result.all()]
