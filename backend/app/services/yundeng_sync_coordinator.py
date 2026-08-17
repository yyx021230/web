from __future__ import annotations

import asyncio
import contextlib
import functools
import inspect
import logging
import threading
import time
import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any, AsyncIterator, Callable

from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.config import settings


logger = logging.getLogger(__name__)


_ACQUIRE_SLOT_SCRIPT = """
local slots_key = KEYS[1]
local token = ARGV[1]
local now_ms = tonumber(ARGV[2])
local expires_at_ms = tonumber(ARGV[3])
local max_slots = tonumber(ARGV[4])
redis.call('ZREMRANGEBYSCORE', slots_key, '-inf', now_ms)
if redis.call('ZCARD', slots_key) < max_slots then
  redis.call('ZADD', slots_key, expires_at_ms, token)
  return 1
end
return 0
"""

_REFRESH_SLOT_SCRIPT = """
if redis.call('ZSCORE', KEYS[1], ARGV[1]) then
  redis.call('ZADD', KEYS[1], ARGV[2], ARGV[1])
  if redis.call('GET', KEYS[2]) == ARGV[1] then
    redis.call('PEXPIRE', KEYS[2], ARGV[3])
  end
  return 1
end
return 0
"""

_REFRESH_ENV_SCRIPT = """
if redis.call('GET', KEYS[1]) == ARGV[1] then
  redis.call('PEXPIRE', KEYS[1], ARGV[2])
  return 1
end
return 0
"""

_RELEASE_ENV_SCRIPT = """
if redis.call('GET', KEYS[1]) == ARGV[1] then
  return redis.call('DEL', KEYS[1])
end
return 0
"""

_START_GATE_SCRIPT = """
local last_ms = tonumber(redis.call('GET', KEYS[1]) or '0')
local now_ms = tonumber(ARGV[1])
local interval_ms = tonumber(ARGV[2])
local wait_ms = interval_ms - (now_ms - last_ms)
if wait_ms <= 0 then
  redis.call('SET', KEYS[1], now_ms, 'PX', math.max(interval_ms * 3, 1000))
  return 0
end
return wait_ms
"""


@dataclass(frozen=True)
class YunDengLease:
    token: str
    environment_id: int
    operation: str
    distributed: bool
    queue_wait_seconds: float


