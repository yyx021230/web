from __future__ import annotations

from copy import deepcopy
import hashlib
from typing import Any


ADAPTATION_CONTRACT_VERSION = "hermes-adaptation-v4"
DEFAULT_ADAPTATION_LEVEL = "replica"

INTERPRETIVE_LAYOUTS: tuple[dict[str, str], ...] = (
    {
        "id": "kinetic_collage",
        "name": "动态剪贴拼贴",
        "brief": (
            "用一条强烈斜向动势贯穿画面；车辆做干净抠图并跨越色块边界，允许局部超出版心；"
            "巨大的车型字母作为背景图形被车辆遮挡，补充信息散落在角落标签中，不设底部横向信息条。"
        ),
    },
    {
        "id": "asymmetric_editorial",
        "name": "非对称杂志分栏",
        "brief": (
            "采用约35/65的不等宽杂志分栏；车型名沿窄栏竖排或旋转排版，车辆从宽栏边缘切入并跨栏；"
            "信息用编辑批注、页码与细线索引承载，不使用居中标题或上下三段式构图。"
        ),
    },
    {
        "id": "technical_dossier",
        "name": "产品技术档案",
        "brief": (
            "将画面设计成高端产品档案页：车辆采用偏心的大幅侧前视图，灯组与轮毂可用两个局部圆形放大窗；"
            "标题、参数与索引沿工程网格分布，使用编号、细线和坐标感，但不得虚构参数或做传统底部信息条。"
        ),
    },
    {
        "id": "paper_cutout",
        "name": "纸张剪贴实验",
        "brief": (
            "用撕纸边缘、半透明描图纸、胶带与印刷套色构成实体拼贴；车辆作为偏置剪影压住多层纸片，"
            "主标题像杂志封面题签一样错位叠压，信息写在小型贴纸或边注中，避免数字科技大屏套路。"
        ),
    },
    {
        "id": "spatial_installation",
        "name": "空间装置海报",
        "brief": (
            "把车型置于抽象建筑装置中，使用巨型立体字、悬浮薄片与大胆负空间形成前中后景；"
            "车辆偏离中轴并与立体文字发生遮挡关系，信息嵌入空间标牌，不使用平铺背景和页脚横条。"
        ),
    },
)

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
        "image": "只保留车型、事实与信息优先级，切换到全新版式原型并重做车辆裁切、标题方向、页面网格和信息载体。",
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


def copy_adaptation_instruction(value: str | None) -> str:
    level = normalize_adaptation_level(value)
    common_logic = (
        "无论档位如何，转化入口只能承接正文尚未公开的信息：如果正文已经列出完整配置报价，结尾不得再承诺发送同一份报价；"
        "城市只用于核对地方政策流程与适用条件，不得写成查询国补后价格的前置条件；"
        "不得使用‘评论、留言、回复、在下方’等方式引导用户报城市或车型。"
    )
    if level == "light":
        return (
            "本篇采用【轻度微改】：保留母文每个段落承担的角色、信息先后顺序、核心卖点顺序和留资/话题位置；"
            "必须改写标题钩子，并至少对三个正文句子改写句式、措辞或节奏；允许调整Emoji与标点。"
            "不能逐字照搬成精准复刻，也不得新增母文没有的信息维度。" + common_logic
        )
    if level == "interpretive":
        return (
            "本篇采用【灵感改编】：只保留母文的核心选题逻辑、事实优先级、说服链路和最终转化目的；"
            "先从决策提醒、避坑观察、场景代入、版本选择中确定一个单一切口，再重新创作标题、开场、段落节奏和收束；"
            "不要求保留原段落数量、行序、Emoji、句式或CTA原话。正文控制在260至480个字符，除最后话题行外使用5至8个短段落，"
            "每段只表达一个意思，长短句交替，至少有一处转折和一处直接与读者对话。"
            "最多选取4项有依据的关键事实；存在多版本价格时，最多举2个版本，不得逐版本列完整清单，不使用编号清单。"
            "开头直接进入具体场景或矛盾，不用‘最近准备……的朋友’‘可以先把……放进清单’等泛化起手式。"
            "成文要像真实运营写的小红书笔记，不要写成公告、参数报告、政策复述或购车说明书。"
            "不得沿用‘藏不住’‘还好发现了’‘直接让人破防’‘甩城市+车型’‘少套路多真诚’‘别被套路当冤大头’等母文套话，"
            "也不能按母文逐行做同义替换、换主题、倒置事实优先级或融合另一篇文案。" + common_logic
        )
    return (
        "本篇采用【精准复刻】：保留母文标题句式、段落顺序、行序、语气、Emoji、标点、留资位置和最后话题行；"
        "只替换旧品牌车型、过期时间、明确禁用词及与当前政策冲突的事实槽。" + common_logic
    )


