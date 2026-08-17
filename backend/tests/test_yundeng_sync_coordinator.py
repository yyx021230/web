import asyncio
from contextlib import asynccontextmanager

import pytest
from redis.exceptions import RedisError

from app.services.yundeng_sync_coordinator import YunDengSyncCoordinator


def _local_coordinator(max_concurrency: int = 5) -> YunDengSyncCoordinator:
    YunDengSyncCoordinator._local_semaphores.clear()
    YunDengSyncCoordinator._local_environment_locks.clear()
    YunDengSyncCoordinator._local_start_locks.clear()
    YunDengSyncCoordinator._local_last_start.clear()
    return YunDengSyncCoordinator(
        redis_url="redis://unused",
        max_concurrency=max_concurrency,
        start_stagger_seconds=0,
        distributed_enabled=False,
    )


@pytest.mark.asyncio
async def test_local_coordinator_caps_total_concurrency_at_five():
    coordinator = _local_coordinator(5)
    running = 0
    peak = 0
    guard = asyncio.Lock()

    async def run(environment_id: int) -> None:
        nonlocal running, peak
        async with coordinator.lease(environment_id, "test"):
            async with guard:
                running += 1
                peak = max(peak, running)
            await asyncio.sleep(0.02)
            async with guard:
                running -= 1

    await asyncio.gather(*(run(index + 1) for index in range(12)))
    assert peak == 5


@pytest.mark.asyncio
async def test_local_coordinator_serializes_the_same_environment():
    coordinator = _local_coordinator(5)
    running_by_environment: dict[int, int] = {}
    peak_by_environment: dict[int, int] = {}

    async def run(environment_id: int) -> None:
        async with coordinator.lease(environment_id, "test"):
            running_by_environment[environment_id] = running_by_environment.get(environment_id, 0) + 1
            peak_by_environment[environment_id] = max(
                peak_by_environment.get(environment_id, 0),
                running_by_environment[environment_id],
            )
            await asyncio.sleep(0.01)
            running_by_environment[environment_id] -= 1

    await asyncio.gather(*(run(7) for _ in range(6)), *(run(8) for _ in range(3)))
    assert peak_by_environment == {7: 1, 8: 1}


@pytest.mark.asyncio
async def test_local_coordinator_releases_slot_after_failure():
    coordinator = _local_coordinator(1)

    with pytest.raises(RuntimeError, match="boom"):
        async with coordinator.lease(1, "test"):
            raise RuntimeError("boom")

    async def acquire_once() -> None:
        async with coordinator.lease(2, "test"):
            pass

    await asyncio.wait_for(acquire_once(), timeout=1)


@pytest.mark.asyncio
async def test_redis_failure_falls_back_to_one_local_sync():
    coordinator = _local_coordinator(5)
    coordinator.distributed_enabled = True
    running = 0
    peak = 0
    guard = asyncio.Lock()

    @asynccontextmanager
    async def broken_distributed_lease(*_args, **_kwargs):
        raise RedisError("redis unavailable")
        yield  # pragma: no cover

    coordinator._distributed_lease = broken_distributed_lease  # type: ignore[method-assign]

    async def run(environment_id: int) -> None:
        nonlocal running, peak
        async with coordinator.lease(environment_id, "test"):
            async with guard:
                running += 1
                peak = max(peak, running)
            await asyncio.sleep(0.01)
            async with guard:
                running -= 1

    await asyncio.gather(*(run(index + 1) for index in range(6)))
    assert peak == 1
