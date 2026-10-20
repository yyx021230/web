"""Shared primary/standby routing. Probes use one real queued job, never a dummy image."""
from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from types import SimpleNamespace
from typing import Any, Awaitable, Callable, TYPE_CHECKING

import httpx
from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.config import settings
from app.adapters.ai_model.image_results import requested_image_count, validate_image_count

if TYPE_CHECKING:
    from app.models.ai_image_provider import AIImageProvider
    from app.services.ai_image_provider_service import AIImageProviderService

logger = logging.getLogger("app")

# Redis TIME and atomic Lua decisions keep clocks, capacity and recovery probes
# consistent between interactive workers and Hermes workers.
_ACQUIRE = """
local clock = redis.call('TIME')
local now = tonumber(clock[1]) + tonumber(clock[2]) / 1000000
local candidates = cjson.decode(ARGV[1])
for _, p in ipairs(candidates) do
  local state = KEYS[1] .. ':state:' .. p.id
  local slots = KEYS[1] .. ':slots:' .. p.id
  redis.call('ZREMRANGEBYSCORE', slots, '-inf', now)
  local count = redis.call('ZCARD', slots)
  local failures = tonumber(redis.call('HGET', state, 'failures') or '0')
  local retry_at = tonumber(redis.call('HGET', state, 'retry_at') or '0')
  local epoch = tonumber(redis.call('HGET', state, 'epoch') or '0')
  local trial = redis.call('HGET', state, 'trial') or ''
  local trial_active = trial ~= '' and redis.call('ZSCORE', slots, trial)
  local probe = failures >= 2
  local ready = not probe or (now >= retry_at and not trial_active and count < p.capacity)
  if ready then
    if count < p.capacity and (failures == 0 or not trial_active) then
      redis.call('ZADD', slots, now + tonumber(ARGV[3]), ARGV[2])
      redis.call('EXPIRE', slots, math.ceil(tonumber(ARGV[3])) + 60)
      if failures > 0 then redis.call('HSET', state, 'trial', ARGV[2]) end
      return cjson.encode({id=p.id, epoch=epoch, probe=probe})
    end
    -- A healthy/suspect primary that is busy must not spill into paid standbys.
    return cjson.encode({reason='capacity'})
  end
end
return cjson.encode({reason='cooldown'})
"""

_FINISH = """
local state = KEYS[1] .. ':state:' .. ARGV[1]
local slots = KEYS[1] .. ':slots:' .. ARGV[1]
local clock = redis.call('TIME')
local now = tonumber(clock[1]) + tonumber(clock[2]) / 1000000
local expiry = tonumber(redis.call('ZSCORE', slots, ARGV[2]) or '0')
redis.call('ZREM', slots, ARGV[2])
if redis.call('HGET', state, 'trial') == ARGV[2] then
  redis.call('HDEL', state, 'trial')
end
if expiry <= now then return 0 end
local epoch = tonumber(redis.call('HGET', state, 'epoch') or '0')
local failures = tonumber(redis.call('HGET', state, 'failures') or '0')
if epoch ~= tonumber(ARGV[3]) then
  -- A second concurrent failure from the same healthy generation can open the
  -- circuit. Old successes and failures from a previous recovery cannot reset it.
  if not (ARGV[4] == 'failure' and failures == 1 and tonumber(ARGV[3]) == epoch - 1) then
    return 0
  end
end
if ARGV[4] == 'success' then
  if failures > 0 then epoch = epoch + 1 end
  redis.call('HSET', state, 'failures', 0, 'retry_at', 0, 'epoch', epoch)
elseif ARGV[4] == 'failure' then
  failures = math.min(2, failures + 1)
  redis.call('HSET', state, 'failures', failures, 'epoch', epoch + 1)
  if failures >= 2 then
    redis.call('HSET', state, 'retry_at', now + tonumber(ARGV[5]))
  end
elseif failures >= 2 then
  -- A cancelled/invalid-input probe is not proof of recovery.
  redis.call('HSET', state, 'retry_at', now + tonumber(ARGV[5]))
end
return 1
"""


