import asyncio

import pytest

from app.services.sms_device_coordinator import SmsDeviceCoordinator


@pytest.mark.asyncio
async def test_same_physical_device_login_flows_are_serialized():
    coordinator = SmsDeviceCoordinator(
        redis_url="redis://unused",
        distributed_enabled=False,
        acquire_timeout_seconds=5,
    )
    first_entered = asyncio.Event()
    release_first = asyncio.Event()
    second_entered = asyncio.Event()

    async def first_flow():
        async with coordinator.lease("device:one"):
            first_entered.set()
            await release_first.wait()

    async def second_flow():
        await first_entered.wait()
        async with coordinator.lease("device:one"):
            second_entered.set()

    first_task = asyncio.create_task(first_flow())
    second_task = asyncio.create_task(second_flow())
    await first_entered.wait()
    await asyncio.sleep(0)
    assert second_entered.is_set() is False

    release_first.set()
    await asyncio.gather(first_task, second_task)
    assert second_entered.is_set() is True


@pytest.mark.asyncio
async def test_different_physical_devices_can_login_concurrently():
    coordinator = SmsDeviceCoordinator(
        redis_url="redis://unused",
        distributed_enabled=False,
        acquire_timeout_seconds=5,
    )
    both_entered = asyncio.Event()
    entered: set[str] = set()

    async def flow(device_id: str):
        async with coordinator.lease(f"device:{device_id}"):
            entered.add(device_id)
            if len(entered) == 2:
                both_entered.set()
            await asyncio.wait_for(both_entered.wait(), timeout=1)

    await asyncio.gather(flow("one"), flow("two"))
    assert entered == {"one", "two"}
