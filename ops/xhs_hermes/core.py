"""Pure planning and validation helpers for the Hermes XHS operator."""

from __future__ import annotations

import hashlib
import json
import random
import re
from decimal import Decimal, InvalidOperation
from functools import lru_cache
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Sequence


EXACT_BANNED_TERMS = (
    "私信", "加微信", "微信号", "扫码", "电话", "站外引流", "白嫖", "白送",
    "送你", "免费", "发你", "评论区", "国旗", "国家", "薅", "崩", "秒发",
    "底价", "全网最低", "最便宜", "抄底", "闭眼冲", "直降", "下调",
    "非节假日不用冲量", "崩了", "降价", "大跳水", "被割韭菜",
)

# Longest keys win so that, for example, 崩了 is handled before 崩.
BANNED_REPLACEMENTS = {
    "非节假日不用冲量": "近期政策窗口",
    "全网最低": "近期行情",
    "被割韭菜": "多花冤枉钱",
    "站外引流": "进一步了解",
    "大跳水": "行情调整",
    "闭眼冲": "按需考虑",
    "最便宜": "更合适",
    "加微信": "💌",
    "微信号": "💌",
    "评论区": "下方",
    "白嫖": "先做功课",
    "白送": "额外权益",
    "送你": "整理给你",
    # Remove the modifier without inventing broader eligibility conditions.
    "免费": "",
    "发你": "给你",
    "扫码": "查看",
    "电话": "沟通",
    "国旗": "相关标识",
    "国家": "全国",
    "秒发": "尽快整理",
    "抄底": "把握时机",
    "直降": "行情调整",
    "下调": "行情调整",
    "崩了": "行情调整",
    "降价": "行情调整",
    "私信": "💌",
    "底价": "💰",
    "薅": "了解",
    "崩": "调整",
}

COMPETITOR_RE = re.compile(
    r"比亚迪|奔驰|宝马|奥迪|理想|小鹏|特斯拉|问界|极氪|腾势|红旗|"
    r"吉利|长安|深蓝(?!色|灰)|蔚来|小米汽车|别克|大众|丰田|本田|广汽|方程豹|"
    r"岚图|智己|奇瑞|星途|凯迪拉克|福特|日产|现代汽车|起亚|领克|"
    r"极狐|阿维塔|奔腾"
)
LEAP_MODEL_CODES = (
    "A05", "A10", "B01", "B10", "C10", "C11", "C16", "D19", "D99",
    "Lafa5", "Lafa5 Ultra", "T03",
)
STALE_MODEL_RE = re.compile(
    r"海豹\s*(?:06GT|06|07)?|海豚|海鸥|海狮\s*(?:05EV|06|08)?|"
    r"宋\s*(?:PLUS|Pro|Ultra)?|元\s*(?:PLUS|UP)|秦\s*(?:PLUS|L|MAX)?|"
    r"唐\s*(?:DM)?|(?<!武)汉\s*(?:EV)?|银河\s*[A-Za-z0-9\-]*|"
    r"(?<![A-Za-z0-9])(?:GLE|GLC)(?![A-Za-z0-9])",
    re.I,
)
MONEY_RE = re.compile(
    r"(?<![A-Za-z0-9])(?:"
    r"[¥￥]\s*\d+(?:[,.]\d+)*(?:\.\d+)?(?:\s*(?:万元|万|元))?"
    r"|\d+(?:[,.]\d+)*(?:\.\d+)?\s*(?:万元|万|元|积分|w)"
    r")(?![A-Za-z])",
    re.I,
)
DAY_DATE_RE = re.compile(
    r"20\d{2}\s*[年/-]\s*\d{1,2}\s*[月/-]\s*\d{1,2}|"
    r"(?<!\d)\d{1,2}\s*月\s*\d{1,2}\s*[日号]"
)
CONFIG_RE = re.compile(
    r"(?:20\d{2}款\s*)?[^，。；;\n]{0,16}(?:舒享版|悦享版|智享版|智驾版|"
    r"旗舰版|豪华版|尊享版|标准版|入门版|高配版|低配版|长续航版|"
    r"纯电版|增程版)|(?<![A-Za-z])\d{3,4}\s*(?:舒享|悦享|智享|智驾|"
    r"旗舰|豪华|尊享|标准)?版",
    re.I,
)
CONFIG_TOKEN_RE = re.compile(
    r"(?<!\d)\d{3,4}(?:舒享|悦享|智享|智驾|激光雷达|旗舰|豪华|尊享|标准)?版|"
    r"(?<!\d)\d{3,4}S(?![A-Za-z0-9])",
    re.I,
)
CONFIG_NAME_RE = re.compile(
    r'(?<![\dA-Za-z])(?:\d{3,4}\s*)?(?:舒享|悦享|智享|智驾|激光雷达|旗舰|豪华|尊享|标准|长续航|纯电|增程)版',
    re.I,
)
TOPIC_RE = re.compile(r"#[^#\n]+\[话题\]#")
CTA_RE = re.compile(
    r"【[^】]*(?:城市|车型)[^】]*】|(?:城市|所在城市)\s*[+＋/、]\s*车型|"
    r"(?:滴滴|溜|甩|敲|扣|戳|留)[^\n]{0,24}(?:城市|车型|💌)|立即咨询",
    re.I,
)
UNSAFE_QUOTE_TEMPLATE_RE = re.compile(
    r"价格表|报价单|配置表|配置对比|官方指导价|裸车价|补贴后到手价|"
    r"第\s*[1-9]\s*行|表头|卡片[①②③④⑤⑥⑦⑧⑨\d]|四栏|五栏|六栏|"
    r"多配置|车型\s*[|｜]|"
    r"(?:[2-9二三四五六七八九]|两)\s*(?:款|组|个)[^。\n]{0,18}(?:车型|配置|信息卡片|价格卡片)|"
    r"(?:车型|配置)[^。\n]{0,12}(?:四宫格|双栏|价格列表|报价列表|价格明细)|"
    r"(?:四宫格|双栏)[^。\n]{0,12}(?:价格|落地价|车型|配置)"
)
MULTI_VEHICLE_QUOTE_RE = re.compile(
    r"全系车型[^。\n]{0,40}(?:报价|价格)|(?:四|五|六|七|八|九|十|\d+)辆车|"
    r"(?:四|五|六|七|八|九|十|\d+)款不同车型[^。\n]{0,30}(?:报价|价格)",
    re.I,
)
QUOTE_TABLE_TYPE = "multi_config_quote"
STANDARD_TEMPLATE_TYPE = "standard"
MAX_STANDARD_TEXT_SLOTS = 9
MAX_QUOTE_TEXT_SLOTS = 30
NO_TEXT_TEMPLATE_RE = re.compile(r"无文字|不显示文字|纯摄影|仅车辆", re.I)
UNKNOWN_FACT_PLACEHOLDER_RE = re.compile(
    r"以(?:官方(?:发布|信息)?|实际(?:情况)?|最终(?:发布|信息)?|具体版本)为准|"
    r"暂未公布|待公布|后续公布|敬请期待"
)


