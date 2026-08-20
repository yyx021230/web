"""Cross-process serialization for SMS-driven logins on one physical phone."""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import logging
import threading
import time
import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import AsyncIterator

from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.config import settings


logger = logging.getLogger(__name__)

_REFRESH_SCRIPT = """
if redis.call('GET', KEYS[1]) == ARGV[1] then
  return redis.call('PEXPIRE', KEYS[1], ARGV[2])
end
return 0
"""

_RELEASE_SCRIPT = """
if redis.call('GET', KEYS[1]) == ARGV[1] then
  return redis.call('DEL', KEYS[1])
end
return 0
"""


@dataclass(frozen=True)
class SmsDeviceLease:
    resource_hash: str
    distributed: bool
    queue_wait_seconds: float


class SmsDeviceCoordinator:
    """Allow only one SMS/QR login flow per physical phone.

    A phone can host two SIMs and two Xiaohongshu app slots. Serializing by
    browser environment or phone number is therefore insufficient: concurrent
    flows can otherwise consume each other's OTP notification.
    """

    _local_guard = threading.Lock()
    _local_locks: dict[tuple[int, int, str], asyncio.Lock] = {}

    def __init__(
        self,
        *,
        redis_url: str,
        lease_seconds: int = 1800,
        acquire_timeout_seconds: int = 1800,
        distributed_enabled: bool = True,
        key_prefix: str = "xhs:sms-login:device",
    ) -> None:
        self.redis_url = redis_url
        self.lease_seconds = max(30, int(lease_seconds or 1800))
        self.acquire_timeout_seconds = max(5, int(acquire_timeout_seconds or 1800))
        self.distributed_enabled = bool(distributed_enabled)
        self.key_prefix = key_prefix.rstrip(":")

    @staticmethod
    def _resource_hash(resource_id: str) -> str:
        normalized = str(resource_id or "").strip().lower()
        if not normalized:
            raise ValueError("短信登录设备锁缺少资源标识")
        return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:32]

    def _redis_key(self, resource_hash: str) -> str:
        return f"{self.key_prefix}:{resource_hash}"

    def _local_lock(self, resource_hash: str) -> asyncio.Lock:
        loop = asyncio.get_running_loop()
        key = (id(self), id(loop), resource_hash)
        with self._local_guard:
            lock = self._local_locks.get(key)
            if lock is None:
                lock = asyncio.Lock()
                self._local_locks[key] = lock
        return lock

    @asynccontextmanager
    async def _local_lease(self, resource_hash: str, started_at: float) -> AsyncIterator[SmsDeviceLease]:
        lock = self._local_lock(resource_hash)
        try:
            await asyncio.wait_for(lock.acquire(), timeout=self.acquire_timeout_seconds)
        except asyncio.TimeoutError as exc:
            raise TimeoutError("等待同一手机的验证码任务释放超时") from exc
        try:
            yield SmsDeviceLease(
                resource_hash=resource_hash,
                distributed=False,
                queue_wait_seconds=max(0.0, time.monotonic() - started_at),
            )
        finally:
            lock.release()

    async def _acquire_distributed(self, redis: Redis, key: str, token: str, deadline: float) -> None:
        ttl_ms = self.lease_seconds * 1000
        while True:
            if await redis.set(key, token, nx=True, px=ttl_ms):
                return
            if time.monotonic() >= deadline:
                raise TimeoutError("等待同一手机的验证码任务释放超时")
            await asyncio.sleep(0.25)

    async def _heartbeat(self, redis: Redis, key: str, token: str) -> None:
        interval = max(10.0, self.lease_seconds / 3)
        ttl_ms = self.lease_seconds * 1000
        while True:
            await asyncio.sleep(interval)
            try:
                refreshed = await redis.eval(_REFRESH_SCRIPT, 1, key, token, ttl_ms)
            except (OSError, RedisError) as exc:
                logger.error("短信登录设备锁心跳访问 Redis 失败: resource_hash=%s error=%s", key.rsplit(":", 1)[-1], exc)
                return
            if int(refreshed or 0) != 1:
                logger.error("短信登录设备锁心跳失效: resource_hash=%s", key.rsplit(":", 1)[-1])
                return

    @asynccontextmanager
    async def _distributed_lease(self, resource_hash: str, started_at: float) -> AsyncIterator[SmsDeviceLease]:
        redis = Redis.from_url(
            self.redis_url,
            encoding="utf-8",
            decode_responses=True,
            socket_connect_timeout=2,
            socket_timeout=5,
        )
        key = self._redis_key(resource_hash)
        token = uuid.uuid4().hex
        deadline = time.monotonic() + self.acquire_timeout_seconds
        acquired = False
        heartbeat: asyncio.Task[None] | None = None
        try:
            await self._acquire_distributed(redis, key, token, deadline)
            acquired = True
            heartbeat = asyncio.create_task(self._heartbeat(redis, key, token))
            yield SmsDeviceLease(
                resource_hash=resource_hash,
                distributed=True,
                queue_wait_seconds=max(0.0, time.monotonic() - started_at),
            )
        finally:
            if heartbeat is not None:
                heartbeat.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await heartbeat
            if acquired:
                with contextlib.suppress(Exception):
                    await redis.eval(_RELEASE_SCRIPT, 1, key, token)
            with contextlib.suppress(Exception):
                await redis.aclose()

    @asynccontextmanager
    async def lease(self, resource_id: str) -> AsyncIterator[SmsDeviceLease]:
        resource_hash = self._resource_hash(resource_id)
        started_at = time.monotonic()
        if self.distributed_enabled:
            entered = False
            try:
                async with self._distributed_lease(resource_hash, started_at) as lease:
                    entered = True
                    yield lease
                    return
            except (OSError, RedisError) as exc:
                if entered:
                    raise
                logger.error("Redis 短信登录设备锁不可用，降级为进程内串行: %s", exc)
        async with self._local_lease(resource_hash, started_at) as lease:
            yield lease


_uses_sqlite = str(getattr(settings, "database_url", "")).lower().startswith("sqlite")
sms_device_coordinator = SmsDeviceCoordinator(
    redis_url=settings.redis_url,
    lease_seconds=getattr(settings, "sms_device_login_lock_lease_seconds", 1800),
    acquire_timeout_seconds=getattr(settings, "sms_device_login_lock_acquire_timeout_seconds", 1800),
    distributed_enabled=bool(getattr(settings, "sms_device_login_lock_enabled", True)) and not _uses_sqlite,
)