class SharedProviderRouter:
    def __init__(self, model_name: str, redis: Redis | None = None):
        self.redis = redis or Redis.from_url(
            settings.redis_url, decode_responses=True,
            socket_connect_timeout=2, socket_timeout=2,
        )
        self.owns_client = redis is None
        self.key = f"{settings.ai_provider_routing_namespace}:{model_name}"

    async def acquire(self, providers: list[AIImageProvider], *, lease_seconds: float) -> dict:
        from app.services.ai_image_provider_service import _provider_max_concurrent

        ordered = sorted(providers, key=lambda p: (not p.is_default, int(p.priority or 0), p.id))
        candidates = [{"id": p.id, "capacity": _provider_max_concurrent(p)} for p in ordered]
        token = uuid.uuid4().hex
        result = json.loads(await self.redis.eval(
            _ACQUIRE, 1, self.key, json.dumps(candidates), token, lease_seconds,
        ))
        return {**result, "token": token} if "id" in result else result

    async def finish(self, lease: dict, outcome: str) -> None:
        await self.redis.eval(
            _FINISH, 1, self.key, lease["id"], lease["token"], lease["epoch"],
            outcome, max(1, settings.ai_provider_recovery_probe_seconds),
        )

    async def close(self) -> None:
        if self.owns_client:
            await self.redis.aclose()


def classify_failure(result: dict, exc: Exception | None = None) -> tuple[bool, bool, bool]:
    """Return provider fault, proven safe to resubmit, and unknown result."""
    from app.services.ai_image_provider_service import _find_status_code, _is_retryable_mentalout_error
    from app.adapters.ai_model.openai_image_tasks import AsyncImageTaskError

    debug = result.get("upstream_debug") or getattr(exc, "debug", None)
    status = _find_status_code(debug)
    transport = exc.__cause__ if isinstance(exc, AsyncImageTaskError) else exc
    unsent = isinstance(transport, (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout))
    unknown = bool(result.get("result_unknown") or getattr(exc, "result_unknown", False))
    unknown |= isinstance(transport, httpx.RequestError) and not unsent
    unknown |= bool(status and (status >= 500 or status in {408, 499} or 200 <= status < 300))
    terminal = isinstance(debug, dict) and debug.get("terminal_failure") is True
    terminal |= bool(result.get("task_id") and result.get("raw_status") in {"failed", "error"}
                     and result.get("result_unknown") is False)
    terminal |= _is_retryable_mentalout_error(str(exc or result.get("error") or ""))
    fault = unsent or unknown or status in {401, 403, 429} or terminal or bool(result.get("image_urls"))
    if isinstance(transport, httpx.PoolTimeout):
        fault = False
    safe = (unsent or status in {401, 403, 429} or terminal) and not unknown
    return bool(fault), bool(safe and not result.get("image_urls")), bool(unknown)


