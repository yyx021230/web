"""项目管理服务"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from app.models.project import Project


class ProjectService:
    """项目服务"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_list(
        self, user_id: int, page: int = 1, limit: int = 20,
    ) -> tuple[list[Project], int]:
        """获取用户项目列表"""
        conditions = [Project.user_id == user_id, Project.deleted_at.is_(None)]

        count_stmt = select(func.count(Project.id)).where(*conditions)
        total_result = await self.db.execute(count_stmt)
        total = total_result.scalar() or 0

        items_stmt = (
            select(Project)
            .where(*conditions)
            .order_by(Project.updated_at.desc())
            .offset((page - 1) * limit)
            .limit(limit)
        )
        items_result = await self.db.execute(items_stmt)
        items = list(items_result.scalars().all())
        return items, total

    async def get_by_id(self, project_id: int, user_id: int) -> Project | None:
        """获取项目详情"""
        result = await self.db.execute(
            select(Project).where(
                Project.id == project_id,
                Project.user_id == user_id,
                Project.deleted_at.is_(None),
            )
        )
        return result.scalar_one_or_none()

    async def create(
        self, user_id: int, name: str, fabric_json: str | None = None,
    ) -> Project:
        """创建项目"""
        project = Project(
            user_id=user_id,
            name=name,
            fabric_json=fabric_json,
        )
        self.db.add(project)
        await self.db.commit()
        await self.db.refresh(project)
        return project

    async def update(
        self, project_id: int, user_id: int,
        name: str | None = None,
        fabric_json: str | None = None,
        thumbnail: str | None = None,
        status: str | None = None,
    ) -> Project | None:
        """更新项目"""
        project = await self.get_by_id(project_id, user_id)
        if not project:
            return None

        if name is not None:
            project.name = name
        if fabric_json is not None:
            project.fabric_json = fabric_json
        if thumbnail is not None:
            project.thumbnail = thumbnail
        if status is not None:
            project.status = status

        await self.db.commit()
        await self.db.refresh(project)
        return project

    async def delete(self, project_id: int, user_id: int) -> bool:
        """软删除项目"""
        project = await self.get_by_id(project_id, user_id)
        if not project:
            return False
        project.deleted_at = func.now()
        await self.db.commit()
        return True
