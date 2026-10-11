from __future__ import annotations

import asyncio
import io
import hashlib
import json
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from PIL import Image
from sqlalchemy import delete, func, select

from app.adapters.phone_cloud_publish import PhoneCloudPublisher, PublishAssets, PublishError, publish_evidence
from app.config import settings
from app.db.session import async_session
from app.models.hermes_publish import HermesPublishAttempt, HermesPublishJob
from app.models.hermes_workflow import HermesWorkflowPost
from app.models.user import User
from app.models.user_xhs_env import UserXHSEnvironment
from app.models.xhs_environment import XHSEnvironment
from app.services.hermes_publish_service import HermesPublishWorker
from app.utils.timezone import cst_now_naive
from tests.conftest import make_auth_headers
from tests.test_hermes_workflows import prepared_posts, seed_owner


def image_bytes():
    output = io.BytesIO()
    Image.new("RGB", (20, 30), "blue").save(output, format="PNG")
    return output.getvalue()


@pytest.fixture
def publish_config(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "phone_cloud_publish_enabled", True)
    monkeypatch.setattr(settings, "phone_cloud_publish_base_url", "https://phone.example.test")
    monkeypatch.setattr(settings, "phone_cloud_publish_http_origins", "")
    monkeypatch.setattr(settings, "phone_cloud_publish_username", "dedicated-test-user")
    monkeypatch.setattr(settings, "phone_cloud_publish_password", "test-only-password")
    monkeypatch.setattr(settings, "phone_cloud_publish_verified_xhs_ids", "stable-42")
    monkeypatch.setattr(settings, "phone_cloud_publish_snapshot_path", str(tmp_path / "private"))
    async def fetch(_self, _url):
        return image_bytes()
    monkeypatch.setattr(PublishAssets, "fetch", fetch)


def proof_for(snapshot):
    return {"version": 1, "accountIdentityVerified": True, "titleExact": True,
            "contentExact": True, "clickedFinalPublish": True, "imageSelectionVerified": False,
            "accountSha256": hashlib.sha256(snapshot.get("xhs_id", snapshot.get("expectedXhsId", "")).encode("utf-8")).hexdigest(),
            "confirmation": "success_text", **{f"{key}Sha256": hashlib.sha256(snapshot[key].encode("utf-8")).hexdigest()
                                                  for key in ("title", "content")}}


class FakePhone:
    target = staticmethod(PhoneCloudPublisher.target)

    def __init__(self):
        self.created = []
        self.rows = []
        self.device_rows = [{"deviceId": "device-a", "listingStatus": "listed", "adbOnline": True,
                             "available": True, "automationStatus": {"deviceAutomationReady": True},
                             "xhsAccounts": [{"xhsId": "stable-42", "appSlot": "app2", "enabled": True}]}]
        self.error = None
        self.cancelled = []

    async def devices(self):
        return self.device_rows

    async def create(self, target, snapshot, images):
        self.created.append((target, snapshot, images))
        if self.error:
            raise self.error
        key = f"remote-{len(self.created)}"
        self.rows.append({"jobId": key, "status": "queued", "result": {"runner": {"publishEvidence": proof_for(snapshot)}}})
        return key

    async def tasks(self):
        return self.rows

    async def cancel(self, key):
        self.cancelled.append(key)
        self.rows = [{**row, "status": "cancelled"} if row["jobId"] == key else row for row in self.rows]


async def approved(client, count=1):
    user_id, env_id = await seed_owner()
    headers = make_auth_headers(user_id)
    async with async_session() as db:
        env = await db.get(XHSEnvironment, env_id)
        env.xhs_account_id = "stable-42"
        await db.commit()
    run = await prepared_posts(client, headers, env_id, count)
    for post in run["posts"]:
        response = await client.post(f"/api/v1/hermes-workflows/posts/{post['id']}/review", headers=headers,
                                     json={"action": "approve", "expected_version": post["version"]})
        assert response.status_code == 200, response.text
    run = (await client.get(f"/api/v1/hermes-workflows/runs/{run['id']}", headers=headers)).json()["data"]
    return user_id, env_id, headers, run


def plan(post, env_id, *, offset=300):
    return {"post_id": post["id"], "environment_id": env_id,
            "expected_version": post["version"],
            "scheduled_at": (cst_now_naive() + timedelta(seconds=offset)).isoformat(timespec="seconds")}


async def schedule(client, count=1):
    user_id, env_id, headers, run = await approved(client, count)
    items = [plan(post, env_id, offset=300 + i * 60) for i, post in enumerate(run["posts"])]
    response = await client.post("/api/v1/hermes-workflows/publish-plan", headers=headers, json={"items": items})
    assert response.status_code == 200, response.text
    async with async_session() as db:
        jobs = list((await db.scalars(select(HermesPublishJob).order_by(HermesPublishJob.id))).all())
        for job in jobs:
            job.scheduled_at = cst_now_naive() - timedelta(seconds=1)
        await db.commit()
    return user_id, headers, run, jobs


