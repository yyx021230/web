"""Browser URL adapters must not mutate generated content or stored provenance."""
from copy import deepcopy

import pytest

from app.models.hermes_workflow import HermesWorkflowPost
from app.services.hermes_workflow_service import browser_image_url, post_version, serialize_post


@pytest.mark.parametrize("value, expected", [
    ("http://backend:8000/uploads/ai-images/result.png", "/uploads/ai-images/result.png"),
    ("http://hermes-api:8000/uploads/ai-images/result.png", "/uploads/ai-images/result.png"),
    ("http://backend:8000/uploads/原图.png?v=2#full", "/uploads/原图.png?v=2#full"),
    (None, None),
    ("", ""),
    ("/uploads/ai-images/result.png", "/uploads/ai-images/result.png"),
    ("https://cdn.example.com/uploads/result.png", "https://cdn.example.com/uploads/result.png"),
    ("http://47.98.127.132:18080/uploads/result.png", "http://47.98.127.132:18080/uploads/result.png"),
    ("http://backend.example.com:8000/uploads/result.png", "http://backend.example.com:8000/uploads/result.png"),
    ("http://backend:8000/api/v1/auth/me", "http://backend:8000/api/v1/auth/me"),
    ("http://backend:8001/uploads/result.png", "http://backend:8001/uploads/result.png"),
    ("http://backend:invalid/uploads/result.png", "http://backend:invalid/uploads/result.png"),
    ("http://[invalid/uploads/result.png", "http://[invalid/uploads/result.png"),
    ("http://user:secret@backend:8000/uploads/result.png", "http://user:secret@backend:8000/uploads/result.png"),
])
def test_only_known_docker_storage_origins_are_remapped(value, expected):
    assert browser_image_url(value) == expected


def test_serialization_remaps_both_images_without_mutating_content_provenance_or_version():
    source = {
        "selected_prompt_image": "http://backend:8000/uploads/ai-images/mother.png",
        "vehicle_image": {"url": "https://cdn.example.com/car.png"},
        "adapted_prompt": "原始提示词保持不变：http://backend:8000/uploads/reference.png",
        "image_task_id": "30403",
        "revision": 2,
    }
    original = deepcopy(source)
    post = HermesWorkflowPost(
        id=1, run_id=1, environment_id=42, owner_user_id=3, slot=1,
        account_name="云先派懂车社", vehicle_model="零跑A05",
        title="保留标题🚗", content="保留全文\n#零跑A05[话题]#",
        image_url="http://backend:8000/uploads/ai-images/result.png",
        hard_pass=True, status="review_pending", publish_status="not_requested",
        source_detail=source,
    )
    version = post_version(post)
    payload = serialize_post(post)
    assert payload["image_url"] == "/uploads/ai-images/result.png"
    assert payload["source_detail"]["selected_prompt_image"] == "/uploads/ai-images/mother.png"
    assert payload["title"] == post.title and payload["content"] == post.content
    assert payload["version"] == version == post_version(post)
    assert payload["source_detail"]["vehicle_image"] == original["vehicle_image"]
    assert payload["source_detail"]["adapted_prompt"] == original["adapted_prompt"]
    assert post.image_url == "http://backend:8000/uploads/ai-images/result.png"
    assert post.source_detail == source == original
    assert payload["source_detail"] is not post.source_detail


def test_missing_and_external_mother_previews_are_unchanged():
    for source in (None, {}, {"selected_prompt_image": None},
                   {"selected_prompt_image": "https://cdn.example.com/mother.png"}):
        post = HermesWorkflowPost(source_detail=source)
        payload = serialize_post(post)
        assert payload["source_detail"] == (source or {})
        assert payload["image_url"] is None

