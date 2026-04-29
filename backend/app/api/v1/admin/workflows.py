"""Admin workflow management API"""
from __future__ import annotations

from datetime import datetime, timezone, timedelta
import time

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, desc, and_

from app.db.session import get_db, async_session
from app.schemas.common import ApiResponse
from app.schemas.workflow import DifyWorkflowCreate, DifyWorkflowUpdate, WorkflowRunRequest, WorkflowRunResponse
from app.core.deps import require_admin
from app.models.user import User
from app.models.dify_workflow import DifyWorkflowConfig
from app.models.dify_task import DifyTask
from app.models.dify_run_log import DifyRunLog
from app.services.dify.workflow_service import DifyWorkflowService
from app.services.dify.dify_client import DifyClient
from app.schemas.workflow import WorkflowRunRequest

# CST = UTC+8
CST = timezone(timedelta(hours=8))

def now_cst():
    return datetime.now(CST).replace(tzinfo=None)


async def _usernames(db: AsyncSession, ids: list[int]) -> dict[int, str]:
    """Fetch usernames by IDs efficiently"""
    unique = set(ids)
    result = await db.execute(select(User.id, User.username).where(User.id.in_(unique)))
    return {r.id: r.username for r in result}


router = APIRouter()


def _parse_dify_params(params_data: dict) -> dict:
    """Parse Dify /v1/parameters response into inputs_schema"""
    inputs_schema = {}
    user_input_form = (
        params_data.get("user_input_form")
        or params_data.get("parameters")
        or params_data.get("inputs")
        or params_data.get("variables")
        or []
    )
    for item in user_input_form:
        if not isinstance(item, dict):
            continue
        keys = list(item.keys())
        if len(keys) == 1 and keys[0] not in ("type", "variable", "label", "required", "name"):
            field_type = keys[0]
            props = item[field_type]
            if isinstance(props, dict):
                key = props.get("variable", props.get("name", ""))
                if key:
                    inputs_schema[key] = {
                        "label": props.get("label", key),
                        "type": field_type,
                        "required": props.get("required", False),
                        "placeholder": props.get("placeholder", ""),
                        "hint": props.get("hint", ""),
                        "max_length": props.get("max_length", None),
                        "options": props.get("options", []),
                        "default": props.get("default", ""),
                    }
        elif "variable" in item or "name" in item:
            field_type = item.get("type", "text-input")
            key = item.get("variable", item.get("name", ""))
            if key:
                inputs_schema[key] = {
                    "label": item.get("label", key),
                    "type": field_type,
                    "required": item.get("required", False),
                    "placeholder": item.get("placeholder", ""),
                    "hint": item.get("hint", ""),
                    "max_length": item.get("max_length", None),
                    "options": item.get("options", []),
                    "default": item.get("default", ""),
                }
    return inputs_schema


# --- Workflow CRUD ---

