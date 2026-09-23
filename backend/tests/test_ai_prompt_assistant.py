from __future__ import annotations

import base64

import pytest

from app.config import settings
from app.models.user import User
from app.schemas.ai_image import PromptReverseRequest
from app.services.ai_prompt_assistant_service import (
    AIPromptAssistantService,
    MODIFY_SYSTEM_PROMPT,
    POLISH_SYSTEM_PROMPT,
    PromptAssistantConfigurationError,
    REVERSE_SYSTEM_PROMPT,
)
from tests.conftest import make_auth_headers, session_factory


class _FakeResponse:
    def __init__(self, content: str):
        self.content = content

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return {"choices": [{"message": {"content": self.content}}]}


class _FakeClient:
    requests: list[dict] = []
    response_content = "result prompt"

    def __init__(self, *args, **kwargs):
        del args, kwargs

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    async def post(self, url: str, **kwargs):
        self.requests.append({"url": url, **kwargs})
        return _FakeResponse(self.response_content)


@pytest.fixture(autouse=True)
def _configure_prompt_assistant(monkeypatch):
    _FakeClient.requests.clear()
    monkeypatch.setattr(settings, "ai_prompt_assistant_api_base_url", "https://prompt.example/v1")
    monkeypatch.setattr(settings, "ai_prompt_assistant_api_key", "test-key")
    monkeypatch.setattr(settings, "ai_prompt_assistant_model", "vision-test")
    monkeypatch.setattr("app.services.ai_prompt_assistant_service.httpx.AsyncClient", _FakeClient)


@pytest.mark.asyncio
async def test_reverse_prompt_uses_multimodal_contract():
    image_data = "data:image/png;base64," + base64.b64encode(b"small image").decode()
    result = await AIPromptAssistantService().reverse_image(image_data)

    assert result == "result prompt"
    assert _FakeClient.requests[0]["url"] == "https://prompt.example/v1/chat/completions"
    payload = _FakeClient.requests[0]["json"]
    assert payload["model"] == "vision-test"
    assert payload["messages"][0]["content"] == REVERSE_SYSTEM_PROMPT
    assert payload["messages"][1]["content"][1]["image_url"]["url"] == image_data
    assert payload["messages"][1]["content"][1]["image_url"]["detail"] == "high"
    assert all(label in REVERSE_SYSTEM_PROMPT for label in ("逐字内容", "归一化坐标", "画布比例", "重建原图"))
    for heading in ("画布与类型", "构图与裁切", "主体与姿势", "背景与空间", "光影与材质", "文字与版式", "硬性约束"):
        assert f"【{heading}】" in REVERSE_SYSTEM_PROMPT


@pytest.mark.asyncio
async def test_modify_prompt_preserves_current_prompt_and_instruction_boundaries():
    await AIPromptAssistantService().modify_prompt("白色汽车，价格 10 万", "只把背景改成雨夜")

    payload = _FakeClient.requests[0]["json"]
    assert payload["model"] == "vision-test"
    assert payload["messages"][0]["content"] == MODIFY_SYSTEM_PROMPT
    assert payload["messages"][1]["content"] == (
        "CURRENT PROMPT:\n白色汽车，价格 10 万\n\nEDIT INSTRUCTION:\n只把背景改成雨夜"
    )
    assert "Change only content required" in MODIFY_SYSTEM_PROMPT


@pytest.mark.asyncio
async def test_prompt_assistant_never_falls_back_to_duckcoding_or_tagging(monkeypatch):
    monkeypatch.setattr(settings, "ai_prompt_assistant_api_base_url", "")
    monkeypatch.setattr(settings, "ai_prompt_assistant_api_key", "")
    monkeypatch.setattr(settings, "xhs_content_tagging_api_base_url", "https://tagging.example/v1")
    monkeypatch.setattr(settings, "xhs_content_tagging_api_key", "tagging-key")
    monkeypatch.setattr(settings, "duckcoding_gpt_image2_api_url", "https://api.duckcoding.ai/v1")
    monkeypatch.setattr(settings, "duckcoding_gpt_image2_api_key", "duckcoding-key")

    with pytest.raises(PromptAssistantConfigurationError, match="内部模型"):
        await AIPromptAssistantService().modify_prompt("原提示词", "修改要求")

    assert _FakeClient.requests == []


@pytest.mark.asyncio
async def test_polish_prompt_uses_fixed_five_section_contract():
    await AIPromptAssistantService().polish_prompt("白色 SUV 停在雨夜街道")

    payload = _FakeClient.requests[0]["json"]
    assert payload["messages"][0]["content"] == POLISH_SYSTEM_PROMPT
    for heading in ("主体与场景", "构图与镜头", "光影与氛围", "材质与细节", "约束条件"):
        assert heading in POLISH_SYSTEM_PROMPT


def test_reverse_prompt_rejects_unsupported_or_invalid_image_data():
    valid = "data:image/webp;base64," + base64.b64encode(b"webp bytes").decode()
    assert PromptReverseRequest(image_data=valid).image_data == valid

    with pytest.raises(ValueError, match="JPEG、PNG 或 WebP"):
        PromptReverseRequest(image_data="data:image/gif;base64,R0lGODlhAQABAIAAAAUEBA==")
    with pytest.raises(ValueError, match="图片数据无效"):
        PromptReverseRequest(image_data="data:image/png;base64," + "!" * 40)


@pytest.mark.asyncio
async def test_prompt_tool_routes_are_authenticated_and_return_unwrapped_contracts(client, monkeypatch):
    image_data = "data:image/png;base64," + base64.b64encode(b"small image").decode()
    unauthenticated = await client.post(
        "/api/v1/ai-image/prompt-tools/polish",
        json={"input": "雨夜汽车"},
    )
    assert unauthenticated.status_code in {401, 403}

    async with session_factory() as db:
        db.add(User(id=912, username="prompt_helper", email="prompt-helper@example.com", hashed_password="x"))
        await db.commit()
    headers = make_auth_headers(912)

    async def fake_polish(self, current):
        return f"polished:{current}"

    async def fake_modify(self, current, instruction):
        return f"modified:{current}:{instruction}"

    async def fake_reverse(self, current_image_data):
        assert current_image_data == image_data
        return "reversed:image"

    monkeypatch.setattr(AIPromptAssistantService, "polish_prompt", fake_polish)
    monkeypatch.setattr(AIPromptAssistantService, "modify_prompt", fake_modify)
    monkeypatch.setattr(AIPromptAssistantService, "reverse_image", fake_reverse)

    polish = await client.post(
        "/api/v1/ai-image/prompt-tools/polish",
        json={"input": "雨夜汽车"},
        headers=headers,
    )
    modify = await client.post(
        "/api/v1/ai-image/prompt-tools/modify",
        json={"input": "雨夜汽车", "instruction": "改成红车"},
        headers=headers,
    )
    reverse = await client.post(
        "/api/v1/ai-image/prompt-tools/reverse",
        json={"image_data": image_data},
        headers=headers,
    )

    assert polish.status_code == modify.status_code == reverse.status_code == 200
    assert polish.json()["data"]["prompt"] == "polished:雨夜汽车"
    assert modify.json()["data"]["prompt"] == "modified:雨夜汽车:改成红车"
    assert reverse.json()["data"]["prompt"] == "reversed:image"
