from __future__ import annotations

from copy import deepcopy
import hashlib
from typing import Any


ADAPTATION_CONTRACT_VERSION = "hermes-adaptation-v10"
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
    {
        "id": "cinematic_split",
        "name": "电影分镜对照",
        "brief": (
            "采用上下错位或左右不等分的两帧电影画幅，用不同道路、光线或使用时刻形成对照；"
            "车辆在两帧中保持同一车型但使用不同取景尺度，标题像片名置于留白区，信息使用字幕条而非贴纸、撕纸或胶带。"
        ),
    },
    {
        "id": "typographic_monument",
        "name": "巨型字体装帧",
        "brief": (
            "用极简纯色或柔和渐变建立大面积负空间，以一组巨型中文标题成为主要构图；"
            "车辆只占一个偏置焦点并与字形穿插，辅助信息使用小号书籍装帧文字，禁止拼贴、撕纸、胶带和满版装饰。"
        ),
    },
    {
        "id": "premium_showroom",
        "name": "高级展陈空间",
        "brief": (
            "把车辆置于克制的美术馆或品牌展厅空间，以建筑光影、展台和大面积留白形成层次；"
            "标题成为墙面导视或悬浮信息牌，信息极少而精准，禁止撕纸拼贴、爆炸贴、粗粝网点和廉价促销背景。"
        ),
    },
    {
        "id": "modular_grid",
        "name": "模块化信息系统",
        "brief": (
            "使用明确的模块网格承载同类信息，卡片尺寸、层级和编号形成统一系统；"
            "车辆作为一个独立主模块偏置出现，其余模块用图标、短标题与关键数字建立秩序，禁止撕纸、胶带和手账拼贴。"
        ),
    },
    {
        "id": "comparison_axis",
        "name": "双轴选择对照",
        "brief": (
            "围绕一条清晰的水平或对角选择轴组织两套对应信息，轴两侧分别承载两个版本或两种场景；"
            "车辆图与标题严格对应各自一侧，中部只保留决策变量，禁止把对应关系打散成随意贴纸。"
        ),
    },
    {
        "id": "route_storyboard",
        "name": "路线时间叙事",
        "brief": (
            "用一条连续路线或时间轴串起三至五个信息节点，从起点、转折到结论形成阅读路径；"
            "车辆沿路线形成主视觉，节点使用统一路牌或站点符号，禁止撕纸拼贴和无方向的散点堆叠。"
        ),
    },
    {
        "id": "contact_sheet",
        "name": "摄影联络片",
        "brief": (
            "采用摄影师联络片或胶片序列结构，用一个大主画面和三至四个等比例细节镜头建立观察感；"
            "车辆主图、灯组、轮毂或使用场景按编号对应，标题与说明像影像档案标注，禁止撕纸边、胶带和促销爆炸贴。"
        ),
    },
    {
        "id": "radial_map",
        "name": "环形关系图",
        "brief": (
            "车辆偏心放置，三至五个信息模块沿弧线或环形轨道围绕主体展开，并用清晰连接关系说明各自角色；"
            "标题位于环形缺口形成视觉入口，整体像现代信息图而非科技大屏，禁止随意散落贴纸。"
        ),
    },
)

# Interpretive mode may redesign a source inside its functional layout family,
# but it must not turn a table into a poster, cards into a table, or a dialog
# into an unrelated hero image.
INTERPRETIVE_LAYOUTS_BY_SOURCE_TYPE: dict[str, tuple[str, ...]] = {
    "hero": (
        "kinetic_collage", "asymmetric_editorial", "spatial_installation",
        "cinematic_split", "typographic_monument", "premium_showroom",
    ),
    "headline": (
        "kinetic_collage", "asymmetric_editorial", "spatial_installation",
        "typographic_monument", "premium_showroom",
    ),
    "collage": (
        "kinetic_collage", "paper_cutout", "asymmetric_editorial",
        "cinematic_split", "route_storyboard", "contact_sheet",
    ),
    "table": ("technical_dossier", "asymmetric_editorial", "modular_grid", "comparison_axis"),
    "cards": (
        "paper_cutout", "technical_dossier", "asymmetric_editorial",
        "modular_grid", "comparison_axis", "radial_map",
    ),
    "list": (
        "asymmetric_editorial", "paper_cutout", "technical_dossier",
        "modular_grid", "route_storyboard", "radial_map",
    ),
    "dialog": ("paper_cutout", "asymmetric_editorial", "cinematic_split", "comparison_axis"),
    "diagram": (
        "technical_dossier", "asymmetric_editorial", "spatial_installation",
        "route_storyboard", "radial_map", "modular_grid",
    ),
}

