import json

from extensions.ext_database import db
from extensions.ext_storage import storage
from models import Account, App
from services.workflow_service import WorkflowService

APP_ID = "d8c545fa-aa04-4fa3-95ad-39f0f7b2ceb5"
CASES = [
    ("零跑", "A10", "A10", ["403舒享版", "505激光雷达版"]),
    ("零跑", "C16", "C16", ["2027", "630尊享版", "280尊享版"]),
    ("零跑", "零跑Lafa5", "Lafa5 Ultra", ["500Ultra", "600Ultra"]),
    ("零跑", "D99", "D99增程", ["480尊享版", "480旗舰版"]),
    ("零跑", "B01", "B01", ["2027", "590舒享版", "670激光雷达版"]),
]

app_model = db.session.get(App, APP_ID)
if not app_model:
    raise RuntimeError("app not found")
account = db.session.get(Account, app_model.updated_by) or db.session.get(Account, app_model.created_by)
if not account:
    raise RuntimeError("account not found")
account.set_tenant_id(app_model.tenant_id)

service = WorkflowService()
draft = service.get_draft_workflow(app_model=app_model)
if not draft:
    raise RuntimeError("draft workflow not found")

results = []
for brand, model, policy_model, expected_terms in CASES:
    inputs = {
        "account_name": "车型知识接入调试",
        "brand": brand,
        "vehicle_model": model,
        "policy_text": f"车型：{policy_model}\n本次只验证车型知识检索，营销政策以用户当次输入为准。",
        "post_count": "1",
        "policy_style": "随机变化",
        "copy_keyword": "",
        "prompt_keyword": "",
        "reference_description": "",
        "image_model": "gptimage2",
        "image_width": "2048",
        "image_height": "2048",
    }
    service.run_draft_workflow_node(
        app_model=app_model,
        draft_workflow=draft,
        node_id="start",
        user_inputs=inputs,
        account=account,
    )
    query_execution = service.run_draft_workflow_node(
        app_model=app_model,
        draft_workflow=draft,
        node_id="build_queries",
        user_inputs={},
        account=account,
    )
    knowledge_execution = service.run_draft_workflow_node(
        app_model=app_model,
        draft_workflow=draft,
        node_id="vehicle_knowledge",
        user_inputs={},
        account=account,
    )
    query_outputs = query_execution.load_full_outputs(db.session, storage) or {}
    knowledge_outputs = knowledge_execution.load_full_outputs(db.session, storage) or {}
    records = knowledge_outputs.get("result") or []
    rendered = json.dumps(records, ensure_ascii=False)
    terms = {term: term in rendered for term in expected_terms}
    documents = []
    for record in records:
        metadata = record.get("metadata") or {}
        name = metadata.get("document_name") or metadata.get("document_title") or metadata.get("source")
        if name and name not in documents:
            documents.append(name)
    results.append({
        "model": model,
        "status": knowledge_execution.status,
        "query": query_outputs.get("vehicle_knowledge_query"),
        "record_count": len(records),
        "documents": documents,
        "expected_terms": terms,
        "preview": rendered[:500],
    })

if not all(item["record_count"] > 0 and all(item["expected_terms"].values()) for item in results):
    print(json.dumps(results, ensure_ascii=False, indent=2))
    raise RuntimeError("one or more knowledge retrieval cases failed")

print(json.dumps(results, ensure_ascii=False, indent=2))
