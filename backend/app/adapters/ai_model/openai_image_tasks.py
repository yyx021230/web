"""Sub2API's opt-in async Images protocol. Never repeat an uncertain POST."""

from __future__ import annotations

import asyncio
import re
import time
from typing import Any, Awaitable, Callable
from urllib.parse import urlsplit

import httpx

from app.adapters.ai_model.image_results import (
    requested_image_count,
    validate_image_count,
)


ImageExtractor = Callable[[dict, str], Awaitable[list[str]]]
ReferenceLoader = Callable[[str, int], Awaitable[tuple | None]]
_TASK_ID = re.compile(r"[A-Za-z0-9_-]{1,160}\Z")
_ACTIVE = {"queued", "pending", "processing", "running", "generating"}


class AsyncImageTaskError(RuntimeError):
    def __init__(self, message: str, *, result_unknown: bool):
        super().__init__(message)
        self.result_unknown = result_unknown


def _base_url(endpoint: str) -> str:
    value = endpoint.rstrip("/")
    parts = urlsplit(value)
    if (
        parts.scheme not in {"http", "https"}
        or not parts.hostname
        or parts.username
        or parts.password
        or parts.query
        or parts.fragment
    ):
        raise ValueError("异步图片入口必须是无凭据、无查询参数的 HTTP(S) 地址")
    for suffix in (
        "/images/generations/async",
        "/images/edits/async",
        "/images/generations",
        "/images/edits",
    ):
        if value.endswith(suffix):
            return value[: -len(suffix)]
    return value


def _safe_error(value: Any, default: str, secret: str = "") -> str:
    if isinstance(value, dict):
        value = value.get("message") or value.get("type") or default
    text = str(value or default)
    if secret:
        text = text.replace(secret, "[redacted]")
    text = re.sub(r"(?i)Bearer\s+\S+", "Bearer [redacted]", text)
    text = re.sub(
        r"(?i)([?&](?:token|api_key|key|secret|signature|access_token)=)[^&\s]+",
        r"\1[redacted]",
        text,
    )
    return re.sub(r"\bsk-[A-Za-z0-9_-]+", "[redacted]", text)[:800]


def _task_id(value: Any) -> str:
    result = str(value or "")
    if not _TASK_ID.fullmatch(result):
        raise ValueError("上游图片任务ID无效，已停止请求")
    return result


def _number(config: dict, key: str, default: float, low: float, high: float) -> float:
    try:
        return max(low, min(high, float(config.get(key, default))))
    except (ValueError, TypeError):
        return default


async def _status(
    client: httpx.AsyncClient,
    provider: Any,
    task_id: str,
    expected: int,
    extractor: ImageExtractor,
) -> dict:
    # Never follow a supplier-provided poll_url or redirect with our bearer token.
    url = f"{_base_url(provider.endpoint_url)}/images/tasks/{_task_id(task_id)}"
    unknown = {
        "task_id": task_id,
        "status": "unknown",
        "image_urls": [],
        "result_unknown": True,
    }
    try:
        response = await client.get(
            url,
            headers={"Authorization": f"Bearer {provider.api_key}"},
            timeout=_number(provider.config or {}, "async_poll_timeout", 30, 1, 120),
        )
    except httpx.RequestError:
        return {**unknown, "error": "上游任务查询暂时中断，将按原任务ID继续查询"}
    if response.status_code >= 400:
        return {
            **unknown,
            "error": f"上游任务查询返回 HTTP {response.status_code}；未重新生成",
        }
    try:
        data = response.json()
    except ValueError:
        return {**unknown, "error": "上游任务查询返回无效JSON；未重新生成"}
    if not isinstance(data, dict):
        return {**unknown, "error": "上游任务查询结构无效；未重新生成"}
    returned_id = data.get("task_id") or data.get("id")
    if returned_id is not None and returned_id != task_id:
        return {**unknown, "error": "上游查询返回了其他任务，已拒绝回填"}
    status = str(data.get("status") or "").lower()
    result = {"task_id": task_id, "raw_status": status, "image_urls": []}
    if status in _ACTIVE:
        return {**result, "status": "generating", "error": None}
    if status in {"failed", "cancelled", "canceled", "error"}:
        # A terminal task response is distinct from an uncertain HTTP failure.
        return {
            **result,
            "status": "failed",
            "result_unknown": False,
            "error": _safe_error(
                data.get("error"), "上游异步图片任务确认失败", provider.api_key
            ),
        }
    if status not in {"completed", "succeeded", "success"}:
        return {
            **unknown,
            "raw_status": status,
            "error": "上游图片任务状态未知；保留任务ID待核验",
        }
    body = data.get("result")
    if not isinstance(body, dict):
        body = {"data": [{"url": data["image_url"]}]} if data.get("image_url") else {}
    try:
        urls = await extractor(body, task_id)
    except Exception:
        return {**unknown, "error": "上游图片已生成但结果暂不可读取；保留任务ID待取回"}
    if not urls:
        return {**unknown, "error": "上游图片任务完成但没有可读取图片；未重新生成"}
    return validate_image_count(
        {**result, "status": "completed", "image_urls": urls}, expected
    )