class YunDengSyncCoordinator:
    """Limit browser-heavy sync work across API and worker processes."""

    _local_guard = threading.Lock()
    _local_semaphores: dict[tuple[int, int, int], asyncio.Semaphore] = {}
    _local_environment_locks: dict[tuple[int, int, int], dict[int, asyncio.Lock]] = {}
    _local_start_locks: dict[tuple[int, int, int], asyncio.Lock] = {}
    _local_last_start: dict[tuple[int, int, int], float] = {}

    def __init__(
        self,
        *,
        redis_url: str,
        max_concurrency: int = 5,
        lease_seconds: int = 1800,
        acquire_timeout_seconds: int = 3600,
        start_stagger_seconds: float = 2.0,
        distributed_enabled: bool = True,
        key_prefix: str = "xhs:yundeng:sync",
    ) -> None:
        self.redis_url = redis_url
        self.max_concurrency = max(1, min(int(max_concurrency or 5), 5))
        self.lease_seconds = max(30, int(lease_seconds or 1800))
        self.acquire_timeout_seconds = max(30, int(acquire_timeout_seconds or 3600))
        self.start_stagger_seconds = max(0.0, min(float(start_stagger_seconds or 0.0), 30.0))
        self.distributed_enabled = bool(distributed_enabled)
        self.key_prefix = key_prefix.rstrip(":")

    @property
    def slots_key(self) -> str:
        return f"{self.key_prefix}:slots"

    @property
    def waiters_key(self) -> str:
        return f"{self.key_prefix}:waiters"

    @property
    def start_gate_key(self) -> str:
        return f"{self.key_prefix}:start-gate"

    def _environment_key(self, environment_id: int) -> str:
        return f"{self.key_prefix}:environment:{int(environment_id)}"

    def _local_primitives(
        self,
        max_concurrency: int,
    ) -> tuple[asyncio.Semaphore, dict[int, asyncio.Lock], asyncio.Lock, tuple[int, int, int]]:
        primitive_key = (id(self), id(asyncio.get_running_loop()), int(max_concurrency))
        with self._local_guard:
            semaphore = self._local_semaphores.get(primitive_key)
            if semaphore is None:
                semaphore = asyncio.Semaphore(max_concurrency)
                self._local_semaphores[primitive_key] = semaphore
            environment_locks = self._local_environment_locks.setdefault(primitive_key, {})
            start_lock = self._local_start_locks.setdefault(primitive_key, asyncio.Lock())
        return semaphore, environment_locks, start_lock, primitive_key

    async def _wait_local_start_gate(
        self,
        start_lock: asyncio.Lock,
        primitive_key: tuple[int, int, int],
    ) -> None:
        if self.start_stagger_seconds <= 0:
            return
        async with start_lock:
            elapsed = time.monotonic() - self._local_last_start.get(primitive_key, 0.0)
            if elapsed < self.start_stagger_seconds:
                await asyncio.sleep(self.start_stagger_seconds - elapsed)
            self._local_last_start[primitive_key] = time.monotonic()

    @asynccontextmanager
    async def _local_lease(
        self,
        environment_id: int,
        operation: str,
        token: str,
        started_at: float,
        *,
        max_concurrency: int | None = None,
    ) -> AsyncIterator[YunDengLease]:
        concurrency = max(1, min(int(max_concurrency or self.max_concurrency), self.max_concurrency))
        semaphore, environment_locks, start_lock, primitive_key = self._local_primitives(concurrency)
        env_lock = environment_locks.setdefault(int(environment_id), asyncio.Lock())
        async with env_lock:
            async with semaphore:
                await self._wait_local_start_gate(start_lock, primitive_key)
                yield YunDengLease(
                    token=token,
                    environment_id=int(environment_id),
                    operation=operation,
                    distributed=False,
                    queue_wait_seconds=max(0.0, time.monotonic() - started_at),
                )

    async def _acquire_environment_lock(self, redis: Redis, environment_id: int, token: str, deadline: float) -> None:
        key = self._environment_key(environment_id)
        ttl_ms = self.lease_seconds * 1000
        while True:
            if await redis.set(key, token, nx=True, px=ttl_ms):
                return
            if time.monotonic() >= deadline:
                raise TimeoutError(f"等待云登环境 {environment_id} 释放超时")
            await asyncio.sleep(0.5)

    async def _acquire_slot(self, redis: Redis, token: str, deadline: float) -> None:
        while True:
            now_ms = int(time.time() * 1000)
            acquired = await redis.eval(
                _ACQUIRE_SLOT_SCRIPT,
                1,
                self.slots_key,
                token,
                now_ms,
                now_ms + self.lease_seconds * 1000,
                self.max_concurrency,
            )
            if int(acquired or 0) == 1:
                return
            if time.monotonic() >= deadline:
                raise TimeoutError("等待云登同步并发槽位超时")
            await asyncio.sleep(0.35)

    async def _wait_distributed_start_gate(self, redis: Redis) -> None:
        interval_ms = int(self.start_stagger_seconds * 1000)
        if interval_ms <= 0:
            return
        while True:
            now_ms = int(time.time() * 1000)
            wait_ms = int(
                await redis.eval(
                    _START_GATE_SCRIPT,
                    1,
                    self.start_gate_key,
                    now_ms,
                    interval_ms,
                )
                or 0
            )
            if wait_ms <= 0:
                return
            await asyncio.sleep(min(wait_ms / 1000.0, self.start_stagger_seconds))

    async def _heartbeat(self, redis: Redis, environment_id: int, token: str) -> None:
        interval = max(10.0, self.lease_seconds / 3)
        ttl_ms = self.lease_seconds * 1000
        while True:
            await asyncio.sleep(interval)
            now_ms = int(time.time() * 1000)
            try:
                refreshed = await redis.eval(
                    _REFRESH_SLOT_SCRIPT,
                    2,
                    self.slots_key,
                    self._environment_key(environment_id),
                    token,
                    now_ms + ttl_ms,
                    ttl_ms,
                )
            except (OSError, RedisError) as exc:
                logger.error(
                    "云登同步租约心跳访问 Redis 失败: env_id=%s operation_token=%s error=%s",
                    environment_id,
                    token,
                    exc,
                )
                return

    async def _heartbeat_environment(self, redis: Redis, environment_id: int, token: str) -> None:
        """Keep the environment lock alive while this job waits for a global slot."""

        interval = max(10.0, self.lease_seconds / 3)
        ttl_ms = self.lease_seconds * 1000
        while True:
            await asyncio.sleep(interval)
            try:
                refreshed = await redis.eval(
                    _REFRESH_ENV_SCRIPT,
                    1,
                    self._environment_key(environment_id),
                    token,
                    ttl_ms,
                )
            except (OSError, RedisError) as exc:
                logger.error(
                    "云登环境锁心跳访问 Redis 失败: env_id=%s operation_token=%s error=%s",
                    environment_id,
                    token,
                    exc,
                )
                return
            if int(refreshed or 0) != 1:
                logger.error(
                    "云登环境锁心跳失效: env_id=%s operation_token=%s",
                    environment_id,
                    token,
                )
                return
            if int(refreshed or 0) != 1:
                logger.error(
                    "云登同步租约心跳失效: env_id=%s operation_token=%s",
                    environment_id,
                    token,
                )
                return

    async def _release_distributed(self, redis: Redis, environment_id: int, token: str) -> None:
        pipe = redis.pipeline(transaction=False)
        pipe.zrem(self.slots_key, token)
        pipe.zrem(self.waiters_key, token)
        await pipe.execute()
        await redis.eval(_RELEASE_ENV_SCRIPT, 1, self._environment_key(environment_id), token)

    @asynccontextmanager
    async def _distributed_lease(self, environment_id: int, operation: str, token: str, started_at: float) -> AsyncIterator[YunDengLease]:
        redis = Redis.from_url(
            self.redis_url,
            encoding="utf-8",
            decode_responses=True,
            socket_connect_timeout=2,
            socket_timeout=5,
        )
        deadline = time.monotonic() + self.acquire_timeout_seconds
        heartbeat: asyncio.Task | None = None
        acquired_environment = False
        acquired_slot = False
        try:
            await self._acquire_environment_lock(redis, environment_id, token, deadline)
            acquired_environment = True
            heartbeat = asyncio.create_task(self._heartbeat_environment(redis, environment_id, token))
            await self._acquire_slot(redis, token, deadline)
            acquired_slot = True
            heartbeat.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await heartbeat
            heartbeat = asyncio.create_task(self._heartbeat(redis, environment_id, token))
            await self._wait_distributed_start_gate(redis)
            yield YunDengLease(
                token=token,
                environment_id=int(environment_id),
                operation=operation,
                distributed=True,
                queue_wait_seconds=max(0.0, time.monotonic() - started_at),
            )
        finally:
            if heartbeat is not None:
                heartbeat.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await heartbeat
            if acquired_environment or acquired_slot:
                with contextlib.suppress(Exception):
                    await self._release_distributed(redis, environment_id, token)
            with contextlib.suppress(Exception):
                await redis.aclose()

    @asynccontextmanager
    async def lease(self, environment_id: int, operation: str) -> AsyncIterator[YunDengLease]:
        environment_id = int(environment_id)
        if environment_id <= 0:
            raise ValueError("云登环境 ID 必须大于 0")
        token = f"{uuid.uuid4().hex}:{environment_id}:{operation}"
        started_at = time.monotonic()
        fallback_concurrency: int | None = None
        if self.distributed_enabled:
            entered = False
            try:
                async with self._distributed_lease(environment_id, operation, token, started_at) as lease:
                    entered = True
                    yield lease
                    return
            except (OSError, RedisError) as exc:
                if entered:
                    raise
                fallback_concurrency = 1
                logger.error("Redis 云登调度不可用，降级为进程内单路同步: %s", exc)
        async with self._local_lease(
            environment_id,
            operation,
            token,
            started_at,
            max_concurrency=fallback_concurrency,
        ) as lease:
            yield lease


