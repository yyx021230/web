from __future__ import annotations
"""Dify 工作流管理服务"""

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc, func
from app.models.dify_workflow import DifyWorkflowConfig
from app.models.dify_run_log import DifyRunLog
from app.services.dify.dify_client import DifyClient


class DifyWorkflowService:
    """Dify 工作流管理服务"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def list_workflows(self) -> list[DifyWorkflowConfig]:
        """列出所有工作流"""
        result = await self.db.execute(
            select(DifyWorkflowConfig).order_by(DifyWorkflowConfig.created_at.desc())
        )
        return list(result.scalars().all())

    async def create_workflow(self, data: dict) -> DifyWorkflowConfig:
        """创建工作流"""
        workflow = DifyWorkflowConfig(**data)
        self.db.add(workflow)
        await self.db.commit()
        await self.db.refresh(workflow)
        return workflow

    async def delete_workflow(self, workflow_id: int) -> bool:
        """删除工作流"""
        result = await self.db.execute(select(DifyWorkflowConfig).where(DifyWorkflowConfig.id == workflow_id))
        workflow = result.scalar_one_or_none()
        if not workflow:
            return False
        await self.db.delete(workflow)
        await self.db.commit()
        return True

    async def get_client(self, workflow_id: int) -> tuple[DifyClient, str]:
        """获取工作流对应的 Dify 客户端和应用类型

        Returns:
            (DifyClient, app_type)
        """
        result = await self.db.execute(select(DifyWorkflowConfig).where(DifyWorkflowConfig.id == workflow_id))
        workflow = result.scalar_one_or_none()
        if not workflow:
            raise ValueError(f"Workflow {workflow_id} not found")

        client = DifyClient(base_url=workflow.base_url, api_key=workflow.api_key)
        return client, workflow.app_type

    async def save_run_log(self, data: dict) -> DifyRunLog:
        """保存运行日志"""
        log = DifyRunLog(**data)
        self.db.add(log)
        await self.db.commit()
        await self.db.refresh(log)
        return log

    async def get_run_logs(self, workflow_id: int, page: int = 1, limit: int = 20) -> tuple[list[DifyRunLog], int]:
        """获取运行日志列表"""
        # Count
        from sqlalchemy import func
        count_stmt = select(func.count()).select_from(DifyRunLog).where(DifyRunLog.workflow_id == workflow_id)
        count_result = await self.db.execute(count_stmt)
        total = count_result.scalar() or 0

        # Paginate
        stmt = (
            select(DifyRunLog)
            .where(DifyRunLog.workflow_id == workflow_id)
            .order_by(desc(DifyRunLog.started_at))
            .offset((page - 1) * limit)
            .limit(limit)
        )
        result = await self.db.execute(stmt)
        return list(result.scalars().all()), total
