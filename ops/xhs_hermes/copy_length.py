"""Source-aware copy budgets, shared by planning, the writer and validation.

Budgets limit verbosity, not meaning: never truncate the output to fit them.
Quote tables get space for the target's actual rows; other notes stay focused.
"""
from __future__ import annotations

import math
import re
from typing import Any


_TAG = re.compile(r"#[^#\s\[\]]{1,32}(?:\[话题\])?#")
_PRICE = re.compile(r"[¥￥]\s*\d|\d[\d,.]*\s*(?:万|元|w)", re.I)


def copy_lengths(content: str) -> dict[str, int]:
    """Count non-whitespace code points; valid short hashtags separately."""
    total = len(re.sub(r"\s+", "", content))
    body = len(re.sub(r"\s+", "", _TAG.sub("", content)))
    return {"body_chars": body, "tag_chars": total - body}


def copy_budget(mother: dict[str, Any] | None, case: dict[str, Any]) -> dict[str, Any]:
    source = str((mother or {}).get("content") or "")
    source_chars = copy_lengths(source)["body_chars"]
    # Repeated priced rows identify a real table, not a CTA promising a quote.
    priced_lines = sum(bool(_PRICE.search(line)) for line in source.splitlines())
    table = priced_lines >= 3 and bool(re.search(r"版|配置|全系", source))
    configurations = {
        str(row.get("configuration") or "").strip()
        for row in case.get("quote_rows") or [] if isinstance(row, dict)
    } - {""}
    if table:
        row_count = len(configurations) or min(priced_lines, 6)
        maximum = min(600, max(300, 180 + 40 * row_count))
    else:
        row_count = 0
        maximum = min(280, max(180, math.ceil(source_chars * 0.75)))
    return {
        "kind": "quote_table" if table else "focused_note",
        "source_body_chars": source_chars,
        "quote_rows": row_count,
        "preferred_body_chars": math.floor(maximum * 0.8),
        "max_body_chars": maximum,
        "max_tag_chars": 80,
    }


def brevity_instruction(budget: dict[str, Any]) -> str:
    table = budget["kind"] == "quote_table"
    detail = (
        "本篇是报价清单：保留本主题需要的完整版本/价格行，一行一个配置；"
        "共同价格口径和适用条件集中说一次，不给每款追加人群建议、智驾介绍或续航选择分析。"
        "开头用一句自然的导语点出这份当期报价的用处，不写后台报告式导语；"
        "表后只保留必要共同条件，不再总结指导价区间、最低价格或续航。"
        "既然逐行列出了价格，就删掉‘指导价区间’概览和‘想快速比预算’等复述段，"
        "也不另加车身结构、座位数、续航参数。这是报价表，不是车型介绍。"
        if table else
        "本篇不是完整报价表：只展开母文的一个主要看点，不顺带塞全版本价格、全套权益或购车检查表。"
        "不为凑数据堆参数；报价仅是母文附带信息时，可删掉整个无关报价段。"
    )
    return (
        f"短文约束：正文优先控制在{budget['preferred_body_chars']}字以内，"
        f"上限{budget['max_body_chars']}字（不含空白与话题标签，按字符计数）；"
        f"话题标签合计不超过{budget['max_tag_chars']}字。没有最低字数，不必写满。"
        + detail
        + "先删重复开场、铺垫、复述结论和泛泛提醒，再精简句子；不靠去掉换行压成一大段。"
        "报价测算、适用对象、选配/标配、互斥条件必须保留，不能为变短删限制词，"
        "也不能逐字截断正文。资料多不等于每条都要写。"
        "讲完即可结束，不强行保留母文的留资尾巴，不追加报城市、索要报价、💌等转化引导。"
        "保留自然的小红书语气，不变成客服或电报。"
    )


def copy_length_check(content: str, mother: dict[str, Any] | None,
                      case: dict[str, Any]) -> dict[str, Any]:
    budget = copy_budget(mother, case)
    lengths = copy_lengths(content)
    errors = []
    if lengths["body_chars"] > budget["max_body_chars"]:
        errors.append(
            f"正文过长：{lengths['body_chars']}字，当前母文类型上限{budget['max_body_chars']}字。"
            + brevity_instruction(budget)
        )
    if lengths["tag_chars"] > budget["max_tag_chars"]:
        errors.append(f"话题标签过长：{lengths['tag_chars']}字，上限{budget['max_tag_chars']}字；删除重复和无关话题。")
    return {**budget, **lengths, "hard_errors": errors}
