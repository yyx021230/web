"""Bounded, idempotent a1b2c3d4e5f6 -> c3d4e5f6a7b8 release migration.

Run from /app in the verified release image, with DATABASE_URL supplied through
an env file. Backup restore testing must precede the production invocation.
"""
import argparse
import asyncio
import json
import os

from alembic import command
from alembic.config import Config
from sqlalchemy import event, text
from sqlalchemy.engine import Engine
from sqlalchemy.ext.asyncio import create_async_engine


OLD_HEAD = "a1b2c3d4e5f6"
NEW_HEAD = "c3d4e5f6a7b8"
TABLES = ("users", "xhs_environments", "copywritings", "prompt_examples", "projects")


def bound_connection(connection, _record):
    cursor = connection.cursor()
    try:
        cursor.execute("SET lock_timeout = '5s'")
        cursor.execute("SET statement_timeout = '120s'")
    finally:
        cursor.close()


async def snapshot(database):
    engine = create_async_engine(os.environ["DATABASE_URL"])
    try:
        async with engine.connect() as connection:
            actual = await connection.scalar(text("SELECT current_database()"))
            if actual != database:
                raise RuntimeError("Database name does not match the explicit target")
            head = await connection.scalar(text("SELECT version_num FROM alembic_version"))
            counts = {name: await connection.scalar(text(f'SELECT count(*) FROM "{name}"')) for name in TABLES}
            return {"database": actual, "head": head, "rows": counts}
    finally:
        await engine.dispose()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", required=True, choices=("hermes_restore", "ai_creative"))
    args = parser.parse_args()
    event.listen(Engine, "connect", bound_connection)
    before = asyncio.run(snapshot(args.database))
    if before["head"] not in (OLD_HEAD, NEW_HEAD):
        raise RuntimeError("Unexpected source migration head")
    if before["head"] != NEW_HEAD:
        command.upgrade(Config("/app/alembic.ini"), NEW_HEAD)
    after = asyncio.run(snapshot(args.database))
    if after["head"] != NEW_HEAD:
        raise RuntimeError("Target migration head not reached")
    if args.database == "hermes_restore" and before["rows"] != after["rows"]:
        raise RuntimeError("Business rows changed in the isolated migration rehearsal")
    print(json.dumps({"migration": "ok", "before": before, "after": after}))


if __name__ == "__main__":
    main()
