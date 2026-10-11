from __future__ import annotations

from pathlib import Path
import pytest
from fastapi import HTTPException
from sqlalchemy import select
from app.db.session import async_session
from app.models.user import User
from app.models.hermes_workflow import HermesWorkflowRun
from app.services.hermes_workflow_service import HermesWorkflowService
from tests.conftest import make_auth_headers
from tests.test_hermes_workflows import seed_owner


@pytest.mark.asyncio
async def test_admin_existing_policy_is_explicit_audited_and_preserves_deadline(client, monkeypatch):
    user_id, env_id = await seed_owner()
    async with async_session() as db:
        user = await db.get(User, user_id)
        user.role = "admin"
        await db.commit()
    policies = [{"case_id": "a05", "vehicle_model": "零跑A05", "policy_deadline": "2026-09-30", "policy_text": "Original"}]
    monkeypatch.setattr('app.services.hermes_workflow_service.policy_summaries', lambda: policies)
    body = {"accounts": [{"environment_id": env_id, "vehicle_model": "零跑A05"}],
            "posts_per_account": 1, "use_existing_policy": True}
    response = await client.post('/api/v1/admin/hermes-workflows/runs', headers=make_auth_headers(user_id), json=body)
    assert response.status_code == 200
    async with async_session() as db:
        run = await db.get(HermesWorkflowRun, response.json()['data']['id'])
        assert run.parameters['policy_snapshot'] == policies
        assert run.parameters['existing_policy_authorization']['authorized_by'] == user_id
        assert '原有效期' in run.parameters['instruction']
    body.pop('use_existing_policy')
    normal = await client.post('/api/v1/admin/hermes-workflows/runs', headers=make_auth_headers(user_id), json=body)
    assert normal.status_code == 200
    assert 'existing_policy_authorization' not in normal.json()['data']['parameters']


@pytest.mark.asyncio
async def test_operator_cannot_opt_out_of_policy_freshness(client):
    user_id, env_id = await seed_owner()
    response = await client.post('/api/v1/admin/hermes-workflows/runs', headers=make_auth_headers(user_id),
                                 json={"accounts": [{"environment_id": env_id, "vehicle_model": "零跑A05"}],
                                       "posts_per_account": 1, "use_existing_policy": True})
    assert response.status_code == 403
    async with async_session() as db:
        with pytest.raises(HTTPException) as error:
            await HermesWorkflowService(db).create_run(source='manual', requested_by=user_id,
                accounts=[], posts_per_account=1, use_existing_policy=True)
        assert error.value.status_code == 403
        assert (await db.scalars(select(HermesWorkflowRun))).all() == []


@pytest.mark.parametrize('authorization,source,requested_by,valid', [
    (None, 'manual', 1, True),
    ({'authorized_by': 1, 'authorized_at': '2026-10-11T15:00:00'}, 'admin_manual', 1, True),
    ({'authorized_by': 1, 'authorized_at': '2026-10-11T15:00:00'}, 'manual', 1, False),
    ({'authorized_by': 2, 'authorized_at': '2026-10-11T15:00:00'}, 'admin_manual', 1, False),
    ({'authorized_by': True, 'authorized_at': 'now'}, 'admin_manual', 1, False),
    ({'authorized_by': 1}, 'admin_manual', 1, False),
    ('true', 'admin_manual', 1, False),
])
def test_worker_policy_override_is_scoped_and_fail_closed(monkeypatch, authorization, source, requested_by, valid):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[2] / 'ops' / 'xhs_hermes'))
    from web_worker import existing_policy_arguments
    run = {'source': source, 'requested_by': requested_by, 'parameters': {}}
    if authorization is not None:
        run['parameters']['existing_policy_authorization'] = authorization
    if not valid:
        with pytest.raises(RuntimeError):
            existing_policy_arguments(run)
    else:
        assert existing_policy_arguments(run) == ([] if authorization is None else ['--no-policy-sync', '--allow-expired-policy'])
