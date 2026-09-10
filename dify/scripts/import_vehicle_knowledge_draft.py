import json
import yaml

from extensions.ext_database import db
from models import Account, App
from services.app_dsl_service import AppDslService
from services.workflow_service import WorkflowService

APP_ID = "d8c545fa-aa04-4fa3-95ad-39f0f7b2ceb5"
DSL_PATH = "/tmp/xhs_copy_image_production_workflow.yml"

app_model = db.session.get(App, APP_ID)
if not app_model:
    raise RuntimeError("app not found")
account = db.session.get(Account, app_model.updated_by) or db.session.get(Account, app_model.created_by)
if not account:
    raise RuntimeError("app owner account not found")
account.set_tenant_id(app_model.tenant_id)

with open(DSL_PATH, "r", encoding="utf-8") as handle:
    incoming = yaml.safe_load(handle)
live = yaml.safe_load(AppDslService.export_dsl(app_model, include_secret=True))

live_env = {
    str(item.get("name")): item
    for item in (live.get("workflow", {}).get("environment_variables", []) or [])
}
incoming_env = incoming.get("workflow", {}).get("environment_variables", []) or []
for item in incoming_env:
    current = live_env.get(str(item.get("name")))
    if current is not None:
        item["value"] = current.get("value", item.get("value"))

result = AppDslService(db.session).import_app(
    account=account,
    import_mode="yaml-content",
    yaml_content=yaml.safe_dump(incoming, allow_unicode=True, sort_keys=False),
    app_id=APP_ID,
)
if str(result.status.value) not in {"completed", "completed-with-warnings"}:
    raise RuntimeError(f"import failed: {result.status.value}: {result.error}")

draft = WorkflowService().get_draft_workflow(app_model=app_model)
if not draft:
    raise RuntimeError("draft not found after import")
knowledge_nodes = [
    node for node in draft.graph_dict.get("nodes", [])
    if node.get("data", {}).get("type") == "knowledge-retrieval"
]
print(json.dumps({
    "status": str(result.status.value),
    "draft_workflow_id": draft.id,
    "node_count": len(draft.graph_dict.get("nodes", [])),
    "edge_count": len(draft.graph_dict.get("edges", [])),
    "knowledge_nodes": [node.get("id") for node in knowledge_nodes],
    "dataset_ids": knowledge_nodes[0].get("data", {}).get("dataset_ids") if knowledge_nodes else [],
}, ensure_ascii=False))
