from __future__ import annotations

from datetime import datetime, timezone


def definitely_not_dispatched(params: dict | None) -> bool:
    params = params or {}
    return (
        (params.get("_routing") or {}).get("phase") in {"preparing", "waiting_provider"}
        and not params.get("_upstream_dispatch_started_at")
        and not params.get("_upstream_attempts")
        and not params.get("provider")
    )


def image_task_progress(status: str, params: dict | None) -> dict:
    params = params or {}
    routing = params.get("_routing") or {}
    phase = status
    messages = {
        "queued": "任务已提交，等待工作进程领取",
        "processing": "正在生成图片",
        "postprocessing": "图片已生成，正在去水印",
        "completed": "生成完成",
        "cancelled": "任务已取消",
        "failed": "任务失败",
    }
    message = messages.get(status, "正在确认任务状态")
    if status == "processing":
        phase = routing.get("phase") or "generating"
        if phase == "preparing":
            message = "正在准备生成任务"
        elif phase == "waiting_provider":
            message = ("可用入口暂时异常，正在等待恢复" if routing.get("reason") == "cooldown"
                       else "可用入口并发已满，正在等待名额")
        elif phase == "submitting":
            message = "已分配入口，正在等待上游生成结果"
    if status == "failed" and params.get("_upstream_result_unknown"):
        phase, message = "review_required", "上游结果待核验，请勿重复提交以免重复计费"
    elif status == "failed" and params.get("_postprocess_failed"):
        phase, message = "postprocess_failed", "图片已生成，去水印处理失败，请勿重新生图"
    waited = 0
    if phase == "waiting_provider" and routing.get("since"):
        try:
            since = datetime.fromisoformat(str(routing["since"]).replace("Z", "+00:00"))
            since = since.replace(tzinfo=timezone.utc) if since.tzinfo is None else since
            waited = max(0, int((datetime.now(timezone.utc) - since).total_seconds()))
        except (TypeError, ValueError):
            pass
    return {"phase": phase, "message": message, "wait_seconds": waited}