async def get_async_image_task_status(
    provider: Any,
    task_id: str,
    expected_count: int,
    image_extractor: ImageExtractor,
) -> dict:
    _task_id(task_id)
    _base_url(provider.endpoint_url)
    timeout = _number(provider.config or {}, "async_poll_timeout", 30, 1, 120)
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=False) as client:
        return await _status(client, provider, task_id, expected_count, image_extractor)


async def generate_async_images(
    provider: Any,
    prompt: str,
    params: dict,
    *,
    request_model: str,
    ref_sources: list[str],
    reference_loader: ReferenceLoader,
    image_extractor: ImageExtractor,
    on_upstream_accepted: Callable[[dict], Awaitable[None]] | None = None,
) -> dict:
    config = provider.config or {}
    base = _base_url(provider.endpoint_url)
    timeout = _number(config, "async_submit_timeout", 60, 1, 120)
    interval = _number(config, "async_poll_interval", 3, 0.001, 30)
    max_polls = int(_number(config, "async_max_polls", 600, 1, 1800))
    max_wait = _number(config, "async_max_wait", 1800, 1, 1800)
    expected = requested_image_count(params)
    send_n = bool(config.get("send_n", False))
    image_urls: list[str] = []
    last_id = ""
    submission_pending = False

    async def mark_pending(value: bool) -> None:
        if on_upstream_accepted:
            await on_upstream_accepted(
                {
                    "provider_id": provider.id,
                    "provider_kind": provider.provider_kind,
                    "query_capability": "openai_images_async",
                    "submission_pending": value,
                }
            )

    try:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=False) as client:
            for index in range(1 if send_n else expected):
                payload = {"model": request_model, "prompt": prompt}
                if (
                    config.get("send_size")
                    and params.get("width")
                    and params.get("height")
                ):
                    payload["size"] = f"{int(params['width'])}x{int(params['height'])}"
                if params.get("quality") in {"low", "medium", "high"}:
                    payload["quality"] = params["quality"]
                if send_n:
                    payload["n"] = expected
                if config.get("response_format"):
                    payload["response_format"] = config["response_format"]
                headers = {"Authorization": f"Bearer {provider.api_key}"}
                if params.get("_provider_request_id"):
                    headers["X-Client-Request-Id"] = (
                        f"{params['_provider_request_id']}-{index}"
                    )
                kwargs: dict[str, Any] = {"headers": headers}
                if ref_sources:
                    ref = await reference_loader(
                        ref_sources[min(index, len(ref_sources) - 1)], index
                    )
                    if not ref:
                        raise AsyncImageTaskError(
                            "参考图不可读取，未提交生图", result_unknown=False
                        )
                    path = "/images/edits/async"
                    kwargs.update(
                        data={k: str(v) for k, v in payload.items()},
                        files=[("image", ref)],
                    )
                else:
                    path = "/images/generations/async"
                    kwargs["json"] = payload
                try:
                    await mark_pending(True)
                except Exception as exc:
                    raise AsyncImageTaskError(
                        "任务已取消或提交记录无法保存，未发送新的生图请求",
                        result_unknown=False,
                    ) from exc
                submission_pending = True
                try:
                    response = await client.post(base + path, **kwargs)
                except httpx.RequestError as exc:
                    unknown = not isinstance(
                        exc,
                        (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout),
                    )
                    if not unknown:
                        await mark_pending(False)
                        submission_pending = False
                    raise AsyncImageTaskError(
                        f"异步图片提交连接异常（{type(exc).__name__}）；未重复提交",
                        result_unknown=unknown,
                    ) from exc
                if response.status_code >= 400:
                    unknown = response.status_code >= 500 or response.status_code in {
                        408,
                        499,
                    }
                    if not unknown:
                        await mark_pending(False)
                        submission_pending = False
                    raise AsyncImageTaskError(
                        f"异步图片提交返回 HTTP {response.status_code}；未回退同步或重复提交",
                        result_unknown=unknown,
                    )
                if response.is_redirect:
                    raise AsyncImageTaskError(
                        "异步图片入口返回重定向，已拒绝转发凭据", result_unknown=True
                    )
                try:
                    accepted = response.json()
                    last_id = _task_id(accepted.get("task_id") or accepted.get("id"))
                except (ValueError, AttributeError) as exc:
                    raise AsyncImageTaskError(
                        "异步图片提交回执无有效任务ID；结果待核验，未重新提交",
                        result_unknown=True,
                    ) from exc
                if on_upstream_accepted:
                    try:
                        await on_upstream_accepted(
                            {
                                "upstream_task_id": last_id,
                                "provider_id": provider.id,
                                "provider_kind": provider.provider_kind,
                                "provider_model": request_model,
                                "query_capability": "openai_images_async",
                                "expected_count": expected if send_n else 1,
                            }
                        )
                    except Exception as exc:
                        raise AsyncImageTaskError(
                            f"上游任务 {last_id} 已受理，但本地记录未确认；禁止重复生成",
                            result_unknown=True,
                        ) from exc
                submission_pending = False
                deadline = time.monotonic() + max_wait
                result = None
                for poll in range(max_polls):
                    result = await _status(
                        client,
                        provider,
                        last_id,
                        expected if send_n else 1,
                        image_extractor,
                    )
                    if result["status"] in {"completed", "failed"}:
                        break
                    if time.monotonic() >= deadline or poll == max_polls - 1:
                        result = {
                            "task_id": last_id,
                            "status": "failed",
                            "image_urls": [],
                            "result_unknown": True,
                            "error": "上游任务尚未确认完成，已保存原任务ID，未重复生成",
                        }
                        break
                    await asyncio.sleep(interval)
                assert result is not None
                image_urls.extend(result.get("image_urls") or [])
                if result["status"] != "completed":
                    return {**result, "image_urls": image_urls}
    except AsyncImageTaskError as exc:
        if not image_urls:
            raise
        return {
            "task_id": last_id,
            "status": "failed",
            "image_urls": image_urls,
            "result_unknown": exc.result_unknown,
            "error": str(exc),
        }
    except Exception as exc:
        return {
            "task_id": last_id,
            "status": "failed",
            "image_urls": image_urls,
            "result_unknown": submission_pending,
            "error": f"异步图片处理异常（{type(exc).__name__}）；已保留已有结果，未重复生成",
        }
    return validate_image_count(
        {"task_id": last_id, "status": "completed", "image_urls": image_urls}, expected
    )