async def generate_primary_first(
    service: AIImageProviderService, *, prompt: str, params: dict, model_name: str,
    on_provider_selected: Callable[[dict], Awaitable[bool | None]] | None = None,
    on_upstream_accepted: Callable[[dict], Awaitable[None]] | None = None,
    on_routing_wait: Callable[[dict], Awaitable[bool | None]] | None = None,
    on_attempt_finished: Callable[[dict], Awaitable[None]] | None = None,
) -> dict:
    from app.services.ai_image_provider_service import (
        _normalize_generation_mode, _resolve_provider_request_model,
    )

    router = SharedProviderRouter(model_name)
    mode = _normalize_generation_mode(params.get("generation_mode")) if model_name == "gptimage25" else None
    has_reference = bool(params.get("image_data") or params.get("image_url") or params.get("images_data"))
    wait_seconds = max(1, int(settings.ai_provider_wait_timeout_seconds))
    deadline = params.get("_provider_routing_deadline")
    deadline = float(deadline) if isinstance(deadline, (int, float)) else None
    lease_seconds = max(60, int(settings.ai_task_timeout_seconds)) + 60
    result: dict[str, Any] = {"status": "failed", "image_urls": [], "provider_configured": True, "provider": None}
    attempts: list[dict] = []

    async def waiting(reason: str) -> bool:
        nonlocal deadline, result
        if deadline is None:
            deadline = time.time() + wait_seconds
        details = {"reason": reason, "deadline": deadline}
        if on_routing_wait and await on_routing_wait(details) is False:
            result = {**result, "status": "cancelled", "error": "任务已取消，未再次发送到上游"}
            return False
        if time.time() >= deadline:
            result = {
                **result, "status": "failed", "result_unknown": False,
                "error": f"等待生图入口恢复或名额超过 {wait_seconds} 秒，任务已停止；未重复提交结果不明的请求",
            }
            return False
        await asyncio.sleep(0.5)
        return True

    try:
        while True:
            if deadline is not None and time.time() >= deadline:
                await waiting("cooldown")
                return {**result, "routing_attempts": attempts}
            providers = await service.list_providers(model_name)
            await service.release_routing_read_transaction()
            eligible = service._eligible_providers(providers, has_reference, mode)
            if not eligible:
                return {**result, "error": "未找到支持当前模型及参考图的已启用生图入口"}
            try:
                lease = await router.acquire(eligible, lease_seconds=lease_seconds)
            except RedisError:
                if not await waiting("routing_unavailable"):
                    return {**result, "routing_attempts": attempts}
                continue
            if "id" not in lease:
                if not await waiting(lease["reason"]):
                    return {**result, "routing_attempts": attempts}
                continue
            provider = next(p for p in eligible if p.id == lease["id"])
            meta = {"id": provider.id, "name": provider.name, "provider_kind": provider.provider_kind,
                    "provider_model": _resolve_provider_request_model(provider, params)}
            outcome, started, accepted, safe = "neutral", time.monotonic(), False, False
            result = {"status": "failed", "image_urls": [], "provider": meta,
                      "provider_configured": True, "error": None}

            async def accepted_callback(details: dict) -> None:
                nonlocal accepted
                # Async pending markers are local intent, not upstream acceptance.
                accepted = accepted or bool(details.get("upstream_task_id"))
                if on_upstream_accepted:
                    await on_upstream_accepted(details)

            try:
                try:
                    if on_provider_selected and await on_provider_selected(meta) is False:
                        return {**result, "status": "cancelled", "error": "任务已取消，未发送到上游"}
                except Exception:
                    logger.exception("Could not persist provider dispatch evidence")
                    return {**result, "status": "failed", "error": "入口调度记录保存失败，尚未发送到上游"}
                exc = None
                try:
                    # Disable adapter-level submission retries; the shared router
                    # owns the two-attempt policy. Do not mutate the ORM config.
                    attempt_provider = SimpleNamespace(**{
                        field: getattr(provider, field) for field in (
                            "id", "name", "model_name", "provider_kind", "provider_model",
                            "endpoint_url", "api_key", "supports_text_input", "supports_image_input",
                        )
                    }, config={**(provider.config or {}), "upstream_retry_attempts": 1,
                               "tool_choice_retry_attempts": 1})
                    generated = await asyncio.wait_for(
                        service._call_provider(attempt_provider, prompt, params, on_upstream_accepted=accepted_callback),
                        timeout=max(60, int(settings.ai_task_timeout_seconds)),
                    )
                    generated = validate_image_count(generated, requested_image_count(params))
                except Exception as error:
                    exc = error
                    generated = {
                        "status": "failed", "image_urls": [], "error": str(error).strip() or type(error).__name__,
                        "upstream_debug": getattr(error, "debug", None),
                        "result_unknown": isinstance(error, asyncio.TimeoutError),
                    }
                result = {**generated, "provider": meta, "provider_configured": True}
                if generated.get("status") == "completed":
                    outcome = "success"
                else:
                    fault, safe, unknown = classify_failure(generated, exc)
                    if accepted and not safe:
                        unknown = True
                    result["result_unknown"] = unknown
                    outcome = "failure" if fault else "neutral"
                    if unknown or generated.get("image_urls"):
                        safe = False
                attempts.append({"provider_id": provider.id, "outcome": outcome, "probe": lease["probe"],
                                 "safe_to_retry": safe, "result_unknown": bool(result.get("result_unknown"))})
                attempts = attempts[-20:]
                # Persist a closed attempt before any safe retry. A failed evidence
                # write must not turn into an untraceable second paid request.
                if on_attempt_finished:
                    try:
                        await on_attempt_finished({**attempts[-1], "deadline": deadline})
                    except Exception:
                        logger.exception("Could not persist closed provider attempt; retry stopped")
                        safe = False
                try:
                    if outcome == "success":
                        await service._mark_success(provider, (time.monotonic() - started) * 1000)
                    elif outcome == "failure":
                        await service._mark_failure(provider, result.get("error") or "入口生成失败",
                                                    (time.monotonic() - started) * 1000)
                except Exception:
                    logger.exception("Failed to persist provider metrics for primary routing")
                    await service.db.rollback()
            finally:
                try:
                    await router.finish(lease, outcome)
                except RedisError:
                    # Never discard successful images or re-POST after a state-store failure.
                    logger.exception("Shared provider outcome could not be recorded")
                    safe = False
            if not safe:
                return {**result, "routing_attempts": attempts}
            # A failed request alone does not consume the recovery wait budget.
            # Start that clock only when no route/slot can currently be acquired.
            await asyncio.sleep(0.25)
    finally:
        await router.close()