def sanitize_copy(title: str, content: str) -> tuple[str, str, list[dict[str, str]]]:
    """Deterministically replace only the explicit banned dictionary."""

    changes: list[dict[str, str]] = []

    def apply(value: str, field: str) -> str:
        for source in sorted(BANNED_REPLACEMENTS, key=len, reverse=True):
            if source not in value:
                continue
            target = BANNED_REPLACEMENTS[source]
            value = value.replace(source, target)
            changes.append({"field": field, "from": source, "to": target})
        return value

    return apply(title.strip(), "title"), apply(content.strip(), "content"), changes


def compact_text(value: str) -> str:
    return re.sub(r"\s+", "", str(value or "")).casefold()

@lru_cache(maxsize=8)
def _vehicle_pattern(vehicle_terms: tuple[str, ...]) -> re.Pattern[str] | None:
    terms = sorted(
        {compact_text(value) for value in vehicle_terms if len(compact_text(value)) >= 2},
        key=len,
        reverse=True,
    )
    if not terms:
        return None
    return re.compile("|".join(re.escape(value) for value in terms), re.I)


def normalize_structure(value: str, vehicle_terms: Sequence[str] = ()) -> str:
    """Remove factual slots while retaining the mother's linguistic skeleton."""

    text = str(value or "").casefold()
    pattern = _vehicle_pattern(tuple(vehicle_terms))
    if pattern is not None:
        text = pattern.sub("〔车型〕", text)
    text = re.sub(r"#[^#\n]+\[话题\]#", "〔话题〕", text)
    text = re.sub(r"20\d{2}\s*年?", "〔年份〕", text)
    text = re.sub(r"(?<!\d)\d{1,2}\s*月", "〔月份〕", text)
    text = re.sub(r"\d+(?:[,.]\d+)*(?:\.\d+)?", "〔数值〕", text)
    text = re.sub(r"[ \t\r]+", "", text)
    return text.strip()


def ngrams(value: str, size: int = 4) -> set[str]:
    if not value:
        return set()
    if len(value) <= size:
        return {value}
    return {value[index:index + size] for index in range(len(value) - size + 1)}


