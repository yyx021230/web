from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from app.adapters.ai_model.openai_image_tasks import (
    AsyncImageTaskError,
    generate_async_images,
    get_async_image_task_status,
)


def provider(**config):
    return SimpleNamespace(
        id=5,
        provider_kind="openai_images",
        endpoint_url="https://relay.test/v1",
        api_key="test-secret",
        provider_model="gpt-image-2",
        config={
            "api_mode": "sub2api_async",
            "async_poll_interval": 0.001,
            "async_max_polls": 3,
            **config,
        },
    )


@pytest.fixture
def transport(monkeypatch):
    original = httpx.AsyncClient
    calls = []
    handlers = []

    def handle(req):
        calls.append(req)
        result = handlers.pop(0)
        if isinstance(result, Exception):
            raise result
        return httpx.Response(result[0], json=result[1])

    monkeypatch.setattr(
        "app.adapters.ai_model.openai_image_tasks.httpx.AsyncClient",
        lambda **kw: original(transport=httpx.MockTransport(handle), **kw),
    )
    return calls, handlers


async def extract(data, seed):
    return [item["url"] for item in data.get("data", []) if item.get("url")]


async def generate(p, callback=None, **params):
    return await generate_async_images(
        p,
        "original prompt",
        params,
        request_model=p.provider_model,
        ref_sources=params.get("images_data", []),
        reference_loader=AsyncMock(return_value=("ref.png", b"png", "image/png")),
        image_extractor=extract,
        on_upstream_accepted=callback,
    )


@pytest.mark.asyncio
async def test_accept_is_persisted_before_poll_and_result_is_nested(transport):
    calls, steps = transport
    steps.extend(
        [
            (
                202,
                {
                    "id": "imgtask_one",
                    "status": "processing",
                    "poll_url": "https://evil.test/steal",
                },
            ),
            (200, {"id": "imgtask_one", "status": "processing"}),
            (
                200,
                {
                    "id": "imgtask_one",
                    "status": "completed",
                    "result": {"data": [{"url": "https://images.test/1.png"}]},
                },
            ),
        ]
    )

    async def accepted(details):
        if "submission_pending" in details:
            assert details["submission_pending"] is True and not calls
            return
        assert len(calls) == 1
        assert details["upstream_task_id"] == "imgtask_one"
        assert details["query_capability"] == "openai_images_async"

    result = await generate(provider(), accepted, width=1536, height=2048)
    assert result["status"] == "completed"
    assert result["image_urls"] == ["https://images.test/1.png"]
    assert [r.method for r in calls] == ["POST", "GET", "GET"]
    assert all(
        r.url.host == "relay.test"
        and r.headers["authorization"] == "Bearer test-secret"
        for r in calls
    )
    assert calls[0].url.path == "/v1/images/generations/async"


@pytest.mark.asyncio
async def test_reference_uses_multipart_edit_and_preserves_generation_settings(
    transport,
):
    calls, steps = transport
    steps.extend(
        [
            (202, {"task_id": "imgtask_edit"}),
            (
                200,
                {
                    "status": "completed",
                    "result": {"data": [{"url": "https://images.test/edit.png"}]},
                },
            ),
        ]
    )
    result = await generate(
        provider(send_size=True),
        images_data=["/uploads/ref.png"],
        width=1536,
        height=2048,
        quality="high",
    )
    assert result["status"] == "completed"
    assert calls[0].url.path == "/v1/images/edits/async"
    body = calls[0].read()
    assert (
        b"1536x2048" in body
        and b"high" in body
        and b"original prompt" in body
        and b'name="image"' in body
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "failure", [httpx.ReadTimeout("lost response"), httpx.WriteError("lost upload")]
)
async def test_uncertain_submit_never_reposts_or_falls_back(transport, failure):
    calls, steps = transport
    steps.append(failure)
    with pytest.raises(AsyncImageTaskError) as error:
        await generate(provider())
    assert error.value.result_unknown is True
    assert len(calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "failure",
    [httpx.ConnectTimeout("no connection"), httpx.ConnectError("no connection")],
)
async def test_unconnected_submit_is_known_not_accepted(transport, failure):
    calls, steps = transport
    steps.append(failure)
    with pytest.raises(AsyncImageTaskError) as error:
        await generate(provider())
    assert error.value.result_unknown is False and len(calls) == 1


