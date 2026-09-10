#!/usr/bin/env python3
"""Synchronize Hermes policy cases from the operator-maintained HTML report.

The report is the source of truth. Its filename/month label is deliberately not
used as the effective period because the operator may keep the same shared file
while replacing its contents. The production batch date supplies the effective
month, and an unchanged report is rejected at the next month boundary.
"""

from __future__ import annotations

import calendar
import datetime as dt
import hashlib
import json
import os
import re
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Iterable


VOID_TAGS = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}
DAY_DATE_RE = re.compile(r"(?:20\d{2}年)?\d{1,2}月\d{1,2}日")
MONEY_RE = re.compile(r"[¥￥]?\s*\d[\d,.]*(?:万)?(?:元)?")


@dataclass
class Node:
    tag: str
    attrs: dict[str, str] = field(default_factory=dict)
    children: list[Any] = field(default_factory=list)

    def classes(self) -> set[str]:
        return set(self.attrs.get("class", "").split())


class TreeParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root = Node("document")
        self.stack = [self.root]

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        node = Node(tag.lower(), {key: value or "" for key, value in attrs})
        self.stack[-1].children.append(node)
        if tag.lower() not in VOID_TAGS:
            self.stack.append(node)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        if tag.lower() not in VOID_TAGS:
            self.stack.pop()

    def handle_endtag(self, tag: str) -> None:
        target = tag.lower()
        for index in range(len(self.stack) - 1, 0, -1):
            if self.stack[index].tag == target:
                del self.stack[index:]
                return

    def handle_data(self, data: str) -> None:
        if data:
            self.stack[-1].children.append(data)


def walk(node: Node) -> Iterable[Node]:
    for child in node.children:
        if isinstance(child, Node):
            yield child
            yield from walk(child)


def first(node: Node, *, tag: str | None = None, class_name: str | None = None, node_id: str | None = None) -> Node | None:
    for candidate in walk(node):
        if tag and candidate.tag != tag:
            continue
        if class_name and class_name not in candidate.classes():
            continue
        if node_id and candidate.attrs.get("id") != node_id:
            continue
        return candidate
    return None


def direct_children(node: Node, tag: str) -> list[Node]:
    return [child for child in node.children if isinstance(child, Node) and child.tag == tag]


def text_content(node: Node, separator: str = " ") -> str:
    chunks: list[str] = []

    def collect(value: Any) -> None:
        if isinstance(value, str):
            stripped = re.sub(r"\s+", " ", value).strip()
            if stripped:
                chunks.append(stripped)
            return
        if isinstance(value, Node):
            for child in value.children:
                collect(child)

    collect(node)
    return separator.join(chunks).strip()


def direct_text(node: Node) -> str:
    return " ".join(
        re.sub(r"\s+", " ", child).strip()
        for child in node.children
        if isinstance(child, str) and child.strip()
    ).strip()


def table_rows(table: Node) -> list[list[Node]]:
    rows: list[list[Node]] = []
    for row in (candidate for candidate in walk(table) if candidate.tag == "tr"):
        cells = [child for child in row.children if isinstance(child, Node) and child.tag in {"th", "td"}]
        if cells:
            rows.append(cells)
    return rows


def normalize_money(value: str) -> str:
    compact = re.sub(r"\s+", "", value).replace("￥", "¥")
    match = MONEY_RE.search(compact)
    return match.group(0) if match else compact


def month_context(batch_date: str) -> tuple[str, str, list[int]]:
    current = dt.date.fromisoformat(batch_date)
    last_day = calendar.monthrange(current.year, current.month)[1]
    return (
        f"{current.year}-{current.month:02d}-{last_day:02d}",
        f"{current.month}月底前",
        [current.month],
    )


LANDING_FIELDS = (
    "cash_discount", "bare_price", "national_scrappage_subsidy",
    "estimated_insurance", "estimated_purchase_tax", "licensing_fee",
    "estimated_national_scrappage_on_road_price",
)
LANDING_LABELS = ("现金优惠", "裸车价", "国补金额测算", "保险估算", "购置税估算", "上牌费估算", "国补条件下落地价估算")


