"""Explicit administrator operation; reads live phone mapping before DB registration."""
from __future__ import annotations

import argparse
import asyncio
import json

from sqlalchemy import select
from app.adapters.phone_cloud_publish import PhoneCloudPublisher
from app.config import settings
from app.db.session import async_session
from app.models.user import User
from app.services.phone_cloud_account_registry import register_verified_account


async def register(args: argparse.Namespace) -> None:
    allowed = {value.strip() for value in settings.phone_cloud_publish_verified_xhs_ids.split(",") if value.strip()}
    if args.xhs_id not in allowed:
        raise ValueError("Account is not in the verified publication allowlist")
    publisher = PhoneCloudPublisher()
    target = publisher.target(await publisher.devices(), args.xhs_id)
    async with async_session() as db:
        operator = await db.scalar(select(User).where(User.username == args.operator))
        owner = await db.scalar(select(User).where(User.username == args.owner))
        if operator is None or owner is None:
            raise ValueError("Unknown administrator or owner")
        env = await register_verified_account(db, operator=operator, owner=owner,
                                              xhs_id=args.xhs_id, name=args.name)
        result = {"environment_id": env.id, "name": env.account_name,
                  "owner_id": owner.id, "source": "phone-cloud" if env.is_phone_cloud else "yundeng",
                  "device_id": target["device_id"], "app_slot": target["app_slot"],
                  "created_publish_tasks": 0}
        await db.commit()
        print(json.dumps(result, ensure_ascii=True))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--operator", required=True)
    parser.add_argument("--owner", required=True)
    parser.add_argument("--xhs-id", required=True)
    parser.add_argument("--name", required=True)
    asyncio.run(register(parser.parse_args()))
