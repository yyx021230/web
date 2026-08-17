"""Remove historical AI reference-image payloads from terminal tasks.

Run this during a maintenance window after deploying terminal-task compaction:

    python -m app.scripts.compact_ai_task_params --batch-size 100 --sleep-seconds 0.2

After the command reaches zero candidates, run ``VACUUM (FULL, ANALYZE) ai_tasks``
once to return the old TOAST file to the host filesystem.
"""

from __future__ import annotations

import argparse
import asyncio

from sqlalchemy import text

from app.db.session import async_session


TERMINAL_STATUSES = ("completed", "failed", "cancelled")


async def compact(*, batch_size: int, sleep_seconds: float, max_rows: int) -> int:
    total = 0
    last_id = 0
    while True:
        remaining = max_rows - total if max_rows > 0 else batch_size
        current_batch = min(batch_size, remaining)
        if current_batch <= 0:
            break
        async with async_session() as session:
            bind = session.get_bind()
            if bind is None or bind.dialect.name != "postgresql":
                raise RuntimeError("Historical compaction is only supported on PostgreSQL")
            rows = (
                await session.execute(
                    text(
                        """
                        SELECT id
                        FROM ai_tasks
                        WHERE id > :last_id
                          AND status IN ('completed', 'failed', 'cancelled')
                          AND (
                            params::jsonb ? 'image_data'
                            OR params::jsonb ? 'image_url'
                            OR params::jsonb ? 'images_data'
                            OR params::jsonb ? '_processing_started_at'
                          )
                        ORDER BY id
                        LIMIT :batch_size
                        """
                    ),
                    {"last_id": last_id, "batch_size": current_batch},
                )
            ).scalars().all()
            if not rows:
                break
            last_id = int(rows[-1])
            result = await session.execute(
                text(
                    """
                    UPDATE ai_tasks
                    SET params = (
                      params::jsonb
                      - 'image_data'
                      - 'image_url'
                      - 'images_data'
                      - '_processing_started_at'
                    )::json
                    WHERE id = ANY(:ids)
                    """
                ),
                {"ids": [int(row_id) for row_id in rows]},
            )
            await session.commit()
            changed = int(result.rowcount or 0)
            total += changed
            print(f"compacted={total} last_id={last_id}", flush=True)
        if sleep_seconds > 0:
            await asyncio.sleep(sleep_seconds)
    return total


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--batch-size", type=int, default=100)
    parser.add_argument("--sleep-seconds", type=float, default=0.2)
    parser.add_argument("--max-rows", type=int, default=0)
    args = parser.parse_args()
    changed = asyncio.run(
        compact(
            batch_size=max(1, min(args.batch_size, 1000)),
            sleep_seconds=max(0.0, args.sleep_seconds),
            max_rows=max(0, args.max_rows),
        )
    )
    print(f"done compacted={changed}")


if __name__ == "__main__":
    main()
