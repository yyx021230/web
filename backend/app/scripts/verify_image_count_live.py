"""Paid four-image acceptance through the real user API in an isolated sandbox.

Run with a private provider snapshot, never with the business database. Does not
mock the provider, Redis, storage, watermark service or user-facing endpoints.
"""
from __future__ import annotations

import argparse
import asyncio
import base64
import hashlib
import io
import json
import logging
import os
from pathlib import Path
import re
import secrets
import time


def configure(args):
    root = Path(args.directory).resolve()
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    snapshot = json.loads((root / "provider-snapshot.private.json").read_text())
    for key, value in snapshot["env"].items():
        os.environ[key] = str(value).lower() if isinstance(value, bool) else str(value)
    namespace = "live-image-count:" + root.name
    env = {
        "APP_ENV": "test", "DEPLOYMENT_ENVIRONMENT": "test",
        "DATABASE_URL": f"sqlite+aiosqlite:///{root / 'acceptance.sqlite'}",
        "REDIS_URL": "redis://127.0.0.1:6379/0",
        "JWT_SECRET_KEY": secrets.token_urlsafe(48), "DEBUG": "false",
        "STORAGE_TYPE": "local", "STORAGE_PATH": str(root / "uploads"),
        "UPLOADS_PUBLIC_BASE_URL": "", "HERMES_REFERENCE_SNAPSHOT_PATH": "",
        "AI_IMAGE_SHADOW_ENABLED": "false", "AI_IMAGE_RECONCILIATION_ENABLED": "false",
        "AI_TASK_INTERACTIVE_CONCURRENCY": "2", "AI_TASK_BATCH_CONCURRENCY": "1",
        "AI_TASK_WORKER_POLL_TIMEOUT_SECONDS": "1", "AI_TASK_WORKER_MIN_INTERVAL_SECONDS": "1",
        "AI_POSTPROCESS_WORKER_CONCURRENCY": "2", "REMOVE_AI_WATERMARKS_MAX_CONCURRENT": "2",
        "GPT_IMAGE2_API_KEY": "", "DUCKCODING_GPT_IMAGE2_API_KEY": "",
    }
    for key in ("AI_TASK_QUEUE_KEY", "AI_TASK_BATCH_QUEUE_KEY", "AI_TASK_PROCESSING_KEY",
                "AI_TASK_MEMBERSHIP_KEY", "AI_POSTPROCESS_QUEUE_KEY",
                "AI_POSTPROCESS_PROCESSING_KEY", "AI_POSTPROCESS_MEMBERSHIP_KEY"):
        env[key] = f"{namespace}:{key.lower()}"
    os.environ.update(env)
    (root / "uploads").mkdir(exist_ok=True)
    logging.basicConfig(filename=root / "runtime.private.log", level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s %(message)s", force=True)
    return root, snapshot


def emit(event, **fields):
    print(json.dumps({"event": event, **fields}, ensure_ascii=False), flush=True)


async def main(args):
    root, snapshot = configure(args)
    import httpx
    import uvicorn
    from PIL import Image
    from sqlalchemy import select, update
    from app.main import app
    from app.core.security import hash_password
    from app.db.base import Base
    from app.db.session import async_session, engine
    from app.models.ai_image_provider import AIImageProvider
    from app.models.ai_task import AITask
    from app.models.user import User
    from app.scripts.ai_worker import AIImageWorker
    from app.scripts.ai_postprocess_worker import AIImagePostprocessWorker
    from app.services.ai_task_queue import ai_image_task_queue, ai_image_postprocess_queue

    credentials_path = root / "login.private.json"
    if credentials_path.exists():
        credentials = json.loads(credentials_path.read_text())
    else:
        credentials = {"username": "four-image-acceptance", "password": secrets.token_urlsafe(24)}
        credentials_path.write_text(json.dumps(credentials))
        credentials_path.chmod(0o600)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with async_session() as db:
        if await db.get(User, 1) is None:
            db.add(User(id=1, username=credentials["username"], email="four-images@example.invalid",
                        hashed_password=hash_password(credentials["password"]), role="viewer", is_active=True))
        for source in snapshot["providers"]:
            if await db.get(AIImageProvider, source["id"]) is None:
                db.add(AIImageProvider(**{**source, "is_enabled": False}))
        await db.commit()

    report_path = root / "results.json"
    report = json.loads(report_path.read_text()) if report_path.exists() else {"cases": {}, "scope": "local-fixed-code-real-upstream"}
    secrets_to_mask = [p["api_key"] for p in snapshot["providers"]] + [snapshot["env"].get("SEEDREAM_API_KEY", "")]

    def clean_error(error):
        value = str(error or "")
        for secret in secrets_to_mask:
            if secret:
                value = value.replace(secret, "[REDACTED]")
        return re.sub(r"(https?://[^\s?]+)\?[^\s]+", r"\1?[REDACTED]", value)[:3000]

    def save_report():
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2))

    async def read_response(client, path, **kwargs):
        # Retrying a read is safe; never retry a billable POST on transport loss.
        for attempt in range(12):
            try:
                response = await client.get(path, **kwargs)
                if response.status_code < 500 or attempt == 11:
                    return response
            except httpx.RequestError:
                if attempt == 11:
                    raise
            emit("read_retry", path=path, attempt=attempt + 1)
            await asyncio.sleep(5)

    reference_path = Path(args.reference).resolve()
    reference = "data:image/png;base64," + base64.b64encode(reference_path.read_bytes()).decode()
    prompt = ("一副红色运动太阳镜，镜面镜片，浅灰背景，干净的商业产品摄影，"
              "细节清晰，柔和自然光。只拍摄单件眼镜，不要人物，不要拼图，不要文字。")
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=args.port,
                                          lifespan="off", log_config=None, access_log=False))
    server.install_signal_handlers = lambda: None
    server_task = asyncio.create_task(server.serve())
    while not server.started:
        if server_task.done():
            raise RuntimeError("Local acceptance API did not start")
        await asyncio.sleep(0.1)
    worker, postworker = AIImageWorker(), AIImagePostprocessWorker()
    workers = [asyncio.create_task(worker.run()), asyncio.create_task(postworker.run())]
    base = f"http://127.0.0.1:{args.port}"
    emit("ready", api=base, report=str(report_path), paid=True)

    async def run_case(client, source, mode, reference_input):
        provider_id = source["id"] if source else 0
        model = source["model_name"] if source else "seedream"
        key = f"p{provider_id}-{mode or 'default'}-{'reference' if reference_input else 'text'}"
        previous = report["cases"].get(key, {})
        if previous.get("finished"):
            emit("already_tested", case=key, status=previous.get("status"))
            return
        row = report["cases"].setdefault(key, {
            "provider_id": provider_id, "provider_name": source["name"] if source else "Seedream",
            "production_enabled": source["is_enabled"] if source else True,
            "model": model, "mode": mode, "input": "reference" if reference_input else "text",
            "requested": 4, "started_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "client_request_id": f"{root.name}-{key}",
        })
        save_report()
        if not row.get("task_id"):
            found = await read_response(client, f"/api/v1/ai-image/requests/{row['client_request_id']}")
            if found.status_code == 200:
                row["task_id"] = found.json()["data"]["task_id"]
            else:
                body = {"model": model, "prompt": prompt + ("以参考图的红色运动眼镜为造型参考。" if reference_input else ""),
                        "width": 1024, "height": 1024, "quality": "low", "count": 4,
                        "client_request_id": row["client_request_id"]}
                if mode:
                    body["generation_mode"] = mode
                if reference_input:
                    body["images_data"] = [reference]
                response = await client.post("/api/v1/ai-image/generate", json=body)
                response.raise_for_status()
                row["task_id"] = response.json()["data"]["task_id"]
        save_report()
        emit("submitted", case=key, task_id=row["task_id"], count=4)
        started = time.monotonic()
        last_status = None
        while True:
            response = await read_response(client, f"/api/v1/ai-image/tasks/{row['task_id']}")
            response.raise_for_status()
            data = response.json()["data"]
            async with async_session() as db:
                task = await db.get(AITask, int(row["task_id"]))
                params = task.params or {}
                row["selected_provider"] = params.get("provider") or params.get("_generation_provider")
                row["upstream_ids"] = [item.get("upstream_task_id") for item in params.get("_upstream_attempts", [])]
                raw = params.get("_postprocess_source_urls") or params.get("_generated_source_urls") or []
                row["source_count_observed"] = max(row.get("source_count_observed", 0), len(raw))
                row["result_counts"] = params.get("_image_result_counts")
            row.update(status=data["status"], elapsed_seconds=round(time.monotonic() - started, 2),
                       delivered=len(data.get("image_urls") or []), error=clean_error(data.get("error")),
                       progress=data.get("progress"))
            if data["status"] != last_status:
                emit("state", case=key, task_id=row["task_id"], status=data["status"],
                     source_count=row["source_count_observed"], delivered=row["delivered"])
                last_status = data["status"]
            save_report()
            if data["status"] in {"completed", "failed", "cancelled"}:
                files = []
                for url in data.get("image_urls") or []:
                    if not url.startswith("/uploads/"):
                        files.append({"valid": False, "reason": "not stored locally"})
                        continue
                    image_response = await read_response(client, url)
                    try:
                        image_response.raise_for_status()
                        with Image.open(io.BytesIO(image_response.content)) as image:
                            image.load()
                            files.append({"url": url, "width": image.width, "height": image.height,
                                          "bytes": len(image_response.content), "valid": True,
                                          "sha256": hashlib.sha256(image_response.content).hexdigest()})
                    except Exception as exc:
                        files.append({"url": url, "valid": False, "error": clean_error(exc)})
                history = (await read_response(client, "/api/v1/ai-image/history", params={"limit": 100})).json()["data"]["items"]
                history_row = next((item for item in history if str(item["id"]) == str(row["task_id"])), {})
                row.update(finished=True, files=files, history_count=len(history_row.get("result_urls") or []),
                           history_requested=(history_row.get("params") or {}).get("count"))
                row["pass"] = (data["status"] == "completed" and len(files) == 4
                               and all(item["valid"] for item in files)
                               and len({item.get("sha256") for item in files}) == 4
                               and row["history_count"] == 4 and row["history_requested"] == 4
                               and (not provider_id or (row["selected_provider"] or {}).get("id") == provider_id))
                save_report()
                emit("finished", case=key, task_id=row["task_id"], status=row["status"],
                     delivered=row["delivered"], passed=row["pass"], seconds=row["elapsed_seconds"], error=row["error"][:500])
                return
            await asyncio.sleep(3)

    try:
        async with httpx.AsyncClient(base_url=base, timeout=60, trust_env=False) as client:
            login = await client.post("/api/v1/auth/login", json=credentials)
            login.raise_for_status()
            client.headers["Authorization"] = "Bearer " + login.json()["access_token"]
            sources = {str(p["id"]): p for p in snapshot["providers"]}
            for id_text in args.providers.split(","):
                source = None if id_text == "seedream" else sources[id_text]
                async with async_session() as db:
                    await db.execute(update(AIImageProvider).values(is_enabled=False))
                    if source:
                        await db.execute(update(AIImageProvider).where(AIImageProvider.id == source["id"]).values(is_enabled=True))
                    await db.commit()
                modes = ["fast", "precision"] if source and source["model_name"] == "gptimage25" else [None]
                for mode in modes:
                    # Keep paid load bounded to two user tasks, without changing
                    # production routing or testing through the admin shortcut.
                    case_tasks = [asyncio.create_task(run_case(client, source, mode, ref)) for ref in (False, True)]
                    outcomes = await asyncio.gather(*case_tasks, return_exceptions=True)
                    for outcome in outcomes:
                        if isinstance(outcome, BaseException):
                            raise outcome
    finally:
        worker.request_stop()
        await workers[0]
        # Generation may have just handed paid images to cleanup after a local
        # observation failed. Drain those before shutting down the second worker.
        for _ in range(120):
            async with async_session() as db:
                pending = await db.scalar(select(AITask.id).where(AITask.status == "postprocessing").limit(1))
            if pending is None or workers[1].done():
                break
            await asyncio.sleep(2)
        postworker.request_stop()
        await workers[1]
        server.should_exit = True
        await server_task
        await ai_image_task_queue.close()
        await ai_image_postprocess_queue.close()
        await engine.dispose()
    emit("complete", cases=len(report["cases"]), passed=sum(bool(r.get("pass")) for r in report["cases"].values()),
         report=str(report_path))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", required=True)
    parser.add_argument("--reference", required=True)
    parser.add_argument("--providers", default="12,13,seedream,6,7,10,4,5,11,14")
    parser.add_argument("--port", type=int, default=8934)
    parser.add_argument("--allow-paid", action="store_true")
    args = parser.parse_args()
    if not args.allow_paid:
        parser.error("Real upstream generation incurs fees; --allow-paid is required")
    asyncio.run(main(args))