@pytest.mark.asyncio
async def test_poll_network_and_503_recover_using_same_id(transport):
    calls, steps = transport
    steps.extend(
        [
            (202, {"id": "imgtask_resume"}),
            httpx.ReadTimeout("query timeout"),
            (503, {"error": "busy"}),
            (
                200,
                {
                    "status": "completed",
                    "result": {"data": [{"url": "https://images.test/resumed.png"}]},
                },
            ),
        ]
    )
    result = await generate(provider())
    assert result["status"] == "completed"
    assert sum(r.method == "POST" for r in calls) == 1
    assert {r.url.path for r in calls[1:]} == {"/v1/images/tasks/imgtask_resume"}


@pytest.mark.asyncio
async def test_poll_exhaustion_retains_accepted_task_and_does_not_resubmit(transport):
    calls, steps = transport
    steps.extend([(202, {"id": "imgtask_slow"}), (200, {"status": "processing"})])
    callback = AsyncMock()
    result = await generate(provider(async_max_polls=1), callback)
    assert result["status"] == "failed" and result["result_unknown"] is True
    assert result["task_id"] == "imgtask_slow" and callback.await_count == 2
    assert len(calls) == 2


@pytest.mark.asyncio
async def test_expired_or_foreign_task_never_becomes_permission_to_regenerate(
    transport,
):
    calls, steps = transport
    steps.append((404, {"error": {"message": "image task not found"}}))
    result = await get_async_image_task_status(
        provider(), "imgtask_missing", 1, extract
    )
    assert result["status"] == "unknown" and result["result_unknown"]
    assert [r.method for r in calls] == ["GET"]


@pytest.mark.asyncio
async def test_remote_failed_is_known_and_preserves_error_without_reposting(transport):
    calls, steps = transport
    steps.extend(
        [
            (202, {"id": "imgtask_failed"}),
            (
                200,
                {
                    "status": "failed",
                    "http_status": 400,
                    "error": {
                        "message": "unsupported size",
                        "type": "invalid_request_error",
                    },
                },
            ),
        ]
    )
    result = await generate(provider())
    assert result["status"] == "failed" and not result.get("result_unknown")
    assert result["error"] == "unsupported size" and len(calls) == 2


@pytest.mark.asyncio
async def test_accepted_id_persistence_failure_stops_without_duplicate_dispatch(
    transport,
):
    calls, steps = transport
    steps.append((202, {"id": "imgtask_saved_upstream"}))
    callback = AsyncMock(side_effect=RuntimeError("db unavailable"))
    with pytest.raises(AsyncImageTaskError) as error:
        await generate(provider(), callback)
    assert error.value.result_unknown is False and not calls


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "task_id",
    ["../secret", "imgtask_x?token=secret", "https://other.test/id", "a" * 161],
)
async def test_invalid_task_id_cannot_change_poll_origin_or_path(transport, task_id):
    calls, steps = transport
    with pytest.raises(ValueError):
        await get_async_image_task_status(provider(), task_id, 1, extract)
    assert not calls


@pytest.mark.asyncio
async def test_four_images_without_send_n_are_exactly_four_submissions(transport):
    calls, steps = transport
    for index in range(4):
        steps.extend(
            [
                (202, {"id": f"imgtask_{index}"}),
                (
                    200,
                    {
                        "status": "completed",
                        "result": {
                            "data": [{"url": f"https://images.test/{index}.png"}]
                        },
                    },
                ),
            ]
        )
    result = await generate(provider(), count=4)
    assert result["status"] == "completed" and len(result["image_urls"]) == 4
    assert sum(r.method == "POST" for r in calls) == 4


@pytest.mark.asyncio
async def test_four_images_with_send_n_are_one_batch(transport):
    import json

    calls, steps = transport
    steps.extend(
        [
            (202, {"id": "imgtask_batch"}),
            (
                200,
                {
                    "status": "completed",
                    "result": {
                        "data": [
                            {"url": f"https://images.test/{i}.png"} for i in range(4)
                        ]
                    },
                },
            ),
        ]
    )
    result = await generate(provider(send_n=True), count=4)
    assert result["status"] == "completed" and len(result["image_urls"]) == 4
    assert json.loads(calls[0].read())["n"] == 4 and len(calls) == 2


