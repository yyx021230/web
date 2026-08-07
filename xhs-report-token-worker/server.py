#!/usr/bin/env python3
"""Minimal XHS report-token worker.

This service intentionally avoids the main web app/database. It serves the
single endpoint used by the Windows backend:

  GET /api/v1/xhs/internal/report-token?account_id=...

Nginx should mount it under /xhs-worker, so the public URL becomes:

  /xhs-worker/api/v1/xhs/internal/report-token
"""

from __future__ import annotations

import json
import os
import signal
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse


HOST = os.getenv("HOST", "127.0.0.1")
PORT = int(os.getenv("PORT", "8791"))
TOKENS_FILE = Path(os.getenv("XHS_REPORT_TOKENS_FILE", "./tokens.ndjson"))
WORKER_INTERNAL_TOKEN = os.getenv("XHS_REPORT_WORKER_INTERNAL_TOKEN", "").strip()

WORKER_PATH = "/api/v1/xhs/internal/report-token"
LEGACY_PATH = "/ztcar-api/carshow/market/xhs/token"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_tokens() -> dict[str, dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {}
    if not TOKENS_FILE.exists():
        return rows

    with TOKENS_FILE.open("r", encoding="utf-8") as f:
        for line_no, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise RuntimeError(f"{TOKENS_FILE}:{line_no} is not valid JSON: {exc}") from exc

            account_id = str(row.get("account_id") or "").strip()
            token = str(row.get("token") or "").strip()
            if not account_id or not token:
                continue
            rows[account_id] = row
    return rows


TOKEN_ROWS = load_tokens()


def api_response(data: Any = None, message: str = "ok", code: int = 0) -> dict[str, Any]:
    return {"code": code, "data": data, "message": message}


class Handler(BaseHTTPRequestHandler):
    server_version = "xhs-report-token-worker/1.0"

    def log_message(self, fmt: str, *args: Any) -> None:
        print(f"[{now_iso()}] {self.address_string()} {fmt % args}", flush=True)

    def write_json(self, status: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def require_worker_token(self) -> bool:
        if not WORKER_INTERNAL_TOKEN:
            return True
        provided = self.headers.get("X-XHS-Worker-Token", "").strip()
        if provided == WORKER_INTERNAL_TOKEN:
            return True
        self.write_json(401, api_response(message="invalid worker token", code=401))
        return False

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        query = parse_qs(parsed.query)

        if parsed.path in {"/health", "/xhs-worker/health"}:
            self.write_json(200, {
                "ok": True,
                "accounts": len(TOKEN_ROWS),
                "tokens_file": str(TOKENS_FILE),
                "time": now_iso(),
            })
            return

        normalized_path = parsed.path
        if normalized_path.startswith("/xhs-worker/"):
            normalized_path = normalized_path.removeprefix("/xhs-worker")

        if normalized_path == WORKER_PATH:
            if not self.require_worker_token():
                return
            account_id = str((query.get("account_id") or [""])[0]).strip()
            if not account_id:
                self.write_json(400, api_response(message="missing account_id", code=400))
                return
            row = TOKEN_ROWS.get(account_id)
            token = str((row or {}).get("token") or "").strip()
            if not token:
                self.write_json(404, api_response(message="token not found", code=404))
                return
            self.write_json(
                200,
                api_response(
                    data={"account_id": account_id, "token": token},
                    message="报表 token 获取成功",
                ),
            )
            return

        # Optional local compatibility path. Keep it disabled by default because
        # the historical endpoint has no worker-token header.
        if normalized_path == LEGACY_PATH and os.getenv("ENABLE_LEGACY_TOKEN_PATH") == "true":
            account_id = str((query.get("id") or [""])[0]).strip()
            row = TOKEN_ROWS.get(account_id)
            token = str((row or {}).get("token") or "").strip()
            if not account_id or not token:
                self.write_json(200, {"success": False, "message": "token not found", "result": None})
                return
            self.write_json(200, {"success": True, "message": "ok", "result": token})
            return

        self.write_json(404, {"error": "not found"})


def main() -> None:
    print(
        f"Starting XHS report-token worker on {HOST}:{PORT}; "
        f"accounts={len(TOKEN_ROWS)}; tokens_file={TOKENS_FILE}",
        flush=True,
    )
    httpd = ThreadingHTTPServer((HOST, PORT), Handler)

    def stop(signum: int, _frame: Any) -> None:
        print(f"Stopping worker by signal {signum}", flush=True)
        httpd.shutdown()

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    httpd.serve_forever()


if __name__ == "__main__":
    main()