@pytest.mark.asyncio
async def test_api_schedule_worker_poll_and_result_are_durable_and_private(client, publish_config):
    user_id, headers, run, jobs = await schedule(client)
    phone = FakePhone()
    await HermesPublishWorker(async_session, phone).tick()
    assert len(phone.created) == 1
    target, snapshot, images = phone.created[0]
    assert target == {"device_id": "device-a", "app_slot": "app2", "expected_xhs_id": "stable-42"}
    assert snapshot["title"] == run["posts"][0]["title"]
    assert images[0].startswith("data:image/png;base64,")
    phone.rows[0]["status"] = "succeeded"
    await HermesPublishWorker(async_session, phone).tick()  # a new Worker instance after restart
    response = await client.get("/api/v1/hermes-workflows/publish-jobs", headers=headers)
    job = response.json()["data"]["items"][0]
    assert job["status"] == "submitted" and job["remote_job_id"] == "remote-1"
    assert job["message"] == "云手机返回发布成功"
    assert "images" not in job and "snapshot" not in job
    async with async_session() as db:
        saved = await db.get(HermesWorkflowPost, run["posts"][0]["id"])
        assert saved.status == "approved" and saved.publish_status == "submitted" and saved.published_at is None
        assert await db.scalar(select(func.count()).select_from(HermesPublishAttempt)) == 1
        stranger = User(username="publish-stranger", email="stranger@example.test", hashed_password="unused", role="viewer", is_active=True)
        db.add(stranger)
        await db.commit()
    assert (await client.get("/api/v1/hermes-workflows/publish-jobs", headers=make_auth_headers(stranger.id))).json()["data"]["total"] == 0
    assert (await client.post(f"/api/v1/hermes-workflows/publish-jobs/{jobs[0].id}/cancel", headers=make_auth_headers(stranger.id))).status_code == 404
    assert (await client.get("/api/v1/admin/hermes-workflows/publish-jobs", headers=headers)).status_code == 403


@pytest.mark.asyncio
async def test_saved_plan_replay_is_idempotent_and_stale_changed_plan_is_rejected(client, publish_config):
    _, env_id, headers, run = await approved(client)
    item = plan(run["posts"][0], env_id)
    for _ in range(2):
        assert (await client.post("/api/v1/hermes-workflows/publish-plan", headers=headers, json={"items": [item]})).status_code == 200
    stale = await client.post("/api/v1/hermes-workflows/publish-plan", headers=headers,
                              json={"items": [{**item, "scheduled_at": "2030-01-01T09:00"}]})
    assert stale.status_code == 409
    async with async_session() as db:
        assert await db.scalar(select(func.count()).select_from(HermesPublishJob)) == 1


@pytest.mark.asyncio
async def test_content_edit_cancels_schedule_but_submission_locks_content(client, publish_config):
    _, headers, run, jobs = await schedule(client)
    current = (await client.get(f"/api/v1/hermes-workflows/runs/{run['id']}", headers=headers)).json()["data"]["posts"][0]
    payload = {"title": "修改标题", "content": current["content"], "comment": "修正", "expected_version": current["version"]}
    response = await client.patch(f"/api/v1/hermes-workflows/posts/{current['id']}", headers=headers, json=payload)
    assert response.status_code == 200, response.text
    assert response.json()["data"]["publish_status"] == "not_requested"
    async with async_session() as db:
        assert (await db.get(HermesPublishJob, jobs[0].id)).status == "cancelled"
        job = await db.get(HermesPublishJob, jobs[0].id)
        job.status = "unknown"
        await db.commit()
    payload["expected_version"] = response.json()["data"]["version"]
    assert (await client.patch(f"/api/v1/hermes-workflows/posts/{current['id']}", headers=headers, json=payload)).status_code == 409


@pytest.mark.asyncio
@pytest.mark.parametrize("remote_status,expected_status", [
    ("failed", "failed"), ("expired", "failed"), ("cancelled", "cancelled"),
    ("bogus", "unknown"), (None, "unknown"),
])
async def test_remote_terminal_or_missing_job_never_republishes(client, publish_config, remote_status, expected_status):
    _, headers, _, jobs = await schedule(client)
    phone = FakePhone()
    worker = HermesPublishWorker(async_session, phone)
    await worker.tick()
    phone.rows = [] if remote_status is None else [{"jobId": "remote-1", "status": remote_status}]
    await worker.tick()
    await worker.tick()
    assert len(phone.created) == 1
    records = (await client.get("/api/v1/hermes-workflows/publish-jobs", headers=headers)).json()["data"]
    assert records["items"][0]["status"] == expected_status
    async with async_session() as db:
        attempt = await db.scalar(select(HermesPublishAttempt))
        assert attempt.status == expected_status


@pytest.mark.asyncio
async def test_post_timeout_persists_unknown_and_restart_cannot_create_again(client, publish_config):
    _, _, _, jobs = await schedule(client)
    phone = FakePhone()
    phone.error = PublishError("publish_response_unknown", uncertain=True)
    await HermesPublishWorker(async_session, phone).tick()
    await HermesPublishWorker(async_session, phone).tick()
    assert len(phone.created) == 1
    async with async_session() as db:
        assert (await db.get(HermesPublishJob, jobs[0].id)).status == "unknown"


