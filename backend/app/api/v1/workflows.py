from __future__ import annotations
"""Dify 工作流 API"""

import time
import json
import asyncio
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Query
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi.responses import StreamingResponse

from app.db.session import get_db
from app.schemas.common import ApiResponse
from app.schemas.workflow import (
    DifyWorkflowCreate,
    DifyWorkflowUpdate,
    WorkflowRunRequest,
    WorkflowRunResponse,
)
from app.services.dify.workflow_service import DifyWorkflowService
from app.services.dify.dify_client import DifyClient
from app.services.dify_task_shadow import (
    detach_deleted_dify_task_safely,
    mirror_dify_task_safely,
)
from app.models.user import User
from app.models.dify_workflow import DifyWorkflowConfig
from app.core.deps import get_current_user, require_admin
from app.core.roles import has_role
from app.utils.timezone import cst_now_naive
from sqlalchemy import select


def now_cst():
    return cst_now_naive()

router = APIRouter()

# ---- Task Queue Manager ----
# 每个 workflow_id 对应一个 asyncio.Lock，确保同一工作流的任务串行执行
_workflow_locks: dict[int, asyncio.Lock] = {}
# 记录每个 workflow 当前是否有任务在运行
_workflow_running: dict[int, bool] = {}


def _get_workflow_lock(wid: int) -> asyncio.Lock:
    if wid not in _workflow_locks:
        _workflow_locks[wid] = asyncio.Lock()
    return _workflow_locks[wid]


def _parse_dify_params(params_data: dict) -> dict:
    """解析 Dify /v1/parameters 响应为 inputs_schema"""
    inputs_schema = {}
    # 尝试多种可能的键名
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
            # Dify 旧格式: {"text-input": {"variable": "...", ...}}
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
            # 扁平格式: {"type": "text-input", "variable": "...", ...}
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


# --- Workflow Configs ---

