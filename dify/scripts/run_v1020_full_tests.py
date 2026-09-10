import concurrent.futures
import json
import time

import httpx
from sqlalchemy import text

from extensions.ext_database import db

APP_ID = "d8c545fa-aa04-4fa3-95ad-39f0f7b2ceb5"
CASES = [
    ("A10", "da1d53dd-11df-4f3a-aad1-9ae24cd171da"),
]

app_token = db.session.execute(text(
    "select token from api_tokens where type='app' and app_id=:app_id order by created_at desc limit 1"
), {"app_id": APP_ID}).scalar_one()

case_inputs = []
for label, run_id in CASES:
    raw = db.session.execute(text(
        "select inputs from workflow_runs where id=:run_id and app_id=:app_id"
    ), {"run_id": run_id, "app_id": APP_ID}).scalar_one()
    inputs = json.loads(raw) if isinstance(raw, str) else dict(raw)
    inputs["account_name"] = f"v10.23车型知识全链路调试-{label}-{int(time.time())}"
    inputs["post_count"] = "1"
    inputs["reference_image"] = None
    case_inputs.append((label, inputs))

def run_case(item):
    label, inputs = item
    started = time.time()
    payload = {
        "inputs": inputs,
        "response_mode": "blocking",
        "user": f"codex-v1023-{label.lower()}",
    }
    with httpx.Client(timeout=httpx.Timeout(1200.0, connect=20.0)) as client:
        response = client.post(
            "http://nginx/v1/workflows/run",
            headers={"Authorization": f"Bearer {app_token}", "Content-Type": "application/json"},
            json=payload,
        )
    result = response.json()
    data = result.get("data") or {}
    outputs = data.get("outputs") or {}
    delivered = []
    if outputs.get("delivery_json"):
        delivered = json.loads(outputs["delivery_json"])
    summary = {
        "label": label,
        "http_status": response.status_code,
        "workflow_run_id": result.get("workflow_run_id") or data.get("id"),
        "status": data.get("status"),
        "error": data.get("error"),
        "elapsed_seconds": round(time.time() - started, 2),
        "delivered_count": len(delivered),
        "blocked_items": outputs.get("blocked_items"),
        "items": [{
            "vehicle_model": row.get("vehicle_model"),
            "title": row.get("title"),
            "content": row.get("content"),
            "image_urls": row.get("image_urls"),
            "image_quality_pass": row.get("image_quality_pass"),
            "source_copy_ids": row.get("source_copy_ids"),
        } for row in delivered],
    }
    print(json.dumps({
        "label": label,
        "status": summary["status"],
        "delivered_count": summary["delivered_count"],
        "elapsed_seconds": summary["elapsed_seconds"],
        "error": summary["error"],
    }, ensure_ascii=False), flush=True)
    return summary

with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
    summaries = list(executor.map(run_case, case_inputs))

for summary in summaries:
    run_id = summary.get("workflow_run_id")
    if not run_id:
        continue
    raw = db.session.execute(text(
        "select outputs from workflow_node_executions "
        "where workflow_run_id=:run_id and node_id='vehicle_knowledge' and status='succeeded' "
        "order by created_at desc limit 1"
    ), {"run_id": run_id}).scalar()
    knowledge = json.loads(raw) if isinstance(raw, str) and raw else (raw or {})
    rendered = json.dumps(knowledge.get("result") or [], ensure_ascii=False)
    names = []
    for record in knowledge.get("result") or []:
        name = (record.get("metadata") or {}).get("document_name")
        if name and name not in names:
            names.append(name)
    summary["knowledge_documents"] = names
    summary["knowledge_preview"] = rendered[:1000]

with open("/tmp/v1023_full_test_results.json", "w", encoding="utf-8") as handle:
    json.dump(summaries, handle, ensure_ascii=False, indent=2)

failed = [item for item in summaries if item["status"] != "succeeded" or item["delivered_count"] != 1]
if failed:
    print(json.dumps(summaries, ensure_ascii=False, indent=2), flush=True)
    raise RuntimeError(f"full workflow failures: {[item['label'] for item in failed]}")

print(json.dumps(summaries, ensure_ascii=False, indent=2), flush=True)