@pytest.mark.asyncio
async def test_remote_device_rejection_waits_and_creates_new_attempt_only_after_definite_rejection(client, publish_config):
    _, _, _, jobs = await schedule(client)
    phone = FakePhone()
    phone.error = PublishError("publish_device_busy", retryable=True)
    worker = HermesPublishWorker(async_session, phone)
    await worker.tick()
    async with async_session() as db:
        job = await db.get(HermesPublishJob, jobs[0].id)
        assert job.status == "waiting_device"
        job.retry_at = cst_now_naive() - timedelta(seconds=1)
        await db.commit()
    phone.error = None
    await worker.tick()
    async with async_session() as db:
        assert (await db.get(HermesPublishJob, jobs[0].id)).status == "queued"
        assert await db.scalar(select(func.count()).select_from(HermesPublishAttempt)) == 2


@pytest.mark.asyncio
async def test_same_physical_phone_is_serial(client, publish_config):
    _, _, _, jobs = await schedule(client, 2)
    phone = FakePhone()
    await HermesPublishWorker(async_session, phone).tick()
    assert len(phone.created) == 1
    async with async_session() as db:
        assert (await db.get(HermesPublishJob, jobs[1].id)).status == "waiting_device"
    phone.rows[0]["status"] = "succeeded"
    async with async_session() as db:
        job = await db.get(HermesPublishJob, jobs[1].id)
        job.retry_at = cst_now_naive() - timedelta(seconds=1)
        await db.commit()
    await HermesPublishWorker(async_session, phone).tick()
    assert len(phone.created) == 2


@pytest.mark.asyncio
async def test_busy_phone_does_not_block_different_phone(client, publish_config, monkeypatch):
    user_id, headers, _, _ = await schedule(client)
    async with async_session() as db:
        env = XHSEnvironment(shop_id="publish-second-device", account_name="第二账号", status="active", xhs_account_id="stable-99")
        db.add(env)
        await db.flush()
        db.add(UserXHSEnvironment(user_id=user_id, environment_id=env.id))
        await db.commit()
        second_id = env.id
    run = await prepared_posts(client, headers, second_id)
    post = run["posts"][0]
    response = await client.post(f"/api/v1/hermes-workflows/posts/{post['id']}/review", headers=headers,
                                 json={"action": "approve", "expected_version": post["version"]})
    assert response.status_code == 200
    reviewed = (await client.get(f"/api/v1/hermes-workflows/runs/{run['id']}", headers=headers)).json()["data"]["posts"][0]
    response = await client.post("/api/v1/hermes-workflows/publish-plan", headers=headers,
                                 json={"items": [plan(reviewed, second_id)]})
    assert response.status_code == 200, response.text
    async with async_session() as db:
        job = await db.scalar(select(HermesPublishJob).where(HermesPublishJob.environment_id == second_id))
        job.scheduled_at = cst_now_naive() - timedelta(seconds=1)
        await db.commit()
    monkeypatch.setattr(settings, "phone_cloud_publish_verified_xhs_ids", "stable-42,stable-99")
    phone = FakePhone()
    phone.device_rows[0]["busy"] = True
    phone.device_rows.append({**FakePhone().device_rows[0], "deviceId": "device-b",
                              "xhsAccounts": [{"xhsId": "stable-99", "appSlot": "app1", "enabled": True}]})
    await HermesPublishWorker(async_session, phone).tick()
    assert len(phone.created) == 1 and phone.created[0][0]["device_id"] == "device-b"
    async with async_session() as db:
        states = set((await db.scalars(select(HermesPublishJob.status))).all())
        assert states == {"queued", "waiting_device"}


@pytest.mark.asyncio
async def test_http_adapter_whole_api_worker_result_path(client, publish_config):
    _, headers, _, _ = await schedule(client)
    received = []
    def handler(request):
        if request.url.path.endswith("auth/login"):
            return httpx.Response(200, json={"session": {"token": "test-session", "expiresAt": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()}})
        assert request.headers["Authorization"] == "Bearer test-session"
        if request.url.path.endswith("devices"):
            return httpx.Response(200, json={"devices": FakePhone().device_rows})
        if request.method == "POST":
            received.append(json.loads(request.content))
            return httpx.Response(201, json={"task": {"jobId": "http-job", "status": "queued"}})
        return httpx.Response(200, json={"tasks": [{"jobId": "http-job", "status": "succeeded",
                                                  "result": {"runner": {"publishEvidence": proof_for(received[0])}}}]})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        worker = HermesPublishWorker(async_session, PhoneCloudPublisher(http))
        await worker.tick()
        await worker.tick()
        await worker.tick()
    assert len(received) == 1
    assert received[0]["deviceId"] == "device-a" and received[0]["xhsAppSlot"] == "app2"
    assert received[0]["expectedXhsId"] == "stable-42"
    assert received[0]["imageDataUrls"][0].startswith("data:image/png;base64,")
    jobs = (await client.get("/api/v1/hermes-workflows/publish-jobs", headers=headers)).json()["data"]["items"]
    assert jobs[0]["status"] == "submitted" and jobs[0]["remote_job_id"] == "http-job"


