"""Sync public profileStat rows into xhs_profile_stat_daily.

Example:
  XHS_PROFILE_STAT_APP_ID=... XHS_PROFILE_STAT_SECRET=... \
  python -m app.scripts.sync_xhs_profile_stat \
    --start-date 2026-04-01 --end-date 2026-06-23 --delay-seconds 65
"""

from __future__ import annotations

import argparse
import asyncio
from datetime import datetime

from app.db.session import async_session
from app.services.xhs_profile_stat_service import XHSProfileStatService


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Sync XHS profileStat daily rows")
    parser.add_argument("--start-date", required=True, help="YYYY-MM-DD")
    parser.add_argument("--end-date", required=True, help="YYYY-MM-DD")
    parser.add_argument("--delay-seconds", type=float, default=65.0, help="Delay between public API requests")
    parser.add_argument("--limit-days", type=int, default=None, help="Only sync the first N missing days")
    parser.add_argument("--max-retries", type=int, default=2, help="Retries per day after a failed public API request")
    parser.add_argument("--no-skip-existing", action="store_true", help="Fetch even if local rows already exist for the day")
    return parser.parse_args()


async def main() -> None:
    args = parse_args()
    start = datetime.strptime(args.start_date, "%Y-%m-%d").date()
    end = datetime.strptime(args.end_date, "%Y-%m-%d").date()
    async with async_session() as db:
        service = XHSProfileStatService(db)
        result = await service.backfill(
            start_date=start,
            end_date=end,
            delay_seconds=args.delay_seconds,
            skip_existing=not args.no_skip_existing,
            limit_days=args.limit_days,
            max_retries=args.max_retries,
        )
    print(result)


if __name__ == "__main__":
    asyncio.run(main())