@pytest.mark.asyncio
async def test_partial_batch_is_retained_and_never_filled_with_duplicate_generation(
    transport,
):
    calls, steps = transport
    steps.extend(
        [
            (202, {"id": "imgtask_short"}),
            (
                200,
                {
                    "status": "completed",
                    "result": {"data": [{"url": "https://images.test/only.png"}]},
                },
            ),
        ]
    )
    result = await generate(provider(send_n=True), count=4)
    assert result["status"] == "failed" and result["image_urls"] == [
        "https://images.test/only.png"
    ]
    assert len(calls) == 2


@pytest.mark.asyncio
async def test_second_submit_timeout_preserves_first_success(transport):
    calls, steps = transport
    steps.extend(
        [
            (202, {"id": "imgtask_first"}),
            (
                200,
                {
                    "status": "completed",
                    "result": {"data": [{"url": "https://images.test/first.png"}]},
                },
            ),
            httpx.ReadTimeout("unknown second"),
        ]
    )
    result = await generate(provider(), count=2)
    assert result["status"] == "failed" and result["result_unknown"]
    assert result["image_urls"] == ["https://images.test/first.png"] and len(calls) == 3


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [401, 404, 422, 502])
async def test_rejected_async_endpoint_never_calls_sync_fallback(transport, status):
    calls, steps = transport
    steps.append((status, {"error": {"message": "async unavailable"}}))
    with pytest.raises(AsyncImageTaskError) as error:
        await generate(provider())
    assert error.value.result_unknown is (status >= 500)
    assert len(calls) == 1 and calls[0].url.path.endswith("/async")


@pytest.mark.asyncio
async def test_acceptance_persistence_failure_keeps_submission_unknown(transport):
    calls, steps = transport
    steps.append((202, {"id": "imgtask_unrecorded"}))

    async def callback(details):
        if "upstream_task_id" in details:
            raise RuntimeError("database unavailable")

    with pytest.raises(AsyncImageTaskError) as error:
        await generate(provider(), callback)
    assert error.value.result_unknown and len(calls) == 1


@pytest.mark.asyncio
async def test_cancel_before_second_image_prevents_further_paid_requests(transport):
    calls, steps = transport
    steps.extend(
        [
            (202, {"id": "imgtask_first"}),
            (200, {"status": "completed", "result": {"data": [{"url": "/one.png"}]}}),
        ]
    )

    async def callback(details):
        if details.get("submission_pending") and calls:
            raise RuntimeError("cancelled")

    result = await generate(provider(), callback, count=4)
    assert result["image_urls"] == ["/one.png"] and result["status"] == "failed"
    assert not result["result_unknown"] and sum(r.method == "POST" for r in calls) == 1


@pytest.mark.asyncio
async def test_reference_failure_preserves_previous_image(transport):
    calls, steps = transport
    steps.extend(
        [
            (202, {"id": "imgtask_one"}),
            (200, {"status": "completed", "result": {"data": [{"url": "/one.png"}]}}),
        ]
    )
    result = await generate_async_images(
        provider(),
        "prompt",
        {"count": 2},
        request_model="gpt-image-2",
        ref_sources=["first", "second"],
        reference_loader=AsyncMock(
            side_effect=[("ref.png", b"png", "image/png"), FileNotFoundError("missing")]
        ),
        image_extractor=extract,
    )
    assert (
        result["image_urls"] == ["/one.png"]
        and not result["result_unknown"]
        and len(calls) == 2
    )


@pytest.mark.asyncio
async def test_error_redacts_actual_credential_and_sensitive_url(transport):
    calls, steps = transport
    steps.append(
        (
            200,
            {
                "status": "failed",
                "error": {
                    "message": "key test-secret https://relay.test?token=private-value&ok=1"
                },
            },
        )
    )
    result = await get_async_image_task_status(provider(), "imgtask_safe", 1, extract)
    assert (
        "test-secret" not in result["error"] and "private-value" not in result["error"]
    )
