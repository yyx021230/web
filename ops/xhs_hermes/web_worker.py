#!/usr/bin/env python3
"""External worker that turns Web Hermes queue rows into local production runs."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import signal
import socket
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any
from worker_runtime import apply_worker_limits, load_dotenv, runner_command
from ocr_backend import backend_name


ROOT = Path(__file__).resolve().parent
DEFAULT_CONFIG = ROOT / "config" / "daily_8x5.json"
DEFAULT_CASES = ROOT / "config" / "cases.json"
REPORT_FILE = ".web-report.json"
PRODUCTION_REVISION = "2026-09-08-image-layout-v3"
STOP_REQUESTED = False


def request_stop(*_: Any) -> None:
    global STOP_REQUESTED
    STOP_REQUESTED = True
    print('Worker draining: finish the current run; do not claim another.', flush=True)


def record_api_health() -> None:
    configured = os.environ.get('HERMES_CONTAINER_HEALTH_PATH')
    if not configured:
        return
    path = Path(configured)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix('.tmp')
        temporary.write_text(json.dumps({'last_api_success': time.time()}))
        os.replace(temporary, path)
    except OSError as exc:
        print(f'Worker health marker failed: {type(exc).__name__}', flush=True)


def request_json(base_url: str, path: str, token: str, body: dict[str, Any], *, timeout: int = 120) -> Any:
    request = urllib.request.Request(
        base_url.rstrip("/") + path,
        method="POST",
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "X-XHS-Worker-Token": token,
        },
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if isinstance(payload, dict) and payload.get("code") not in (None, 0):
        raise RuntimeError(str(payload.get("message") or payload))
    record_api_health()
    return payload.get("data") if isinstance(payload, dict) else payload


def write_report(run_output: Path, path: str, body: dict[str, Any]) -> Path:
    report_path = run_output / REPORT_FILE
    temporary = report_path.with_suffix(".tmp")
    temporary.write_text(
        json.dumps({"path": path, "body": body}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    os.replace(temporary, report_path)
    return report_path


def send_report(base_url: str, token: str, report_path: Path) -> None:
    report = json.loads(report_path.read_text(encoding="utf-8"))
    request_json(base_url, str(report["path"]), token, dict(report["body"]))
    report_path.unlink(missing_ok=True)


def flush_pending_reports(base_url: str, token: str, output_root: Path) -> None:
    """Acknowledge completed local work before claiming anything new."""
    for report_path in sorted(output_root.rglob(REPORT_FILE), key=lambda path: path.stat().st_mtime):
        send_report(base_url, token, report_path)


def normalized_model(value: str) -> str:
    return value.replace("零跑", "").replace(" ", "").casefold()


def resolve_case_id(account: dict[str, Any], cases: dict[str, Any]) -> str:
    configured = str(account.get("case_id") or "").strip()
    if configured:
        if configured not in cases:
            raise KeyError(f"unknown Hermes case_id: {configured}")
        return configured
    target = normalized_model(str(account.get("vehicle_model") or ""))
    exact = [
        case_id for case_id, case in cases.items()
        if normalized_model(str(case.get("vehicle_model") or "")) == target
    ]
    if len(exact) != 1:
        raise KeyError(f"cannot uniquely match vehicle model to Hermes case: {account.get('vehicle_model')}")
    return exact[0]


def build_run_config(run: dict[str, Any], path: Path) -> tuple[dict[str, Any], str]:
    base = apply_worker_limits(json.loads(DEFAULT_CONFIG.read_text(encoding="utf-8")))
    cases = json.loads(DEFAULT_CASES.read_text(encoding="utf-8"))
    parameters = run.get("parameters") or {}
    posts_per_account = int(parameters.get("posts_per_account") or 1)
    accounts = []
    for account in parameters.get("accounts") or []:
        post_count = int(account.get("post_count") or posts_per_account)
        vehicle_models = [
            str(value).strip()
            for value in account.get("vehicle_models") or []
            if str(value).strip()
        ]
        if vehicle_models:
            if account.get("case_id") and len(set(vehicle_models)) == 1:
                case_ids = [resolve_case_id(account, cases)] * post_count
            else:
                case_ids = [
                    resolve_case_id({"vehicle_model": vehicle_models[index % len(vehicle_models)]}, cases)
                    for index in range(post_count)
                ]
        else:
            case_id = resolve_case_id(account, cases)
            case_ids = [case_id] * post_count
        accounts.append({
            "id": int(account["environment_id"]),
            "name": str(account.get("account_name") or f"账号{account['environment_id']}"),
            "post_count": post_count,
            "case_ids": case_ids,
        })
    if not accounts:
        raise RuntimeError("run has no accounts")
    base.update({
        "production_contract": "flexible",
        "accounts": accounts,
        "posts_per_account": max(int(account["post_count"]) for account in accounts),
        "operator_instruction": str(parameters.get("instruction") or "").strip(),
        "requested_copy_type": parameters.get('copy_type'),
        "requested_image_type": parameters.get('image_type'),
        "web_policy_fingerprint": parameters.get('policy_fingerprint'),
    })
    path.write_text(json.dumps(base, ensure_ascii=False, indent=2), encoding="utf-8")
    batch_date = str(run.get("scheduled_for") or run.get("created_at") or "")[:10]
    if len(batch_date) != 10:
        batch_date = time.strftime("%Y-%m-%d")
    return base, batch_date


def find_delivery(output_root: Path) -> Path | None:
    deliveries = sorted(output_root.rglob("delivery.json"), key=lambda path: path.stat().st_mtime, reverse=True)
    if deliveries:
        return deliveries[0]
    candidates = sorted(output_root.rglob("delivery_candidate.json"), key=lambda path: path.stat().st_mtime, reverse=True)
    return candidates[0] if candidates else None


def send_progress(base_url: str, token: str, run_id: int, worker_id: str,
                  run_output: Path, last_digest: str | None) -> str | None:
    snapshots = sorted(run_output.rglob('progress.json'), key=lambda path: path.stat().st_mtime, reverse=True)
    if not snapshots:
        return last_digest
    content = snapshots[0].read_bytes()
    digest = hashlib.sha256(content).hexdigest()
    if digest == last_digest:
        return last_digest
    delivery = json.loads(content)
    if not delivery.get('posts'):
        return last_digest
    request_json(base_url, f'/api/v1/hermes-workflows/worker/runs/{run_id}/progress', token,
                 {'worker_id': worker_id, 'delivery': delivery}, timeout=5)
    # Advance only after acknowledgement. The durable snapshot survives a
    # disconnect and repeats safely without overwriting user edits/reviews.
    return digest


def capabilities() -> dict[str, Any]:
    cases = json.loads(DEFAULT_CASES.read_text(encoding="utf-8")) if DEFAULT_CASES.exists() else {}
    return {
        "platform": platform.platform(),
        "production_revision": PRODUCTION_REVISION,
        "python": platform.python_version(),
        "case_ids": sorted(cases),
        "models": sorted({str(row.get("vehicle_model") or "") for row in cases.values()}),
        "image_ocr": backend_name(),
    }


def retryable_image_keys(delivery: dict[str, Any]) -> list[str]:
    """Return posts whose copy is complete but whose final image is missing.

    Missing final images do not imply failed plans. Resume the checkpoint;
    replace templates only for confirmed, exhausted image-generation failures.
    """
    keys: list[str] = []
    for post in delivery.get("posts") or []:
        if not isinstance(post, dict):
            continue
        key = str(post.get("key") or "").strip()
        has_copy = bool(str(post.get("title") or "").strip() and str(post.get("content") or "").strip())
        has_image = bool(str(post.get("image_url") or "").strip())
        if key and has_copy and post.get("copy_ok") is not False and not has_image and not post.get("hard_pass"):
            keys.append(key)
    return keys


def image_recovery_arguments(delivery: dict[str, Any]) -> list[str]:
    retry_keys = set(retryable_image_keys(delivery))
    failed_images = [
        str(post["key"]) for post in delivery.get("posts") or []
        if isinstance(post, dict) and post.get("key") in retry_keys
        and post.get("image_plan_ok") is True and post.get("image_status") == "failed"
    ]
    # Ready plans, submitted tasks and completed siblings retain their state.
    # Plan failures already carry their own bounded same/new-template strategy.
    return ["--retry-image-keys", *failed_images] if failed_images else []


def run_once(base_url: str, token: str, worker_id: str, output_root: Path) -> bool:
    run = request_json(
        base_url,
        "/api/v1/hermes-workflows/worker/claim",
        token,
        {"worker_id": worker_id, "capabilities": capabilities()},
    )
    if not run:
        return False
    run_id = int(run["id"])
    run_output = output_root / f"run-{run_id}"
    run_output.mkdir(parents=True, exist_ok=True)
    try:
        with tempfile.TemporaryDirectory(prefix=f"hermes-web-{run_id}-") as directory:
            config_path = Path(directory) / "config.json"
            _, batch_date = build_run_config(run, config_path)
            log_path = run_output / "worker.log"
            run_started = time.monotonic()
            last_progress_digest: str | None = None
            with log_path.open("a", encoding="utf-8") as log_file:
                base_command = [
                    *runner_command(),
                    "--config", str(config_path),
                    "--batch-date", batch_date,
                    "--output-root", str(run_output),
                ]

                def execute(extra_args: list[str]) -> int:
                    nonlocal last_progress_digest
                    process = subprocess.Popen(
                        [*base_command, *extra_args],
                        cwd=str(ROOT.parent.parent),
                        text=True,
                        stdout=log_file,
                        stderr=subprocess.STDOUT,
                    )
                    next_heartbeat = 0.0
                    while True:
                        try:
                            last_progress_digest = send_progress(
                                base_url, token, run_id, worker_id, run_output, last_progress_digest)
                        except (OSError, ValueError, RuntimeError) as exc:
                            print(f'worker progress pending retry: {type(exc).__name__}: {exc}', flush=True)
                        if process.poll() is not None:
                            break
                        if time.monotonic() - run_started > 4 * 60 * 60:
                            process.terminate()
                            try:
                                process.wait(timeout=20)
                            except subprocess.TimeoutExpired:
                                process.kill()
                            raise TimeoutError("Hermes run exceeded the four-hour safety limit")
                        try:
                            if time.monotonic() < next_heartbeat:
                                process.wait(timeout=2)
                                continue
                            next_heartbeat = time.monotonic() + 25
                            request_json(
                                base_url,
                                "/api/v1/hermes-workflows/worker/heartbeat",
                                token,
                                {
                                    "worker_id": worker_id,
                                    "status": "running",
                                    "current_run_id": run_id,
                                    "capabilities": capabilities(),
                                },
                            )
                        except subprocess.TimeoutExpired:
                            continue
                        except (urllib.error.URLError, TimeoutError, RuntimeError) as exc:
                            print(f"worker heartbeat error: {type(exc).__name__}: {exc}", flush=True)
                        try:
                            process.wait(timeout=2)
                        except subprocess.TimeoutExpired:
                            pass
                    return int(process.returncode or 0)

                return_code = execute([])
                recovery_rounds = max(0, min(3, int(os.environ.get("HERMES_IMAGE_RECOVERY_ROUNDS", "2"))))
                for recovery_round in range(1, recovery_rounds + 1):
                    if return_code == 0:
                        break
                    candidate_path = find_delivery(run_output)
                    if candidate_path is None:
                        break
                    candidate = json.loads(candidate_path.read_text(encoding="utf-8"))
                    retry_keys = retryable_image_keys(candidate)
                    if not retry_keys:
                        break
                    recovery_args = image_recovery_arguments(candidate)
                    log_file.write(json.dumps({
                        "stage": "worker_image_recovery",
                        "round": recovery_round,
                        "keys": retry_keys,
                        "strategy": "resume_failed_stages",
                        "new_template_keys": recovery_args[1:],
                    }, ensure_ascii=False) + "\n")
                    log_file.flush()
                    return_code = execute(recovery_args)
        delivery_path = find_delivery(run_output)
        if delivery_path is None:
            raise RuntimeError(f"Hermes exited {return_code} without a delivery manifest")
        delivery = json.loads(delivery_path.read_text(encoding="utf-8"))
        if return_code != 0:
            delivery.setdefault("error", f"Hermes exited with code {return_code}")
        report = write_report(
            run_output,
            f"/api/v1/hermes-workflows/worker/runs/{run_id}/complete",
            {"worker_id": worker_id, "delivery": delivery},
        )
        send_report(base_url, token, report)
    except Exception as exc:
        # If generation already finished and only the Web acknowledgement
        # failed, keep the success report intact for the next polling cycle.
        # Replacing it with a failure would discard a valid local delivery.
        if (run_output / REPORT_FILE).exists():
            raise
        report = write_report(
            run_output,
            f"/api/v1/hermes-workflows/worker/runs/{run_id}/fail",
            {"worker_id": worker_id, "error": f"{type(exc).__name__}: {exc}"},
        )
        send_report(base_url, token, report)
    return True


def main() -> int:
    load_dotenv(ROOT / ".env")
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default=os.environ.get("HERMES_WEB_BASE_URL", "http://127.0.0.1:8000"))
    parser.add_argument("--token", default=os.environ.get("XHS_WORKER_INTERNAL_TOKEN", ""))
    parser.add_argument("--worker-id", default=os.environ.get("HERMES_WORKER_ID", f"{socket.gethostname()}-hermes"))
    parser.add_argument("--poll-seconds", type=int, default=10)
    parser.add_argument("--output-root", default=str(ROOT.parent.parent / "outputs" / "xhs_hermes_web"))
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    if not args.token:
        raise SystemExit("XHS_WORKER_INTERNAL_TOKEN is required")
    output_root = Path(args.output_root).resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    signal.signal(signal.SIGTERM, request_stop)
    signal.signal(signal.SIGINT, request_stop)
    while not STOP_REQUESTED:
        try:
            flush_pending_reports(args.base_url, args.token, output_root)
            worked = run_once(args.base_url, args.token, args.worker_id, output_root)
            if args.once:
                return 0
            if not worked:
                time.sleep(max(3, args.poll_seconds))
        except (urllib.error.URLError, TimeoutError, RuntimeError) as exc:
            if args.once:
                raise
            print(f"worker polling error: {type(exc).__name__}: {exc}", flush=True)
            time.sleep(max(5, args.poll_seconds))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
