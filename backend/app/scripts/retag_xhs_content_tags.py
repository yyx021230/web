from __future__ import annotations

import argparse
import asyncio
import csv
import sqlite3
import time
from collections import Counter
from pathlib import Path
from types import SimpleNamespace

import httpx

from app.api.v1.xhs import _infer_xhs_content_tag_by_rules, _tag_xhs_account_note_with_model


DEFAULT_DB_PATH = Path(__file__).resolve().parents[2] / "dev.db"
DEFAULT_OUTPUT_PATH = Path(__file__).resolve().parents[2] / "content_tag_retag_all_results.csv"
DEFAULT_FAILED_PATH = Path(__file__).resolve().parents[2] / "content_tag_retag_all_failed.csv"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Retag XHS account notes with the full content tag strategy.",
    )
    parser.add_argument("--db", default=str(DEFAULT_DB_PATH), help="SQLite dev.db path")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT_PATH), help="CSV result path")
    parser.add_argument("--failed-output", default=str(DEFAULT_FAILED_PATH), help="CSV failed result path")
    parser.add_argument("--limit", type=int, default=0, help="Limit rows for testing; 0 means all eligible rows")
    parser.add_argument("--concurrency", type=int, default=10, help="Model request concurrency")
    parser.add_argument("--dry-run", action="store_true", help="Do not write tags back to the database")
    parser.add_argument("--all", action="store_true", help="Retag all eligible rows; default only tags rows missing tags")
    parser.add_argument("--environment-id", type=int, default=0, help="Optional xhs environment_id filter")
    parser.add_argument("--status", default="", help="Optional note status filter, e.g. active")
    return parser.parse_args()


def fetch_rows(db_path: Path, limit: int, environment_id: int, status: str, retag_all: bool) -> list[sqlite3.Row]:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        conditions = [
            "title <> ''",
            "detail_synced_at is not null",
            "content_status = 'from_detail'",
            "content is not null",
            "content <> ''",
        ]
        params: list[object] = []
        if environment_id:
            conditions.append("environment_id = ?")
            params.append(environment_id)
        if status:
            conditions.append("status = ?")
            params.append(status)
        if not retag_all:
            conditions.append(
                "("
                "primary_content_tag is null or primary_content_tag = '' or "
                "secondary_content_tag is null or secondary_content_tag = ''"
                ")"
            )
        sql = f"""
            select id, primary_content_tag, secondary_content_tag, account_name, title,
                   coalesce(content, '') as content, coalesce(published_at, '') as published_at,
                   post_url, liked_count, collected_count, comment_count
            from xhs_account_notes
            where {' and '.join(conditions)}
            order by id asc
        """
        if limit > 0:
            sql += " limit ?"
            params.append(limit)
        return list(conn.execute(sql, params))
    finally:
        conn.close()


async def tag_one(client: httpx.AsyncClient, row: sqlite3.Row, semaphore: asyncio.Semaphore) -> dict:
    note = SimpleNamespace(
        id=int(row["id"]),
        title=row["title"] or "",
        content=row["content"] or "",
    )
    source = "title_rule" if _infer_xhs_content_tag_by_rules(note) else "model"
    last_error = ""
    for attempt in range(1, 4):
        async with semaphore:
            try:
                primary, secondary = await _tag_xhs_account_note_with_model(client, note)
                old_primary = row["primary_content_tag"] or ""
                old_secondary = row["secondary_content_tag"] or ""
                return {
                    "id": int(row["id"]),
                    "source": source,
                    "old_primary": old_primary,
                    "old_secondary": old_secondary,
                    "new_primary": primary,
                    "new_secondary": secondary,
                    "changed": "yes" if (primary != old_primary or secondary != old_secondary) else "no",
                    "error": "",
                    "account_name": row["account_name"] or "",
                    "title": row["title"] or "",
                    "published_at": row["published_at"] or "",
                    "post_url": row["post_url"] or "",
                }
            except Exception as exc:
                last_error = str(exc)[:500]
        if any(token in last_error for token in ("503", "429", "Server disconnected", "timeout", "Timeout")):
            await asyncio.sleep(min(2 * attempt, 6))
        else:
            break

    return {
        "id": int(row["id"]),
        "source": source,
        "old_primary": row["primary_content_tag"] or "",
        "old_secondary": row["secondary_content_tag"] or "",
        "new_primary": "",
        "new_secondary": "",
        "changed": "no",
        "error": last_error,
        "account_name": row["account_name"] or "",
        "title": row["title"] or "",
        "published_at": row["published_at"] or "",
        "post_url": row["post_url"] or "",
    }


