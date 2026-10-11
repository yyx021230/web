"""Offline acceptance checks; all phone publishing uses in-memory doubles."""

from __future__ import annotations

import base64
import json
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from sqlalchemy import select

from app.adapters.phone_cloud_publish import PhoneCloudPublisher
from app.config import settings
from app.db.session import async_session
from app.models.hermes_publish import HermesPublishAttempt, HermesPublishJob
from app.models.hermes_workflow import HermesWorkflowPost
from app.models.user_xhs_env import UserXHSEnvironment
from app.models.xhs_environment import XHSEnvironment
from app.services.hermes_publish_service import HermesPublishWorker
from app.utils.timezone import cst_now_naive
from tests.conftest import make_auth_headers
from tests.test_cloud_phone_publish import FakePhone, image_bytes, plan
from tests.test_cloud_phone_publish import publish_config  # noqa: F401
from tests.test_hermes_workflows import prepared_posts, seed_owner


@pytest.mark.asyncio
@pytest.mark.usefixtures("publish_config")
async def test_ten_account_batch_preserves_reviewed_content_and_never_replays(client, monkeypatch):
    owner_id, first_env_id = await seed_owner()
    headers = make_auth_headers(owner_id)
    env_ids = [first_env_id]
    async with async_session() as db:
        first = await db.get(XHSEnvironment, first_env_id)
        first.xhs_account_id = "stable-0"
        for index in range(1, 10):
            env = XHSEnvironment(shop_id=f"audit-account-{index}", account_name=f"Account {index}",
                                 status="active", department="xhs", xhs_account_id=f"stable-{index}")
            db.add(env)
            await db.flush()
            db.add(UserXHSEnvironment(user_id=owner_id, environment_id=env.id))
            env_ids.append(env.id)
        await db.commit()
    monkeypatch.setattr(settings, "phone_cloud_publish_verified_xhs_ids", ",".join(f"stable-{i}" for i in range(10)))

    phone = FakePhone()
    phone.device_rows = []
    expected = {}
    items = []
    for index, env_id in enumerate(env_ids):
        run = await prepared_posts(client, headers, env_id)
        post = run["posts"][0]
        title = f"Daily car guide {index}"
        content = f"City driving checklist {index}\n\nSpace and parking. \U0001f697\n#Cars"
        edited = await client.patch(f"/api/v1/hermes-workflows/posts/{post['id']}", headers=headers,
                                    json={"title": title, "content": content, "comment": "Editorial revision",
                                          "expected_version": post["version"]})
        assert edited.status_code == 200, edited.text
        reviewed = await client.post(f"/api/v1/hermes-workflows/posts/{post['id']}/review", headers=headers,
                                     json={"action": "approve", "expected_version": edited.json()["data"]["version"]})
        assert reviewed.status_code == 200, reviewed.text
        post = (await client.get(f"/api/v1/hermes-workflows/runs/{run['id']}", headers=headers)).json()["data"]["posts"][0]
        items.append(plan(post, env_id))
        slot = "app2" if index % 2 else "app1"
        phone.device_rows.append({**FakePhone().device_rows[0], "deviceId": f"device-{index}",
                                  "xhsAccounts": [{"xhsId": f"stable-{index}", "appSlot": slot, "enabled": True}]})
        expected[f"stable-{index}"] = (title, content, f"device-{index}", slot)

    response = await client.post("/api/v1/hermes-workflows/publish-plan", headers=headers, json={"items": items})
    assert response.status_code == 200, response.text
    async with async_session() as db:
        for job in (await db.scalars(select(HermesPublishJob))).all():
            job.scheduled_at = cst_now_naive() - timedelta(seconds=1)
        await db.commit()

    await HermesPublishWorker(async_session, phone).tick()
    await HermesPublishWorker(async_session, phone).tick()
    assert len(phone.created) == 10
    assert {snapshot["xhs_id"] for _, snapshot, _ in phone.created} == set(expected)
    for target, snapshot, images in phone.created:
        title, content, device, slot = expected[snapshot["xhs_id"]]
        assert (snapshot["title"], snapshot["content"]) == (title, content)
        assert target == {"device_id": device, "app_slot": slot, "expected_xhs_id": snapshot["xhs_id"]}
        assert len(images) == 1
        assert base64.b64decode(images[0].split(",", 1)[1]) == image_bytes()

    phone.rows = [{**row, "status": "succeeded"} for row in phone.rows]
    await HermesPublishWorker(async_session, phone).tick()
    await HermesPublishWorker(async_session, phone).tick()
    assert len(phone.created) == 10
    async with async_session() as db:
        jobs = list((await db.scalars(select(HermesPublishJob))).all())
        attempts = list((await db.scalars(select(HermesPublishAttempt))).all())
        posts = list((await db.scalars(select(HermesWorkflowPost))).all())
        assert len(jobs) == len(attempts) == 10
        assert {job.status for job in jobs} == {"submitted"}
        assert len({attempt.remote_job_id for attempt in attempts}) == 10
        assert all(post.publish_status == "submitted" and post.published_at is None for post in posts)
    # Reload/save cannot turn an already submitted batch into ten new publishes.
    replay = await client.post("/api/v1/hermes-workflows/publish-plan", headers=headers, json={"items": items})
    assert replay.status_code == 409
    assert len(phone.created) == 10


@pytest.mark.asyncio
@pytest.mark.usefixtures("publish_config")
async def test_http_payload_preserves_normal_copy_unicode_and_images_verbatim():
    snapshot = {"title": "Daily car guide", "content": "A normal car guide.\n\n\U0001f697 #Cars\nKeep this ending."}
    image = "data:image/png;base64," + base64.b64encode(image_bytes()).decode("ascii")
    requests = []

    def handle(request):
        if request.url.path.endswith("/auth/login"):
            return httpx.Response(200, json={"session": {"token": "offline-token", "expiresAt":
                (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()}})
        assert request.url.path == "/api/v1/user/automation/xhs-publish-tasks"
        requests.append(json.loads(request.content))
        return httpx.Response(201, json={"task": {"jobId": "offline-job"}})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        publisher = PhoneCloudPublisher(client)
        assert await publisher.create({"device_id": "device-a", "app_slot": "app2", "expected_xhs_id": "stable-42"}, snapshot, [image]) == "offline-job"
    assert requests == [{"deviceId": "device-a", "xhsAppSlot": "app2", "expectedXhsId": "stable-42", **snapshot, "imageDataUrls": [image]}]
