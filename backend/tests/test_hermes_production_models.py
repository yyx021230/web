from __future__ import annotations

import json
from pathlib import Path

import pytest
from sqlalchemy import func, select

from app.db.session import async_session
from app.models.hermes_workflow import HermesWorkflowPost, HermesWorkflowRun
from app.services.hermes_policy_service import available_production_models
from tests.conftest import make_auth_headers
from tests.test_hermes_workflows import seed_owner


def set_policies(monkeypatch, rows):
    for module in (
        "app.api.v1.hermes_workflows",
        "app.services.hermes_workflow_service",
    ):
        monkeypatch.setattr(f"{module}.policy_summaries", lambda: rows)


async def assert_no_run_created():
    async with async_session() as db:
        assert await db.scalar(select(func.count(HermesWorkflowRun.id))) == 0
        assert await db.scalar(select(func.count(HermesWorkflowPost.id))) == 0


def test_available_models_use_worker_uniqueness_rule():
    assert available_production_models([
        {"vehicle_model": "零跑A05"}, {"vehicle_model": " A05 "},
        {"vehicle_model": "零跑C11"}, {"vehicle_model": ""},
    ]) == ["零跑C11"]


@pytest.mark.asyncio
@pytest.mark.parametrize("policies,expected", [
    ([{"case_id": "a05", "vehicle_model": "零跑A05"}], ["零跑A05"]),
    ([], []),
    ([{"vehicle_model": "零跑A05"}, {"vehicle_model": "A05"}], []),
])
async def test_bootstrap_only_offers_unique_configured_models(client, monkeypatch, policies, expected):
    user_id, _ = await seed_owner()
    set_policies(monkeypatch, policies)
    response = await client.get("/api/v1/hermes-workflows/bootstrap", headers=make_auth_headers(user_id))
    assert response.status_code == 200
    assert response.json()["data"]["vehicle_models"] == expected


@pytest.mark.asyncio
@pytest.mark.parametrize("policies,model", [
    ([{"case_id": "a05", "vehicle_model": "零跑A05"}], "零跑C11"),
    ([], "零跑A05"),
    ([{"vehicle_model": "零跑A05"}, {"vehicle_model": "A05"}], "零跑A05"),
])
async def test_single_rejects_missing_or_ambiguous_model_before_enqueue(client, monkeypatch, policies, model):
    user_id, env_id = await seed_owner()
    set_policies(monkeypatch, policies)
    response = await client.post("/api/v1/hermes-workflows/runs", headers=make_auth_headers(user_id),
                                 json={"account_id": env_id, "vehicle_model": model, "post_count": 1})
    assert response.status_code == 400
    assert "生产案例" in response.text
    await assert_no_run_created()


@pytest.mark.asyncio
async def test_batch_missing_model_does_not_partially_enqueue(client, monkeypatch):
    user_id, env_id = await seed_owner()
    set_policies(monkeypatch, [{"case_id": "a05", "vehicle_model": "零跑A05"}])
    response = await client.post("/api/v1/hermes-workflows/runs/batch", headers=make_auth_headers(user_id), json={
        "accounts": [{"environment_id": env_id, "post_count": 2}],
        "vehicle_models": ["零跑A05", "零跑C11"],
    })
    assert response.status_code == 400
    await assert_no_run_created()


@pytest.mark.asyncio
@pytest.mark.parametrize("case_id", ["missing-case", "a05"])
async def test_explicit_case_cannot_override_selected_vehicle(client, monkeypatch, case_id):
    user_id, env_id = await seed_owner()
    set_policies(monkeypatch, [
        {"case_id": "a05", "vehicle_model": "零跑A05"},
        {"case_id": "c11", "vehicle_model": "零跑C11"},
    ])
    response = await client.post("/api/v1/hermes-workflows/runs", headers=make_auth_headers(user_id),
                                 json={"account_id": env_id, "vehicle_model": "零跑C11", "case_id": case_id})
    assert response.status_code == 400
    assert "不匹配" in response.text
    await assert_no_run_created()


@pytest.mark.asyncio
async def test_configured_c11_reaches_worker_config_without_model_calls(client, monkeypatch, tmp_path):
    user_id, env_id = await seed_owner()
    policies = [{"case_id": "c11-editorial", "vehicle_model": "零跑C11", "quote_rows": []}]
    set_policies(monkeypatch, policies)
    response = await client.post("/api/v1/hermes-workflows/runs", headers=make_auth_headers(user_id),
                                 json={"account_id": env_id, "vehicle_model": "零跑C11", "post_count": 1})
    assert response.status_code == 200
    run = response.json()["data"]
    async with async_session() as db:
        persisted = await db.get(HermesWorkflowRun, run["id"])
        assert persisted.parameters["policy_snapshot"] == policies
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[2] / "ops" / "xhs_hermes"))
    import web_worker
    cases = tmp_path / "cases.json"
    cases.write_text(json.dumps({"c11-editorial": {"vehicle_model": "零跑C11"}}))
    monkeypatch.setattr(web_worker, "DEFAULT_CASES", cases)
    config, _ = web_worker.build_run_config(run, tmp_path / "run-config.json")
    assert config["accounts"][0]["case_ids"] == ["c11-editorial"]