@pytest.mark.asyncio
@pytest.mark.parametrize("status, body, expected", [
    (400, {"error": "publish_image_required"}, "failed"),
    (422, {"error": "invalid_payload"}, "failed"),
    (500, {"error": "server_error"}, "unknown"),
    (201, {"task": {}}, "unknown"),
])
async def test_create_rejection_or_unknown_is_persistent_and_not_replayed(client, publish_config, status, body, expected):
    _, headers, _, _ = await schedule(client)
    created = []
    def handler(request):
        if request.url.path.endswith("auth/login"):
            return httpx.Response(200, json={"session": {"token": "test-session", "expiresAt": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()}})
        if request.url.path.endswith("devices"):
            return httpx.Response(200, json={"devices": FakePhone().device_rows})
        created.append(request)
        return httpx.Response(status, json=body)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        worker = HermesPublishWorker(async_session, PhoneCloudPublisher(http))
        await worker.tick()
        await worker.tick()
    assert len(created) == 1
    row = (await client.get("/api/v1/hermes-workflows/publish-jobs", headers=headers)).json()["data"]["items"][0]
    assert row["status"] == expected
    async with async_session() as db:
        attempt = await db.scalar(select(HermesPublishAttempt))
        assert attempt.evidence["images"][0]["sha256"] and attempt.evidence["code"]


@pytest.mark.asyncio
async def test_poll_budget_and_read_failure_never_recreate_and_late_success_reconciles(client, publish_config):
    _, headers, _, jobs = await schedule(client)
    phone = FakePhone()
    worker = HermesPublishWorker(async_session, phone)
    await worker.tick()
    async with async_session() as db:
        job = await db.get(HermesPublishJob, jobs[0].id)
        job.lease_until = cst_now_naive() - timedelta(seconds=settings.phone_cloud_publish_max_observe_seconds + 1)
        await db.commit()
    async def unavailable():
        raise PublishError("publish_api_unavailable", retryable=True)
    original = phone.tasks
    phone.tasks = unavailable
    await worker.tick()
    result = (await client.get("/api/v1/hermes-workflows/publish-jobs", headers=headers)).json()["data"]["items"][0]
    assert result["status"] == "unknown" and result["error_code"] == "publish_observation_timeout"
    phone.tasks = original
    phone.rows[0]["status"] = "succeeded"
    await worker.tick()
    result = (await client.get("/api/v1/hermes-workflows/publish-jobs", headers=headers)).json()["data"]["items"][0]
    assert result["status"] == "submitted" and len(phone.created) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("state, expected", [("preparing", "scheduled"), ("submitting", "unknown"), ("cancel_requested", "unknown")])
async def test_expired_claim_recovery_distinguishes_before_and_after_submission(client, publish_config, state, expected):
    _, _, _, jobs = await schedule(client)
    async with async_session() as db:
        job = await db.get(HermesPublishJob, jobs[0].id)
        job.status, job.claim_token = state, "old-token"
        job.lease_until = cst_now_naive() - timedelta(seconds=10)
        await db.commit()
    await HermesPublishWorker(async_session, FakePhone()).recover()
    async with async_session() as db:
        assert (await db.get(HermesPublishJob, jobs[0].id)).status == expected


@pytest.mark.asyncio
async def test_two_workers_cannot_claim_one_schedule(client, publish_config):
    await schedule(client)
    worker = HermesPublishWorker(async_session, FakePhone())
    results = await asyncio.gather(worker.claim(), worker.claim())
    assert sum(result is not None for result in results) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["assignment", "version", "identity", "disabled", "unverified", "late"])
async def test_dispatch_rechecks_permissions_identity_version_and_feature_gate(client, publish_config, monkeypatch, change):
    _, _, run, jobs = await schedule(client)
    phone = FakePhone()
    async with async_session() as db:
        job = await db.get(HermesPublishJob, jobs[0].id)
        if change == "assignment":
            await db.execute(delete(UserXHSEnvironment))
        elif change == "version":
            (await db.get(HermesWorkflowPost, run["posts"][0]["id"])).title = "未经审核的新标题"
        elif change == "identity":
            (await db.get(XHSEnvironment, job.environment_id)).xhs_account_id = "another-account"
        elif change == "late":
            job.scheduled_at = cst_now_naive() - timedelta(hours=2)
        await db.commit()
    if change == "disabled":
        monkeypatch.setattr(settings, "phone_cloud_publish_enabled", False)
    if change == "unverified":
        monkeypatch.setattr(settings, "phone_cloud_publish_verified_xhs_ids", "")
    await HermesPublishWorker(async_session, phone).tick()
    assert not phone.created
    async with async_session() as db:
        assert (await db.get(HermesPublishJob, jobs[0].id)).status == ("scheduled" if change == "disabled" else "failed")


@pytest.mark.asyncio
async def test_cancel_local_and_remote_are_not_withdrawal_and_no_retry(client, publish_config):
    _, headers, _, jobs = await schedule(client)
    phone = FakePhone()
    await HermesPublishWorker(async_session, phone).tick()
    response = await client.post(f"/api/v1/hermes-workflows/publish-jobs/{jobs[0].id}/cancel", headers=headers)
    assert response.json()["data"]["status"] == "cancel_requested"
    await HermesPublishWorker(async_session, phone).tick()
    assert phone.cancelled == ["remote-1"]
    await HermesPublishWorker(async_session, phone).tick()
    async with async_session() as db:
        job = await db.get(HermesPublishJob, jobs[0].id)
        assert job.status == "cancelled" and "不可撤回" in job.message
    assert len(phone.created) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("legacy", [False, True])