def image_adaptation_instruction(value: str | None) -> str:
    level = normalize_adaptation_level(value)
    if level == "light":
        return (
            "本图采用【轻度微改】：完整保留母版构图、镜头、车辆占比、信息层级、文字位置和对齐；"
            "必须从主色、场景、材质、装饰、光线中选择两个不同维度做清晰但克制的变化，至少一个不是颜色变化；"
            "不能只把原主色换成相邻色。"
        )
    if level == "interpretive":
        return (
            "本图采用【灵感改编】：母图只提供创作起点，不再约束其海报骨架、文字位置、车辆位置或装饰形式；"
            "只保留目标车型、事实、信息优先级与车辆主体地位。必须切换到程序指定的全新版式原型，"
            "同时重做页面网格、车辆取景与裁切、标题方向和信息载体；主色不得沿用母版或相邻色。"
            "严禁继续使用‘顶部居中大标题＋中部完整车辆＋底部横向信息条’的原三段式结构。"
        )
    return (
        "本图采用【精准复刻】：母图是完整复刻蓝图，保留整体构图、镜头、车辆占比、字号层级、对齐、配色和装饰；"
        "场景只轻微改变一个维度。"
    )


def final_image_fidelity_instruction(value: str | None) -> str:
    level = normalize_adaptation_level(value)
    if level == "light":
        return "保留母版构图、镜头、文字位置、字号层级与对齐，完整落实计划中的两个不同视觉变化，不能退回近似色换色。"
    if level == "interpretive":
        return (
            "只保留目标车型、事实、信息优先级与车辆主体地位；必须严格执行计划指定的全新版式原型，"
            "改掉页面网格、车辆取景、标题方向和信息载体。严禁退回顶部居中标题、中间整车、底部横条的原三段式模板。"
        )
    return "只轻微改变母版场景，完整保留母版构图、镜头、文字位置、字号层级、对齐、颜色和装饰。"


_VISUAL_DIMENSIONS = {
    "palette", "scene", "material", "decoration", "lighting", "typography", "composition",
}


def visual_change_contract_errors(plan: dict[str, Any], value: str | None) -> list[str]:
    """Validate that freer levels describe concrete, independently auditable changes."""
    level = normalize_adaptation_level(value)
    changes = plan.get("visual_changes")
    if level == "replica" and changes is None:
        return []
    if not isinstance(changes, list):
        return ["缺少visual_changes视觉变化清单"]
    expected = (1, 1) if level == "replica" else (2, 2) if level == "light" else (5, 7)
    errors: list[str] = []
    if not expected[0] <= len(changes) <= expected[1]:
        errors.append(f"{level}档视觉变化数量应为{expected[0]}至{expected[1]}项")
    dimensions: list[str] = []
    for row in changes:
        if not isinstance(row, dict):
            errors.append("visual_changes每项必须是对象")
            continue
        dimension = str(row.get("dimension") or "").strip().lower()
        before = str(row.get("from") or "").strip()
        after = str(row.get("to") or "").strip()
        if dimension not in _VISUAL_DIMENSIONS:
            errors.append("visual_changes包含未知维度")
        elif dimension in dimensions:
            errors.append("visual_changes维度重复")
        dimensions.append(dimension)
        if not before or not after or before == after:
            errors.append("visual_changes必须明确填写不同的from与to")
    if level == "light" and dimensions and all(item == "palette" for item in dimensions):
        errors.append("轻度微改不能只改变颜色")
    if level == "interpretive":
        layout = str(plan.get("layout_archetype") or "").strip()
        required_layout = str(plan.get("required_layout_archetype") or "").strip()
        allowed_layouts = {row["id"] for row in INTERPRETIVE_LAYOUTS}
        if layout not in allowed_layouts:
            errors.append("灵感改编缺少有效的全新版式原型")
        elif required_layout and layout != required_layout:
            errors.append(f"灵感改编必须使用指定版式原型：{required_layout}")
        if "palette" not in dimensions:
            errors.append("灵感改编必须更换主色体系")
        if "composition" not in dimensions:
            errors.append("灵感改编必须重做页面构图")
        if "typography" not in dimensions:
            errors.append("灵感改编必须重做标题排版")
        structural = {"scene", "material", "decoration", "lighting", "typography", "composition"}
        if len(structural.intersection(dimensions)) < 4:
            errors.append("灵感改编除主色外还需改变至少四个视觉维度")
    return list(dict.fromkeys(errors))


def interpretive_layout_direction(*parts: object) -> dict[str, str]:
    """Choose a reproducible layout family so a batch varies without becoming random noise."""
    key = "\x1f".join(str(part or "").strip() for part in parts)
    digest = hashlib.sha256(key.encode("utf-8")).digest()
    return deepcopy(INTERPRETIVE_LAYOUTS[int.from_bytes(digest[:4], "big") % len(INTERPRETIVE_LAYOUTS)])


def interpretive_layout_by_id(value: str | None) -> dict[str, str] | None:
    layout_id = str(value or "").strip()
    return next((deepcopy(row) for row in INTERPRETIVE_LAYOUTS if row["id"] == layout_id), None)