def yundeng_sync_guard(environment_argument: str, operation: str) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Guard a service method for the full browser/MCP lifetime."""

    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        signature = inspect.signature(func)

        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            bound = signature.bind(*args, **kwargs)
            environment = bound.arguments.get(environment_argument)
            environment_id = int(getattr(environment, "id", environment) or 0)
            environment_name = str(getattr(environment, "account_name", "") or environment_id)
            progress_callback = bound.arguments.get("progress_callback")

            async def emit(payload: dict[str, Any]) -> None:
                if not progress_callback:
                    return
                result = progress_callback(payload)
                if asyncio.iscoroutine(result):
                    await result

            await emit(
                {
                    "phase": "waiting_yundeng_slot",
                    "detail": f"{environment_name} 正在等待云登同步槽位",
                    "runner_id": environment_id,
                    "runner_name": environment_name,
                    "sync_operation": operation,
                }
            )
            async with yundeng_sync_coordinator.lease(environment_id, operation) as lease:
                await emit(
                    {
                        "phase": "yundeng_slot_acquired",
                        "detail": f"{environment_name} 已取得云登同步槽位",
                        "runner_id": environment_id,
                        "runner_name": environment_name,
                        "sync_operation": operation,
                        "queue_wait_seconds": round(lease.queue_wait_seconds, 3),
                        "distributed_lease": lease.distributed,
                    }
                )
                return await func(*args, **kwargs)

        return wrapper

    return decorator


_uses_sqlite = str(getattr(settings, "database_url", "")).lower().startswith("sqlite")
yundeng_sync_coordinator = YunDengSyncCoordinator(
    redis_url=settings.redis_url,
    max_concurrency=getattr(settings, "xhs_yundeng_sync_concurrency", 5),
    lease_seconds=getattr(settings, "xhs_yundeng_lease_seconds", 1800),
    acquire_timeout_seconds=getattr(settings, "xhs_yundeng_acquire_timeout_seconds", 3600),
    start_stagger_seconds=getattr(settings, "xhs_yundeng_start_stagger_seconds", 2.0),
    distributed_enabled=bool(getattr(settings, "xhs_yundeng_distributed_coordinator_enabled", True)) and not _uses_sqlite,
)