def jaccard(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return 0.0
    return len(left & right) / max(1, len(left | right))


def structure_digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


def mother_document(row: dict[str, Any]) -> str:
    return f"{row.get('title') or ''}\n{row.get('content') or ''}".strip()


def has_lead_structure(row: dict[str, Any]) -> bool:
    return bool(CTA_RE.search(mother_document(row)))


def money_values(value: str) -> set[str]:
    """Return comparable base-unit monetary values from RMB/wan expressions."""

    values: set[str] = set()
    for match in MONEY_RE.finditer(str(value or "")):
        token = match.group(0).replace("¥", "").replace("￥", "").replace(",", "").strip().casefold()
        multiplier = Decimal(10000) if "万" in token or token.endswith("w") else Decimal(1)
        number_match = re.search(r"\d+(?:\.\d+)?", token)
        if not number_match:
            continue
        try:
            amount = Decimal(number_match.group(0)) * multiplier
        except InvalidOperation:
            continue
        values.add(format(amount.normalize(), "f"))
    return values


def is_multi_config_quote(value: str) -> bool:
    """Identify actual same-model configuration/price rows, not generic CTA wording."""

    text = str(value or "")
    if MULTI_VEHICLE_QUOTE_RE.search(text):
        return False
    row_configs: set[str] = set()
    for segment in re.split(r"[\n；;]", text):
        config = CONFIG_RE.search(segment)
        if config and MONEY_RE.search(segment):
            row_configs.add(compact_text(config.group(0)))
    if len(row_configs) >= 2:
        return True
    configs = {compact_text(match.group(0)) for match in CONFIG_RE.finditer(text)}
    return (
        len(configs) >= 2
        and len(money_values(text)) >= 2
        and re.search(r"价格表|报价单|配置表|配置对比|官方指导价|补贴后|落地参考", text) is not None
    )


def is_multi_config_quote_layout(value: str) -> bool:
    """Recognize a reusable same-model quote table even if old row prices are omitted."""

    text = str(value or "")
    if MULTI_VEHICLE_QUOTE_RE.search(text):
        return False
    configs = {compact_text(match.group(0)) for match in CONFIG_TOKEN_RE.finditer(text)}
    has_table_layout = re.search(
        r"价格表|配置表|配置对比|报价列表|价格明细|表格|两列|车型版本|裸车价|"
        r"(?:四|五|六|七|八|九|\d+)宫格",
        text,
    ) is not None
    return len(configs) >= 2 and has_table_layout


def copy_content_type(value: dict[str, Any] | str) -> str:
    text = mother_document(value) if isinstance(value, dict) else str(value or "")
    return QUOTE_TABLE_TYPE if is_multi_config_quote(text) else STANDARD_TEMPLATE_TYPE


def prompt_template_type(value: dict[str, Any] | str) -> str:
    text = str(value.get("chinese") or "") if isinstance(value, dict) else str(value or "")
    return QUOTE_TABLE_TYPE if is_multi_config_quote(text) or is_multi_config_quote_layout(text) else STANDARD_TEMPLATE_TYPE


def precise_config_mentions(value: str) -> list[str]:
    return list(dict.fromkeys(match.group(0) for match in CONFIG_TOKEN_RE.finditer(str(value or ""))))


def source_slot_count(prompt: str) -> int:
    """Conservative estimate of quoted print, excluding explicit prompt metadata.

    Keep ambiguous quotes and repeated placements: equal text can appear twice
    on the image. Never discard real copy just because it contains “背景/字体”.
    This is an admission budget, not the later exact slot mapping or OCR check.
    """
    pairs = r'「([^」\n]{1,80})」|“([^”\n]{1,80})”|【([^】\n]{1,80})】|"([^"\n]{1,80})"'
    count = 0
    for match in re.finditer(pairs, prompt):
        value = next(group for group in match.groups() if group is not None).strip()
        before, after = prompt[max(0, match.start() - 40):match.start()], prompt[match.end():match.end() + 40]
        explicit_print = re.search(
            r'(?:文字|标题|文案|标语|标注|写着|写上|印有|显示|内容为|小字|大字|添加)[^，。；\n“”「」【】"]{0,16}$',
            before,
        )
        if not explicit_print:
            if match.group(3) is not None and (
                re.fullmatch(r'目标|画面结构|设计细节|风格|画面|文案|底部|重点|氛围|输出', value)
                or re.match(r'(?:风格描述|背景描述|前景描述|调性|光影风格|字体风格|副标题样式)[，,]如', value)
                or before.endswith('画面主体为')
            ):
                continue
            # Bracketed instruction headings followed by ':' are not artwork.
            if match.group(3) is not None and re.match(r'\s*[:：]', after) and re.match(
                r'(?:整体(?:配色|风格|构图|要求)|画面(?:排版|构图|布局)|'
                r'价格信息[-－—].*(?:可选|添加)|(?:背景|字体|镜头|材质|光影)(?:设置|说明|要求))', value
            ):
                continue
            # Quoted names of materials/shapes are descriptions, not labels.
            if re.match(r'\s*(?:轮毂|质感|材质|纹理|笔触|字体风格)', after):
                continue
        count += 1
    return count


def safe_prompt_pool(items: Iterable[dict[str, Any]], *, allow_quote_table: bool) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for raw in items:
        prompt = str(raw.get("chinese") or "").strip()
        image_url = str(raw.get("image_url") or "").strip()
        if not prompt or not image_url or not 180 <= len(prompt) <= 2600:
            continue
        if NO_TEXT_TEMPLATE_RE.search(prompt):
            continue
        if MULTI_VEHICLE_QUOTE_RE.search(prompt):
            continue
        template_type = prompt_template_type(prompt)
        if not allow_quote_table and UNSAFE_QUOTE_TEMPLATE_RE.search(prompt):
            continue
        if not re.search(r"海报|封面", prompt) or not re.search(r"文字|标题|文案|字体|LOGO|logo", prompt):
            continue
        slots = source_slot_count(prompt)
        maximum_slots = MAX_QUOTE_TEXT_SLOTS if template_type == QUOTE_TABLE_TYPE else MAX_STANDARD_TEXT_SLOTS
        if slots < 2 or slots > maximum_slots:
            continue
        row = dict(raw)
        row["source_slot_count"] = slots
        row["template_type"] = template_type
        result.append(row)
    return result


@dataclass(frozen=True)
class MemoryText:
    text: str
    grams: set[str]


ACCOUNT_HISTORY_LIMIT = 15
ACCOUNT_HIGH_SIMILARITY = 0.85


def account_memory_text(value: str, vehicle_terms: Sequence[str] = ()) -> MemoryText:
    """Compare whole-copy structure, not shared hashtags or short lead CTAs."""
    lines = []
    for raw in str(value or "").splitlines():
        line = raw.strip()
        if not line or line.startswith('#'):
            continue
        if len(line) <= 80 and CTA_RE.search(line):
            continue
        line = re.sub(r'#[^\s#]+#?', '', line)
        if line.strip():
            lines.append(line)
    text = normalize_structure('\n'.join(lines), vehicle_terms)
    text = re.sub(r'[^\w\u4e00-\u9fff]+', '', text)
    # Titles and thin/missing bodies cannot establish whole-post repetition.
    return MemoryText(text=text, grams=ngrams(text) if len(text) >= 60 else set())


def account_repetition_check(
    title: str, content: str, recent: Sequence[dict[str, Any]],
    vehicle_terms: Sequence[str] = (),
) -> dict[str, Any]:
    current = account_memory_text(f'{title}\n{content}', vehicle_terms)
    matches = []
    for row in recent[:ACCOUNT_HISTORY_LIMIT]:
        if not str(row.get('content') or '').strip():
            continue
        previous = account_memory_text(mother_document(row), vehicle_terms)
        if not current.grams or not previous.grams:
            continue
        matches.append((jaccard(current.grams, previous.grams), row))
    score, closest = max(matches, key=lambda value: value[0], default=(0.0, {}))
    return {
        'status': ('insufficient_history' if not matches else
                   'high_similarity' if score >= ACCOUNT_HIGH_SIMILARITY else 'allowed'),
        'score': round(score, 4),
        'high_similarity_threshold': ACCOUNT_HIGH_SIMILARITY,
        'closest_note_id': closest.get('id'),
        'closest_title': closest.get('title'),
        'history_count': len(recent[:ACCOUNT_HISTORY_LIMIT]),
        'compared_bodies': len(matches),
        'blocking': False,
        'metric': 'normalized_full_copy_4gram_jaccard_not_semantic_percentage',
    }


def _memory_text(value: str, vehicle_terms: Sequence[str]) -> MemoryText:
    # Full posts can be close to 1,000 characters. Repetition is already clear
    # from the title, opening structure and CTA/topic tail; keeping that excerpt
    # makes 40-post planning fast without weakening near-template detection.
    lines = [line.strip() for line in str(value or "").splitlines() if line.strip()]
    excerpt_lines = lines if len(lines) <= 10 else lines[:7] + lines[-3:]
    text = normalize_structure("\n".join(excerpt_lines)[:900], vehicle_terms)
    return MemoryText(text=text, grams=ngrams(text))


def select_diverse_rows(
    pool: Sequence[dict[str, Any]],
    *,
    count: int,
    historical_texts_by_account: dict[int, list[str]],
    task_account_ids: Sequence[int],
    vehicle_terms: Sequence[str],
    excluded_ids: set[int] | None = None,
    text_getter=mother_document,
    id_key: str = "id",
    candidate_window: int = 72,
    unique_structure: bool = True,
    near_duplicate_cap: float = 0.72,
    account_near_duplicate_cap: float | None = None,
    tolerate_moderate_similarity: bool = False,
    rng: random.Random | random.SystemRandom | None = None,
) -> list[dict[str, Any]]:
    """Random-window selection with diversity as a score, never a retry loop.

    The pool is shuffled first. Copy mode accepts moderate similarity and picks
    randomly below the high-overlap caps; legacy/image mode ranks by similarity.
    An exhausted window expands once, then relaxes visibly rather than looping.
    """

    if len(task_account_ids) != count:
        raise ValueError("task_account_ids length must equal count")
    randomizer = rng or random.SystemRandom()
    excluded = set(excluded_ids or set())
    available = [row for row in pool if int(row.get(id_key) or 0) not in excluded]
    randomizer.shuffle(available)
    if len(available) < count:
        raise ValueError(f"available rows {len(available)} is smaller than requested {count}")

    memory_builder = account_memory_text if tolerate_moderate_similarity else _memory_text
    history = {
        account_id: [memory_builder(text, vehicle_terms) for text in texts if text]
        for account_id, texts in historical_texts_by_account.items()
    }
    selected: list[dict[str, Any]] = []
    selected_memory: list[tuple[int, MemoryText]] = []
    selected_structure_ids: set[str] = set()
    memory_cache: dict[int, MemoryText] = {}

    def row_memory(row: dict[str, Any]) -> MemoryText:
        cache_key = id(row)
        if cache_key not in memory_cache:
            memory_cache[cache_key] = memory_builder(text_getter(row), vehicle_terms)
        return memory_cache[cache_key]

    for account_id in task_account_ids:
        window_size = min(max(1, candidate_window), len(available))
        account_refs = history.get(account_id, []) + [
            item for owner, item in selected_memory if owner == account_id
        ]
        all_refs = [item for _, item in selected_memory]

        def score_candidate(index: int) -> dict[str, Any]:
            row = available[index]
            memory = row_memory(row)
            account_overlap = max((jaccard(memory.grams, item.grams) for item in account_refs), default=0.0)
            batch_overlap = max((jaccard(memory.grams, item.grams) for item in all_refs), default=0.0)
            digest = structure_digest(memory.text)
            return {
                "index": index,
                "memory": memory,
                "structure_id": digest,
                "account_overlap": account_overlap,
                "batch_overlap": batch_overlap,
                # Lower is better. A tiny random tiebreaker avoids stable first-row bias.
                "score": (account_overlap, batch_overlap, randomizer.random()),
            }

        def eligible(indexes: Iterable[int]) -> list[dict[str, Any]]:
            rows = [score_candidate(index) for index in indexes]
            if unique_structure:
                rows = [row for row in rows if row["structure_id"] not in selected_structure_ids]
            return rows

        relaxed = False
        selection_note = "random_window"
        candidates = eligible(range(window_size))
        def below_caps(row: dict[str, Any]) -> bool:
            return row['batch_overlap'] <= near_duplicate_cap and (
                account_near_duplicate_cap is None or row['account_overlap'] < account_near_duplicate_cap
            )

        feasible = [row for row in candidates if below_caps(row)]

        # A random window keeps the selection non-deterministic. Expand once only
        # when that window contains an exact/recent structural collision; this is
        # bounded and cannot fall into a regenerate loop.
        if not feasible and window_size < len(available):
            candidates = eligible(range(len(available)))
            feasible = [row for row in candidates if below_caps(row)]
            selection_note = "expanded_for_diversity"

        if feasible:
            # Once safely below the high-similarity boundary, normal similarity
            # is acceptable. Do not always force the least-similar writing style.
            best = min(feasible, key=lambda row: row['score'][2] if tolerate_moderate_similarity else row['score'])
        elif candidates:
            # The cap is a soft portfolio guard. If the library cannot satisfy it,
            # keep moving with the least-similar remaining structure and record it.
            best = min(
                candidates,
                key=lambda row: (row["batch_overlap"], row["account_overlap"], row["score"][2]),
            )
            relaxed = True
            selection_note = "near_duplicate_cap_relaxed"
        else:
            # This is only possible when every remaining ID has a structure already
            # selected. ID uniqueness is still preserved; the relaxation is visible.
            candidates = [score_candidate(index) for index in range(len(available))]
            best = min(
                candidates,
                key=lambda row: (row["batch_overlap"], row["account_overlap"], row["score"][2]),
            )
            relaxed = True
            selection_note = "exact_structure_unavoidable"

        best_index = int(best["index"])
        best_memory = best["memory"]
        best_score = best["score"]
        chosen = available.pop(best_index)
        chosen = dict(chosen)
        chosen["structure_id"] = best["structure_id"]
        chosen["selection_account_similarity"] = round(best_score[0], 4)
        chosen["selection_batch_similarity"] = round(best_score[1], 4)
        chosen["selection_relaxed"] = relaxed
        chosen["selection_note"] = selection_note
        selected.append(chosen)
        selected_memory.append((account_id, best_memory))
        selected_structure_ids.add(best["structure_id"])
    return selected


def validate_copy(
    *,
    title: str,
    content: str,
    mother: dict[str, Any] | None,
    case: dict[str, Any],
) -> dict[str, Any]:
    full = f"{title}\n{content}"
    target = str(case.get("vehicle_model") or "")
    target_code = target.replace("零跑", "").replace(" ", "")
    policy = str(case.get("policy_text") or "")
    hard: list[str] = []
    warnings: list[str] = []

    if not title.strip():
        hard.append("标题为空")
    elif len(title.strip()) > 20:
        hard.append(f"标题超过20字：{len(title.strip())}")
    if not content.strip():
        hard.append("正文为空")
    elif len(content.strip()) > 1000:
        hard.append(f"正文超过1000字：{len(content.strip())}")
    if target_code and target_code.casefold() not in full.casefold():
        hard.append("目标车型未出现在标题或正文")

    placeholder_hits = UNKNOWN_FACT_PLACEHOLDER_RE.findall(content)
    if len(placeholder_hits) >= 2:
        hard.append(
            f"未知产品事实被占位语连续填充：{len(placeholder_hits)}处；"
            "应改用已登记事实或删除整个无依据段落"
        )

    nonblank = [line.strip() for line in content.splitlines() if line.strip()]
    if not nonblank or not TOPIC_RE.search(nonblank[-1]):
        hard.append("最后一个非空行缺少话题标签")
    if mother and has_lead_structure(mother) and not CTA_RE.search(content):
        hard.append("母文中的留资入口没有被保留")

    banned = sorted({term for term in EXACT_BANNED_TERMS if term in full})
    banned.extend(str(term) for term in case.get("policy_banned_terms") or [] if str(term) in full)
    if banned:
        hard.append("出现明确禁用词：" + "、".join(sorted(set(banned))))

    competitors = sorted(set(COMPETITOR_RE.findall(full)))
    if competitors:
        hard.append("残留竞品品牌：" + "、".join(competitors))
    stale_models = sorted(set(match.group(0) for match in STALE_MODEL_RE.finditer(full)))
    if stale_models:
        hard.append("残留旧车型：" + "、".join(stale_models))
    other_models = []
    for code in LEAP_MODEL_CODES:
        normalized = code.replace(" ", "")
        if normalized.casefold() == target_code.casefold():
            continue
        if re.search(rf"零跑\s*{re.escape(code)}(?![A-Za-z0-9])", full, re.I):
            other_models.append(code)
    if other_models:
        hard.append("残留其他零跑车型：" + "、".join(sorted(set(other_models))))

    if DAY_DATE_RE.search(full):
        hard.append("公开文案出现具体到日的日期")
    allowed_months = {int(value) for value in case.get("allowed_months") or []}
    stale_months = sorted({
        int(value) for value in re.findall(r"(?<!\d)(\d{1,2})\s*月", full)
        if int(value) not in allowed_months
    })
    if stale_months:
        hard.append("出现当前政策没有的月份：" + "、".join(f"{value}月" for value in stale_months))

    normalized_policy = compact_text(policy)
    policy_money = money_values(MONEY_RE.sub(lambda m: '' if '积分' in m.group(0) else m.group(0), policy))
    unsupported_money = sorted({
        match.group(0) for match in MONEY_RE.finditer(full)
        if compact_text(match.group(0)) not in normalized_policy
        and ('积分' in match.group(0) or not money_values(match.group(0)) or not money_values(match.group(0)) <= policy_money)
    })
    if unsupported_money:
        hard.append("政策未提供的金额：" + "、".join(unsupported_money))
    unsupported_configs = sorted({
        match.group(0) for match in CONFIG_NAME_RE.finditer(full)
        if compact_text(match.group(0)) not in normalized_policy
    } | {
        value for value in precise_config_mentions(full)
        if compact_text(value) not in normalized_policy
    })
    if unsupported_configs:
        hard.append("政策未提供的配置名：" + "、".join(unsupported_configs))

    if case.get("vehicle_stage") == "new" and re.search(r"有现车|现车可提", full):
        hard.append("新车型不能宣传现车可提")
    if not case.get("allow_multi_config_quote") and re.search(
        r"(?:全系|各配置)[^。！!\n]{0,18}(?:报价单|价格表|落地价)|多配置报价",
        full,
    ):
        hard.append("当前政策没有完整分配置价格，不能承诺多配置报价")

    if mother:
        source_lines = [line for line in str(mother.get("content") or "").splitlines() if line.strip()]
        output_lines = [line for line in content.splitlines() if line.strip()]
        ratio = len(output_lines) / max(1, len(source_lines))
        if ratio < 0.5 or ratio > 1.7:
            hard.append(f"正文结构与母文严重偏离：母文{len(source_lines)}行，输出{len(output_lines)}行")
        elif ratio < 0.75 or ratio > 1.3:
            warnings.append(f"正文行数与母文有差异：母文{len(source_lines)}行，输出{len(output_lines)}行")

    return {
        "pass": not hard,
        "hard_errors": list(dict.fromkeys(hard)),
        "warnings": list(dict.fromkeys(warnings)),
        "blocking_rule": "hard_errors_only",
    }


def numeric_tokens(value: str) -> set[str]:
    return money_values(value)


def validate_image_plan(plan: dict[str, Any], copy: dict[str, Any], case: dict[str, Any]) -> list[str]:
    prompt = str(plan.get("adapted_prompt") or "").strip()
    blocks = [str(value).strip() for value in plan.get("text_blocks") or [] if str(value).strip()]
    mappings = plan.get("slot_mappings") or []
    source_slots = int(plan.get("source_slot_count") or 0)
    target = str(case.get("vehicle_model") or "")
    template_type = str(plan.get("template_type") or prompt_template_type(plan.get("selected_prompt_original") or ""))
    quote_mode = template_type == QUOTE_TABLE_TYPE
    support = f"{copy.get('title') or ''}\n{copy.get('content') or ''}"
    # A quote template may complement ordinary copy with exact rows from the
    # current structured policy. Other image templates stay copy-bound.
    if quote_mode:
        support += "\n" + json.dumps(case.get("quote_rows") or [], ensure_ascii=False)
    errors: list[str] = []
    if not prompt:
        errors.append("adapted_prompt为空")
    if target and compact_text(target) not in compact_text(prompt):
        errors.append("生图提示词缺少目标车型")
    foreign = sorted(set(COMPETITOR_RE.findall(prompt)))
    if foreign:
        errors.append("生图提示词残留竞品：" + "、".join(foreign))
    banned = sorted({term for term in EXACT_BANNED_TERMS if term in prompt or any(term in block for block in blocks)})
    if banned:
        errors.append("图片文字出现禁用词：" + "、".join(banned))
    if quote_mode and not case.get("allow_multi_config_quote"):
        errors.append("当前车型不能使用多配置报价结构")
    if DAY_DATE_RE.search(prompt) or any(DAY_DATE_RE.search(block) for block in blocks):
        errors.append("图片文字出现具体到日的日期")
    maximum_slots = MAX_QUOTE_TEXT_SLOTS if quote_mode else MAX_STANDARD_TEXT_SLOTS
    if not 2 <= len(blocks) <= maximum_slots:
        errors.append(f"图片文字槽数量异常：{len(blocks)}")
    if 2 <= source_slots <= maximum_slots and len(blocks) < source_slots - 1:
        errors.append(f"母版文字槽删减过多：母版约{source_slots}槽，输出{len(blocks)}槽")
    if not isinstance(mappings, list) or len(mappings) != len(blocks):
        errors.append("缺少逐槽母版文字映射")
    else:
        mapped_outputs = [str(row.get("output") or "").strip() for row in mappings if isinstance(row, dict)]
        if mapped_outputs != blocks:
            errors.append("逐槽映射与最终文字槽不一致")
        source_prompt = compact_text(plan.get("selected_prompt_original") or "")
        untraceable = [
            str(row.get("source") or "").strip()
            for row in mappings if isinstance(row, dict)
            and str(row.get("source") or "").strip()
            and compact_text(row.get("source") or "") not in source_prompt
        ]
        if len(untraceable) > 1:
            errors.append("逐槽映射有多个文字槽无法在母版中定位")
    # Repeated rating stars are intentional decorations, not duplicated copy.
    copy_blocks = [block for block in blocks if not re.fullmatch(r"[★☆⭐✦✧]+", block)]
    if len(copy_blocks) != len(set(copy_blocks)):
        errors.append("图片文字槽重复")
    if any(block not in prompt for block in blocks):
        errors.append("图片文字槽没有逐字写入提示词")
    unsupported = sorted(numeric_tokens("\n".join(blocks)) - numeric_tokens(support))
    if unsupported:
        errors.append("图片文字出现未登记金额：" + "、".join(unsupported))
    for block in blocks:
        match = CONFIG_TOKEN_RE.search(block) or CONFIG_RE.search(block)
        if match and compact_text(match.group(0)) not in compact_text(support):
            errors.append("图片文字出现未登记配置名：" + match.group(0))
            break
        if len(block) > 48:
            errors.append("单个图片文字槽超过48字")
            break
    if NO_TEXT_TEMPLATE_RE.search(prompt):
        errors.append("生图提示词要求了无文字图片")
    return list(dict.fromkeys(errors))


def angle_for_prompt(prompt: str) -> str:
    if re.search(r"侧后|后侧|车尾\s*45", prompt):
        return "斜后方"
    if re.search(r"纯侧面|正侧|侧面平视", prompt):
        return "侧面"
    if re.search(r"正面视角|正前", prompt):
        return "正前方"
    return "斜前方"


# Approved 2026-09-08: script-equivalent characters in configuration names only.
# This is deliberately not fuzzy OCR repair or whole-document conversion. The
# source text, numbers, confidence, banned-word/date/brand checks stay unchanged.
OCR_CONFIG_SCRIPT_RULE = "ocr-config-script-equivalence-v1"
_OCR_CONFIG_SCRIPT_MAP = str.maketrans({
    "悅": "悦", "駕": "驾", "艦": "舰", "華": "华", "標": "标", "準": "准",
    "門": "门", "長": "长", "續": "续", "純": "纯", "電": "电", "達": "达",
})
_OCR_CONFIG_EXTRA_NAME_RE = re.compile(r"(?:入门|高配|低配)版")


def ocr_configuration_comparison(value: str) -> dict[str, Any]:
    """Return an audit-only view; fold only spans recognized as existing trims.

    All mappings are one character to one character, so offsets refer to the
    original input. Digits/Latin letters/punctuation are never repaired.
    """
    original = str(value or "")
    folded = original.translate(_OCR_CONFIG_SCRIPT_MAP)
    spans = sorted({match.span() for pattern in (CONFIG_TOKEN_RE, CONFIG_NAME_RE, _OCR_CONFIG_EXTRA_NAME_RE)
                    for match in pattern.finditer(folded)})
    merged: list[list[int]] = []
    for start, end in spans:
        if merged and start < merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    text = list(original)
    changes: list[dict[str, Any]] = []
    for start, end in merged:
        if original[start:end] == folded[start:end]:
            continue
        text[start:end] = folded[start:end]
        changes.append({"start": start, "end": end, "from": original[start:end], "to": folded[start:end]})
    return {"text": "".join(text), "changes": changes}


def image_ocr_errors(
    lines: Sequence[dict[str, Any] | str],
    *,
    copy: dict[str, Any],
    case: dict[str, Any],
    expected_text_blocks: Sequence[str] | None = None,
    allow_policy_facts: bool = False,
    min_confidence: float = 0.56,
    configuration_audit: dict[str, Any] | None = None,
) -> list[str]:
    accepted: list[str] = []
    low_confidence_risks: list[str] = []
    for raw in lines:
        if isinstance(raw, dict):
            confidence = float(raw.get("confidence") or 0.0)
            text = str(raw.get("text") or "").strip()
            if confidence < min_confidence:
                is_hard_fact = (
                    MONEY_RE.search(text) is not None
                    or DAY_DATE_RE.search(text) is not None
                    or CONFIG_RE.search(ocr_configuration_comparison(text)["text"]) is not None
                    or COMPETITOR_RE.search(text) is not None
                    or any(term in text for term in EXACT_BANNED_TERMS)
                    or re.search(r"零跑\s*[A-Za-z0-9]{2,}", text, re.I) is not None
                )
                if confidence >= 0.25 and is_hard_fact:
                    low_confidence_risks.append(text)
                continue
        else:
            text = str(raw).strip()
        if text:
            accepted.append(text)
    # Low-confidence decorative text stays ignored, but an OCR line containing
    # a recognizable amount/date/config/brand/model is still part of the hard
    # fact audit. This closes the gap where small footer prices were skipped.
    full = "\n".join(accepted + low_confidence_risks)
    support = f"{copy.get('title') or ''}\n{copy.get('content') or ''}"
    if allow_policy_facts:
        support += "\n" + json.dumps(case.get("quote_rows") or [], ensure_ascii=False)
    target = str(case.get("vehicle_model") or "")
    target_code = target.replace("零跑", "").replace(" ", "")
    errors: list[str] = []
    banned = sorted({term for term in EXACT_BANNED_TERMS if term in full})
    if banned:
        errors.append("OCR识别到禁用词：" + "、".join(banned))
    competitors = sorted(set(COMPETITOR_RE.findall(full)))
    if competitors:
        errors.append("OCR识别到竞品品牌：" + "、".join(competitors))
    for code in LEAP_MODEL_CODES:
        if code.replace(" ", "").casefold() == target_code.casefold():
            continue
        if re.search(rf"零跑\s*{re.escape(code)}(?![A-Za-z0-9])", full, re.I):
            errors.append("OCR识别到其他零跑车型：" + code)
    unsupported_money = sorted(numeric_tokens(full) - numeric_tokens(support))
    if unsupported_money:
        errors.append("OCR识别到未登记金额：" + "、".join(unsupported_money))
    if DAY_DATE_RE.search(full):
        errors.append("OCR识别到具体日期")
    config_full = ocr_configuration_comparison(full)
    config_support = ocr_configuration_comparison(support)
    ocr_config_mentions = precise_config_mentions(config_full["text"])
    if not ocr_config_mentions:
        ocr_config_mentions = [match.group(0) for match in CONFIG_RE.finditer(config_full["text"])]
    for value in ocr_config_mentions:
        if compact_text(value) not in compact_text(config_support["text"]):
            errors.append("OCR识别到未登记配置名：" + value)
    expected = "\n".join(str(value) for value in (expected_text_blocks or []) if str(value).strip())
    missing_money = sorted(numeric_tokens(expected) - numeric_tokens(full))
    if missing_money:
        errors.append("OCR未完整识别计划金额：" + "、".join(missing_money))
    config_expected = ocr_configuration_comparison(expected)
    recognized_compact = compact_text(config_full["text"])
    expected_configs = precise_config_mentions(config_expected["text"])
    if not expected_configs:
        expected_configs = [match.group(0) for match in CONFIG_RE.finditer(config_expected["text"])]
    missing_configs = sorted({value for value in expected_configs if compact_text(value) not in recognized_compact})
    if missing_configs:
        errors.append("OCR未完整识别计划配置名：" + "、".join(missing_configs))
    if configuration_audit is not None:
        configuration_audit.update({
            "rule": OCR_CONFIG_SCRIPT_RULE,
            "scope": "configuration_names_only",
            "ocr_changes": config_full["changes"],
            "ocr_comparison_text": config_full["text"] if config_full["changes"] else None,
            "ocr_audit_source_text": full if config_full["changes"] else None,
            "support_changes": config_support["changes"],
            "expected_changes": config_expected["changes"],
        })
    return list(dict.fromkeys(errors))


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))