async def test_cloud_success_does_not_require_proof_in_new_or_legacy_jobs(client, publish_config, legacy):
    _, _, _, jobs = await schedule(client)
    phone = FakePhone()
    worker = HermesPublishWorker(async_session, phone)
    async with async_session() as db:
        saved = await db.get(HermesPublishJob, jobs[0].id)
        assert "publish_proof_required" not in saved.snapshot
        if legacy:
            saved.snapshot = {**saved.snapshot, "publish_proof_required": True}
            await db.commit()
    await worker.tick()
    phone.rows[0].update(status="succeeded", result={})
    await worker.tick()
    await worker.tick()
    async with async_session() as db:
        saved = await db.get(HermesPublishJob, jobs[0].id)
        assert saved.status == "submitted" and saved.error_code is None
    assert len(phone.created) == 1


@pytest.mark.asyncio
async def test_reconcile_old_evidence_conflict_only_polls_selected_original_job(client, publish_config):
    _, _, _, jobs = await schedule(client, count=2)
    phone = FakePhone()
    worker = HermesPublishWorker(async_session, phone)
    await worker.tick()
    phone.rows[0].update(status="succeeded", result={})
    async with async_session() as db:
        waiting = await db.get(HermesPublishJob, jobs[1].id)
        assert waiting.status == "waiting_device"
        waiting.retry_at = cst_now_naive() - timedelta(seconds=1)
        await db.commit()
    await worker.tick()
    assert len(phone.created) == 2
    async with async_session() as db:
        for item in jobs:
            saved = await db.get(HermesPublishJob, item.id)
            saved.status = "unknown"
            saved.error_code = "publish_evidence_conflict"
            saved.snapshot = {**saved.snapshot, "publish_proof_required": True}
        await db.commit()
    for row in phone.rows:
        row.update(status="succeeded", result={})

    async def forbidden(*_args, **_kwargs):
        raise AssertionError("Reconciliation must not create or cancel a remote task")

    phone.create = forbidden
    phone.cancel = forbidden
    await worker.poll(job_id=jobs[0].id)
    await worker.poll(job_id=jobs[0].id)
    async with async_session() as db:
        saved = await db.get(HermesPublishJob, jobs[0].id)
        untouched = await db.get(HermesPublishJob, jobs[1].id)
        assert saved.status == "submitted" and saved.error_code is None
        assert saved.remote_job_id == "remote-1"
        assert untouched.status == "unknown" and untouched.error_code == "publish_evidence_conflict"
        post = await db.get(HermesWorkflowPost, saved.post_id)
        assert post.publish_status == "submitted"
        assert await db.scalar(select(func.count()).select_from(HermesPublishAttempt)) == 2
    assert len(phone.created) == 2


@pytest.mark.asyncio
async def test_cancel_preparing_fences_late_worker_and_delete_keeps_evidence(client, publish_config):
    _, headers, run, jobs = await schedule(client)
    phone = FakePhone()
    worker = HermesPublishWorker(async_session, phone)
    claimed = await worker.claim()
    response = await client.post(f"/api/v1/hermes-workflows/publish-jobs/{jobs[0].id}/cancel", headers=headers)
    assert response.json()["data"]["status"] == "cancelled"
    await worker.dispatch(*claimed)
    assert not phone.created
    assert (await client.delete(f"/api/v1/hermes-workflows/runs/{run['id']}", headers=headers)).status_code == 409


@pytest.mark.asyncio
async def test_cancellation_during_create_keeps_returned_remote_id(client, publish_config):
    _, headers, _, jobs = await schedule(client)
    phone = FakePhone()
    original = phone.create
    async def create(target, snapshot, images):
        cancelled = await client.post(f"/api/v1/hermes-workflows/publish-jobs/{jobs[0].id}/cancel", headers=headers)
        assert cancelled.json()["data"]["status"] == "cancel_requested"
        return await original(target, snapshot, images)
    phone.create = create
    await HermesPublishWorker(async_session, phone).tick()
    async with async_session() as db:
        job = await db.get(HermesPublishJob, jobs[0].id)
        assert job.status == "cancel_requested" and job.remote_job_id == "remote-1"


@pytest.mark.asyncio
async def test_api_rejects_changed_account_and_missing_revision_or_identity(client, publish_config):
    _, env_id, headers, run = await approved(client)
    item = plan(run["posts"][0], env_id)
    assert (await client.post("/api/v1/hermes-workflows/publish-plan", headers=headers, json={"items": [{**item, "expected_version": None}]})).status_code == 409
    async with async_session() as db:
        (await db.get(XHSEnvironment, env_id)).xhs_account_id = None
        await db.commit()
    assert (await client.post("/api/v1/hermes-workflows/publish-plan", headers=headers, json={"items": [item]})).status_code == 409


@pytest.mark.asyncio
async def test_http_login_refresh_precise_payload_and_no_post_replay(publish_config):
    requests = []
    def handler(request):
        requests.append(request)
        if request.url.path.endswith("auth/login"):
            return httpx.Response(200, json={"session": {"token": "synthetic-token", "expiresAt": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()}})
        if request.url.path.endswith("devices"):
            if sum(r.url.path.endswith("devices") for r in requests) == 1:
                return httpx.Response(401)
            return httpx.Response(200, json={"devices": FakePhone().device_rows})
        raise httpx.ReadTimeout("synthetic lost create response")
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        publisher = PhoneCloudPublisher(http)
        target = publisher.target(await publisher.devices(), "stable-42")
        with pytest.raises(PublishError) as exc:
            await publisher.create(target, {"title": "审核标题", "content": "审核正文"}, ["data:image/png;base64,eA=="])
        assert exc.value.uncertain
    assert sum(r.url.path.endswith("auth/login") for r in requests) == 2
    assert sum(r.method == "POST" and r.url.path.endswith("xhs-publish-tasks") for r in requests) == 1
    import json
    assert json.loads(requests[-1].content)["xhsAppSlot"] == "app2"
    assert "test-only-password" not in str(exc.value)