@router.get("")
async def list_workflows(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """列出当前用户有权访问的已启用工作流"""
    from sqlalchemy import true
    from sqlalchemy.orm import selectinload
    
    if has_role(current_user, "admin"):
        # 管理员看到所有已启用的
        result = await db.execute(
            select(DifyWorkflowConfig).where(DifyWorkflowConfig.is_enabled == true())
        )
        workflows = list(result.scalars().all())
    else:
        # 普通用户只看到分配给他们的
        stmt = (
            select(User)
            .options(selectinload(User.workflows))
            .where(User.id == current_user.id)
        )
        result = await db.execute(stmt)
        user = result.scalar_one()
        workflows = [w for w in user.workflows if w.is_enabled]

    return ApiResponse(data=[
        {
            "id": w.id,
            "name": w.app_name,
            "app_type": w.app_type,
            "description": w.description,
            "enabled": w.is_enabled,
            "inputsSchema": w.inputs_schema,
        }
        for w in workflows
    ])


@router.post("/fetch-params")
async def fetch_workflow_params(
    req: dict,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """从 Dify 获取工作流参数定义"""
    base_url = req.get("base_url", "http://8.163.58.214/v1")
    api_key = req.get("api_key", "")
    if not api_key:
        raise HTTPException(status_code=400, detail="缺少 api_key")

    client = DifyClient(base_url=base_url, api_key=api_key)
    params_data = await client.get_app_parameters()

    import logging
    logger = logging.getLogger(__name__)
    logger.info(f"Dify parameters full response: {params_data}")

    inputs_schema = _parse_dify_params(params_data)
    return ApiResponse(data={
        "inputs_schema": inputs_schema,
        "_raw": params_data,
    })


@router.post("")
async def create_workflow(
    req: DifyWorkflowCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """添加工作流（需登录）"""
    service = DifyWorkflowService(db)

    try:
        # 如果前端传了 inputs_schema，直接使用；否则从 Dify 获取
        if req.inputs_schema:
            inputs_schema = req.inputs_schema
        else:
            client = DifyClient(base_url=req.base_url or "http://8.163.58.214/v1", api_key=req.api_key)
            params_data = await client.get_app_parameters()
            inputs_schema = _parse_dify_params(params_data)

        # 合并请求数据
        data = req.model_dump(exclude={"inputs_schema"})
        data["inputs_schema"] = inputs_schema

        workflow = await service.create_workflow(data)
        return ApiResponse(data={"id": workflow.id})
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"获取工作流参数失败: {str(e)}")


@router.put("/{workflow_id}")
async def update_workflow(
    workflow_id: int,
    req: DifyWorkflowUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """更新工作流（需登录）"""
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
async def delete_workflow(
    workflow_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """删除工作流（需登录）"""
    service = DifyWorkflowService(db)
    deleted = await service.delete_workflow(workflow_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="工作流不存在")
    return ApiResponse(message="已删除")


# --- Tasks (Background Execution) ---

@router.post("/{workflow_id}/tasks")
async def create_task(
    workflow_id: int,
    req: dict,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """创建后台任务（同一工作流的任务会排队，不同工作流可并行）"""
    from app.models.dify_task import DifyTask
    from sqlalchemy import select as _select
    from app.models.dify_workflow import DifyWorkflowConfig

    # Create task record
    task = DifyTask(
        workflow_id=workflow_id,
        user_id=current_user.id,
        status="queued",
        inputs=req.get("inputs", {}),
        created_at=now_cst(),
    )
    db.add(task)
    await db.commit()
    await db.refresh(task)
    task_id = task.id
    await mirror_dify_task_safely(task_id)

    # Start background executor — 每个 workflow 串行，不同 workflow 并行
    asyncio.create_task(_execute_queued_task(workflow_id, task_id, req.get("inputs", {}), current_user.id))

    return ApiResponse(data={"task_id": task.id, "status": "queued"})


async def _execute_queued_task(workflow_id: int, task_id: int, inputs: dict, user_id: int):
    """从队列中执行指定任务。同一 workflow_id 串行，不同 workflow 并行。"""
    import logging
    import traceback as _tb
    from sqlalchemy import select, desc, func
    from app.db.session import async_session as _async_session
    from app.services.dify.dify_client import DifyClient
    from app.models.dify_run_log import DifyRunLog
    from app.models.dify_workflow import DifyWorkflowConfig
    from app.models.dify_task import DifyTask

    logger = logging.getLogger(__name__)
    lock = _get_workflow_lock(workflow_id)

    # 等待同一工作流的前置任务完成
    async with lock:
        # 检查任务是否已被取消
        async with _async_session() as check_db:
            result = await check_db.execute(select(DifyTask).where(DifyTask.id == task_id))
            t = result.scalar_one_or_none()
            if not t or t.status == "cancelled":
                logger.info(f"Task {task_id} was cancelled before execution")
                return

        # 标记为 running
        async with _async_session() as bg_db:
            task_result = await bg_db.execute(select(DifyTask).where(DifyTask.id == task_id))
            task_rec = task_result.scalar_one()
            task_rec.status = "running"
            task_rec.progress = "正在执行..."
            await bg_db.commit()
        await mirror_dify_task_safely(task_id)

        # 执行 Dify API 调用
        try:
            async with _async_session() as bg_db:
                wf_result = await bg_db.execute(
                    select(DifyWorkflowConfig).where(DifyWorkflowConfig.id == workflow_id)
                )
                wf = wf_result.scalar_one_or_none()
                if not wf:
                    raise ValueError(f"Workflow {workflow_id} not found")

                client = DifyClient(base_url=wf.base_url, api_key=wf.api_key)
                is_streaming = False
                start_time = time.time()

                if wf.app_type == "workflow":
                    result_data = await client.run_workflow(inputs=inputs, streaming=is_streaming)
                elif wf.app_type == "chat":
                    query = inputs.get("query", "")
                    result_data = await client.chat(query=query, inputs=inputs, streaming=is_streaming)
                elif wf.app_type == "completion":
                    result_data = await client.completion(inputs=inputs, streaming=is_streaming)
                else:
                    raise ValueError(f"Unsupported app type: {wf.app_type}")

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
                await mirror_dify_task_safely(task_id)

                log = DifyRunLog(
                    workflow_id=workflow_id,
                    user_id=user_id,
                    inputs=inputs,
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

                logger.info(f"Task {task_id} completed in {elapsed_ms:.0f}ms, status={task_rec.status}")

        except Exception as e:
            logger.error(f"Task {task_id} failed: {e}\n{_tb.format_exc()}")
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
                        await mirror_dify_task_safely(task_id)
            except Exception:
                pass


@router.get("/tasks")
async def list_tasks(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取任务列表"""
    from app.models.dify_task import DifyTask
    from sqlalchemy import select, desc, func

    # Count
    count_stmt = select(func.count()).select_from(DifyTask)
    count_result = await db.execute(count_stmt)
    total = count_result.scalar() or 0

    # Paginate - show last 50 tasks
    stmt = (
        select(DifyTask)
        .where(DifyTask.user_id == current_user.id)
        .order_by(desc(DifyTask.created_at))
        .limit(50)
    )
    result = await db.execute(stmt)
    tasks = list(result.scalars().all())

    # 计算每个 queued 任务的排队位置
    # 按 workflow_id 分组，统计每个 workflow 下 queued 任务的数量和顺序
    queued_by_workflow: dict[int, list[int]] = {}
    for t in tasks:
        if t.status == "queued":
            queued_by_workflow.setdefault(t.workflow_id, []).append(t.id)

    # 反转以获取创建时间升序（排在前面的是先创建的）
    for wid in queued_by_workflow:
        queued_by_workflow[wid].reverse()

    # 构建 task_id -> queue_position 映射
    queue_positions: dict[int, int] = {}
    for wid, task_ids in queued_by_workflow.items():
        for idx, tid in enumerate(task_ids):
            queue_positions[tid] = idx + 1

    return ApiResponse(data={
        "items": [
            {
                "id": t.id,
                "workflow_id": t.workflow_id,
                "status": t.status,
                "inputs": t.inputs,
                "outputs": t.outputs,
                "error": t.error,
                "progress": t.progress,
                "elapsed_ms": t.elapsed_ms,
                "viewed": t.viewed,
                "queue_position": queue_positions.get(t.id),
                "created_at": str(t.created_at),
                "finished_at": str(t.finished_at) if t.finished_at else None,
            }
            for t in tasks
        ],
        "total": total,
    })


# --- Run Workflow (Synchronous) ---

@router.post("/{workflow_id}/run")
async def run_workflow(
    workflow_id: int,
    req: WorkflowRunRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """运行工作流"""
    service = DifyWorkflowService(db)

    try:
        client, app_type = await service.get_client(workflow_id)
        is_streaming = req.response_mode == "streaming"
        start_time = time.time()

        import logging
        logger = logging.getLogger(__name__)
        logger.info(f"Running workflow {workflow_id} (type={app_type}) with inputs: {req.inputs}")

        # 根据 app_type 调用不同的 Dify API
        if app_type == "workflow":
            result = await client.run_workflow(inputs=req.inputs, streaming=is_streaming)
        elif app_type == "chat":
            query = req.inputs.get("query", req.inputs.get("content", ""))
            result = await client.chat(query=query, inputs=req.inputs, streaming=is_streaming)
        elif app_type == "completion":
            result = await client.completion(inputs=req.inputs, streaming=is_streaming)
        else:
            raise ValueError(f"不支持的应用类型: {app_type}")

        if is_streaming:
            # SSE stream — 同时记录日志
            async def event_stream():
                full_output = []
                try:
                    async for chunk in result:
                        full_output.append(chunk)
                        yield f"data: {chunk}\n\n"
                finally:
                    # 流结束后保存日志
                    elapsed_ms = (time.time() - start_time) * 1000
                    await service.save_run_log({
                        "workflow_id": workflow_id,
                        "user_id": current_user.id,
                        "inputs": req.inputs,
                        "outputs": {"streaming": True, "chunks": len(full_output)},
                        "status": "succeeded",
                        "started_at": now_cst(),
                        "finished_at": now_cst(),
                        "elapsed_ms": elapsed_ms,
                    })
            return StreamingResponse(event_stream(), media_type="text/event-stream")
        else:
            elapsed_ms = (time.time() - start_time) * 1000

            # 解析结果（不同 API 返回的字段结构不同）
            if app_type == "workflow":
                task_id = result.get("workflow_run_id", result.get("task_id", ""))
                status_str = result.get("status", "succeeded")
                outputs = result.get("data", {}).get("outputs", result.get("outputs", {}))
                error = result.get("data", {}).get("error", result.get("error"))
            elif app_type == "chat":
                task_id = result.get("message_id", result.get("conversation_id", ""))
                status_str = "succeeded"
                outputs = {"answer": result.get("answer", "")}
                error = None
            else:  # completion
                task_id = result.get("message_id", "")
                status_str = "succeeded"
                outputs = result.get("data", result.get("outputs", {}))
                error = result.get("error")

            try:
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
            except Exception as log_err:
                import logging as _log
                _log.getLogger(__name__).warning(f"Failed to save run log: {log_err}")

            return ApiResponse(data=WorkflowRunResponse(
                task_id=str(task_id),
                status=status_str,
                outputs=outputs if isinstance(outputs, dict) else {"result": outputs},
                error=error,
            ).model_dump())

    except ValueError as e:
        import logging as _logging
        _logging.getLogger(__name__).error(f"Workflow error: {e}")
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        import traceback as _tb
        import logging as _logging
        _logging.getLogger(__name__).error(f"Workflow error: {e}\n{_tb.format_exc()}")
        raise HTTPException(status_code=500, detail=f"运行失败: {str(e)}")


@router.post("/{workflow_id}/chat")
async def chat_workflow(
    workflow_id: int,
    req: dict,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """聊天模式运行"""
    service = DifyWorkflowService(db)
    client, _ = await service.get_client(workflow_id)

    is_streaming = req.get("response_mode") == "streaming"
    result = await client.chat(
        query=req["query"],
        inputs=req.get("inputs", {}),
        conversation_id=req.get("conversation_id"),
        streaming=is_streaming,
    )

    if is_streaming:
        async def event_stream():
            async for chunk in result:
                yield f"data: {chunk}\n\n"
        return StreamingResponse(event_stream(), media_type="text/event-stream")

    return ApiResponse(data=result)


@router.post("/tasks/{task_id}/stop")
async def stop_task(
    task_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """停止/取消任务（需登录）"""
    from app.models.dify_task import DifyTask

    result = await db.execute(select(DifyTask).where(DifyTask.id == task_id))
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")

    # 所有权校验
    if task.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="无权操作")

    if task.status in ("succeeded", "failed", "cancelled"):
        return ApiResponse(message=f"任务已{task.status}，无法停止")

    # 取消排队中的任务
    if task.status in ("queued", "running"):
        task.status = "cancelled"
        task.finished_at = now_cst()
        await db.commit()
        await mirror_dify_task_safely(task_id)
        return ApiResponse(message="任务已取消")

    return ApiResponse(message="已停止")


@router.delete("/tasks/{task_id}")
async def delete_task(
    task_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """删除或取消任务记录（需登录）

    - queued 任务：取消并删除
    - running 任务：不允许删除
    - 已完成任务：直接删除
    """
    from app.models.dify_task import DifyTask

    result = await db.execute(select(DifyTask).where(DifyTask.id == task_id))
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")

    # 所有权校验
    if task.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="无权操作")

    if task.status == "running":
        raise HTTPException(status_code=400, detail="执行中的任务不允许删除")

    # queued 任务先取消再删除
    if task.status == "queued":
        task.status = "cancelled"
        task.finished_at = now_cst()
        await db.commit()
        await mirror_dify_task_safely(task_id)

    await mirror_dify_task_safely(task_id)

    await db.delete(task)
    await db.commit()
    await detach_deleted_dify_task_safely(task_id)
    return ApiResponse(message="已删除")


@router.patch("/tasks/{task_id}/view")
async def mark_task_viewed(
    task_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """标记任务为已查看"""
    from app.models.dify_task import DifyTask

    result = await db.execute(select(DifyTask).where(DifyTask.id == task_id))
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    if task.user_id != current_user.id and not has_role(current_user, "admin"):
        raise HTTPException(status_code=403, detail="无权操作")
    task.viewed = 1
    await db.commit()
    return ApiResponse(message="已标记")


# --- Logs ---

@router.get("/logs")
async def get_all_logs(
    page: int = Query(default=1, ge=1, description="页码"),
    limit: int = Query(default=20, ge=1, le=100, description="每页数量"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取所有运行日志"""
    from app.models.dify_run_log import DifyRunLog
    from sqlalchemy import desc, func
    conditions = []
    if not has_role(current_user, "admin"):
        conditions.append(DifyRunLog.user_id == current_user.id)
    # Count
    count_stmt = select(func.count()).select_from(DifyRunLog).where(*conditions)
    count_result = await db.execute(count_stmt)
    total = count_result.scalar() or 0

    # Paginate
    stmt = (
        select(DifyRunLog)
        .where(*conditions)
        .order_by(desc(DifyRunLog.started_at))
        .offset((page - 1) * limit)
        .limit(limit)
    )
    result = await db.execute(stmt)
    logs = list(result.scalars().all())

    return ApiResponse(data={
        "items": [
            {
                "id": log.id,
                "workflow_id": log.workflow_id,
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


@router.get("/{workflow_id}/logs")
async def get_logs(
    workflow_id: int,
    page: int = Query(default=1, ge=1, description="页码"),
    limit: int = Query(default=20, ge=1, le=100, description="每页数量"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取运行日志"""
    from app.models.dify_run_log import DifyRunLog
    from sqlalchemy import desc, func

    conditions = [DifyRunLog.workflow_id == workflow_id]
    if not has_role(current_user, "admin"):
        conditions.append(DifyRunLog.user_id == current_user.id)

    total_result = await db.execute(
        select(func.count()).select_from(DifyRunLog).where(*conditions)
    )
    total = total_result.scalar() or 0
    result = await db.execute(
        select(DifyRunLog)
        .where(*conditions)
        .order_by(desc(DifyRunLog.started_at))
        .offset((page - 1) * limit)
        .limit(limit)
    )
    logs = list(result.scalars().all())
    return ApiResponse(data={
        "items": [
            {
                "id": log.id,
                "workflow_id": log.workflow_id,
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


# --- File Upload ---

@router.post("/files/upload")
async def upload_file(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """上传文件到 Dify（需登录）"""
    # 使用请求体中的 api_key，或默认值
    service = DifyWorkflowService(db)
    workflows = await service.list_workflows()
    if not workflows:
        raise HTTPException(status_code=400, detail="请先添加工作流")

    # 使用第一个工作流的配置
    first = workflows[0]
    client = DifyClient(base_url=first.base_url, api_key=first.api_key)

    file_content = await file.read()
    result = await client.upload_file(
        file_content=file_content,
        filename=file.filename or "upload",
        mimetype=file.content_type or "application/octet-stream",
    )
    return ApiResponse(data=result)
