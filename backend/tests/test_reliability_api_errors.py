from __future__ import annotations

import pytest

from app.core.security import hash_password
from app.models.user import User
from app.services.ai_image_reconciliation_service import (
    AIImageReconciliationConflict,
    AIImageReconciliationError,
    AIImageReconciliationNotFound,
    AIImageReconciliationService,
)
from app.services.dify_task_parity_service import DifyTaskParityService
from app.services.xhs_homepage_sync_parity_service import HomepageSyncParityService
from app.services.xhs_report_refresh_parity_service import ReportRefreshParityService
from tests.conftest import make_auth_headers, session_factory


async def _admin_headers() -> dict[str, str]:
    async with session_factory() as db:
        user = User(
            username="reliability-admin",
            email="reliability-admin@example.com",
            hashed_password=hash_password("test-password"),
            role="admin",
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
        return make_auth_headers(user.id)


@pytest.mark.asyncio
async def test_scheduler_leader_reports_empty_lease_as_unhealthy(client):
    response = await client.get(
        "/api/v1/admin/reliability/scheduler-leader",
        headers=await _admin_headers(),
    )

    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["owner_id"] is None
    assert payload["is_healthy"] is False
    assert payload["lease_expires_at"] is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("path", "service_class"),
    [
        (
            "/api/v1/admin/reliability/xhs-homepage-shadow",
            HomepageSyncParityService,
        ),
        (
            "/api/v1/admin/reliability/xhs-account-data-shadow"
            "?sync_kind=engagement",
            HomepageSyncParityService,
        ),
        (
            "/api/v1/admin/reliability/xhs-report-refresh-shadow",
            ReportRefreshParityService,
        ),
        (
            "/api/v1/admin/reliability/dify-task-shadow",
            DifyTaskParityService,
        ),
    ],
)
async def test_shadow_parity_validation_errors_are_http_400(
    client,
    monkeypatch,
    path,
    service_class,
):
    async def reject_report(*_args, **_kwargs):
        raise ValueError("invalid parity window")

    monkeypatch.setattr(service_class, "build_report", reject_report)
    response = await client.get(path, headers=await _admin_headers())

    assert response.status_code == 400
    assert response.json()["detail"] == "invalid parity window"


@pytest.mark.asyncio
async def test_ai_image_shadow_list_validation_error_is_http_400(client, monkeypatch):
    async def reject_list(*_args, **_kwargs):
        raise AIImageReconciliationError("invalid review status")

    monkeypatch.setattr(AIImageReconciliationService, "list_jobs", reject_list)
    response = await client.get(
        "/api/v1/admin/reliability/ai-image-shadow",
        headers=await _admin_headers(),
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "invalid review status"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("error", "status_code"),
    [
        (AIImageReconciliationNotFound("job missing"), 404),
        (AIImageReconciliationConflict("job busy"), 409),
        (AIImageReconciliationError("bad job"), 400),
    ],
)
async def test_ai_image_reconcile_errors_have_stable_http_statuses(
    client,
    monkeypatch,
    error,
    status_code,
):
    async def reject_reconcile(*_args, **_kwargs):
        raise error

    monkeypatch.setattr(
        AIImageReconciliationService,
        "reconcile_job",
        reject_reconcile,
    )
    response = await client.post(
        "/api/v1/admin/reliability/ai-image-shadow/999/reconcile",
        headers=await _admin_headers(),
    )

    assert response.status_code == status_code
    assert response.json()["detail"] == str(error)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("error", "status_code"),
    [
        (AIImageReconciliationNotFound("job missing"), 404),
        (AIImageReconciliationConflict("job busy"), 409),
        (AIImageReconciliationError("bad resolution"), 400),
    ],
)
async def test_ai_image_manual_resolution_errors_have_stable_http_statuses(
    client,
    monkeypatch,
    error,
    status_code,
):
    async def reject_resolution(*_args, **_kwargs):
        raise error

    monkeypatch.setattr(
        AIImageReconciliationService,
        "manual_resolve",
        reject_resolution,
    )
    response = await client.post(
        "/api/v1/admin/reliability/ai-image-shadow/999/resolve",
        headers=await _admin_headers(),
        json={"outcome": "failed", "reason": "verified upstream failure"},
    )

    assert response.status_code == status_code
    assert response.json()["detail"] == str(error)


@pytest.mark.asyncio
async def test_reliability_api_rejects_non_admin_role_assignment(client):
    async with session_factory() as db:
        user = User(
            username="reliability-viewer",
            email="reliability-viewer@example.com",
            hashed_password=hash_password("test-password"),
            role="viewer",
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
        headers = make_auth_headers(user.id)

    response = await client.get(
        "/api/v1/admin/reliability/scheduler-leader",
        headers=headers,
    )
    assert response.status_code == 403