def write_csv(path: Path, rows: list[dict]) -> None:
    if not rows:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def write_back(db_path: Path, rows: list[dict]) -> None:
    ok_rows = [row for row in rows if not row["error"]]
    conn = sqlite3.connect(db_path, timeout=60)
    try:
        conn.executemany(
            """
            update xhs_account_notes
            set primary_content_tag = ?,
                secondary_content_tag = ?,
                updated_at = CURRENT_TIMESTAMP
            where id = ?
            """,
            [(row["new_primary"], row["new_secondary"], row["id"]) for row in ok_rows],
        )
        conn.commit()
    finally:
        conn.close()


async def run() -> None:
    args = parse_args()
    db_path = Path(args.db).expanduser().resolve()
    output_path = Path(args.output).expanduser().resolve()
    failed_path = Path(args.failed_output).expanduser().resolve()

    rows = fetch_rows(db_path, args.limit, args.environment_id, args.status.strip(), args.all)
    print(f"eligible={len(rows)} dry_run={args.dry_run} concurrency={args.concurrency}", flush=True)
    if not rows:
        return

    semaphore = asyncio.Semaphore(max(1, args.concurrency))
    results: list[dict] = []
    started_at = time.time()

    async with httpx.AsyncClient(timeout=httpx.Timeout(150.0, connect=20.0), trust_env=False) as client:
        tasks = [asyncio.create_task(tag_one(client, row, semaphore)) for row in rows]
        for index, task in enumerate(asyncio.as_completed(tasks), 1):
            result = await task
            results.append(result)
            if index % 250 == 0 or index == len(tasks):
                ok_count = sum(1 for row in results if not row["error"])
                error_count = len(results) - ok_count
                source_counts = Counter(row["source"] for row in results if not row["error"])
                print(
                    "progress="
                    f"{index}/{len(tasks)} ok={ok_count} err={error_count} "
                    f"title_rule={source_counts.get('title_rule', 0)} "
                    f"model={source_counts.get('model', 0)} "
                    f"elapsed={time.time() - started_at:.1f}s",
                    flush=True,
                )

    results.sort(key=lambda row: row["id"])
    ok_results = [row for row in results if not row["error"]]
    failed_results = [row for row in results if row["error"]]

    write_csv(output_path, results)
    if failed_results:
        write_csv(failed_path, failed_results)

    if not args.dry_run:
        write_back(db_path, ok_results)

    print(f"final_total={len(results)}", flush=True)
    print(f"final_success={len(ok_results)}", flush=True)
    print(f"final_failed={len(failed_results)}", flush=True)
    print(f"source={Counter(row['source'] for row in ok_results)}", flush=True)
    print(f"changed={Counter(row['changed'] for row in ok_results)}", flush=True)
    print(f"new_primary={Counter(row['new_primary'] for row in ok_results).most_common()}", flush=True)
    print(f"results={output_path}", flush=True)
    if failed_results:
        print(f"failed={failed_path}", flush=True)
        print(f"failed_errors={Counter(row['error'] for row in failed_results).most_common(10)}", flush=True)
    if args.dry_run:
        print("dry_run=true; database was not modified", flush=True)
    else:
        print(f"database_updated={len(ok_results)}", flush=True)


if __name__ == "__main__":
    asyncio.run(run())