@pytest.mark.asyncio
@pytest.mark.parametrize("code,retryable", [
    ("publish_account_identity_mismatch", False), ("idempotency_conflict", False),
    ("device_busy", True), ("account_slot_busy", True), ("xhs_device_not_available", True),
])
async def test_create_conflicts_only_retry_known_nonaccepted_busy_errors(publish_config, code, retryable):
    calls = []
    def handler(request):
        calls.append(request)
        return httpx.Response(409, json={"error": code})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        publisher = PhoneCloudPublisher(http)
        publisher.token = "fake-token"
        publisher.expires_at = datetime.now(timezone.utc) + timedelta(hours=1)
        with pytest.raises(PublishError) as exc:
            await publisher.create({"device_id": "fake", "app_slot": "app1", "expected_xhs_id": "123"},
                                   {"title": "标题", "content": "正文"}, ["fake-image"])
        assert exc.value.retryable is retryable
        assert not exc.value.uncertain
        assert len(calls) == 1


def test_remote_publish_proof_is_strict_and_strips_sensitive_fields():
    proof = publish_evidence({"result": {"runner": {"publishEvidence": {
        "version": 1, "titleExact": "true", "contentExact": True, "confirmation": {},
        "titleSha256": "a" * 64, "token": "fake-secret", "content": "private-body"}}}})
    assert proof["titleExact"] is False and proof["contentExact"] is True
    assert proof["confirmation"] == "none" and proof["titleSha256"] == "a" * 64
    assert "token" not in proof and "content" not in proof
    assert publish_evidence({"result": {"publishEvidence": {"version": True}}}) == {}


@pytest.mark.asyncio
@pytest.mark.parametrize("conflict", [None, "titleExact", "accountIdentityVerified", "contentSha256", "accountSha256"])
async def test_optional_proof_is_audited_but_does_not_override_cloud_success(client, publish_config, conflict):
    _, headers, _, jobs = await schedule(client)
    phone = FakePhone()
    worker = HermesPublishWorker(async_session, phone)
    await worker.tick()
    async with async_session() as db:
        saved = await db.get(HermesPublishJob, jobs[0].id)
        proof = {"version": 1, "accountIdentityVerified": True, "titleExact": True,
                 "contentExact": True, "clickedFinalPublish": True, "imageSelectionVerified": False,
                 "accountSha256": hashlib.sha256(saved.snapshot["xhs_id"].encode("utf-8")).hexdigest(),
                 "confirmation": "success_text"}
        for key in ("title", "content"):
            proof[f"{key}Sha256"] = hashlib.sha256(saved.snapshot[key].encode("utf-8")).hexdigest()
    if conflict:
        proof[conflict] = "f" * 64 if conflict.endswith("Sha256") else False
    phone.rows[0].update(status="succeeded", result={"runner": {"publishEvidence": {**proof, "token": "fake-secret"}}})
    await worker.tick()
    await worker.tick()
    async with async_session() as db:
        saved = await db.get(HermesPublishJob, jobs[0].id)
        attempt = await db.scalar(select(HermesPublishAttempt))
        assert saved.status == "submitted" and saved.error_code is None
        assert attempt.evidence["remote_publish_proof"] == proof
        assert attempt.evidence["images"]
    assert len(phone.created) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("base,allowlist,allowed", [
    ("https://phone.example.test", "", True),
    ("http://phone.example.test", "", False),
    ("http://phone.example.test/", "http://phone.example.test/", True),
    ("http://phone.example.test", "http://another.example.test", False),
    ("http://phone.example.test:8080", "http://phone.example.test", False),
    ("http://phone.example.test/path", "http://phone.example.test/path", False),
    ("http://user:password@phone.example.test", "http://user:password@phone.example.test", False),
    ("http://phone.example.test?query=1", "http://phone.example.test?query=1", False),
    ("http://phone.example.test#fragment", "http://phone.example.test#fragment", False),
])
async def test_plain_http_requires_explicit_exact_origin(monkeypatch, base, allowlist, allowed):
    monkeypatch.setattr(settings, "phone_cloud_publish_base_url", base)
    monkeypatch.setattr(settings, "phone_cloud_publish_http_origins", allowlist)
    requests = []
    def handler(request):
        requests.append(request)
        return httpx.Response(200, json={"devices": []})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        publisher = PhoneCloudPublisher(http)
        if allowed:
            await publisher._send("GET", "/api/v1/user/devices")
        else:
            with pytest.raises(PublishError) as exc:
                await publisher._send("GET", "/api/v1/user/devices")
            assert exc.value.code == "publish_configuration_invalid"
    assert len(requests) == int(allowed)


def test_no_nickname_fallback_and_ambiguous_binding_is_rejected():
    rows = FakePhone().device_rows
    with pytest.raises(PublishError):
        PhoneCloudPublisher.target(rows, "nickname")
    with pytest.raises(PublishError) as exc:
        PhoneCloudPublisher.target(rows * 2, "stable-42")
    assert exc.value.code == "publish_account_ambiguous"


