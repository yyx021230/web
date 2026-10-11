"""Explicitly-started publisher, independent from AI generation and old publish loops."""

import asyncio
import logging

from app.db.session import async_session
from app.services.hermes_publish_service import HermesPublishWorker
from app.services.scheduler_leader import SchedulerLeaderCoordinator, SchedulerLoopSpec


async def publish_loop() -> None:
    worker = HermesPublishWorker(async_session)
    while True:
        try:
            await worker.tick()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logging.getLogger(__name__).error("Publisher cycle failed: %s", type(exc).__name__)
        await asyncio.sleep(5)


async def main() -> None:
    coordinator = SchedulerLeaderCoordinator(async_session,
        [SchedulerLoopSpec("cloud-phone-publish", publish_loop)], lease_key="cloud-phone-publish-worker")
    await coordinator.run()


if __name__ == "__main__":
    asyncio.run(main())