def landing_prices(section: Node, quotes: list[dict[str, str]]) -> list[dict[str, str]]:
    """Join the report's second table by exact config label, never by row order."""
    detail = first(section, class_name="landing-detail")
    if detail is None:
        return []
    table = first(detail, tag="table")
    if table is None:
        raise ValueError("landing detail is present but has no table")
    rows = table_rows(table)
    headers = [text_content(c) for c in rows[0]] if rows else []
    expected = ("车型", "指导价", "现金优惠", "裸车价", "国补", "保险", "购置税", "上牌", "落地价")
    if len(headers) != 9 or any(token not in value for token, value in zip(expected, headers)):
        raise ValueError("unrecognized landing-price columns; refusing to misalign prices")
    remaining = {re.sub(r"\s+", "", r["configuration"]): r for r in quotes}
    result = []
    for cells in rows[1:]:
        if len(cells) != 9:
            raise ValueError("incomplete landing-price row")
        label = re.sub(r"\s+", "", direct_text(cells[0]) or text_content(cells[0]))
        # The report's second table appends a propulsion badge to the config.
        matching = [key for key in remaining if label == key or (
            label.startswith(key) and re.fullmatch(r"(?:纯电|增程)(?:[·•][\w\u4e00-\u9fff]+)*", label[len(key):])
        )]
        if len(matching) != 1:
            raise ValueError(f"landing configuration cannot be matched uniquely: {label}")
        original = remaining.pop(matching[0])
        if normalize_money(text_content(cells[1])) != original["official_guide_price"]:
            raise ValueError(f"landing guide price conflicts with main table: {label}")
        values = [normalize_money(text_content(cell)) for cell in cells[2:]]
        if not all(re.fullmatch(r"[¥￥]?\d[\d,]*(?:\.\d+)?(?:万元|万|元)?", v) for v in values):
            raise ValueError(f"invalid landing amount: {label}")
        result.append({"configuration": original["configuration"], **dict(zip(LANDING_FIELDS, values))})
    if remaining:
        raise ValueError("landing table does not cover every main-table configuration")
    return result


def publication_constraints(root: Node, section: Node, stage: str, *, allow_local_amounts: bool = False) -> dict[str, Any]:
    """Translate only the supplied report's explicit publication conditions."""
    report = text_content(root, separator="")
    section_text = text_content(section, separator="")
    has_guidelines = "厂家宣传规范" in report
    # 省补价格可在运营侧的“最新政策”中展示，但绝不作为文案或图片生产事实。
    # 保留参数只为兼容旧配置；历史的运营覆盖不再改变生产边界。
    hide_local = True
    rules = []
    if hide_local:
        rules.append("地方性补贴只能概括提及；不在标题、正文或图片中展示其金额、比例、上限或省补后价格，不将其加入综合权益。")
    banned = [word for word in ("内部价", "底价", "最优惠", "至高可省", "半价理想") if has_guidelines and word in report]
    if has_guidelines:
        rules.extend([
            "厂家综合权益值是报告标注总值，不再把国补、贴息、选装等已含项目重复相加；不得超过对应车型报告值。",
            "试驾礼可概括提及，不展示具体金额，不计入综合权益；门店自行增加的现金优惠或礼品不能作为线上报价来源。",
        ])
        if stage == "new":
            rules.append("新车型综合价值只用‘综合权益’或‘综合权益价值’，不包装成优惠；首销期不能宣传门店有现车可提。")
        else:
            rules.append("往期车型综合价值可用‘综合权益优惠’或‘综合权益’，保留原文表达，不强行新增权益段。")
        rules.append("不使用文件明确禁止的误导性表述：" + "、".join(banned) + "。")
    exclusive = []
    if "本品增换购" in section_text and "超级置换" in section_text and "二选一" in section_text:
        exclusive.append({"left": "本品增换购", "right": "超级置换"})
        rules.append("本品增换购与超级置换为二选一，不能相加或宣传同一订单同时享受。")
    if "B/C级车展" in section_text and "新能源下乡" in section_text and "不同时享受" in section_text:
        exclusive.append({"left": "车展", "right": "下乡"})
        rules.append("车展专项积分与新能源下乡积分二选一，不可相加或同时享受。")
    unconfirmed_finance = "现金优惠是否可同享" in section_text
    if unconfirmed_finance:
        rules.append("金融方案与现金优惠能否同享尚需门店确认，不能承诺两项叠加。")
    return {"version": 1, "hide_local_subsidy_amounts": hide_local,
            "new_vehicle_no_benefit_discount": has_guidelines and stage == "new",
            "new_vehicle_no_stock": has_guidelines and stage == "new",
            "no_trial_gift_amount": has_guidelines, "explicit_banned_terms": banned,
            "mutually_exclusive_benefits": exclusive,
            "finance_cash_stacking_unconfirmed": unconfirmed_finance, "rules": rules}