@pytest.mark.asyncio
async def test_assets_are_private_immutable_and_no_traversal_or_untrusted_remote_fetch(monkeypatch, tmp_path):
    uploads = tmp_path / "uploads"
    uploads.mkdir()
    (uploads / "car.png").write_bytes(image_bytes())
    monkeypatch.setattr(settings, "storage_path", str(uploads))
    monkeypatch.setattr(settings, "phone_cloud_publish_snapshot_path", str(tmp_path / "private"))
    monkeypatch.setattr(settings, "phone_cloud_publish_image_origins", "")
    assets = PublishAssets()
    images = await assets.freeze(["/uploads/car.png"])
    (uploads / "car.png").write_bytes(b"original-replaced")
    assert (await assets.data_urls(images))[0].startswith("data:image/png;base64,")
    for url in ["/uploads/%2e%2e/secret.png", "https://untrusted.example.test/a.png", "http://127.0.0.1/private"]:
        with pytest.raises(PublishError):
            await assets.freeze([url])
    (tmp_path / "private" / images[0]["sha256"]).write_bytes(b"tampered")
    with pytest.raises(PublishError) as exc:
        await assets.data_urls(images)
    assert exc.value.code == "publish_image_changed"


@pytest.mark.parametrize("data", [b"not-an-image", b"x" * 3_000_001])
def test_invalid_images_are_never_silently_dropped(data):
    with pytest.raises(PublishError):
        PublishAssets.mime(data)


@pytest.mark.asyncio
@pytest.mark.parametrize('base', ['http://127.0.0.1:8000', 'https://studio.example.test/app'])
async def test_configured_local_upload_origin_is_read_without_http(monkeypatch, tmp_path, base):
    uploads = tmp_path / 'uploads'
    uploads.mkdir()
    original = image_bytes()
    (uploads / 'car.png').write_bytes(original)
    monkeypatch.setattr(settings, 'storage_type', 'local')
    monkeypatch.setattr(settings, 'storage_path', str(uploads))
    monkeypatch.setattr(settings, 'uploads_public_base_url', base)
    monkeypatch.setattr(settings, 'phone_cloud_publish_image_origins', '')
    monkeypatch.setattr(settings, 'phone_cloud_publish_snapshot_path', str(tmp_path / 'private'))
    monkeypatch.setattr(httpx, 'AsyncClient', lambda *args, **kwargs: pytest.fail('own uploads must not use HTTP'))
    assets = PublishAssets()
    assert await assets.fetch(base + '/uploads/car.png') == original
    images = await assets.freeze([base + '/uploads/car.png'])
    assert (await assets.data_urls(images))[0].startswith('data:image/png;base64,')


@pytest.mark.asyncio
@pytest.mark.parametrize('url', [
    'http://127.0.0.1:8001/uploads/car.png',
    'http://127.0.0.1:8000.evil.test/uploads/car.png',
    'http://user:password@127.0.0.1:8000/uploads/car.png',
    'http://127.0.0.1:8000/private/car.png',
    'http://127.0.0.1:8000/uploads/%2e%2e/secret.png',
    'http://127.0.0.1:8000/uploads/link.png',
])
async def test_own_upload_mapping_cannot_authorize_other_sources(monkeypatch, tmp_path, url):
    uploads = tmp_path / 'uploads'
    uploads.mkdir()
    (tmp_path / 'secret.png').write_bytes(image_bytes())
    (uploads / 'link.png').symlink_to(tmp_path / 'secret.png')
    monkeypatch.setattr(settings, 'storage_type', 'local')
    monkeypatch.setattr(settings, 'storage_path', str(uploads))
    monkeypatch.setattr(settings, 'uploads_public_base_url', 'http://127.0.0.1:8000')
    monkeypatch.setattr(settings, 'phone_cloud_publish_image_origins', '')
    monkeypatch.setattr(httpx, 'AsyncClient', lambda *args, **kwargs: pytest.fail('denied source must not be fetched'))
    with pytest.raises(PublishError) as exc:
        await PublishAssets().fetch(url)
    assert exc.value.code in {'publish_image_origin_denied', 'publish_image_missing'}


@pytest.mark.asyncio
async def test_save_plan_with_own_absolute_image_freezes_real_file(client, monkeypatch, tmp_path):
    uploads = tmp_path / 'uploads'
    uploads.mkdir()
    (uploads / 'car.png').write_bytes(image_bytes())
    monkeypatch.setattr(settings, 'storage_type', 'local')
    monkeypatch.setattr(settings, 'storage_path', str(uploads))
    monkeypatch.setattr(settings, 'uploads_public_base_url', 'http://127.0.0.1:8000')
    monkeypatch.setattr(settings, 'phone_cloud_publish_image_origins', '')
    monkeypatch.setattr(settings, 'phone_cloud_publish_snapshot_path', str(tmp_path / 'private'))
    user_id, env_id, headers, run = await approved(client)
    async with async_session() as db:
        post = await db.get(HermesWorkflowPost, run['posts'][0]['id'])
        post.image_url = 'http://127.0.0.1:8000/uploads/car.png'
        await db.commit()
    run = (await client.get(f"/api/v1/hermes-workflows/runs/{run['id']}", headers=headers)).json()['data']
    response = await client.post('/api/v1/hermes-workflows/publish-plan', headers=headers,
                                json={'items': [plan(run['posts'][0], env_id)]})
    assert response.status_code == 200, response.text
    async with async_session() as db:
        job = (await db.scalars(select(HermesPublishJob))).one()
        assert job.status == 'scheduled' and job.remote_job_id is None
        assert job.snapshot['images'][0]['bytes'] == len(image_bytes())
        assert (tmp_path / 'private' / job.snapshot['images'][0]['sha256']).read_bytes() == image_bytes()
        assert await db.scalar(select(func.count()).select_from(HermesPublishAttempt)) == 0


