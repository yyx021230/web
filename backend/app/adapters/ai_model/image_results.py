"""Count and completion rules shared by generation and result recovery."""

from __future__ import annotations

from typing import Any


def requested_image_count(params: dict | None) -> int:
    return max(1, min(int((params or {}).get("count") or 1), 4))


def unique_image_urls(urls: list | None) -> list[str]:
    return list(dict.fromkeys(url for url in (urls or []) if isinstance(url, str) and url.strip()))


def validate_image_count(result: dict, expected: int) -> dict:
    urls = unique_image_urls(result.get("image_urls"))
    result = {**result, "image_urls": urls}
    if result.get("status") == "completed" and len(urls) < expected:
        result.update(
            status="failed",
            error=f"图片数量不足：请求 {expected} 张，实际返回 {len(urls)} 张；未自动重新生成，避免重复计费",
        )
    return result


def batch_result(
    data: dict[str, Any], task_id: str, api_base: str, expected_count: int | None = None,
) -> dict:
    """A child image is progress, not proof that the whole batch completed."""
    successes = {"succeeded", "success", "completed", "done", "finished"}
    failures = {"failed", "cancelled", "canceled", "error"}
    raw_status = str(data.get("status") or "").strip().lower()
    tasks = [item for item in (data.get("tasks") or []) if isinstance(item, dict)]
    urls, errors, active = [], [], False
    for item in tasks:
        status = str(item.get("status") or "").strip().lower()
        active = active or bool(status and status not in successes | failures)
        for key in ("errorMessage", "error_message", "error", "message", "detail", "debugMessage"):
            if item.get(key):
                errors.append(str(item[key]))
                break
        if status in failures or (status and status not in successes):
            continue
        sources = [item] + [item[key] for key in ("result", "output", "data") if isinstance(item.get(key), dict)]
        url = next((source[key] for source in sources
                    for key in ("imageUrl", "image_url", "url", "outputUrl", "output_url")
                    if source.get(key)), None)
        if url:
            urls.append(f"{api_base}{url}" if str(url).startswith("/") else str(url))
    urls = unique_image_urls(urls)
    expected = expected_count or data.get("count") or len(tasks) or 1
    expected = max(int(expected), int(data.get("count") or 0), len(tasks))
    result = {"task_id": task_id, "status": "generating", "raw_status": raw_status,
              "image_urls": urls, "error": None}
    if raw_status in failures:
        detail = errors[0] if errors else f"任务{raw_status}"
        if urls:
            detail = f"请求 {expected} 张，已返回 {len(urls)} 张；{detail}；未重跑已成功图片"
        result.update(status="failed", error=detail)
    elif raw_status in successes and not active:
        if not urls:
            result.update(status="unknown", error="上游任务已完成但没有返回图片")
        else:
            result["status"] = "completed"
            result = validate_image_count(result, expected)
    return result
