from __future__ import annotations

from copy import deepcopy
from typing import Any


ADAPTATION_CONTRACT_VERSION = "hermes-adaptation-v4"
DEFAULT_ADAPTATION_LEVEL = "replica"

_PROFILES: dict[str, dict[str, Any]] = {
    "replica": {
        "label": "精准复刻",
        "short_label": "复刻",
        "description": "最大程度保留母文与母图，只替换必要信息",
        "copy": "保留标题句式、段落与行序、语气、表情、标点和转化位置，只替换必要事实槽。",
        "image": "保留构图、镜头、车辆占比、文字层级、配色和装饰，只轻改一个场景维度。",
    },
    "light": {
        "label": "轻度微改",
        "short_label": "轻改",
        "description": "结构不变，改写表达并调整少量视觉元素",
        "copy": "保留段落角色、信息顺序和转化路径，可改写标题钩子、措辞、节奏、表情和标点。",
        "image": "保留构图与信息层级，明确改变两个视觉维度，且不能只做近似色换色。",
    },
    "interpretive": {
        "label": "灵感改编",
        "short_label": "改编",
        "description": "保留事实逻辑，切换全新版式并重新创作",
        "copy": "只保留选题逻辑、事实优先级和转化目的，选择一个鲜明切口，以短段落和自然口吻重新创作。",
        "image": "只保留车型、事实与信息优先级，切换全新版式原型并重做车辆裁切、标题方向、页面网格和信息载体。",
    },
}


def normalize_adaptation_level(value: str | None) -> str:
    normalized = str(value or "").strip().lower()
    return normalized if normalized in _PROFILES else DEFAULT_ADAPTATION_LEVEL


def adaptation_contract(value: str | None) -> dict[str, Any]:
    level = normalize_adaptation_level(value)
    return {
        "version": ADAPTATION_CONTRACT_VERSION,
        "level": level,
        **deepcopy(_PROFILES[level]),
        "hard_guard": "车型、品牌、年款、配置、政策事实、金额、适用条件、禁用词、图片文字与OCR校验不因档位放宽。",
        "source_rule": "每篇只使用代码指定的一篇母文与一张母图，不换源、不拼接、不融合。",
    }
