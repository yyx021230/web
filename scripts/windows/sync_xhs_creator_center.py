"""Run a one-shot creator-center sync through a dedicated YunDeng runner.

This file is intentionally executable through ``python -`` so Windows can pipe
it into the existing backend container without rebuilding the production image.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import logging
import re
import sys
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import func, select

from app.db.session import async_session
from app.models.xhs_environment import XHSEnvironment
from app.services.xhs_service import XHS_MCP_EXTERNAL_API, XHSService
from app.services.yundeng_sync_coordinator import yundeng_sync_coordinator


logger = logging.getLogger("xhs_creator_center_sync")


@dataclass(frozen=True)
class EnvironmentInfo:
    id: int
    shop_id: str
    account_name: str
    xhs_account_id: str
    status: str


def _environment_info(environment: XHSEnvironment) -> EnvironmentInfo:
    return EnvironmentInfo(
        id=int(environment.id),
        shop_id=str(environment.shop_id or ""),
        account_name=str(environment.account_name or ""),
        xhs_account_id=str(environment.xhs_account_id or ""),
        status=str(environment.status or ""),
    )


def _normalize(value: Any) -> str:
    return str(value or "").strip()


def save_export_workbook(
    content: bytes,
    *,
    identity: dict[str, str],
    export_directory: str,
) -> Path:
    output_directory = Path(export_directory)
    output_directory.mkdir(parents=True, exist_ok=True)
    identity_name = _normalize(identity.get("account_name")) or "xhs-account"
    identity_id = _normalize(identity.get("xhs_account_id")) or "unknown-id"
    safe_name = re.sub(r"[^\w.-]+", "_", identity_name, flags=re.UNICODE).strip("._")
    safe_id = re.sub(r"[^A-Za-z0-9_-]+", "_", identity_id).strip("_")
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    output_path = output_directory / f"{timestamp}_{safe_name}_{safe_id}.xlsx"
    output_path.write_bytes(content)
    return output_path


def validate_target_identity(
    target: XHSEnvironment,
    identity: dict[str, str],
) -> None:
    actual_id = _normalize(identity.get("xhs_account_id"))
    actual_name = _normalize(identity.get("account_name"))
    target_id = _normalize(target.xhs_account_id)
    target_name = _normalize(target.account_name)

    if actual_id and target_id:
        if actual_id != target_id:
            raise RuntimeError(
                "Refusing to import creator data into the wrong account: "
                f"logged-in xhs_account_id={actual_id}, "
                f"target xhs_account_id={target_id} ({target_name})."
            )
        return

    if actual_name and target_name and actual_name == target_name:
        return

    raise RuntimeError(
        "The logged-in account cannot be safely matched to the selected target. "
        f"logged-in id/name={actual_id or '-'} / {actual_name or '-'}, "
        f"target id/name={target_id or '-'} / {target_name or '-'}.",
    )


async def resolve_runner(db: Any, runner_name: str) -> XHSEnvironment:
    normalized_name = _normalize(runner_name)
    rows = list(
        (
            await db.execute(
                select(XHSEnvironment).where(
                    func.trim(XHSEnvironment.account_name) == normalized_name
                )
            )
        )
        .scalars()
        .all()
    )
    if not rows:
        raise RuntimeError(f"YunDeng runner not found: {normalized_name}")
    if len(rows) != 1:
        raise RuntimeError(
            f"YunDeng runner name is not unique: {normalized_name} ({len(rows)} rows)"
        )
    runner = rows[0]
    if _normalize(runner.status) != "active":
        raise RuntimeError(f"YunDeng runner is not active: {normalized_name}")
    if not bool(runner.is_sync_runner):
        raise RuntimeError(
            f"Environment is not marked as a sync runner: {normalized_name}"
        )
    return runner


async def _load_unique_target_by_name(
    db: Any,
    account_name: str,
) -> XHSEnvironment:
    rows = list(
        (
            await db.execute(
                select(XHSEnvironment).where(
                    XHSEnvironment.is_sync_runner.is_not(True),
                    func.trim(XHSEnvironment.account_name) == _normalize(account_name),
                )
            )
        )
        .scalars()
        .all()
    )
    if not rows:
        raise RuntimeError(f"Target business account not found: {account_name}")
    if len(rows) != 1:
        raise RuntimeError(
            f"Target business account name is not unique: {account_name} ({len(rows)} rows)"
        )
    return rows[0]


async def resolve_target(
    db: Any,
    identity: dict[str, str],
    *,
    target_environment_id: int | None = None,
    target_account_name: str | None = None,
) -> XHSEnvironment:
    if target_environment_id:
        target = (
            await db.execute(
                select(XHSEnvironment).where(
                    XHSEnvironment.id == int(target_environment_id)
                )
            )
        ).scalar_one_or_none()
        if target is None:
            raise RuntimeError(
                f"Target business environment not found: {target_environment_id}"
            )
    elif _normalize(target_account_name):
        target = await _load_unique_target_by_name(db, _normalize(target_account_name))
    else:
        actual_id = _normalize(identity.get("xhs_account_id"))
        if not actual_id:
            raise RuntimeError(
                "The logged-in account did not return xhs_account_id. "
                "Specify --target-environment-id or --target-account-name."
            )
        rows = list(
            (
                await db.execute(
                    select(XHSEnvironment).where(
                        XHSEnvironment.is_sync_runner.is_not(True),
                        XHSEnvironment.xhs_account_id == actual_id,
                    )
                )
            )
            .scalars()
            .all()
        )
        if not rows:
            raise RuntimeError(
                "No business account is mapped to the logged-in xhs_account_id "
                f"{actual_id}. Add the mapping first or specify an explicit target."
            )
        if len(rows) != 1:
            matches = ", ".join(
                f"{row.id}:{_normalize(row.account_name)}" for row in rows
            )
            raise RuntimeError(
                "The logged-in xhs_account_id maps to multiple business accounts. "
                f"Use --target-environment-id. Matches: {matches}"
            )
        target = rows[0]

    if bool(target.is_sync_runner):
        raise RuntimeError("Creator-center data cannot be imported into a sync runner.")
    validate_target_identity(target, identity)
    return target


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="One-shot XHS creator-center sync through YunDeng runner Test2"
    )
    parser.add_argument(
        "--runner-name",
        default="\u6d4b\u8bd52",
        help="Exact YunDeng runner environment name (default: Test2 in Chinese)",
    )
    parser.add_argument(
        "--target-environment-id",
        type=int,
        default=None,
        help="Optional explicit business environment ID",
    )
    parser.add_argument(
        "--target-account-name",
        default=None,
        help="Optional exact business account name",
    )
    parser.add_argument(
        "--identity-only",
        action="store_true",
        help="Verify runner login and account mapping without exporting or writing data",
    )
    parser.add_argument(
        "--export-only",
        action="store_true",
        help="Download and validate the creator workbook without writing database rows",
    )
    parser.add_argument(
        "--export-directory",
        default="/app/uploads/creator-center-exports",
        help="Persistent container directory for --export-only workbooks",
    )
    parser.add_argument(
        "--keep-browser-open",
        action="store_true",
        help="Do not stop the YunDeng browser after the run",
    )
    return parser.parse_args(argv)


async def run(args: argparse.Namespace) -> dict[str, Any]:
    if XHS_MCP_EXTERNAL_API:
        raise RuntimeError(
            "XHS_MCP_API_BASE_URL is configured. This script refuses external MCP mode "
            "because it cannot prove that the service is attached to the Test2 browser."
        )

    mcp_pid: int | None = None
    mcp_port: int | None = None
    runner: XHSEnvironment | None = None
    browser_acquired = False

    async with async_session() as db:
        service = XHSService(db)
        runner = await resolve_runner(db, args.runner_name)
        runner_info = _environment_info(runner)
        logger.info(
            "Resolved runner id=%s name=%s shop_id=%s",
            runner_info.id,
            runner_info.account_name,
            runner_info.shop_id,
        )

        try:
            async with yundeng_sync_coordinator.lease(
                int(runner.id), "standalone_creator_center"
            ) as lease:
                logger.info(
                    "Acquired YunDeng lease distributed=%s wait_seconds=%.3f",
                    lease.distributed,
                    lease.queue_wait_seconds,
                )
                active_runner, ws_url = (
                    await service._acquire_ready_sync_browser_ws_with_fallback(
                        int(runner.id), allow_fallback=False
                    )
                )
                if active_runner is None or not ws_url:
                    raise RuntimeError(
                        f"Unable to start or attach YunDeng runner: {runner_info.account_name}"
                    )
                if int(active_runner.id) != int(runner.id):
                    raise RuntimeError(
                        "Runner fallback is not allowed for this script: "
                        f"expected={runner.id}, actual={active_runner.id}"
                    )
                browser_acquired = True

                mcp_port = await service._allocate_free_port()
                mcp_api = f"http://localhost:{mcp_port}"
                mcp_pid = await service._start_mcp(ws_url, mcp_port)
                if not mcp_pid:
                    raise RuntimeError("Failed to start the temporary XHS MCP process.")
                await service._wait_mcp_ready(mcp_api, timeout=30)

                login_status = await service._get_mcp_login_status(mcp_api, probe=True)
                if not bool(login_status.get("is_logged_in")):
                    raise RuntimeError(
                        f"{runner_info.account_name} is not logged in. "
                        "Log in manually in YunDeng before running this script."
                    )

                identity = await service._get_mcp_current_profile_identity(mcp_api)
                if not _normalize(identity.get("xhs_account_id")) and not _normalize(
                    identity.get("account_name")
                ):
                    raise RuntimeError(
                        "The logged-in XHS identity is empty; no data was exported."
                    )

                if args.export_only:
                    content = await service._download_creator_stats_excel(mcp_api)
                    rows = service._parse_creator_stats_excel(content)
                    if not rows:
                        raise RuntimeError(
                            "The creator-center workbook was downloaded but contained no "
                            "recognizable note rows. Nothing was written to the database."
                        )
                    output_path = save_export_workbook(
                        content,
                        identity=identity,
                        export_directory=args.export_directory,
                    )
                    return {
                        "mode": "export-only",
                        "success": True,
                        "database_changed": False,
                        "runner": asdict(runner_info),
                        "logged_in_identity": identity,
                        "target": None,
                        "exported_rows": len(rows),
                        "file_size_bytes": len(content),
                        "sha256": hashlib.sha256(content).hexdigest(),
                        "saved_path": str(output_path),
                    }

                try:
                    target = await resolve_target(
                        db,
                        identity,
                        target_environment_id=args.target_environment_id,
                        target_account_name=args.target_account_name,
                    )
                except RuntimeError as exc:
                    if args.identity_only:
                        return {
                            "mode": "identity-only",
                            "success": True,
                            "database_changed": False,
                            "mapping_verified": False,
                            "mapping_error": str(exc),
                            "runner": asdict(runner_info),
                            "logged_in_identity": identity,
                            "target": None,
                        }
                    raise
                target_info = _environment_info(target)
                logger.info(
                    "Verified logged-in identity xhs_account_id=%s nickname=%s target=%s:%s",
                    _normalize(identity.get("xhs_account_id")) or "-",
                    _normalize(identity.get("account_name")) or "-",
                    target_info.id,
                    target_info.account_name,
                )

                base_result: dict[str, Any] = {
                    "mode": "identity-only" if args.identity_only else "sync",
                    "runner": asdict(runner_info),
                    "logged_in_identity": identity,
                    "target": asdict(target_info),
                }
                if args.identity_only:
                    return {
                        **base_result,
                        "success": True,
                        "database_changed": False,
                        "mapping_verified": True,
                    }

                content = await service._download_creator_stats_excel(mcp_api)
                rows = service._parse_creator_stats_excel(content)
                if not rows:
                    raise RuntimeError(
                        "The creator-center export contained no recognizable note rows; "
                        "the database was not changed."
                    )
                import_result = await service._import_creator_note_stats_rows(target, rows)
                await db.commit()
                return {
                    **base_result,
                    "success": True,
                    "database_changed": True,
                    "exported_rows": len(rows),
                    **import_result,
                }
        except Exception:
            await db.rollback()
            raise
        finally:
            if mcp_pid is not None:
                await service._stop_mcp(mcp_pid)
            elif mcp_port is not None:
                service._release_reserved_mcp_port(mcp_port)
            if browser_acquired and not args.keep_browser_open:
                await service._stop_browser(runner_info.shop_id)


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        stream=sys.stdout,
    )
    args = parse_args(argv)
    if args.identity_only and args.export_only:
        raise SystemExit("Use only one of --identity-only and --export-only.")
    if args.target_environment_id and _normalize(args.target_account_name):
        raise SystemExit(
            "Use only one of --target-environment-id and --target-account-name."
        )
    try:
        result = asyncio.run(run(args))
    except Exception as exc:
        logger.exception("Creator-center sync failed")
        print(
            json.dumps(
                {"success": False, "error": str(exc)},
                ensure_ascii=False,
            )
        )
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