INTERPRETIVE_NARRATIVES: tuple[dict[str, str], ...] = (
    {
        "id": "scene_contrast",
        "name": "双场景反差",
        "brief": "用两个具体但不同的用车场景开篇，在差异中自然推出判断；不要使用固定的‘我更建议/这点要注意’句式。",
    },
    {
        "id": "reverse_filter",
        "name": "反向排除法",
        "brief": "先写哪些人不适合某个选择，再逐步缩小到适合人群；结尾给出清晰判断，不写常规参数总结。",
    },
    {
        "id": "decision_path",
        "name": "决策路径",
        "brief": "围绕一个决定依次经过使用半径、补能或预算三个判断节点，像真实思考过程，不写编号清单。",
    },
    {
        "id": "misread_reveal",
        "name": "误区揭示",
        "brief": "从一个容易看错或算错的点切入，先给反直觉结论，再解释为什么；避免‘别只看’成为固定标题模板。",
    },
    {
        "id": "day_in_motion",
        "name": "一天动线",
        "brief": "沿早高峰、白天补能、周末出行等时间变化推进，用第三方观察口吻代入，不能虚构作者亲测经历。",
    },
    {
        "id": "two_person_dialogue",
        "name": "两类用户对话",
        "brief": "让两种真实需求形成简短对照或问答，再由事实完成裁决；不使用客服式问答和统一话术。",
    },
    {
        "id": "budget_ledger",
        "name": "预算账本",
        "brief": "从一笔具体预算如何分配切入，讲清多花或少花换来的东西；不罗列完整配置表。",
    },
    {
        "id": "single_variable",
        "name": "一个变量定选择",
        "brief": "只抓住一个最能改变选择的变量展开，其他事实仅作证据；让正文更聚焦，避免每篇都覆盖同一套卖点。",
    },
    {
        "id": "process_before_result",
        "name": "先流程后结果",
        "brief": "从办理、核对或实际决策顺序进入，把容易颠倒的步骤讲清楚，最后才落到车型或版本判断。",
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
        "description": "保留母文选题，自由改写表达并审核同批重复",
        "copy": "依据母文真实话题与目标车型资料规划写作，成稿后检查跑题、事实和同批语义重复，不套固定叙事骨架。",
        "image": "保留车型、事实、信息优先级和母图功能类型，在同类型内切换全新版式原型并重做车辆裁切、标题方向、页面网格和视觉语言。",
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
        from copy_voice import XHS_VOICE_GUIDANCE
        return (
            "本篇采用【灵感改编】：先读懂指定母文为什么有人愿意看，保留它的核心话题、信息优先级和阅读收益，"
            "再改标题、具体措辞、展开方式与节奏；不是只保留车型名后自由换选题。"
            "外观观察不能改成续航版本二选一，权益说明不能改成预算选车，报价清单仍应让人看懂报价。"
            "按已核验的选题计划写作，所有汽车事实只来自目标车型政策或知识库；资料不支持的卖点不能编造。"
            "学习母文中具体、有吸引力的表达方式，不搬运旧车事实、亲测经历或违规话术。"
            "母文在种草，新稿也要有种草的吸引力，而不是一律改成‘到店核对这几项’的检查表。"
            "可以写明确的主观喜好和未来打算，不可编造已经发生的逛店、试驾或购车经历。"
            "无法支持的细节宁可删掉，也不必逐条变成观察问题。不要把全部已知参数和权益都塞进来；"
            "非报价主题不要习惯性接一份全版本报价表；只引用理解本篇主题所必需的价格与条件。"
            "每段都要服务本篇重点，删去泛泛的‘核对条件、适合自己、理性选择’式重复总结。"
            "执行xhs_get_copy_case返回的copy_budget与brevity_instruction：先挑重点再写，不是写长了才机械截短。"
            "不写满字数，不强行保留留资尾巴。报价清单保留必要行，但不在每个价格后追加选车分析。"
            "标题也要学到母文让人停下来的原因：具体的信息收益、情绪或反差，不要退化成‘车型+资料类别’的目录名；"
            "不能靠编造亲历、新政策或无依据比较来做钩子。"
            "保留小红书笔记的亲近感和可读性，避免客服式导语、编辑部总结和抽象空话；"
            "长短、分段、Emoji和清单由内容需要决定，不按固定段数、表情数量或两版本配额填空。"
            "不要每篇都写成‘提问—比较两档续航—看充电条件—核对政策’。"
            "写作规则是内部约束，不得把‘不展示地方补贴金额’‘线上不能写’‘按要求改写’等编辑指令放进成稿；"
            "也不要向读者解释‘不套原车型叙事’‘政策时间写到哪里’等改写过程。"
            "真实政策的适用条件仍须清楚说明。" + common_logic + '\n' + XHS_VOICE_GUIDANCE
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
            "本图采用【灵感改编】：必须锁定母图的功能类型和信息组织关系；报价表仍是报价表，分块卡片仍是分块卡片，"
            "车型对照、清单笔记、对话问答、图解科普和多图拼贴也必须各自保持原类型，严禁跨类型改造。"
            "在这个硬边界内，母图不再约束具体海报骨架、文字坐标、车辆位置、装饰形式和视觉语言；"
            "必须切换到程序指定且与母图类型兼容的全新版式原型，重做页面网格、车辆取景与裁切、标题方向及同类型载体的造型，"
            "主色不得沿用母版或相邻色。可以重排同类型内部结构，但不能删掉定义该类型的关系：表格必须有共同表头和行列，"
            "卡片必须分块承载，对照必须保持对应关系，对话必须保留问答顺序，图解必须保留标注或连接关系。"
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
            "保留目标车型、事实、信息优先级、母图功能类型及其核心信息关系；必须严格执行计划指定的兼容版式原型，"
            "在同类型内改掉页面网格、车辆取景、标题方向、载体造型和视觉语言。不得把报价表改成情绪海报或卡片，"
            "也不得让卡片、对照、清单、对话、图解、拼贴互相跨类型。"
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


def interpretive_layout_compatible(layout_id: str | None, source_layout_type: str | None) -> bool:
    source_type = str(source_layout_type or "").strip()
    if not source_type or source_type not in INTERPRETIVE_LAYOUTS_BY_SOURCE_TYPE:
        return any(row["id"] == str(layout_id or "").strip() for row in INTERPRETIVE_LAYOUTS)
    return str(layout_id or "").strip() in INTERPRETIVE_LAYOUTS_BY_SOURCE_TYPE[source_type]


def interpretive_layout_direction(
    *parts: object,
    source_layout_type: str | None = None,
    usage_counts: dict[str, int] | None = None,
    excluded_ids: set[str] | None = None,
) -> dict[str, str]:
    """Choose a compatible, reproducible layout while balancing the current batch."""
    key = "\x1f".join(str(part or "").strip() for part in parts)
    digest = hashlib.sha256(key.encode("utf-8")).digest()
    allowed_ids = INTERPRETIVE_LAYOUTS_BY_SOURCE_TYPE.get(str(source_layout_type or "").strip())
    candidates = (
        tuple(row for row in INTERPRETIVE_LAYOUTS if row["id"] in allowed_ids)
        if allowed_ids else INTERPRETIVE_LAYOUTS
    )
    available = tuple(row for row in candidates if row["id"] not in (excluded_ids or set()))
    if available:
        candidates = available
    if usage_counts:
        least_used = min(int(usage_counts.get(row["id"], 0)) for row in candidates)
        candidates = tuple(row for row in candidates if int(usage_counts.get(row["id"], 0)) == least_used)
    return deepcopy(candidates[int.from_bytes(digest[:4], "big") % len(candidates)])


def interpretive_narrative_direction(
    *parts: object,
    usage_counts: dict[str, int] | None = None,
    excluded_ids: set[str] | None = None,
) -> dict[str, str]:
    """Assign a distinct writing skeleton instead of repeating one XHS cadence."""
    key = "\x1f".join(str(part or "").strip() for part in parts)
    digest = hashlib.sha256(key.encode("utf-8")).digest()
    candidates = tuple(
        row for row in INTERPRETIVE_NARRATIVES
        if row["id"] not in (excluded_ids or set())
    ) or INTERPRETIVE_NARRATIVES
    if usage_counts:
        least_used = min(int(usage_counts.get(row["id"], 0)) for row in candidates)
        candidates = tuple(row for row in candidates if int(usage_counts.get(row["id"], 0)) == least_used)
    return deepcopy(candidates[int.from_bytes(digest[4:8], "big") % len(candidates)])


def interpretive_layout_by_id(
    value: str | None,
    source_layout_type: str | None = None,
) -> dict[str, str] | None:
    layout_id = str(value or "").strip()
    if not interpretive_layout_compatible(layout_id, source_layout_type):
        return None
    return next((deepcopy(row) for row in INTERPRETIVE_LAYOUTS if row["id"] == layout_id), None)