@pytest.mark.parametrize("alpha", [0, 150, 255])
def test_large_png_is_prepared_losslessly_with_original_digest(alpha):
    import hashlib
    # Uncompressed source crosses the limit; the repeating pixels compress
    # readily, so this tests real encoding rather than mocking the converter.
    source = Image.new("RGBA", (1100, 800), (40, 80, 120, alpha))
    output = io.BytesIO()
    source.save(output, format="PNG", compress_level=0)
    original = output.getvalue()
    assert 3_000_000 < len(original) < 25_000_000
    prepared, provenance = PublishAssets.prepare(original)
    assert len(prepared) <= 3_000_000
    assert PublishAssets.mime(prepared) == "image/webp"
    decoded = Image.open(io.BytesIO(prepared))
    assert decoded.size == source.size and decoded.convert("RGBA").tobytes() == source.tobytes()
    assert provenance == {"source_sha256": hashlib.sha256(original).hexdigest(),
                          "source_bytes": len(original), "preparation": "lossless_png_to_webp"}


def test_small_images_are_not_reencoded():
    original = image_bytes()
    assert PublishAssets.prepare(original) == (original, {})


def test_incompressible_png_is_rejected_without_lossy_fallback():
    import random
    source = Image.frombytes("RGB", (1100, 1000), random.Random(102).randbytes(3_300_000))
    output = io.BytesIO()
    source.save(output, format="PNG", compress_level=0)
    with pytest.raises(PublishError) as exc:
        PublishAssets.prepare(output.getvalue())
    assert exc.value.code == "publish_image_too_large"


@pytest.mark.asyncio
async def test_large_png_snapshot_preserves_provenance_and_wire_format(monkeypatch, tmp_path):
    uploads = tmp_path / "uploads"
    uploads.mkdir()
    source = Image.new("RGB", (1200, 900), "blue")
    source.save(uploads / "large.png", format="PNG", compress_level=0)
    monkeypatch.setattr(settings, "storage_path", str(uploads))
    monkeypatch.setattr(settings, "phone_cloud_publish_snapshot_path", str(tmp_path / "private"))
    assets = PublishAssets()
    images = await assets.freeze(["/uploads/large.png"])
    assert images[0]["source_bytes"] > 3_000_000
    assert images[0]["bytes"] < 3_000_000
    assert images[0]["preparation"] == "lossless_png_to_webp"
    assert (await assets.data_urls(images))[0].startswith("data:image/webp;base64,")
    assert (uploads / "large.png").stat().st_size == images[0]["source_bytes"]


@pytest.mark.parametrize("data", [b"x" * 3_000_001, b"x" * 25_000_001])
def test_large_invalid_or_oversized_inputs_are_rejected(data):
    with pytest.raises(PublishError):
        PublishAssets.prepare(data)


def test_lossless_preparation_bounds_decoded_pixels(monkeypatch):
    import app.adapters.phone_cloud_publish as adapter
    monkeypatch.setattr(adapter, "MAX_LOSSLESS_IMAGE_PIXELS", 800_000)
    source = Image.new("RGBA", (1100, 800), "blue")
    output = io.BytesIO()
    source.save(output, format="PNG", compress_level=0)
    assert 3_000_000 < len(output.getvalue()) < 25_000_000
    with pytest.raises(PublishError) as exc:
        PublishAssets.prepare(output.getvalue())
    assert exc.value.code == "publish_image_too_large"


@pytest.mark.asyncio
async def test_concurrent_image_snapshots_are_atomic(publish_config):
    assets = PublishAssets()
    copies = await asyncio.gather(*(assets.freeze(["/uploads/test.png"]) for _ in range(8)))
    assert all(copy == copies[0] for copy in copies)
    assert len(list(assets.root().iterdir())) == 1
    assert (await assets.data_urls(copies[0]))[0].startswith("data:image/png;base64,")


def test_publish_migration_postgres_ddl_is_additive_and_bounded():
    import importlib
    import re
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    migration = importlib.import_module("app.alembic.versions.d5a8c2e7f901_cloud_phone_publish_jobs")
    output = io.StringIO()
    context = MigrationContext.configure(dialect_name="postgresql", opts={"as_sql": True, "output_buffer": output})
    with Operations.context(context):
        migration.upgrade()
        migration.downgrade()
    sql = output.getvalue()
    assert "CREATE TABLE hermes_publish_jobs" in sql
    assert "CREATE TABLE hermes_publish_attempts" in sql
    assert "ALTER TABLE hermes_workflow_posts" not in sql
    assert "INSERT INTO" not in sql
    assert all(len(name.encode()) <= 63 for name in re.findall(r"(?:CONSTRAINT|INDEX) (\w+)", sql))