def parse_report(source: bytes, *, source_url: str, batch_date: str, overrides: dict[str, Any] | None = None) -> tuple[dict[str, Any], dict[str, Any]]:
    digest = hashlib.sha256(source).hexdigest()
    parser = TreeParser()
    parser.feed(source.decode("utf-8-sig", errors="replace"))
    title_node = first(parser.root, tag="title")
    report_title = text_content(title_node) if title_node else "零跑全系购车政策报告"
    deadline, public_deadline, allowed_months = month_context(batch_date)
    declared = re.search(r"权益有效期至\s*(20\d{2})年(\d{1,2})月(\d{1,2})日", text_content(parser.root))
    if declared:
        declared_date = dt.date(*map(int, declared.groups()))
        if declared_date.isoformat()[:7] != batch_date[:7] or dt.date.fromisoformat(batch_date) > declared_date:
            raise ValueError("report effective period does not cover requested production date")
        deadline = declared_date.isoformat()
    override_map = overrides or {}
    publication_override = override_map.get("_publication") or {}
    if not isinstance(publication_override, dict):
        raise ValueError("publication override must be an object")
    allow_local_amounts = (
        publication_override.get("allow_local_subsidy_amounts") is True
        and publication_override.get("effective_period") == batch_date[:7]
    )
    cases: dict[str, Any] = {}
    excluded: dict[str, list[str]] = {}
    audit_rows: dict[str, Any] = {}

    sections = [node for node in walk(parser.root) if "report-section" in node.classes() and node.attrs.get("id")]
    for section in sections:
        section_id = section.attrs["id"].lower()
        title_box = first(section, class_name="report-title")
        vehicle_model = direct_text(title_box) if title_box else ""
        if not vehicle_model:
            continue
        subtitle_box = first(section, class_name="report-subtitle")
        subtitle = text_content(subtitle_box) if subtitle_box else ""
        banner = first(section, class_name="benefit-banner")
        banner_value_box = first(banner, class_name="value") if banner else None
        banner_value = normalize_money(text_content(banner_value_box)) if banner_value_box else ""
        case_override = override_map.get(section_id) if isinstance(override_map.get(section_id), dict) else {}
        banner_text = text_content(banner) if banner else ""
        stage = "new" if "新车型" in banner_text else "current" if "往期车型" in banner_text else str(case_override.get("vehicle_stage") or "current")
        constraints = publication_constraints(parser.root, section, stage, allow_local_amounts=allow_local_amounts)

        tables = [node for node in walk(section) if node.tag == "table"]
        if not tables:
            continue
        primary_rows = table_rows(tables[0])
        if len(primary_rows) < 2:
            continue
        headers = [text_content(cell) for cell in primary_rows[0]]
        if len(headers) < 4 or "车型" not in headers[0] or "指导价" not in headers[1]:
            continue

        quote_rows: list[dict[str, str]] = []
        benefit_items: list[str] = []
        day_bound_items: list[str] = []
        for cells in primary_rows[1:]:
            if len(cells) < 4:
                continue
            configuration = direct_text(cells[0]) or text_content(cells[0])
            row = {
                "configuration": configuration,
                "official_guide_price": normalize_money(text_content(cells[1])),
                "national_scrappage_after_price": normalize_money(text_content(cells[2])),
                "provincial_trade_in_after_price": normalize_money(text_content(cells[3])),
            }
            if all(row.values()):
                quote_rows.append(row)
            if len(cells) >= 5:
                item_nodes = [candidate for candidate in walk(cells[4]) if "item" in candidate.classes()]
                values = [text_content(candidate, separator="") for candidate in item_nodes]
                if not values:
                    values = [text_content(cells[4], separator="")]
                for value in values:
                    if not value:
                        continue
                    if DAY_DATE_RE.search(value):
                        day_bound_items.append(value)
                    else:
                        benefit_items.append(value)

        if len(quote_rows) != len({row["configuration"] for row in quote_rows}):
            raise ValueError(f"{section_id}: duplicate configuration names in policy table")
        display_quote_rows = [dict(row) for row in quote_rows]
        landings = landing_prices(section, quote_rows)
        audit_rows[f"{section_id}-current"] = {"source_quote_rows": [dict(row) for row in quote_rows], "landing_price_rows": landings}
        landing_by_config = {row["configuration"]: row for row in landings}
        for row in quote_rows:
            if constraints["hide_local_subsidy_amounts"]:
                # Keep a useful explanation in the existing policy-viewer cell;
                # the original value remains only in the audit, not model input.
                row["provincial_trade_in_after_price"] = "不在线上展示金额"
            row.update(landing_by_config.get(row["configuration"], {}))
        if landings:
            constraints["has_reported_landing_estimates"] = True
            constraints["rules"].append("落地价明细仅为报告按指定保险、税费及上牌假设的测算，不是实际成交承诺；引用落地价时必须标注‘报告测算/估算’，不能把只扣补贴的车价当落地价。只在母文或母图对应价格槽需要时使用，不硬加明细或列。")
        allow_quote = len(quote_rows) >= 2 and all(
            row["official_guide_price"] and row["national_scrappage_after_price"]
            for row in quote_rows
        )

        quote_lines = [
            (
                f"{row['configuration']}：官方指导价{row['official_guide_price']}；"
                f"国补后价格（按政策条件测算）{row['national_scrappage_after_price']}。"
            )
            for row in quote_rows
        ]
        policy_parts = [
            f"车型：{vehicle_model}。",
            f"当前运营确认政策期为{batch_date[:7]}，对外时间只写{public_deadline}、近期或本月。",
            f"车型概览：{subtitle}。" if subtitle else "",
            f"厂家综合权益图标注值：{banner_value}。" if banner_value else "",
            "分配置价格（补贴后价格为按报告公式测算，不得表述为无条件成交价或落地价）：",
            *quote_lines,
            *[f"{row['configuration']}报告测算明细：" + "；".join(f"{label}{row[field]}" for label, field in zip(LANDING_LABELS, LANDING_FIELDS)) + "。" for row in landings],
            *[value + ("。" if not value.endswith(("。", "！", "；")) else "") for value in benefit_items],
            "涉及补贴后的价格，必须同时表达适用条件或‘按相应条件测算’，不得省略条件。",
        ]
        extra_rules = [str(value).strip() for value in case_override.get("extra_rules") or [] if str(value).strip()]
        policy_parts.extend(value + ("。" if not value.endswith(("。", "！", "；")) else "") for value in extra_rules)
        policy_parts.extend(constraints["rules"])
        policy_text = "".join(value for value in policy_parts if value)
        case_id = f"{section_id}-current"
        cases[case_id] = {
            "brand": str(case_override.get("brand") or "零跑汽车"),
            "vehicle_model": vehicle_model,
            "vehicle_stage": stage,
            "policy_source": f"WorkBuddy零跑全系购车政策表（运营确认按{batch_date[:7]}执行）",
            "policy_source_title": report_title,
            "policy_source_url": source_url,
            "policy_fingerprint": digest,
            "policy_deadline": deadline,
            "public_deadline": public_deadline,
            "allowed_months": allowed_months,
            "allow_multi_config_quote": allow_quote,
            "quote_rows": quote_rows,
            "display_quote_rows": display_quote_rows,
            "policy_banned_terms": list(dict.fromkeys([*case_override.get("policy_banned_terms", []), *constraints["explicit_banned_terms"]])),
            "publication_constraints": constraints,
            "packaged_benefit_value": banner_value,
            "policy_text": policy_text,
        }
        if day_bound_items:
            excluded[case_id] = day_bound_items

    metadata = {
        "source_url": source_url,
        "source_title": report_title,
        "source_fingerprint": digest,
        "effective_period": batch_date[:7],
        "parsed_at": dt.datetime.now().isoformat(timespec="seconds"),
        "case_count": len(cases),
        "excluded_day_specific_facts": excluded,
        "source_rows_for_audit_only": audit_rows,
    }
    return cases, metadata


def atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(data)
    os.replace(temporary, path)


def load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def download(url: str, timeout: int = 45) -> bytes:
    parts = urllib.parse.urlsplit(url)
    query = urllib.parse.parse_qsl(parts.query, keep_blank_values=True)
    query.append(("hermes_refresh", str(int(time.time()))))
    refresh_url = urllib.parse.urlunsplit((parts.scheme, parts.netloc, parts.path, urllib.parse.urlencode(query), parts.fragment))
    request = urllib.request.Request(refresh_url, headers={"User-Agent": "HermesPolicySync/1.0", "Cache-Control": "no-cache"})
    # The production host sometimes inherits a dead local HTTP proxy. This URL
    # is public, so connect directly and keep policy refresh independent of it.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(request, timeout=timeout) as response:
        data = response.read(4 * 1024 * 1024 + 1)
    if not data or len(data) > 4 * 1024 * 1024:
        raise RuntimeError("policy source is empty or over 4 MB")
    return data


def sync_policy(*, settings_path: Path, cases_path: Path, batch_date: str, cache_dir: Path) -> dict[str, Any]:
    settings = load_json(settings_path)
    source_url = str(settings.get("content_url") or "").strip()
    if not source_url:
        raise RuntimeError(f"policy content_url missing in {settings_path}")
    configured_overrides = settings.get("overrides_path")
    overrides_path = Path(configured_overrides) if configured_overrides else settings_path.with_name("policy_overrides.json")
    if not overrides_path.is_absolute():
        overrides_path = settings_path.parent / overrides_path
    overrides = load_json(overrides_path)
    source_cache = cache_dir / "source.html"
    metadata_cache = cache_dir / "metadata.json"
    previous_metadata = load_json(metadata_cache)
    used_cache = False
    try:
        source = download(source_url, timeout=int(settings.get("timeout_seconds") or 45))
    except Exception as exc:
        if not source_cache.exists():
            raise RuntimeError(f"policy download failed and no verified cache exists: {exc}") from exc
        if previous_metadata.get("source_url") != source_url:
            raise RuntimeError("policy source changed; refusing the previous document's cache") from exc
        source = source_cache.read_bytes()
        if hashlib.sha256(source).hexdigest() != previous_metadata.get("source_fingerprint"):
            raise RuntimeError("policy cache fingerprint does not match verified metadata") from exc
        used_cache = True

    cases, metadata = parse_report(source, source_url=source_url, batch_date=batch_date, overrides=overrides)
    minimum_cases = int(settings.get("minimum_case_count") or 1)
    required_case_ids = [str(value) for value in settings.get("required_case_ids") or []]
    if len(cases) < minimum_cases:
        raise RuntimeError(f"policy parser found {len(cases)} cases; expected at least {minimum_cases}")
    missing = sorted(case_id for case_id in required_case_ids if case_id not in cases)
    if missing:
        raise RuntimeError("policy parser missing required cases: " + ", ".join(missing))

    old_period = str(previous_metadata.get("effective_period") or "")
    old_fingerprint = str(previous_metadata.get("source_fingerprint") or "")
    new_period = str(metadata["effective_period"])
    new_fingerprint = str(metadata["source_fingerprint"])
    if old_period and old_period != new_period and old_fingerprint == new_fingerprint:
        raise RuntimeError(
            f"policy table was not updated for {new_period}; source fingerprint is unchanged from {old_period}"
        )
    if used_cache and old_period and old_period != new_period:
        raise RuntimeError(f"cannot use {old_period} policy cache for {new_period}")

    metadata["used_verified_cache"] = used_cache
    metadata["case_ids"] = sorted(cases)
    metadata["share_url"] = str(settings.get("share_url") or source_url)
    for case in cases.values():
        case["policy_content_url"] = source_url
        case["policy_source_url"] = metadata["share_url"]
    display_rows = {
        case_id: list(case.pop("display_quote_rows", []) or [])
        for case_id, case in cases.items()
    }
    encoded_cases = json.dumps(cases, ensure_ascii=False, indent=2).encode("utf-8") + b"\n"
    encoded_display = json.dumps(display_rows, ensure_ascii=False, indent=2).encode("utf-8") + b"\n"
    encoded_metadata = json.dumps(metadata, ensure_ascii=False, indent=2).encode("utf-8") + b"\n"
    atomic_write(cases_path, encoded_cases)
    atomic_write(cases_path.with_name("policy_display.json"), encoded_display)
    backend_snapshot = Path(__file__).resolve().parents[2] / "backend" / "app" / "data" / "hermes_policy_cases.json"
    backend_display = backend_snapshot.with_name("hermes_policy_display.json")
    production_cases = Path(__file__).resolve().parent / "config" / "cases.json"
    if cases_path.resolve() == production_cases.resolve() and backend_snapshot.parent.exists():
        atomic_write(backend_snapshot, encoded_cases)
        atomic_write(backend_display, encoded_display)
    if not used_cache:
        atomic_write(source_cache, source)
    atomic_write(metadata_cache, encoded_metadata)
    return metadata