@router.get("")
async def admin_list_workflows(
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=20, ge=1, le=100),
    search: str | None = Query(default=None, description="搜索名称"),
    created_by: int | None = Query(default=None, description="按创建者筛选"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """列出所有工作流（管理员，可按创建者筛选）"""
    conditions = []
    if search:
        conditions.append(DifyWorkflowConfig.app_name.ilike(f"%{search}%"))
    if created_by:
        conditions.append(DifyWorkflowConfig.created_by == created_by)

    count_stmt = select(func.count()).select_from(DifyWorkflowConfig).where(*conditions) if conditions else select(func.count()).select_from(DifyWorkflowConfig)
    count_result = await db.execute(count_stmt)
    total = count_result.scalar() or 0

    stmt = (
        select(DifyWorkflowConfig)
        .where(*conditions) if conditions else select(DifyWorkflowConfig)
        .order_by(desc(DifyWorkflowConfig.created_at))
        .offset((page - 1) * limit)
        .limit(limit)
    )
    result = await db.execute(stmt)
    items = list(result.scalars().all())

    creator_ids = [w.created_by for w in items if w.created_by]
    names = await _usernames(db, creator_ids) if creator_ids else {}

    return ApiResponse(data={
        "items": [
            {
                "id": w.id,
                "name": w.app_name,
                "app_type": w.app_type,
                "description": w.description,
                "enabled": w.is_enabled,
                "inputs_schema": w.inputs_schema,
                "base_url": w.base_url,
                "api_key_prefix": w.api_key[:8] + "..." if w.api_key else "",
                "created_by": w.created_by,
                "created_by_name": names.get(w.created_by) if w.created_by else None,
                "created_at": str(w.created_at),
            }
            for w in items
        ],
        "total": total,
        "page": page,
        "limit": limit,
    })


@router.post("")
async def admin_create_workflow(
    req: DifyWorkflowCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """创建工作流（管理员）"""
    service = DifyWorkflowService(db)

    try:
        if req.inputs_schema:
            inputs_schema = req.inputs_schema
        else:
            client = DifyClient(base_url=req.base_url or "http://8.163.58.214/v1", api_key=req.api_key)
            params_data = await client.get_app_parameters()
            inputs_schema = _parse_dify_params(params_data)

        data = req.model_dump(exclude={"inputs_schema"})
        data["created_by"] = current_user.id
        data["inputs_schema"] = inputs_schema

        workflow = await service.create_workflow(data)
        return ApiResponse(data={"id": workflow.id})
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"获取工作流参数失败: {str(e)}")


@router.post("/fetch-params")
async def admin_fetch_workflow_params(
    req: dict,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """从 Dify 获取工作流参数定义（管理员）"""
    base_url = req.get("base_url", "http://8.163.58.214/v1")
    api_key = req.get("api_key", "")
    if not api_key:
        raise HTTPException(status_code=400, detail="缺少 api_key")

    client = DifyClient(base_url=base_url, api_key=api_key)
    params_data = await client.get_app_parameters()

    inputs_schema = _parse_dify_params(params_data)
    return ApiResponse(data={"inputs_schema": inputs_schema, "_raw": params_data})


@router.put("/{workflow_id}")
async def admin_update_workflow(
    workflow_id: int,
    req: DifyWorkflowUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """更新工作流（管理员）"""
    result = await db.execute(select(DifyWorkflowConfig).where(DifyWorkflowConfig.id == workflow_id))
    workflow = result.scalar_one_or_none()
    if not workflow:
        raise HTTPException(status_code=404, detail="工作流不存在")

    update_data = req.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(workflow, key, value)

    await db.commit()
    await db.refresh(workflow)
    return ApiResponse(data={"id": workflow.id})


@router.delete("/{workflow_id}")
async def admin_delete_workflow(
    workflow_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """删除工作流（管理员）"""
    service = DifyWorkflowService(db)
    deleted = await service.delete_workflow(workflow_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="工作流不存在")
    return ApiResponse(message="已删除")


# --- Workflow Execution ---

@router.post("/{workflow_id}/run")
async def admin_run_workflow(
    workflow_id: int,
    req: WorkflowRunRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """运行工作流（管理员）"""
    service = DifyWorkflowService(db)

    try:
        client, app_type = await service.get_client(workflow_id)
        is_streaming = req.response_mode == "streaming"
        start_time = time.time()

        if app_type == "workflow":
            result = await client.run_workflow(inputs=req.inputs, streaming=False)
        elif app_type == "chat":
            query = req.inputs.get("query", req.inputs.get("content", ""))
            result = await client.chat(query=query, inputs=req.inputs, streaming=False)
        elif app_type == "completion":
            result = await client.completion(inputs=req.inputs, streaming=False)
        else:
            raise ValueError(f"不支持的应用类型: {app_type}")

        elapsed_ms = (time.time() - start_time) * 1000

        if app_type == "workflow":
            task_id = result.get("workflow_run_id", result.get("task_id", ""))
            outputs = result.get("data", {}).get("outputs", result.get("outputs", {}))
            error = result.get("data", {}).get("error", result.get("error"))
        elif app_type == "chat":
            task_id = result.get("message_id", "")
            outputs = {"answer": result.get("answer", "")}
            error = None
        else:
            task_id = result.get("message_id", "")
            outputs = result.get("data", result.get("outputs", {}))
            error = result.get("error")

        await service.save_run_log({
            "workflow_id": workflow_id,
            "user_id": current_user.id,
            "inputs": req.inputs,
            "outputs": outputs if isinstance(outputs, dict) else {"result": outputs},
            "status": "succeeded" if not error else "failed",
            "task_id": str(task_id),
            "error": error,
            "started_at": now_cst(),
            "finished_at": now_cst(),
            "elapsed_ms": elapsed_ms,
        })

        return ApiResponse(data=WorkflowRunResponse(
            task_id=str(task_id),
            status="succeeded" if not error else "failed",
            outputs=outputs if isinstance(outputs, dict) else {"result": outputs},
            error=error,
        ).model_dump())

    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"运行失败: {str(e)}")


@router.post("/{workflow_id}/tasks")
async def admin_create_task(
    workflow_id: int,
    req: dict,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """创建后台任务（异步执行）"""
    import asyncio

    task = DifyTask(
        workflow_id=workflow_id,
        user_id=req.get("user_id", current_user.id),
        status="pending",
        inputs=req.get("inputs", {}),
        created_at=now_cst(),
    )
    db.add(task)
    await db.commit()
    await db.refresh(task)
    task_id = task.id

    async def run_in_background():
        import logging
        import traceback
        from app.db.session import async_session as _async_session
        from app.services.dify.dify_client import DifyClient

        logger = logging.getLogger(__name__)
        try:
            async with _async_session() as bg_db:
                result = await bg_db.execute(
                    select(DifyWorkflowConfig).where(DifyWorkflowConfig.id == workflow_id)
                )
                wf = result.scalar_one_or_none()
                if not wf:
                    return

                task_result = await bg_db.execute(select(DifyTask).where(DifyTask.id == task_id))
                task_rec = task_result.scalar_one()
                task_rec.status = "running"
                task_rec.progress = "正在执行..."
                await bg_db.commit()

                client = DifyClient(base_url=wf.base_url, api_key=wf.api_key)
                start_time = time.time()

                if wf.app_type == "workflow":
                    result_data = await client.run_workflow(inputs=req.get("inputs", {}), streaming=False)
                elif wf.app_type == "chat":
                    query = req.get("inputs", {}).get("query", "")
                    result_data = await client.chat(query=query, inputs=req.get("inputs", {}), streaming=False)
                elif wf.app_type == "completion":
                    result_data = await client.completion(inputs=req.get("inputs", {}), streaming=False)
                else:
                    raise ValueError(f"Unsupported app_type: {wf.app_type}")

                elapsed_ms = (time.time() - start_time) * 1000

                if wf.app_type == "workflow":
                    task_id_str = result_data.get("workflow_run_id", result_data.get("task_id", ""))
                    outputs = result_data.get("data", {}).get("outputs", result_data.get("outputs", {}))
                    error = result_data.get("data", {}).get("error", result_data.get("error"))
                elif wf.app_type == "chat":
                    task_id_str = result_data.get("message_id", "")
                    outputs = {"answer": result_data.get("answer", "")}
                    error = None
                else:
                    task_id_str = result_data.get("message_id", "")
                    outputs = result_data.get("data", result_data.get("outputs", {}))
                    error = result_data.get("error")

                task_result = await bg_db.execute(select(DifyTask).where(DifyTask.id == task_id))
                task_rec = task_result.scalar_one()
                task_rec.status = "failed" if error else "succeeded"
                task_rec.task_id = str(task_id_str)
                task_rec.outputs = outputs if isinstance(outputs, dict) else {"result": outputs}
                task_rec.error = error
                task_rec.progress = ""
                task_rec.elapsed_ms = elapsed_ms
                task_rec.finished_at = now_cst()
                await bg_db.commit()

                log = DifyRunLog(
                    workflow_id=workflow_id,
                    user_id=task_rec.user_id,
                    inputs=req.get("inputs", {}),
                    outputs=outputs if isinstance(outputs, dict) else {"result": outputs},
                    status="failed" if error else "succeeded",
                    task_id=str(task_id_str),
                    error=error,
                    elapsed_ms=elapsed_ms,
                    started_at=now_cst(),
                    finished_at=now_cst(),
                )
                bg_db.add(log)
                await bg_db.commit()

                logger.info(f"Task {task_id} completed in {elapsed_ms:.0f}ms")

        except Exception as e:
            logger.error(f"Task {task_id} failed: {e}\n{traceback.format_exc()}")
            try:
                async with _async_session() as bg_db:
                    task_result = await bg_db.execute(select(DifyTask).where(DifyTask.id == task_id))
                    task_rec = task_result.scalar_one_or_none()
                    if task_rec:
                        task_rec.status = "failed"
                        task_rec.error = str(e)
                        task_rec.progress = ""
                        task_rec.finished_at = now_cst()
                        await bg_db.commit()
            except Exception:
                pass

    asyncio.create_task(run_in_background())
    return ApiResponse(data={"task_id": task.id, "status": "pending"})


# --- Tasks (all users) ---

@router.get("/tasks")
async def admin_list_tasks(
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=20, ge=1, le=100),
    username: str | None = Query(default=None, description="按用户名筛选"),
    workflow_id: int | None = Query(default=None, description="按工作流筛选"),
    status: str | None = Query(default=None, description="按状态筛选"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """查看所有用户任务（管理员）"""
    conditions = []
    if username:
        user_result = await db.execute(select(User).where(User.username == username))
        u = user_result.scalar_one_or_none()
        if u:
            conditions.append(DifyTask.user_id == u.id)
    if workflow_id:
        conditions.append(DifyTask.workflow_id == workflow_id)
    if status:
        conditions.append(DifyTask.status == status)

    count_stmt = select(func.count()).select_from(DifyTask).where(*conditions) if conditions else select(func.count()).select_from(DifyTask)
    count_result = await db.execute(count_stmt)
    total = count_result.scalar() or 0

    stmt = (
        select(DifyTask)
        .where(*conditions) if conditions else select(DifyTask)
        .order_by(desc(DifyTask.created_at))
        .offset((page - 1) * limit)
        .limit(limit)
    )
    result = await db.execute(stmt)
    items = list(result.scalars().all())

    user_ids = [t.user_id for t in items if t.user_id]
    names = await _usernames(db, user_ids) if user_ids else {}

    return ApiResponse(data={
        "items": [
            {
                "id": t.id,
                "workflow_id": t.workflow_id,
                "user_id": t.user_id,
                "user_name": names.get(t.user_id),
                "status": t.status,
                "inputs": t.inputs,
                "outputs": t.outputs,
                "error": t.error,
                "progress": t.progress,
                "elapsed_ms": t.elapsed_ms,
                "viewed": t.viewed,
                "created_at": str(t.created_at),
                "finished_at": str(t.finished_at) if t.finished_at else None,
            }
            for t in items
        ],
        "total": total,
        "page": page,
        "limit": limit,
    })


@router.delete("/tasks/{task_id}")
async def admin_delete_task(
    task_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """删除任务记录（管理员）"""
    result = await db.execute(select(DifyTask).where(DifyTask.id == task_id))
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    if task.status in ("running", "pending"):
        raise HTTPException(status_code=400, detail="执行中的任务不允许删除")

    await db.delete(task)
    await db.commit()
    return ApiResponse(message="已删除")


@router.patch("/tasks/{task_id}/view")
async def admin_mark_task_viewed(
    task_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """标记任务为已查看（管理员）"""
    result = await db.execute(select(DifyTask).where(DifyTask.id == task_id))
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    task.viewed = 1
    await db.commit()
    return ApiResponse(message="已标记")


# --- Logs (all users) ---

@router.get("/logs")
async def admin_get_all_logs(
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=20, ge=1, le=100),
    username: str | None = Query(default=None, description="按用户名筛选"),
    workflow_id: int | None = Query(default=None, description="按工作流筛选"),
    status: str | None = Query(default=None, description="按状态筛选"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """获取所有运行日志（管理员，可按用户/工作流筛选）"""
    conditions = []
    if username:
        user_result = await db.execute(select(User).where(User.username == username))
        u = user_result.scalar_one_or_none()
        if u:
            conditions.append(DifyRunLog.user_id == u.id)
    if workflow_id:
        conditions.append(DifyRunLog.workflow_id == workflow_id)
    if status:
        conditions.append(DifyRunLog.status == status)

    count_stmt = select(func.count()).select_from(DifyRunLog).where(*conditions) if conditions else select(func.count()).select_from(DifyRunLog)
    count_result = await db.execute(count_stmt)
    total = count_result.scalar() or 0

    stmt = (
        select(DifyRunLog)
        .where(*conditions) if conditions else select(DifyRunLog)
        .order_by(desc(DifyRunLog.started_at))
        .offset((page - 1) * limit)
        .limit(limit)
    )
    result = await db.execute(stmt)
    logs = list(result.scalars().all())

    user_ids = [log.user_id for log in logs if log.user_id]
    names = await _usernames(db, user_ids) if user_ids else {}

    return ApiResponse(data={
        "items": [
            {
                "id": log.id,
                "workflow_id": log.workflow_id,
                "user_id": log.user_id,
                "user_name": names.get(log.user_id),
                "status": log.status,
                "inputs": log.inputs,
                "outputs": log.outputs,
                "error": log.error,
                "task_id": log.task_id,
                "started_at": str(log.started_at),
                "finished_at": str(log.finished_at) if log.finished_at else None,
                "elapsed_ms": log.elapsed_ms,
            }
            for log in logs
        ],
        "total": total,
        "page": page,
        "limit": limit,
    })
