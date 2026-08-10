from __future__ import annotations

import asyncio
import json
import re
import uuid
from datetime import date, datetime

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Query, Header
from fastapi.responses import StreamingResponse
from io import BytesIO
from pydantic import BaseModel
from sqlalchemy import and_, or_, select
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession
import httpx
from app.db.session import get_db, async_session
from app.core.deps import get_current_user, require_admin
from app.core.roles import (
    ROLE_ADMIN,
    ROLE_BRAND_LEAD,
    ROLE_BRAND_OPS,
    ROLE_XHS_LEAD,
    ROLE_XHS_OPS,
    get_user_roles,
    has_role,
)
from app.models.user import User
from app.models.xhs_post import XHSPost
from app.models.xhs_account_note import XHSAccountNote
from app.models.xhs_environment import XHSEnvironment
from app.models.xhs_account_sync_run import XHSAccountSyncRun, XHSAccountSyncRunItem
from app.schemas.common import ApiResponse
from app.schemas.xhs import (
    AccountNoteListOut,
    AccountNoteOut,
    AccountNoteBrowseRecordRequest,
    AccountNoteBatchUpdateRequest,
    AccountNoteContentTagOut,
    AccountNoteContentTagRequest,
    AccountNoteUpdateRequest,
    CreativeReportCompareOut,
    EnvironmentOut,
    PublishRequest,
    PublishOut,
    PostOut,
    PostListOut,
    PostStatsOut,
    PostUpdateRequest,
    ReportListOut,
)
from app.services.xhs_service import XHSService, SyncJobCancelled
from app.services.xhs_ad_dashboard_service import XHSAdDashboardService
from app.services.vehicle_catalog_service import VehicleCatalogService
from app.services.xhs_profile_stat_service import XHSProfileStatService
from app.services.xhs_homepage_sync_shadow import (
    SHADOW_PROGRESS_PHASES_BY_KIND,
    mirror_account_data_sync_shadow_safely,
    mirror_homepage_sync_shadow_safely,
)
from app.services.xhs_report_refresh_shadow import (
    create_report_refresh_run_safely,
    finish_report_refresh_run_safely,
    mark_report_refresh_running_safely,
    record_report_refresh_result_safely,
)
from app.config import settings
import logging
from openpyxl import Workbook

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/xhs", tags=["小红书发布"])
XHS_BACKGROUND_JOBS: dict[str, dict] = {}
XHS_BACKGROUND_JOB_TASKS: dict[str, asyncio.Task] = {}

XHS_CONTENT_TAG_TREE = {
    "新车行情爆料": {
        "官方调价/价格大调",
        "终端优惠/门店隐藏价",
        "月度购车政策",
        "内部消息/实锤爆料",
        "改款/配置调整",
        "限时福利/节点活动",
        "区域专属政策",
    },
    "购车落地价核算": {
        "全款落地价核算",
        "贷款/月供方案核算",
        "购车费用明细拆解",
        "城市报价差异",
        "本地底价/一对一算价",
        "砍价技巧/谈价空间",
        "杂费避坑/费用减免",
    },
    "车型选购对比": {
        "同级车型横向对比",
        "竞品二选一",
        "高低配/版本选择",
        "新旧款车型对比",
        "预算内车型推荐",
        "家用/通勤场景选车",
        "人群需求选车",
    },
    "实车静态/动态测评": {
        "外观内饰实拍",
        "空间/座椅体验",
        "车机/智能座舱体验",
        "动力/底盘/操控体验",
        "油耗/电耗/续航实测",
        "试驾体验",
        "产品优缺点总结",
    },
    "购车避坑干货": {
        "4S店套路拆解",
        "贷款/金融隐形消费",
        "合同/订金避坑",
        "捆绑装潢/强制消费",
        "库存车/展车辨别",
        "提车验车流程",
        "新手买车通用清单",
    },
    "用车养护与功能教程": {
        "车机/隐藏功能教程",
        "保养周期/保养省钱",
        "车险选购",
        "新能源电池养护",
        "夏季/冬季用车技巧",
        "故障提醒/常见问题",
        "日常用车省钱技巧",
    },
    "汽车改装与外观分享": {
        "车身贴膜/改色",
        "轮毂/外观件改装",
        "内饰升级",
        "车载好物推荐",
        "灯光/氛围感升级",
        "改装案例分享",
        "颜值实拍/配色展示",
    },
    "汽车日常泛内容": {
        "车主日常/Vlog",
        "自驾出行/爱车随拍",
        "车展/门店现场",
        "汽车热点快讯",
        "品牌/行业泛资讯",
        "情绪文案/生活方式",
        "无明确目的兜底内容",
    },
}
XHS_CONTENT_TAG_PRIMARY_LABELS = set(XHS_CONTENT_TAG_TREE.keys())
XHS_CONTENT_TAG_SECONDARY_LABELS = {
    secondary for secondaries in XHS_CONTENT_TAG_TREE.values() for secondary in secondaries
}
XHS_CONTENT_TAG_SECONDARY_ALIASES = {
    "生活方式": "情绪文案/生活方式",
    "热点快讯": "汽车热点快讯",
}

_XHS_TAG_RULES: list[tuple[str, str, re.Pattern[str]]] = [
    (
        "购车落地价核算",
        "全款落地价核算",
        re.compile(r"(落地价|全款|贷款|月供|首付|购置税|上牌费|裸车价|费用明细|购车费用|城市差价|不同城市.*差价)", re.I),
    ),
    (
        "新车行情爆料",
        "月度购车政策",
        re.compile(r"(新政|政策|行情|优惠|降价|放价|价格(?:大调|调整|下调|上调|优惠|政策)|报价|底价|好价|这个价|价了|夯价|团价|团购|补贴|权益|大调|冲量|清仓|限时|福利|置换|贴息|现金优惠|年中|月底|季度|现车|内部|内幕|透底|曝光|公示|实锤|已确认|确认调整|更新|上线|下定|订车)", re.I),
    ),
    (
        "购车避坑干货",
        "新手买车通用清单",
        re.compile(r"(避坑|套路|合同|订金|定金|验车|提车|库存车|展车|新手买车|不会买车|注意事项|必看攻略|别踩坑|强制消费)", re.I),
    ),
    (
        "车型选购对比",
        "预算内车型推荐",
        re.compile(r"(怎么选|选哪|对比|横评|PK|pk|相比|高配|低配|版本选择|推荐|纠结|闭眼|轿车还是SUV|SUV还是轿车|预算.*选|家用.*选)", re.I),
    ),
    (
        "用车养护与功能教程",
        "车机/隐藏功能教程",
        re.compile(r"(车机|隐藏功能|功能教程|按键|空调|雨刮|蓝牙|导航|OTA|系统设置|新手.*上手)", re.I),
    ),
    (
        "用车养护与功能教程",
        "保养周期/保养省钱",
        re.compile(r"(保养|养护|维修|胎压|轮胎|刹车片|机油|滤芯|用车省钱|保养省钱)", re.I),
    ),
    (
        "用车养护与功能教程",
        "车险选购",
        re.compile(r"(车险|商业险|交强险|三者险|保险怎么买)", re.I),
    ),
    (
        "用车养护与功能教程",
        "新能源电池养护",
        re.compile(r"(电池养护|电池保养|充电技巧|快充|慢充|续航衰减|冬季续航|夏季续航)", re.I),
    ),
    (
        "汽车改装与外观分享",
        "车身贴膜/改色",
        re.compile(r"(贴膜|改色|车衣|隐形车衣|太阳膜|配色方案)", re.I),
    ),
    (
        "汽车改装与外观分享",
        "轮毂/外观件改装",
        re.compile(r"(轮毂|卡钳|包围|尾翼|外观件|改装件)", re.I),
    ),
    (
        "汽车改装与外观分享",
        "车载好物推荐",
        re.compile(r"(车载好物|脚垫|香薰|手机支架|充电器|收纳|配件推荐)", re.I),
    ),
    (
        "汽车改装与外观分享",
        "改装案例分享",
        re.compile(r"(改装|加装|内饰升级|氛围灯|灯光升级|改装案例)", re.I),
    ),
    (
        "实车静态/动态测评",
        "试驾体验",
        re.compile(r"(试驾|驾驶感受|开起来|好开|动态体验)", re.I),
    ),
    (
        "实车静态/动态测评",
        "油耗/电耗/续航实测",
        re.compile(r"(油耗|电耗|续航实测|真实续航|百公里|能耗)", re.I),
    ),
    (
        "实车静态/动态测评",
        "空间/座椅体验",
        re.compile(r"(空间|座椅|后排|后备箱|乘坐体验|零重力座椅)", re.I),
    ),
    (
        "实车静态/动态测评",
        "外观内饰实拍",
        re.compile(r"(实拍|外观内饰|内饰|外观|静态体验|到店看车)", re.I),
    ),
    (
        "汽车日常泛内容",
        "汽车热点快讯",
        re.compile(r"(热点|快讯|资讯|行业|事故|法规|新规|销量|新闻)", re.I),
    ),
    (
        "汽车日常泛内容",
        "车主日常/Vlog",
        re.compile(r"(日常|vlog|Vlog|通勤|上班|生活方式|打工人)", re.I),
    ),
]


def _strip_content_tag_number(value: str | None) -> str:
    cleaned = re.sub(r"^\s*\d+(?:\.\d+)?(?:[.)、:：-]|\s+)\s*", "", (value or "").strip())
    return XHS_CONTENT_TAG_SECONDARY_ALIASES.get(cleaned, cleaned)


def _extract_json_object(text: str) -> dict:
    cleaned = (text or "").strip()
    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s*```$", "", cleaned)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start >= 0 and end > start:
            return json.loads(cleaned[start : end + 1])
        raise


def _infer_xhs_content_tag_by_rules(note: XHSAccountNote) -> tuple[str, str] | None:
    title = note.title or ""

    # 只对标题做强规则截断；正文必须交给模型理解，避免关键词误伤。
    # 顺序上先处理费用核算、避坑、选购，再处理行情；泛化的“价格”不能单独决定标签。
    for primary, secondary, pattern in (
        _XHS_TAG_RULES[0],
        _XHS_TAG_RULES[2],
        _XHS_TAG_RULES[3],
        _XHS_TAG_RULES[1],
        *_XHS_TAG_RULES[4:],
    ):
        if pattern.search(title):
            return primary, secondary

    return None


def _split_xhs_content_and_hashtags(content: str | None) -> tuple[str, list[str]]:
    text = content or ""
    hashtags: list[str] = []

    def collect(match: re.Match[str]) -> str:
        tag = (match.group(1) or match.group(2) or "").strip()
        tag = re.sub(r"\[话题\]$", "", tag).strip()
        if tag and tag not in hashtags:
            hashtags.append(tag)
        return " "

    cleaned = re.sub(r"#\s*([^#\n\r]+?)\s*\[话题\]\s*#", collect, text)
    cleaned = re.sub(r"#\s*([^#\s，。！？、,.;；:：]+)", collect, cleaned)
    cleaned = re.sub(r"[ \t]{2,}", " ", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()
    return cleaned, hashtags


def _build_xhs_content_tagging_prompt(note: XHSAccountNote) -> str:
    cleaned_content, hashtags = _split_xhs_content_and_hashtags(note.content)
    post = {
        "id": str(note.id),
        "title": note.title or "",
        "content_without_hashtags": cleaned_content[:900],
        "hashtags": hashtags[:30],
    }
    return f"""你是资深小红书汽车内容运营分析师，擅长识别汽车销售线索内容的真实商业意图。

请根据输入的小红书笔记标题和正文，为每篇笔记打内容标签。

核心任务：
1. 每篇笔记只能选择 1 个一级标签。
2. 每篇笔记只能选择该一级标签下的 1 个二级标签。
3. 不允许多选，不允许自造标签，不允许输出标签体系以外的标签。
4. 一级标签和二级标签都只输出中文标签名称，不要带任何数字编号。
5. 判断依据是“这篇内容的主卖点/主转化目的是什么”，不是按正文里偶然出现的词分类。
6. 标题权重大于正文，正文开头权重大于结尾 CTA。
7. 输入里的 content_without_hashtags 已移除话题词；hashtags 是作者挂的流量话题，只能弱参考，绝不能因为话题词里出现“避坑/试驾/改装/车机/落地价/资讯”等词就改变主标签。

一级标签强制优先级，从上到下匹配，命中上层就不要再往下看：
1. 【购车落地价核算】只要主体在算钱：落地价、裸车价、全款、贷款、月供、首付、购置税、保险、上牌费、杂费、城市差价、本地底价、一对一算价。
2. 【新车行情爆料】主体在讲买车价格/政策变化：新政、政策、行情、优惠、降价、放价、报价、底价、团价、团购、补贴、大调、冲量、清仓、限时福利、置换、贴息、现车、内部、实锤、已确认、更新、上线、下定、订车。注意，“价格/最新价格”不是绝对归因词，必须结合上下文判断。
3. 【购车避坑干货】主体是通用买车防坑：4S店套路、贷款陷阱、合同/订金、捆绑装潢、库存车/展车、提车验车、新手买车清单。
4. 【车型选购对比】主体是选择决策：怎么选、选哪台、同价位谁更好、竞品对比、高低配/版本、新旧款、预算内推荐、家用/通勤场景推荐。
5. 【实车静态/动态测评】主体是车辆本身体验，并且没有价格/政策主卖点：外观内饰实拍、空间、座椅、车机体验、驾驶感受、底盘、油耗/电耗/续航、试驾、产品优缺点。
6. 【用车养护与功能教程】主体必须是提车后的使用：保养周期、车险怎么买、新能源电池养护、冬夏用车、故障提醒、车机隐藏功能、日常用车省钱。
7. 【汽车改装与外观分享】主体必须是改装/加装/颜值改造：贴膜、改色、轮毂、外观件、内饰升级、灯光氛围、车载好物、改装案例。
8. 【汽车日常泛内容】仅当前 7 类都不匹配时使用：车主日常、自驾随拍、车展门店现场、热点快讯、行业泛资讯、情绪文案、生活方式。

禁止误判规则：
1. 标题或正文出现“新政/行情/优惠/团价/放价/补贴/报价/底价/大调/冲量/实锤/已确认/政策”，不要打成【实车静态/动态测评】【用车养护与功能教程】【汽车改装与外观分享】【汽车日常泛内容】。
2. “价格/最新价格/多少钱”需要看语境：在费用拆解里归【购车落地价核算】；在选车对比里归【车型选购对比】；在政策优惠变化里才归【新车行情爆料】。
3. “保养省钱”“用车省钱”只有在提车后保养/充电/保险/维修/功能使用场景下才属于【用车养护与功能教程】；买车优惠省钱不属于养护。
4. “好看、颜值、外观、内饰”只有在贴膜/改色/改装/配色/实拍展示为主体时才属于【汽车改装与外观分享】；车型价格政策内容不属于改装。
5. “车机、空间、底盘、续航”只有在真实体验/测评为主体时才属于【实车静态/动态测评】；价格政策内容不属于测评。
6. “汽车日常泛内容”是兜底标签，不能承接任何明确买车转化内容。

反例校准：
- “极氪007GT 团价开启”“极氪8X季末放价”“理想L8 6月新政确认”“这个价了”“行情大调” => 新车行情爆料。
- “本地真实落地价”“全款/贷款明细”“月供多少”“保险上牌购置税” => 购车落地价核算。
- “男友买车思路”“第一次买车怎么选”“轿车还是SUV” => 车型选购对比或购车避坑干货，不要打成改装/养护。
- “提车后保养周期”“车机隐藏功能”“新能源电池夏季养护” => 用车养护与功能教程。
- “贴膜改色案例”“轮毂改装”“车载好物加装” => 汽车改装与外观分享。

标签体系：
新车行情爆料：官方调价/价格大调，终端优惠/门店隐藏价，月度购车政策，内部消息/实锤爆料，改款/配置调整，限时福利/节点活动，区域专属政策
购车落地价核算：全款落地价核算，贷款/月供方案核算，购车费用明细拆解，城市报价差异，本地底价/一对一算价，砍价技巧/谈价空间，杂费避坑/费用减免
车型选购对比：同级车型横向对比，竞品二选一，高低配/版本选择，新旧款车型对比，预算内车型推荐，家用/通勤场景选车，人群需求选车
实车静态/动态测评：外观内饰实拍，空间/座椅体验，车机/智能座舱体验，动力/底盘/操控体验，油耗/电耗/续航实测，试驾体验，产品优缺点总结
购车避坑干货：4S店套路拆解，贷款/金融隐形消费，合同/订金避坑，捆绑装潢/强制消费，库存车/展车辨别，提车验车流程，新手买车通用清单
用车养护与功能教程：车机/隐藏功能教程，保养周期/保养省钱，车险选购，新能源电池养护，夏季/冬季用车技巧，故障提醒/常见问题，日常用车省钱技巧
汽车改装与外观分享：车身贴膜/改色，轮毂/外观件改装，内饰升级，车载好物推荐，灯光/氛围感升级，改装案例分享，颜值实拍/配色展示
汽车日常泛内容：车主日常/Vlog，自驾出行/爱车随拍，车展/门店现场，汽车热点快讯，品牌/行业泛资讯，情绪文案/生活方式，无明确目的兜底内容

只返回 JSON，不要 markdown，不要解释。
返回结构：
{{"items":[{{"id":"输入里的 id","primary_tag":"一级标签名称","secondary_tag":"二级标签名称","confidence":0.0,"reason":"一句话说明"}}]}}

输入笔记：
{json.dumps([post], ensure_ascii=False)}
"""


async def _tag_xhs_account_note_with_model(client: httpx.AsyncClient, note: XHSAccountNote) -> tuple[str, str]:
    rule_tag = _infer_xhs_content_tag_by_rules(note)
    if rule_tag:
        return rule_tag

    api_base = (settings.xhs_content_tagging_api_base_url or "").rstrip("/")
    api_key = (settings.xhs_content_tagging_api_key or "").strip()
    if not api_base or not api_key:
        raise RuntimeError("内容标签模型配置缺失")
    response = await client.post(
        f"{api_base}/chat/completions",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json={
            "model": settings.xhs_content_tagging_model or "gpt-5.4-mini",
            "temperature": 0.1,
            "max_completion_tokens": 900,
            "messages": [{"role": "user", "content": _build_xhs_content_tagging_prompt(note)}],
        },
    )
    response.raise_for_status()
    envelope = response.json()
    if envelope.get("error"):
        raise RuntimeError(envelope["error"].get("message") or "模型请求失败")
    content = envelope.get("choices", [{}])[0].get("message", {}).get("content", "")
    parsed = _extract_json_object(content)
    item = (parsed.get("items") or [{}])[0]
    primary = _strip_content_tag_number(item.get("primary_tag"))
    secondary = _strip_content_tag_number(item.get("secondary_tag"))
    if primary not in XHS_CONTENT_TAG_PRIMARY_LABELS:
        raise RuntimeError(f"一级标签无效：{primary}")
    if secondary not in XHS_CONTENT_TAG_SECONDARY_LABELS:
        raise RuntimeError(f"二级标签无效：{secondary}")
    if secondary not in XHS_CONTENT_TAG_TREE.get(primary, set()):
        raise RuntimeError(f"二级标签不属于一级标签：{primary} / {secondary}")
    return primary, secondary


async def _load_account_note_out(db: AsyncSession, note_id: int) -> XHSAccountNote | None:
    stmt = (
        select(XHSAccountNote)
        .where(XHSAccountNote.id == note_id)
        .options(
            selectinload(XHSAccountNote.environment),
            selectinload(XHSAccountNote.assigned_runner_environment),
        )
    )
    return (await db.execute(stmt)).scalar_one_or_none()


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _parse_environment_ids(value: str | None) -> list[int]:
    if not value:
        return []
    result: list[int] = []
    for item in str(value).split(","):
        try:
            number = int(item.strip())
        except (TypeError, ValueError):
            continue
        if number > 0 and number not in result:
            result.append(number)
    return result


def _target_ids_from_runner_assignments(value: str | None) -> list[int]:
    if not value:
        return []
    try:
        payload = json.loads(value)
    except (TypeError, ValueError, json.JSONDecodeError):
        return []
    if not isinstance(payload, dict):
        return []
    result: list[int] = []
    for env_ids in payload.values():
        if not isinstance(env_ids, list):
            continue
        for env_id in env_ids:
            try:
                number = int(env_id)
            except (TypeError, ValueError):
                continue
            if number > 0 and number not in result:
                result.append(number)
    return result


async def _resolve_sync_history_targets(
    db: AsyncSession,
    *,
    sync_kind: str,
    environment_id: int | None,
    target_environment_ids: str | None = None,
    runner_account_assignments: str | None = None,
) -> list[XHSEnvironment]:
    target_ids = _parse_environment_ids(target_environment_ids)
    if not target_ids:
        target_ids = _target_ids_from_runner_assignments(runner_account_assignments)
    if not target_ids and environment_id:
        target_ids = [environment_id]

    stmt = select(XHSEnvironment).where(XHSEnvironment.status == "active")
    if target_ids:
        stmt = stmt.where(XHSEnvironment.id.in_(target_ids))
    elif sync_kind in {"posts", "engagement"}:
        stmt = stmt.where(XHSEnvironment.is_sync_runner.is_(False))
    else:
        # 详情同步按帖子选取，无法在提交时可靠预判最终会命中的账号。
        return []
    return list((await db.execute(stmt.order_by(XHSEnvironment.account_name.asc()))).scalars().all())


async def _create_sync_history_run(
    db: AsyncSession,
    *,
    job: dict,
    sync_kind: str,
    source: str,
    requested_by_user_id: int,
    request_config: dict,
    targets: list[XHSEnvironment],
    parent_run_id: int | None = None,
) -> XHSAccountSyncRun:
    run = XHSAccountSyncRun(
        job_id=str(job["job_id"]),
        sync_kind=sync_kind,
        source=source,
        status="queued",
        requested_by_user_id=requested_by_user_id,
        parent_run_id=parent_run_id,
        request_config=request_config,
        message="任务排队中",
    )
    db.add(run)
    await db.flush()
    for env in targets:
        db.add(
            XHSAccountSyncRunItem(
                run_id=run.id,
                environment_id=env.id,
                account_name=(env.account_name or "").strip(),
                status="queued",
            )
        )
    await db.commit()
    job["history_run_id"] = run.id
    if sync_kind == "posts":
        await mirror_homepage_sync_shadow_safely(run.id, legacy_job=job)
    elif sync_kind in {"engagement", "details"}:
        await mirror_account_data_sync_shadow_safely(run.id, legacy_job=job)
    return run


async def _mirror_account_sync_shadow_safely(
    history_run_id: int | None,
    *,
    legacy_job: dict,
) -> int | None:
    job_type = str(legacy_job.get("job_type") or "")
    if job_type == "account_notes_sync":
        return await mirror_homepage_sync_shadow_safely(
            history_run_id,
            legacy_job=legacy_job,
        )
    if job_type in {"account_note_engagement_sync", "account_note_details_sync"}:
        return await mirror_account_data_sync_shadow_safely(
            history_run_id,
            legacy_job=legacy_job,
        )
    return None


async def _update_sync_history_from_progress(history_run_id: int | None, payload: dict) -> None:
    if not history_run_id:
        return
    phase = str(payload.get("phase") or "")
    account_name = str(payload.get("account_name") or "").strip()
    now = datetime.now()
    async with async_session() as session:
        run = (await session.execute(select(XHSAccountSyncRun).where(XHSAccountSyncRun.id == history_run_id))).scalar_one_or_none()
        if run is None:
            return
        if run.status == "queued":
            run.status = "running"
            run.started_at = now
        run.message = str(payload.get("detail") or run.message or "")
        if run.sync_kind == "details" and payload.get("current_note_id"):
            try:
                note_id = int(payload["current_note_id"])
            except (TypeError, ValueError):
                note_id = 0
            note = None
            if note_id > 0:
                note = (await session.execute(select(XHSAccountNote).where(XHSAccountNote.id == note_id))).scalar_one_or_none()
            if note is not None:
                environment = (
                    await session.execute(select(XHSEnvironment).where(XHSEnvironment.id == note.environment_id))
                ).scalar_one_or_none()
                account_name = (getattr(environment, "account_name", None) or note.account_name or "未知账号").strip()
                item = (
                    await session.execute(
                        select(XHSAccountSyncRunItem).where(
                            XHSAccountSyncRunItem.run_id == history_run_id,
                            XHSAccountSyncRunItem.environment_id == note.environment_id,
                        )
                    )
                ).scalars().first()
                if item is None:
                    item = XHSAccountSyncRunItem(
                        run_id=history_run_id,
                        environment_id=note.environment_id,
                        account_name=account_name,
                        status="running",
                        started_at=now,
                        result={"succeeded_note_count": 0, "failed_note_ids": []},
                    )
                    session.add(item)
                    await session.flush()
                result = dict(item.result or {})
                if bool(payload.get("current_note_succeeded")):
                    succeeded_note_ids = {int(value) for value in result.get("succeeded_note_ids") or [] if str(value).isdigit()}
                    if note_id not in succeeded_note_ids:
                        succeeded_note_ids.add(note_id)
                        result["succeeded_note_count"] = int(result.get("succeeded_note_count") or 0) + 1
                    result["succeeded_note_ids"] = sorted(succeeded_note_ids)
                    if item.status != "failed":
                        item.status = "succeeded"
                else:
                    failed_note_ids = {int(value) for value in result.get("failed_note_ids") or [] if str(value).isdigit()}
                    failed_note_ids.add(note_id)
                    result["failed_note_ids"] = sorted(failed_note_ids)
                    item.status = "failed"
                    item.error = str(payload.get("current_note_error") or "帖子详情同步失败")
                item.result = result
                item.message = str(payload.get("detail") or "")
                item.finished_at = now
        if account_name:
            candidates = list(
                (
                    await session.execute(
                        select(XHSAccountSyncRunItem)
                        .where(XHSAccountSyncRunItem.run_id == history_run_id)
                        .order_by(XHSAccountSyncRunItem.id.asc())
                    )
                ).scalars().all()
            )
            item = next((candidate for candidate in candidates if (candidate.account_name or "").strip() == account_name), None)
            if item is not None:
                if phase in {"opening_runner", "fetching_account_posts", "fetching_account_engagements", "syncing_account_engagements"} and item.status == "queued":
                    item.status = "running"
                    item.started_at = now
                elif phase in {"account_posts_completed", "account_engagement_completed", "account_engagement_skipped"}:
                    item.status = "succeeded"
                    item.message = str(payload.get("detail") or "同步完成")
                    item.error = None
                    item.finished_at = now
                    item.result = {
                        key: payload.get(key)
                        for key in ("created_notes", "updated_notes", "metric_synced_notes", "exported_rows", "unmatched_notes", "duplicate_title_skips")
                        if payload.get(key) is not None
                    }
                elif phase in {"account_posts_failed", "account_engagement_failed"}:
                    item.status = "failed"
                    item.message = str(payload.get("detail") or "同步失败")
                    item.error = str(payload.get("error") or item.message)
                    item.finished_at = now
        await session.commit()


async def _apply_detail_history_result(history_run_id: int | None, result: dict | None) -> None:
    if not history_run_id or not isinstance(result, dict):
        return
    for note_id in result.get("synced_note_ids") or []:
        await _update_sync_history_from_progress(
            history_run_id,
            {"phase": "runner_processing", "current_note_id": note_id, "current_note_succeeded": True, "detail": "帖子详情同步完成"},
        )
    for note_id in result.get("failed_note_ids") or []:
        await _update_sync_history_from_progress(
            history_run_id,
            {"phase": "runner_processing", "current_note_id": note_id, "current_note_succeeded": False, "current_note_error": "帖子详情同步失败", "detail": "帖子详情同步失败"},
        )


async def _finish_sync_history_run(
    history_run_id: int | None,
    *,
    status: str,
    message: str,
    error: str | None = None,
) -> None:
    if not history_run_id:
        return
    now = datetime.now()
    async with async_session() as session:
        run = (await session.execute(select(XHSAccountSyncRun).where(XHSAccountSyncRun.id == history_run_id))).scalar_one_or_none()
        if run is None:
            return
        run.status = status
        run.message = message
        run.error = error
        run.finished_at = now
        items = list((await session.execute(select(XHSAccountSyncRunItem).where(XHSAccountSyncRunItem.run_id == history_run_id))).scalars().all())
        for item in items:
            if item.status in {"queued", "running"}:
                if status == "cancelled":
                    item.status = "cancelled"
                    item.error = None
                    item.message = message or "任务已中止"
                else:
                    item.status = "failed"
                    item.error = error or "任务未返回该账号的完成回执，请重新运行"
                    item.message = "未确认完成"
                item.finished_at = now
        await session.commit()


def _serialize_sync_history_run(run: XHSAccountSyncRun, *, include_items: bool = True) -> dict:
    items = list(run.items or [])
    return {
        "id": run.id,
        "job_id": run.job_id,
        "sync_kind": run.sync_kind,
        "source": run.source,
        "status": run.status,
        "message": run.message,
        "error": run.error,
        "parent_run_id": run.parent_run_id,
        "request_config": run.request_config or {},
        "created_at": run.created_at.isoformat() if run.created_at else None,
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "finished_at": run.finished_at.isoformat() if run.finished_at else None,
        "summary": {
            "total": len(items),
            "succeeded": sum(item.status == "succeeded" for item in items),
            "failed": sum(item.status == "failed" for item in items),
            "running": sum(item.status in {"queued", "running"} for item in items),
        },
        "items": [
            {
                "id": item.id,
                "environment_id": item.environment_id,
                "account_name": item.account_name,
                "status": item.status,
                "message": item.message,
                "error": item.error,
                "result": item.result or {},
                "started_at": item.started_at.isoformat() if item.started_at else None,
                "finished_at": item.finished_at.isoformat() if item.finished_at else None,
            }
            for item in items
        ] if include_items else [],
    }


def _new_job(
    job_type: str,
    *,
    environment_id: int | None,
    target_environment_ids: str | None = None,
    scrape_environment_id: int | None = None,
    scrape_environment_ids: str | None = None,
    sync_account_limit: int | None = None,
    runner_account_assignments: str | None = None,
    sync_mode: str | None = None,
    sync_limit: int | None = None,
    sync_limit_per_runner: int | None = None,
    pause_seconds_min: float | None = None,
    pause_seconds_max: float | None = None,
    max_post_age_days: int | None = None,
    report_type: str | None = None,
    account_id: str | None = None,
    account_name: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    days: int | None = None,
) -> dict:
    job_id = uuid.uuid4().hex
    now = _now_iso()
    job = {
        "job_id": job_id,
        "job_type": job_type,
        "environment_id": environment_id,
        "target_environment_ids": target_environment_ids,
        "scrape_environment_id": scrape_environment_id,
        "scrape_environment_ids": scrape_environment_ids,
        "sync_account_limit": sync_account_limit,
        "runner_account_assignments": runner_account_assignments,
        "sync_mode": sync_mode,
        "sync_limit": sync_limit,
        "sync_limit_per_runner": sync_limit_per_runner,
        "pause_seconds_min": pause_seconds_min,
        "pause_seconds_max": pause_seconds_max,
        "max_post_age_days": max_post_age_days,
        "report_type": report_type,
        "account_id": account_id,
        "account_name": account_name,
        "start_date": start_date,
        "end_date": end_date,
        "days": days,
        "status": "queued",
        "cancel_requested": False,
        "message": "任务排队中",
        "progress": {
            "phase": "queued",
            "detail": "任务排队中",
            "current": 0,
            "total": 0,
            "percent": 0,
            "updated_at": now,
        },
        "result": None,
        "error": None,
        "created_at": now,
        "updated_at": now,
        "started_at": None,
        "finished_at": None,
    }
    XHS_BACKGROUND_JOBS[job_id] = job
    return job


def _update_job_progress(job: dict, **patch) -> None:
    now = _now_iso()
    progress = dict(job.get("progress") or {})
    progress.update({key: value for key, value in patch.items() if value is not None})
    progress["updated_at"] = now
    job["progress"] = progress
    job["updated_at"] = now
    detail = progress.get("detail")
    if detail and job.get("status") in {"queued", "running"}:
        job["message"] = str(detail)


def _build_sync_job_result_from_progress(job: dict, *, details: bool) -> dict:
    progress = dict(job.get("progress") or {})
    if details:
        total_notes = int(progress.get("total") or 0)
        synced_notes = int(progress.get("synced_notes") or 0)
        failed_notes = int(progress.get("failed_notes") or 0)
        return {
            "total_notes": total_notes,
            "matched_notes": int(progress.get("matched_notes") or total_notes),
            "synced_notes": synced_notes,
            "failed_notes": failed_notes,
            "skipped_notes": int(progress.get("skipped_notes") or 0),
        }
    return {
        "synced_accounts": int(progress.get("synced_accounts") or 0),
        "created_notes": int(progress.get("created_notes") or 0),
        "updated_notes": int(progress.get("updated_notes") or 0),
        "metric_synced_notes": int(progress.get("metric_synced_notes") or 0),
        "total_notes": int(progress.get("total_notes") or 0),
        "exported_rows": int(progress.get("exported_rows") or 0),
        "unmatched_notes": int(progress.get("unmatched_notes") or 0),
        "duplicate_title_skips": int(progress.get("duplicate_title_skips") or 0),
    }


def _finish_sync_job(job: dict, *, status: str, message: str, details: bool, error: str | None = None) -> None:
    job["status"] = status
    job["message"] = message
    job["error"] = error
    job["result"] = _build_sync_job_result_from_progress(job, details=details)
    job["updated_at"] = _now_iso()
    job["finished_at"] = _now_iso()
    _update_job_progress(job, phase=status, detail=message)


async def _run_account_note_sync_job(
    job_id: str,
    *,
    user_id: int,
    environment_id: int | None,
    target_environment_ids: str | None = None,
    scrape_environment_id: int | None,
    scrape_environment_ids: str | None = None,
    sync_account_limit: int | None = None,
    runner_account_assignments: str | None = None,
    details: bool,
    sync_mode: str = "all",
    sync_limit: int | None = None,
    sync_limit_per_runner: int | None = None,
    pause_seconds_min: float | None = None,
    pause_seconds_max: float | None = None,
    max_post_age_days: int | None = None,
    engagement_only: bool = False,
    history_run_id: int | None = None,
    target_note_ids: str | None = None,
) -> None:
    job = XHS_BACKGROUND_JOBS[job_id]
    sync_kind = "details" if details else "engagement" if engagement_only else "posts"
    if job.get("cancel_requested"):
        _finish_sync_job(job, status="cancelled", message="任务已中止", details=details)
        await _finish_sync_history_run(history_run_id, status="cancelled", message="任务已中止")
        await _mirror_account_sync_shadow_safely(history_run_id, legacy_job=job)
        XHS_BACKGROUND_JOB_TASKS.pop(job_id, None)
        return
    job["status"] = "running"
    job["started_at"] = _now_iso()
    job["updated_at"] = _now_iso()
    if engagement_only:
        job["message"] = "正在同步账号互动数据"
    else:
        job["message"] = "正在同步账号帖子数据" if details else "正在同步账号帖子"
    _update_job_progress(
        job,
        phase="running",
        detail=job["message"],
        current=0,
        total=0,
        percent=0,
    )
    await _mirror_account_sync_shadow_safely(history_run_id, legacy_job=job)
    try:
        async def report_progress(payload: dict) -> None:
            current_job = XHS_BACKGROUND_JOBS.get(job_id)
            if not current_job:
                return
            _update_job_progress(current_job, **payload)
            await _update_sync_history_from_progress(history_run_id, payload)
            if str(payload.get("phase") or "") in SHADOW_PROGRESS_PHASES_BY_KIND[sync_kind]:
                await _mirror_account_sync_shadow_safely(
                    history_run_id,
                    legacy_job=current_job,
                )

        async with async_session() as session:
            user = (await session.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
            if not user:
                raise RuntimeError("用户不存在")
            service = XHSService(session)
            if engagement_only:
                result = await service.sync_account_note_engagements(
                    user=user,
                    environment_id=environment_id,
                    target_environment_ids=target_environment_ids,
                    sync_account_limit=sync_account_limit,
                    runner_account_assignments=runner_account_assignments,
                    progress_callback=report_progress,
                    cancel_check=lambda: bool(XHS_BACKGROUND_JOBS.get(job_id, {}).get("cancel_requested")),
                )
            elif details:
                result = await service.sync_existing_account_note_stats(
                    environment_id=environment_id,
                    target_note_ids=target_note_ids,
                    scrape_environment_id=scrape_environment_id,
                    scrape_environment_ids=scrape_environment_ids,
                    sync_mode=sync_mode,
                    sync_limit=sync_limit,
                    sync_limit_per_runner=sync_limit_per_runner,
                    pause_seconds_min=pause_seconds_min,
                    pause_seconds_max=pause_seconds_max,
                    max_post_age_days=max_post_age_days,
                    progress_callback=report_progress,
                    cancel_check=lambda: bool(XHS_BACKGROUND_JOBS.get(job_id, {}).get("cancel_requested")),
                )
            else:
                result = await service.sync_account_notes(
                    user=user,
                    environment_id=environment_id,
                    scrape_environment_id=scrape_environment_id,
                    scrape_environment_ids=scrape_environment_ids,
                    sync_account_limit=sync_account_limit,
                    runner_account_assignments=runner_account_assignments,
                    limit_per_env=60,
                    progress_callback=report_progress,
                    cancel_check=lambda: bool(XHS_BACKGROUND_JOBS.get(job_id, {}).get("cancel_requested")),
                )
        job["status"] = "succeeded"
        if engagement_only:
            job["message"] = "账号互动同步完成"
        else:
            job["message"] = "账号帖子数据同步完成" if details else "账号帖子同步完成"
        job["result"] = result
        job["updated_at"] = _now_iso()
        job["finished_at"] = _now_iso()
        if details:
            await _apply_detail_history_result(history_run_id, result if isinstance(result, dict) else None)
        _update_job_progress(
            job,
            phase="succeeded",
            detail=job["message"],
            current=int(result.get("total_notes") or result.get("synced_accounts") or 0) if isinstance(result, dict) else 0,
            total=int(result.get("total_notes") or result.get("synced_accounts") or 0) if isinstance(result, dict) else 0,
            percent=100,
            synced_notes=int(result.get("synced_notes") or 0) if isinstance(result, dict) else 0,
            failed_notes=int(result.get("failed_notes") or 0) if isinstance(result, dict) else 0,
            created_notes=int(result.get("created_notes") or 0) if isinstance(result, dict) else 0,
            updated_notes=int(result.get("updated_notes") or 0) if isinstance(result, dict) else 0,
            synced_accounts=int(result.get("synced_accounts") or 0) if isinstance(result, dict) else 0,
            metric_synced_notes=int(result.get("metric_synced_notes") or 0) if isinstance(result, dict) else 0,
        )
        await _finish_sync_history_run(history_run_id, status="succeeded", message=job["message"])
        await _mirror_account_sync_shadow_safely(history_run_id, legacy_job=job)
    except SyncJobCancelled as exc:
        _finish_sync_job(job, status="cancelled", message=str(exc), details=details)
        await _finish_sync_history_run(history_run_id, status="cancelled", message=str(exc))
        await _mirror_account_sync_shadow_safely(history_run_id, legacy_job=job)
    except Exception as exc:
        logger.exception("账号帖子同步后台任务失败: job_id=%s details=%s", job_id, details)
        job["status"] = "failed"
        job["message"] = str(exc)
        job["error"] = str(exc)
        job["updated_at"] = _now_iso()
        job["finished_at"] = _now_iso()
        _update_job_progress(job, phase="failed", detail=str(exc))
        await _finish_sync_history_run(history_run_id, status="failed", message=str(exc), error=str(exc))
        await _mirror_account_sync_shadow_safely(history_run_id, legacy_job=job)
    finally:
        XHS_BACKGROUND_JOB_TASKS.pop(job_id, None)


async def _run_report_refresh_job(
    job_id: str,
    *,
    report_type: str,
    account_id: str | None,
    account_name: str | None,
    start_date: str | None,
    end_date: str | None,
    days: int,
    history_run_id: int | None = None,
) -> None:
    job = XHS_BACKGROUND_JOBS[job_id]
    job["status"] = "running"
    job["started_at"] = _now_iso()
    job["updated_at"] = _now_iso()
    job["message"] = f"正在刷新{report_type}报表缓存"
    await mark_report_refresh_running_safely(history_run_id)
    try:
        async with async_session() as session:
            service = XHSService(session)
            result = await service.refresh_jg_report_cache(
                report_type=report_type,
                account_id=account_id,
                account_name=account_name,
                start_date=start_date,
                end_date=end_date,
                days=days,
            )
        await record_report_refresh_result_safely(
            history_run_id,
            report_type=report_type,
            status="succeeded",
            result=result,
        )
        job["status"] = "succeeded"
        job["message"] = "报表缓存刷新完成"
        job["result"] = result
        job["updated_at"] = _now_iso()
        job["finished_at"] = _now_iso()
        await finish_report_refresh_run_safely(
            history_run_id,
            status="succeeded",
            message=job["message"],
        )
    except Exception as exc:
        logger.exception("报表缓存刷新后台任务失败: job_id=%s report_type=%s", job_id, report_type)
        job["status"] = "failed"
        job["message"] = str(exc)
        job["error"] = str(exc)
        job["updated_at"] = _now_iso()
        job["finished_at"] = _now_iso()
        await record_report_refresh_result_safely(
            history_run_id,
            report_type=report_type,
            status="failed",
            error=str(exc),
        )
        await finish_report_refresh_run_safely(
            history_run_id,
            status="failed",
            message=job["message"],
            error=str(exc),
        )

REPORT_EXPORT_COLUMNS = [
    ("账户名称", "account_name"),
    ("投放ID", "account_id"),
    ("时间", "time"),
    ("计划名称(标的名称)", "campaign_name"),
    ("计划ID(标的ID)", "campaign_id"),
    ("消费", "fee"),
    ("展现量", "impression"),
    ("点击量", "click"),
    ("点赞", "like"),
    ("评论", "comment"),
    ("收藏", "collect"),
    ("关注", "follow"),
    ("分享", "share"),
    ("互动量", "interaction"),
    ("行动按钮点击量", "action_button_click"),
    ("私信进线数", "message_consult"),
    ("私信留资数", "msg_leads_num"),
    ("私信进线人数", "message_user"),
    ("私信留资人数", "msg_leads_user_cnt"),
    ("私信开口数", "initiative_message"),
    ("私信开口人数", "msg_chat_user_cnt"),
    ("私信开口条数", "message"),
]

CREATIVE_REPORT_EXPORT_COLUMNS = [
    ("日期", "time"),
    ("笔记/素材", "note_material"),
    ("标记", "ai_origin_type"),
    ("单元名称", "unit_name"),
    ("单元ID", "unit_id"),
    ("计划名称", "campaign_name"),
    ("计划ID", "campaign_id"),
    ("消费", "fee"),
    ("展现量", "impression"),
    ("点击量", "click"),
    ("点击率", "ctr"),
    ("平均点击成本", "cpc"),
    ("平均千次展示费用", "cpm"),
    ("互动量", "interaction"),
    ("平均互动成本", "avg_interaction_cost"),
    ("5s播放量", "play_5s"),
    ("私信进线数", "message_consult"),
    ("私信开口数", "initiative_message"),
    ("私信留资数", "msg_leads_num"),
    ("私信进线成本", "message_consult_cost"),
    ("私信开口成本", "initiative_message_cost"),
    ("私信留资成本", "msg_leads_cost"),
    ("店铺成交订单量(15日)", "shop_pay_order_num_15d"),
    ("店铺成交订单转化率(15日)", "shop_pay_order_cvr_15d"),
]

EASY_NOTE_REPORT_EXPORT_COLUMNS = [
    ("账户名称", "account_name"),
    ("投放ID", "account_id"),
    ("时间", "time"),
    ("笔记标题", "note_title"),
    ("笔记ID", "note_id"),
    ("创意名称", "creativity_name"),
    ("创意ID", "creativity_id"),
    ("消费", "fee"),
    ("展现量", "impression"),
    ("点击量", "click"),
    ("点击率", "ctr"),
    ("点赞", "like"),
    ("评论", "comment"),
    ("收藏", "collect"),
    ("关注", "follow"),
    ("分享", "share"),
    ("互动量", "interaction"),
    ("行动按钮点击量", "action_button_click"),
    ("私信进线数", "message_consult"),
    ("私信留资数", "msg_leads_num"),
    ("私信进线人数", "message_user"),
    ("私信留资人数", "msg_leads_user_cnt"),
    ("私信开口数", "initiative_message"),
    ("私信开口人数", "msg_chat_user_cnt"),
    ("私信开口条数", "message"),
]

STANDARD_NOTE_REPORT_EXPORT_COLUMNS = [
    ("账户名称", "account_name"),
    ("投放ID", "account_id"),
    ("时间", "time"),
    ("笔记图片", "note_image"),
    ("笔记标题", "note_title"),
    ("笔记ID", "note_id"),
    ("消费", "fee"),
    ("展现量", "impression"),
    ("点击量", "click"),
    ("点击率", "ctr"),
    ("点赞", "like"),
    ("评论", "comment"),
    ("收藏", "collect"),
    ("关注", "follow"),
    ("分享", "share"),
    ("互动量", "interaction"),
    ("行动按钮点击量", "action_button_click"),
    ("私信进线数", "message_consult"),
    ("私信留资数", "msg_leads_num"),
    ("私信进线人数", "message_user"),
    ("私信留资人数", "msg_leads_user_cnt"),
    ("私信开口数", "initiative_message"),
    ("私信开口人数", "msg_chat_user_cnt"),
    ("私信开口条数", "message"),
]

REPORT_EXPORT_COLUMNS = [
    ("账户名称", "account_name"),
    ("投放ID", "account_id"),
    ("时间", "time"),
    ("计划名称(标的名称)", "campaign_name"),
    ("计划ID(标的ID)", "campaign_id"),
    ("消费", "fee"),
    ("展现量", "impression"),
    ("点击量", "click"),
    ("点赞", "like"),
    ("评论", "comment"),
    ("收藏", "collect"),
    ("关注", "follow"),
    ("分享", "share"),
    ("互动量", "interaction"),
    ("行动按钮点击量", "action_button_click"),
    ("私信进线数", "message_consult"),
    ("私信进线人数", "message_user"),
    ("私信留资数", "msg_leads_num"),
    ("私信留资人数", "msg_leads_user_cnt"),
    ("私信开口数", "initiative_message"),
    ("私信开口人数", "msg_chat_user_cnt"),
    ("私信开口条数", "message"),
]

REPORT_NUMERIC_KEYS = {
    "fee",
    "impression",
    "click",
    "like",
    "comment",
    "collect",
    "follow",
    "share",
    "interaction",
    "action_button_click",
    "message_consult",
    "msg_leads_num",
    "message_user",
    "msg_leads_user_cnt",
    "initiative_message",
    "msg_chat_user_cnt",
    "message",
}

AI_ORIGIN_EXPORT_LABELS = {
    "manual": "纯手工",
    "text_ai": "仅文案 AI",
    "image_ai": "仅图片 AI",
    "all_ai": "图文都 AI",
}


def _export_ai_origin_value(row: dict) -> str:
    matched = bool(row.get("account_note_matched"))
    value = str(row.get("ai_origin_type") or "").strip()
    if not matched:
        return "未找到"
    if not value:
        return "未设置"
    return AI_ORIGIN_EXPORT_LABELS.get(value, "未设置")


def _export_value(row: dict, key: str):
    if key == "ai_origin_type":
        return _export_ai_origin_value(row)
    value = row.get(key, "")
    if key in REPORT_NUMERIC_KEYS and value in (None, ""):
        return 0
    return value


def _split_csv(value: str | None) -> list[str]:
    if not value:
        return []
    return [item.strip() for item in str(value).split(",") if item.strip()]


def _require_xhs_ad_dashboard_access(user: User) -> None:
    if not has_role(user, "admin", "xhs_lead", "buyer"):
        raise HTTPException(status_code=403, detail="无权访问小红书投流看板")


def _resolve_xhs_ad_dashboard_viewer_scope(user: User, buyer_user_id: int | None) -> tuple[str, int | None]:
    if has_role(user, "admin", "xhs_lead"):
        return "all", buyer_user_id
    if has_role(user, "buyer"):
        own_user_id = int(user.id)
        if buyer_user_id and int(buyer_user_id) != own_user_id:
            raise HTTPException(status_code=403, detail="投手只能查看自己负责的广告账户")
        return f"buyer:self:{own_user_id}", own_user_id
    return "denied", buyer_user_id


def _require_xhs_insights_access(user: User) -> None:
    if not has_role(user, "admin", "xhs_lead", "xhs_ops", "brand_lead", "brand_ops"):
        raise HTTPException(status_code=403, detail="无权访问小红书运营数据")


def _resolve_xhs_insights_owner_scope(user: User) -> tuple[set[str] | None, set[int] | None]:
    """Leads see their department; operators only see their own assignments."""
    roles = set(get_user_roles(user))
    if ROLE_ADMIN in roles:
        return None, None
    department_roles: set[str] = set()
    if ROLE_XHS_LEAD in roles:
        department_roles.update({ROLE_XHS_LEAD, ROLE_XHS_OPS})
    if ROLE_BRAND_LEAD in roles:
        department_roles.update({ROLE_BRAND_LEAD, ROLE_BRAND_OPS})
    if department_roles:
        return department_roles, None
    return None, {int(user.id)}


class WorkerEditRequest(BaseModel):
    title: str
    content: str
    tags: list[str] = []


def require_xhs_worker_token(x_xhs_worker_token: str | None = Header(default=None)):
    expected = (getattr(settings, "xhs_worker_internal_token", "") or "").strip()
    if not expected:
        raise HTTPException(status_code=503, detail="XHS Worker internal token 未配置")
    if x_xhs_worker_token != expected:
        raise HTTPException(status_code=403, detail="XHS Worker internal token 无效")


@router.post("/upload-image")
async def upload_image(
    files: list[UploadFile] = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """上传图片，支持单张或多张，返回本地绝对路径列表"""
    service = XHSService(db)
    uploaded: list[dict[str, str]] = []
    for file in files:
        content = await file.read()
        if len(content) > 20 * 1024 * 1024:  # 20MB
            raise HTTPException(status_code=400, detail=f"{file.filename or '图片'} 大小超过20MB限制")

        ct = file.content_type or ""
        if not ct.startswith("image/"):
            raise HTTPException(status_code=400, detail=f"{file.filename or '文件'} 不是图片文件")

        file_path = await service.save_upload_image(content, file.filename or "upload.jpg")
        uploaded.append({
            "file_name": file.filename or "upload.jpg",
            "file_path": service.local_upload_path_to_url(file_path),
        })

    if len(uploaded) == 1:
        return ApiResponse(data=uploaded[0])
    return ApiResponse(data={"files": uploaded})


@router.get("/environments")
async def list_environments(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取可用的云登环境列表"""
    service = XHSService(db)
    envs = await service.list_environments(current_user)

    # 如果本地还没有同步过环境，先同步
    if not envs and current_user.role == "admin":
        await service.sync_environments_from_yundeng()
        envs = await service.list_environments(current_user)

    serialized_envs: list[EnvironmentOut] = []
    for env in envs:
        item = EnvironmentOut.model_validate(env)
        if current_user.role != "admin":
            item.sync_cloud_session_id = None
            item.sync_cloud_api_key = None
            item.sync_cloud_update_config = None
            item.sync_browser_start_config = None
        serialized_envs.append(item)

    return ApiResponse(data=serialized_envs)


@router.post("/publish")
async def publish_post(
    req: PublishRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """发布小红书帖子"""
    service = XHSService(db)

    env = await service.get_environment(req.environment_id)
    if not env:
        raise HTTPException(status_code=404, detail="云登环境不存在")

    # 权限检查
    envs = await service.list_environments(current_user)
    if env not in envs and current_user.role != "admin":
        raise HTTPException(status_code=403, detail="无权使用该环境")

    try:
        post = await service.publish(
            user=current_user,
            env=env,
            title=req.title,
            content=req.content,
            image_paths=req.image_paths,
            tags=req.tags,
            ai_origin_type=req.ai_origin_type,
            is_original=req.is_original,
            visibility=req.visibility,
            scheduled_at=req.scheduled_at,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except RuntimeError as e:
        logger.warning(f"发布接口运行时异常: env_id={req.environment_id}, error={e}")
        return ApiResponse(code=1, message=str(e) or "发布失败，请稍后重试")
    except Exception as e:
        logger.error(f"发布接口异常: env_id={req.environment_id}, error={e}", exc_info=True)
        return ApiResponse(code=1, message="发布失败，请检查环境或稍后重试")

    if post.status == "scheduled":
        message = "定时发布已创建"
    elif post.status == "publishing":
        message = "已提交发布任务"
    elif post.status == "failed":
        return ApiResponse(
            code=1,
            data=PublishOut(
                post_id=post.id,
                feed_id=post.feed_id,
                status=post.status,
                scheduled_at=post.scheduled_at,
            ),
            message="发布失败，请检查环境或稍后重试",
        )
    else:
        message = "发布成功"
    return ApiResponse(
        data=PublishOut(
            post_id=post.id,
            feed_id=post.feed_id,
            status=post.status,
            scheduled_at=post.scheduled_at,
        ),
        message=message,
    )


@router.get("/posts")
async def list_posts(
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=20, ge=1, le=100),
    status: str | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取帖子列表"""
    service = XHSService(db)
    items, total = await service.list_posts(current_user, page, limit, status)

    return ApiResponse(
        data=PostListOut(
            items=[PostOut.model_validate(p) for p in items],
            total=total,
            page=page,
            limit=limit,
        )
    )


@router.get("/report/simple")
async def get_simple_report(
    account_id: str | None = Query(default=None),
    account_name: str | None = Query(default=None),
    start_date: str | None = Query(default=None),
    end_date: str | None = Query(default=None),
    days: int = Query(default=30, ge=1, le=180),
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=20, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = XHSService(db)
    data = await service.get_jg_report_cached(
        report_type="simple",
        account_id=account_id,
        account_name=account_name,
        start_date=start_date,
        end_date=end_date,
        days=days,
        page=page,
        limit=limit,
    )
    return ApiResponse(data=ReportListOut(**data))


@router.get("/report/standard")
async def get_standard_report(
    account_id: str | None = Query(default=None),
    account_name: str | None = Query(default=None),
    start_date: str | None = Query(default=None),
    end_date: str | None = Query(default=None),
    days: int = Query(default=30, ge=1, le=180),
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=20, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = XHSService(db)
    data = await service.get_jg_report_cached(
        report_type="standard",
        account_id=account_id,
        account_name=account_name,
        start_date=start_date,
        end_date=end_date,
        days=days,
        page=page,
        limit=limit,
    )
    return ApiResponse(data=ReportListOut(**data))


@router.get("/report/simple-note")
async def get_simple_note_report(
    account_id: str | None = Query(default=None),
    account_name: str | None = Query(default=None),
    start_date: str | None = Query(default=None),
    end_date: str | None = Query(default=None),
    days: int = Query(default=30, ge=1, le=180),
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=20, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = XHSService(db)
    data = await service.get_jg_report_cached(
        report_type="simple_note",
        account_id=account_id,
        account_name=account_name,
        start_date=start_date,
        end_date=end_date,
        days=days,
        page=page,
        limit=limit,
    )
    return ApiResponse(data=ReportListOut(**data))


@router.get("/report/standard-note")
async def get_standard_note_report(
    account_id: str | None = Query(default=None),
    account_name: str | None = Query(default=None),
    start_date: str | None = Query(default=None),
    end_date: str | None = Query(default=None),
    days: int = Query(default=30, ge=1, le=180),
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=20, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = XHSService(db)
    data = await service.get_jg_report_cached(
        report_type="standard_note",
        account_id=account_id,
        account_name=account_name,
        start_date=start_date,
        end_date=end_date,
        days=days,
        page=page,
        limit=limit,
    )
    return ApiResponse(data=ReportListOut(**data))


@router.get("/report/creative")
async def get_creative_report(
    account_id: str | None = Query(default=None),
    account_name: str | None = Query(default=None),
    start_date: str | None = Query(default=None),
    end_date: str | None = Query(default=None),
    days: int = Query(default=30, ge=1, le=180),
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=20, ge=1, le=200),
    ai_origin_filter: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = XHSService(db)
    data = await service.get_jg_report_cached(
        report_type="creative",
        account_id=account_id,
        account_name=account_name,
        start_date=start_date,
        end_date=end_date,
        days=days,
        page=page,
        limit=limit,
        creative_ai_filter=ai_origin_filter,
    )
    return ApiResponse(data=ReportListOut(**data))


@router.get("/report/creative/compare")
async def get_creative_report_compare(
    account_id: str | None = Query(default=None),
    account_name: str | None = Query(default=None),
    start_date: str | None = Query(default=None),
    end_date: str | None = Query(default=None),
    days: int = Query(default=30, ge=1, le=180),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = XHSService(db)
    data = await service.get_creative_report_ai_compare(
        account_id=account_id,
        account_name=account_name,
        start_date=start_date,
        end_date=end_date,
        days=days,
    )
    return ApiResponse(data=CreativeReportCompareOut(**data))


@router.get("/report/accounts")
async def get_report_accounts(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = XHSService(db)
    data = await service.list_report_accounts()
    return ApiResponse(data=data)


@router.get("/profile-stat/owners")
async def get_xhs_profile_stat_owner_rows(
    start_date: str | None = Query(default=None),
    end_date: str | None = Query(default=None),
    days: int = Query(default=30, ge=1, le=180),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _require_xhs_insights_access(current_user)
    service = XHSProfileStatService(db)
    allowed_owner_roles, allowed_owner_ids = _resolve_xhs_insights_owner_scope(current_user)
    data = await service.owner_rows(
        start_date=start_date,
        end_date=end_date,
        days=days,
        allowed_owner_roles=allowed_owner_roles,
        allowed_owner_ids=allowed_owner_ids,
    )
    return ApiResponse(data=data)


@router.get("/ad-dashboard")
async def get_xhs_ad_dashboard(
    start_date: str | None = Query(default=None),
    end_date: str | None = Query(default=None),
    days: int = Query(default=30, ge=1, le=180),
    account_ids: str | None = Query(default=None, description="逗号分隔广告账户ID"),
    xhs_account_ids: str | None = Query(default=None, description="逗号分隔小红书专业号ID"),
    report_type: str = Query(default="all", pattern="^(all|simple|standard)$"),
    buyer_user_id: int | None = Query(default=None),
    include_content_tags: bool = Query(default=True),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _require_xhs_ad_dashboard_access(current_user)
    viewer_scope, effective_buyer_user_id = _resolve_xhs_ad_dashboard_viewer_scope(current_user, buyer_user_id)
    service = XHSAdDashboardService(db)
    data = await service.dashboard(
        start_date=start_date,
        end_date=end_date,
        days=days,
        account_ids=_split_csv(account_ids),
        xhs_account_ids=_split_csv(xhs_account_ids),
        report_type=report_type,
        buyer_user_id=effective_buyer_user_id,
        include_content_tags=include_content_tags,
        viewer_scope=viewer_scope,
    )
    return ApiResponse(data=data)


@router.get("/ad-dashboard/content-tags")
async def get_xhs_ad_dashboard_content_tags(
    start_date: str | None = Query(default=None),
    end_date: str | None = Query(default=None),
    days: int = Query(default=30, ge=1, le=180),
    account_ids: str | None = Query(default=None, description="逗号分隔广告账户ID"),
    xhs_account_ids: str | None = Query(default=None, description="逗号分隔小红书专业号ID"),
    report_type: str = Query(default="all", pattern="^(all|simple|standard)$"),
    buyer_user_id: int | None = Query(default=None),
    level: str = Query(default="primary", pattern="^(primary|secondary)$"),
    primary_tag: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _require_xhs_ad_dashboard_access(current_user)
    viewer_scope, effective_buyer_user_id = _resolve_xhs_ad_dashboard_viewer_scope(current_user, buyer_user_id)
    service = XHSAdDashboardService(db)
    data = await service.content_tag_modules(
        start_date=start_date,
        end_date=end_date,
        days=days,
        account_ids=_split_csv(account_ids),
        xhs_account_ids=_split_csv(xhs_account_ids),
        report_type=report_type,
        buyer_user_id=effective_buyer_user_id,
        level=level,
        primary_tag=primary_tag,
        viewer_scope=viewer_scope,
    )
    return ApiResponse(data=data)


@router.post("/ad-dashboard/cache/refresh")
async def refresh_xhs_ad_dashboard_cache(
    start_date: str | None = Query(default=None),
    end_date: str | None = Query(default=None),
    days: int = Query(default=30, ge=1, le=180),
    account_ids: str | None = Query(default=None, description="逗号分隔广告账户ID"),
    xhs_account_ids: str | None = Query(default=None, description="逗号分隔小红书专业号ID"),
    report_type: str = Query(default="all", pattern="^(all|simple|standard)$"),
    buyer_user_id: int | None = Query(default=None),
    include_content_tags: bool = Query(default=True),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _require_xhs_ad_dashboard_access(current_user)
    viewer_scope, effective_buyer_user_id = _resolve_xhs_ad_dashboard_viewer_scope(current_user, buyer_user_id)
    service = XHSAdDashboardService(db)
    data = await service.dashboard(
        start_date=start_date,
        end_date=end_date,
        days=days,
        account_ids=_split_csv(account_ids),
        xhs_account_ids=_split_csv(xhs_account_ids),
        report_type=report_type,
        buyer_user_id=effective_buyer_user_id,
        include_content_tags=include_content_tags,
        force_refresh=True,
        viewer_scope=viewer_scope,
    )
    return ApiResponse(data={
        "status": "refreshed",
        "start_date": data.get("start_date"),
        "end_date": data.get("end_date"),
        "include_content_tags": include_content_tags,
    })


@router.get("/ad-dashboard/export")
async def export_xhs_ad_dashboard_table(
    table: str = Query(..., pattern="^(brand|note)$"),
    start_date: str | None = Query(default=None),
    end_date: str | None = Query(default=None),
    days: int = Query(default=30, ge=1, le=180),
    account_ids: str | None = Query(default=None),
    xhs_account_ids: str | None = Query(default=None),
    report_type: str = Query(default="all", pattern="^(all|simple|standard)$"),
    buyer_user_id: int | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _require_xhs_ad_dashboard_access(current_user)
    viewer_scope, effective_buyer_user_id = _resolve_xhs_ad_dashboard_viewer_scope(current_user, buyer_user_id)
    service = XHSAdDashboardService(db)
    data = await service.dashboard(
        start_date=start_date,
        end_date=end_date,
        days=days,
        account_ids=_split_csv(account_ids),
        xhs_account_ids=_split_csv(xhs_account_ids),
        report_type=report_type,
        buyer_user_id=effective_buyer_user_id,
        viewer_scope=viewer_scope,
    )
    wb = Workbook()
    ws = wb.active
    if table == "brand":
        ws.title = "品牌消耗转化表"
        columns = [
            ("品牌/子品牌", "brand"),
            ("消费", "fee"),
            ("展现量", "impression"),
            ("点击量", "click"),
            ("点击率", "ctr"),
            ("平均点击成本", "avg_click_cost"),
            ("转化数", "conversion"),
            ("转化成本", "conversion_cost"),
            ("互动量", "interaction"),
        ]
        rows = data.get("brand_rows") or []
    else:
        ws.title = "笔记消耗转化表"
        columns = [
            ("笔记/素材ID", "note_id"),
            ("笔记/素材名称", "note_title"),
            ("账户名称", "account_name"),
            ("小红书账号", "xhs_account_name"),
            ("投放类型", "report_types"),
            ("消费", "fee"),
            ("展现量", "impression"),
            ("点击量", "click"),
            ("点击率", "ctr"),
            ("平均点击成本", "avg_click_cost"),
            ("开口数", "openings"),
            ("转化数", "conversion"),
            ("转化成本", "conversion_cost"),
            ("开口转化率", "opening_conversion_rate"),
            ("互动量", "interaction"),
        ]
        rows = data.get("note_rows") or []

    ws.append([label for label, _ in columns])
    for row in rows:
        values = []
        for _, key in columns:
            value = row.get(key, "")
            if isinstance(value, list):
                value = "、".join(str(item) for item in value)
            values.append(value)
        ws.append(values)

    output = BytesIO()
    wb.save(output)
    output.seek(0)
    filename = f"xhs_ad_{table}_{data.get('start_date')}_{data.get('end_date')}.xlsx"
    return StreamingResponse(
        output,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/account-notes")
async def list_account_notes(
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=20, ge=1, le=100),
    environment_id: int | None = Query(default=None),
    keyword: str | None = Query(default=None),
    ai_origin_type: str | None = Query(default=None),
    status: str | None = Query(default=None, pattern="^(active|offline|all)$"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = XHSService(db)
    items, total, total_accounts = await service.list_account_notes(
        current_user,
        page=page,
        limit=limit,
        environment_id=environment_id,
        keyword=keyword,
        ai_origin_type=ai_origin_type,
        status=status,
    )
    return ApiResponse(
        data=AccountNoteListOut(
            items=[AccountNoteOut.model_validate(item) for item in items],
            total=total,
            page=page,
            limit=limit,
            total_accounts=total_accounts,
        )
    )


@router.get("/account-notes/insights")
async def list_account_notes_for_insights(
    start_date: date | None = Query(default=None),
    end_date: date | None = Query(default=None),
    limit: int = Query(default=5000, ge=1, le=10000),
    status: str | None = Query(default="active", pattern="^(active|offline|all)$"),
    include_items: bool = Query(default=True),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = XHSService(db)
    items, total, total_accounts = await service.list_account_notes_for_insights(
        current_user,
        start_date=start_date,
        end_date=end_date,
        limit=limit,
        status=status,
    )
    # A single-day filter can legitimately have no notes while the customer-lead
    # table still has data. Avoid an unnecessary catalog query in that case.
    if items:
        XHSService.set_vehicle_catalog_entries(await VehicleCatalogService(db).match_entries())
    dashboard = XHSService.build_insights_dashboard(items, start_date=start_date, end_date=end_date)
    return ApiResponse(
        data=AccountNoteListOut(
            items=[AccountNoteOut.model_validate(item) for item in items] if include_items else [],
            total=total,
            page=1,
            limit=limit,
            total_accounts=total_accounts,
            dashboard=dashboard,
        )
    )


@router.post("/account-notes/sync")
async def sync_account_notes(
    environment_id: int | None = Query(default=None),
    scrape_environment_id: int | None = Query(default=None),
    scrape_environment_ids: str | None = Query(default=None),
    sync_account_limit: int | None = Query(default=None, ge=1, le=1000),
    runner_account_assignments: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    job = _new_job(
        "account_notes_sync",
        environment_id=environment_id,
        scrape_environment_id=scrape_environment_id,
        scrape_environment_ids=scrape_environment_ids,
        sync_account_limit=sync_account_limit,
        runner_account_assignments=runner_account_assignments,
    )
    history_run = await _create_sync_history_run(
        db,
        job=job,
        sync_kind="posts",
        source="manual",
        requested_by_user_id=current_user.id,
        request_config={
            "environment_id": environment_id,
            "scrape_environment_id": scrape_environment_id,
            "scrape_environment_ids": scrape_environment_ids,
            "sync_account_limit": sync_account_limit,
            "runner_account_assignments": runner_account_assignments,
        },
        targets=await _resolve_sync_history_targets(
            db,
            sync_kind="posts",
            environment_id=environment_id,
            runner_account_assignments=runner_account_assignments,
        ),
    )
    task = asyncio.create_task(
        _run_account_note_sync_job(
            job["job_id"],
            user_id=current_user.id,
            environment_id=environment_id,
            scrape_environment_id=scrape_environment_id,
            scrape_environment_ids=scrape_environment_ids,
            sync_account_limit=sync_account_limit,
            runner_account_assignments=runner_account_assignments,
            details=False,
            history_run_id=history_run.id,
        )
    )
    XHS_BACKGROUND_JOB_TASKS[job["job_id"]] = task
    return ApiResponse(data=job, message="账号帖子同步任务已开始")


@router.post("/account-notes/sync-engagement")
async def sync_account_note_engagements(
    environment_id: int | None = Query(default=None),
    target_environment_ids: str | None = Query(default=None),
    sync_account_limit: int | None = Query(default=None, ge=1, le=1000),
    runner_account_assignments: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    job = _new_job(
        "account_note_engagement_sync",
        environment_id=environment_id,
        target_environment_ids=target_environment_ids,
        sync_account_limit=sync_account_limit,
        runner_account_assignments=runner_account_assignments,
    )
    history_run = await _create_sync_history_run(
        db,
        job=job,
        sync_kind="engagement",
        source="manual",
        requested_by_user_id=current_user.id,
        request_config={
            "environment_id": environment_id,
            "target_environment_ids": target_environment_ids,
            "sync_account_limit": sync_account_limit,
            "runner_account_assignments": runner_account_assignments,
        },
        targets=await _resolve_sync_history_targets(
            db,
            sync_kind="engagement",
            environment_id=environment_id,
            target_environment_ids=target_environment_ids,
            runner_account_assignments=runner_account_assignments,
        ),
    )
    task = asyncio.create_task(
        _run_account_note_sync_job(
            job["job_id"],
            user_id=current_user.id,
            environment_id=environment_id,
            target_environment_ids=target_environment_ids,
            scrape_environment_id=None,
            scrape_environment_ids=None,
            sync_account_limit=sync_account_limit,
            runner_account_assignments=runner_account_assignments,
            details=False,
            engagement_only=True,
            history_run_id=history_run.id,
        )
    )
    XHS_BACKGROUND_JOB_TASKS[job["job_id"]] = task
    return ApiResponse(data=job, message="账号互动同步任务已开始")


@router.post("/account-notes/sync-details")
async def sync_account_note_details(
    environment_id: int | None = Query(default=None),
    target_note_ids: str | None = Query(default=None),
    scrape_environment_id: int | None = Query(default=None),
    scrape_environment_ids: str | None = Query(default=None),
    sync_mode: str = Query(default="all"),
    sync_limit: int | None = Query(default=None, ge=1, le=1000),
    sync_limit_per_runner: int | None = Query(default=None, ge=1, le=60),
    pause_seconds_min: float | None = Query(default=None, ge=0, le=900),
    pause_seconds_max: float | None = Query(default=None, ge=0, le=900),
    max_post_age_days: int | None = Query(default=None, ge=0, le=3650),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    job = _new_job(
        "account_note_details_sync",
        environment_id=environment_id,
        scrape_environment_id=scrape_environment_id,
        scrape_environment_ids=scrape_environment_ids,
        sync_mode=sync_mode,
        sync_limit=sync_limit,
        sync_limit_per_runner=sync_limit_per_runner,
        pause_seconds_min=pause_seconds_min,
        pause_seconds_max=pause_seconds_max,
        max_post_age_days=max_post_age_days,
    )
    job["target_note_ids"] = target_note_ids
    history_run = await _create_sync_history_run(
        db,
        job=job,
        sync_kind="details",
        source="manual",
        requested_by_user_id=current_user.id,
        request_config={
            "environment_id": environment_id,
            "target_note_ids": target_note_ids,
            "scrape_environment_id": scrape_environment_id,
            "scrape_environment_ids": scrape_environment_ids,
            "sync_mode": sync_mode,
            "sync_limit": sync_limit,
            "sync_limit_per_runner": sync_limit_per_runner,
            "pause_seconds_min": pause_seconds_min,
            "pause_seconds_max": pause_seconds_max,
            "max_post_age_days": max_post_age_days,
        },
        targets=await _resolve_sync_history_targets(
            db,
            sync_kind="details",
            environment_id=environment_id,
        ),
    )
    task = asyncio.create_task(
        _run_account_note_sync_job(
            job["job_id"],
            user_id=current_user.id,
            environment_id=environment_id,
            scrape_environment_id=scrape_environment_id,
            scrape_environment_ids=scrape_environment_ids,
            details=True,
            sync_mode=sync_mode,
            sync_limit=sync_limit,
            sync_limit_per_runner=sync_limit_per_runner,
            pause_seconds_min=pause_seconds_min,
            pause_seconds_max=pause_seconds_max,
            max_post_age_days=max_post_age_days,
            history_run_id=history_run.id,
            target_note_ids=target_note_ids,
        )
    )
    XHS_BACKGROUND_JOB_TASKS[job["job_id"]] = task
    return ApiResponse(data=job, message="账号帖子数据同步任务已开始")


@router.get("/account-notes/sync-history")
async def list_account_note_sync_history(
    limit: int = Query(default=20, ge=1, le=100),
    current_user: User = Depends(require_admin),
):
    async with async_session() as session:
        runs = list(
            (
                await session.execute(
                    select(XHSAccountSyncRun)
                    .options(selectinload(XHSAccountSyncRun.items))
                    .order_by(XHSAccountSyncRun.id.desc())
                    .limit(limit)
                )
            ).scalars().all()
        )
    return ApiResponse(data=[_serialize_sync_history_run(run) for run in runs])


@router.get("/account-notes/sync-history/{run_id}")
async def get_account_note_sync_history(
    run_id: int,
    current_user: User = Depends(require_admin),
):
    async with async_session() as session:
        run = (
            await session.execute(
                select(XHSAccountSyncRun)
                .options(selectinload(XHSAccountSyncRun.items))
                .where(XHSAccountSyncRun.id == run_id)
            )
        ).scalar_one_or_none()
    if run is None:
        raise HTTPException(status_code=404, detail="同步历史不存在")
    return ApiResponse(data=_serialize_sync_history_run(run))


def _filter_retry_runner_assignments(value: str | None, failed_environment_ids: list[int]) -> str | None:
    if not value:
        return None
    try:
        payload = json.loads(value)
    except (TypeError, ValueError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    allowed = set(failed_environment_ids)
    filtered: dict[str, list[int]] = {}
    for runner_id, env_ids in payload.items():
        if not isinstance(env_ids, list):
            continue
        selected: list[int] = []
        for env_id in env_ids:
            try:
                normalized_id = int(env_id)
            except (TypeError, ValueError):
                continue
            if normalized_id in allowed:
                selected.append(normalized_id)
        if selected:
            filtered[str(runner_id)] = selected
    return json.dumps(filtered, ensure_ascii=False) if filtered else None


@router.post("/account-notes/sync-history/{run_id}/retry-failed")
async def retry_failed_account_note_sync_history(
    run_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    previous = (
        await db.execute(
            select(XHSAccountSyncRun)
            .options(selectinload(XHSAccountSyncRun.items))
            .where(XHSAccountSyncRun.id == run_id)
        )
    ).scalar_one_or_none()
    if previous is None:
        raise HTTPException(status_code=404, detail="同步历史不存在")
    failed_items = [item for item in previous.items if item.status == "failed" and item.environment_id]
    failed_environment_ids = sorted({int(item.environment_id) for item in failed_items if item.environment_id})
    if previous.sync_kind == "details":
        failed_note_ids = sorted({
            int(note_id)
            for item in failed_items
            for note_id in (item.result or {}).get("failed_note_ids", [])
            if str(note_id).isdigit() and int(note_id) > 0
        })
        if not failed_note_ids:
            raise HTTPException(status_code=400, detail="这次任务没有可重跑的失败帖子")
        config = dict(previous.request_config or {})
        target_note_ids = ",".join(str(item) for item in failed_note_ids)
        job = _new_job(
            "account_note_details_sync",
            environment_id=None,
            scrape_environment_id=config.get("scrape_environment_id"),
            scrape_environment_ids=config.get("scrape_environment_ids"),
            sync_mode="all",
            sync_limit=len(failed_note_ids),
            sync_limit_per_runner=config.get("sync_limit_per_runner"),
            pause_seconds_min=config.get("pause_seconds_min"),
            pause_seconds_max=config.get("pause_seconds_max"),
            max_post_age_days=None,
        )
        job["target_note_ids"] = target_note_ids
        retry_config = {
            **config,
            "environment_id": None,
            "target_note_ids": target_note_ids,
            "sync_mode": "all",
            "sync_limit": len(failed_note_ids),
            "max_post_age_days": None,
        }
        history_run = await _create_sync_history_run(
            db,
            job=job,
            sync_kind="details",
            source="retry_failed",
            requested_by_user_id=current_user.id,
            request_config=retry_config,
            targets=[],
            parent_run_id=previous.id,
        )
        task = asyncio.create_task(
            _run_account_note_sync_job(
                job["job_id"],
                user_id=current_user.id,
                environment_id=None,
                scrape_environment_id=retry_config.get("scrape_environment_id"),
                scrape_environment_ids=retry_config.get("scrape_environment_ids"),
                details=True,
                sync_mode="all",
                sync_limit=len(failed_note_ids),
                sync_limit_per_runner=retry_config.get("sync_limit_per_runner"),
                pause_seconds_min=retry_config.get("pause_seconds_min"),
                pause_seconds_max=retry_config.get("pause_seconds_max"),
                max_post_age_days=None,
                history_run_id=history_run.id,
                target_note_ids=target_note_ids,
            )
        )
        XHS_BACKGROUND_JOB_TASKS[job["job_id"]] = task
        return ApiResponse(data=job, message=f"已下发 {len(failed_note_ids)} 条失败帖子的重跑任务")
    if not failed_environment_ids:
        raise HTTPException(status_code=400, detail="这次任务没有可重跑的失败账号")

    config = dict(previous.request_config or {})
    if previous.sync_kind == "posts":
        filtered_assignments = _filter_retry_runner_assignments(config.get("runner_account_assignments"), failed_environment_ids)
        if not filtered_assignments:
            raise HTTPException(status_code=400, detail="原任务未保存测试账号分配，无法安全重跑失败账号")
        job = _new_job(
            "account_notes_sync",
            environment_id=None,
            scrape_environment_id=config.get("scrape_environment_id"),
            scrape_environment_ids=config.get("scrape_environment_ids"),
            sync_account_limit=len(failed_environment_ids),
            runner_account_assignments=filtered_assignments,
        )
        retry_config = {
            "environment_id": None,
            "scrape_environment_id": config.get("scrape_environment_id"),
            "scrape_environment_ids": config.get("scrape_environment_ids"),
            "sync_account_limit": len(failed_environment_ids),
            "runner_account_assignments": filtered_assignments,
        }
        history_run = await _create_sync_history_run(
            db,
            job=job,
            sync_kind="posts",
            source="retry_failed",
            requested_by_user_id=current_user.id,
            request_config=retry_config,
            targets=await _resolve_sync_history_targets(
                db,
                sync_kind="posts",
                environment_id=None,
                runner_account_assignments=filtered_assignments,
            ),
            parent_run_id=previous.id,
        )
        task = asyncio.create_task(
            _run_account_note_sync_job(
                job["job_id"],
                user_id=current_user.id,
                environment_id=None,
                scrape_environment_id=retry_config["scrape_environment_id"],
                scrape_environment_ids=retry_config["scrape_environment_ids"],
                sync_account_limit=len(failed_environment_ids),
                runner_account_assignments=filtered_assignments,
                details=False,
                history_run_id=history_run.id,
            )
        )
    else:
        target_environment_ids = ",".join(str(item) for item in failed_environment_ids)
        job = _new_job(
            "account_note_engagement_sync",
            environment_id=None,
            target_environment_ids=target_environment_ids,
            sync_account_limit=len(failed_environment_ids),
        )
        retry_config = {
            "environment_id": None,
            "target_environment_ids": target_environment_ids,
            "sync_account_limit": len(failed_environment_ids),
            "runner_account_assignments": None,
        }
        history_run = await _create_sync_history_run(
            db,
            job=job,
            sync_kind="engagement",
            source="retry_failed",
            requested_by_user_id=current_user.id,
            request_config=retry_config,
            targets=await _resolve_sync_history_targets(
                db,
                sync_kind="engagement",
                environment_id=None,
                target_environment_ids=target_environment_ids,
            ),
            parent_run_id=previous.id,
        )
        task = asyncio.create_task(
            _run_account_note_sync_job(
                job["job_id"],
                user_id=current_user.id,
                environment_id=None,
                target_environment_ids=target_environment_ids,
                scrape_environment_id=None,
                scrape_environment_ids=None,
                sync_account_limit=len(failed_environment_ids),
                runner_account_assignments=None,
                details=False,
                engagement_only=True,
                history_run_id=history_run.id,
            )
        )
    XHS_BACKGROUND_JOB_TASKS[job["job_id"]] = task
    return ApiResponse(data=job, message=f"已下发 {len(failed_environment_ids)} 个失败账号的重跑任务")


@router.get("/account-notes/sync-jobs/{job_id}")
async def get_account_note_sync_job(
    job_id: str,
    current_user: User = Depends(require_admin),
):
    job = XHS_BACKGROUND_JOBS.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="同步任务不存在")
    return ApiResponse(data=job)


@router.post("/account-notes/sync-jobs/{job_id}/cancel")
async def cancel_account_note_sync_job(
    job_id: str,
    current_user: User = Depends(require_admin),
):
    job = XHS_BACKGROUND_JOBS.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="同步任务不存在")
    status = str(job.get("status") or "")
    if status in {"succeeded", "failed", "cancelled"}:
        return ApiResponse(data=job, message="任务已结束，无需中止")

    job["cancel_requested"] = True
    if status == "queued":
        _finish_sync_job(
            job,
            status="cancelled",
            message="任务已中止，未开始的任务已取消",
            details=job.get("job_type") == "account_note_details_sync",
        )
        task = XHS_BACKGROUND_JOB_TASKS.pop(job_id, None)
        if task is not None:
            task.cancel()
        await _finish_sync_history_run(
            job.get("history_run_id"),
            status="cancelled",
            message="任务已中止，未开始的任务已取消",
        )
        await _mirror_account_sync_shadow_safely(
            job.get("history_run_id"),
            legacy_job=job,
        )
        return ApiResponse(data=job, message="同步任务已中止")

    job["status"] = "cancelling"
    job["message"] = "正在中止任务，已完成的数据会保留"
    _update_job_progress(job, phase="cancelling", detail=job["message"])
    await _mirror_account_sync_shadow_safely(
        job.get("history_run_id"),
        legacy_job=job,
    )
    return ApiResponse(data=job, message="已发送中止请求")


@router.patch("/account-notes/{note_id}")
async def update_account_note(
    note_id: int,
    req: AccountNoteUpdateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = XHSService(db)
    try:
        note = await service.update_account_note_ai_origin_type(current_user, note_id, req.ai_origin_type)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    hydrated_note = await _load_account_note_out(db, int(note.id))
    return ApiResponse(data=AccountNoteOut.model_validate(hydrated_note or note), message="标记已更新")


@router.post("/account-notes/{note_id}/record-browse")
async def record_account_note_browse(
    note_id: int,
    req: AccountNoteBrowseRecordRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = XHSService(db)
    envs = await service.list_environments(current_user)
    allowed_env_ids = {env.id for env in envs}
    stmt = select(XHSAccountNote).where(XHSAccountNote.id == note_id)
    if current_user.role != "admin":
        stmt = stmt.where(XHSAccountNote.environment_id.in_(allowed_env_ids))
    note = (await db.execute(stmt)).scalar_one_or_none()
    if note is None:
        raise HTTPException(status_code=404, detail="账号帖子不存在")

    event = await service.record_account_note_browse(note, browse_source=req.browse_source, commit=True)
    await db.refresh(note)
    return ApiResponse(
        data={
            "event_id": event.id,
            "note_id": note.id,
            "browse_source": event.browse_source,
            "runner_environment_id": event.runner_environment_id,
            "runner_account_name": event.runner_account_name,
        },
        message="浏览记录已更新",
    )


@router.post("/account-notes/batch-update")
async def batch_update_account_notes(
    req: AccountNoteBatchUpdateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = XHSService(db)
    try:
        result = await service.batch_update_account_note_ai_origin_type(
            current_user,
            req.note_ids,
            req.ai_origin_type,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return ApiResponse(data=result, message="批量标记已更新")


@router.post("/account-notes/tag-content")
async def tag_account_note_content(
    req: AccountNoteContentTagRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = XHSService(db)
    envs = await service.list_environments(current_user)
    allowed_env_ids = {env.id for env in envs}
    if not allowed_env_ids:
        return ApiResponse(
            data=AccountNoteContentTagOut(
                matched_count=0,
                tagged_count=0,
                failed_count=0,
                concurrency=req.concurrency,
            ),
            message="暂无可打标账号数据",
        )
    if req.environment_id is not None and req.environment_id not in allowed_env_ids:
        return ApiResponse(
            data=AccountNoteContentTagOut(
                matched_count=0,
                tagged_count=0,
                failed_count=0,
                concurrency=req.concurrency,
            ),
            message="暂无可打标账号数据",
        )

    conditions = [
        XHSAccountNote.environment_id.in_(allowed_env_ids),
        XHSAccountNote.title != "",
        XHSAccountNote.detail_synced_at.is_not(None),
        XHSAccountNote.content_status == "from_detail",
        XHSAccountNote.content.is_not(None),
        XHSAccountNote.content != "",
        or_(
            XHSAccountNote.primary_content_tag.is_(None),
            XHSAccountNote.primary_content_tag == "",
            XHSAccountNote.secondary_content_tag.is_(None),
            XHSAccountNote.secondary_content_tag == "",
        ),
    ]
    if req.environment_id is not None:
        conditions.append(XHSAccountNote.environment_id == req.environment_id)
    ai_origin_value = (req.ai_origin_type or "").strip()
    if ai_origin_value:
        if ai_origin_value == "__unset__":
            conditions.append(or_(XHSAccountNote.ai_origin_type == "", XHSAccountNote.ai_origin_type.is_(None)))
        elif ai_origin_value != "all":
            conditions.append(XHSAccountNote.ai_origin_type == ai_origin_value)
    status_value = (req.status or "").strip()
    if status_value and status_value != "all":
        conditions.append(XHSAccountNote.status == status_value)
    keyword_value = (req.keyword or "").strip()
    if keyword_value:
        pattern = f"%{keyword_value}%"
        conditions.append(
            or_(
                XHSAccountNote.title.ilike(pattern),
                XHSAccountNote.feed_id.ilike(pattern),
                XHSAccountNote.red_id.ilike(pattern),
            )
        )

    stmt = (
        select(XHSAccountNote)
        .where(and_(*conditions))
        .order_by(XHSAccountNote.environment_id.asc(), XHSAccountNote.sort_index.asc(), XHSAccountNote.id.desc())
    )
    notes = list((await db.execute(stmt)).scalars().all())
    if not notes:
        return ApiResponse(
            data=AccountNoteContentTagOut(
                matched_count=0,
                tagged_count=0,
                failed_count=0,
                concurrency=req.concurrency,
            ),
            message="当前范围没有可打标的账号帖子正文",
        )

    semaphore = asyncio.Semaphore(req.concurrency)
    failed_items: list[dict] = []
    tagged_results: list[tuple[XHSAccountNote, str, str]] = []

    async with httpx.AsyncClient(timeout=httpx.Timeout(120.0, connect=15.0), trust_env=False) as client:
        async def run_one(note: XHSAccountNote) -> None:
            async with semaphore:
                try:
                    primary, secondary = await _tag_xhs_account_note_with_model(client, note)
                    tagged_results.append((note, primary, secondary))
                except Exception as exc:
                    failed_items.append({
                        "id": int(note.id),
                        "title": note.title or note.feed_id,
                        "error": str(exc)[:240],
                    })

        await asyncio.gather(*(run_one(note) for note in notes))

    primary_counts: dict[str, int] = {}
    for note, primary, secondary in tagged_results:
        note.primary_content_tag = primary
        note.secondary_content_tag = secondary
        primary_counts[primary] = primary_counts.get(primary, 0) + 1
    if tagged_results:
        await db.commit()

    result = AccountNoteContentTagOut(
        matched_count=len(notes),
        tagged_count=len(tagged_results),
        failed_count=len(failed_items),
        concurrency=req.concurrency,
        primary_counts=primary_counts,
        failed_items=failed_items[:20],
    )
    return ApiResponse(data=result, message=f"内容标签已更新 {len(tagged_results)} 条")


@router.post("/account-notes/{note_id}/sync-stats")
async def sync_account_note_stats(
    note_id: int,
    scrape_environment_id: int | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = XHSService(db)
    try:
        note, synced, skipped = await service.sync_account_note_stats(
            current_user,
            note_id,
            scrape_environment_id=scrape_environment_id,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=400, detail=str(e))
    hydrated_note = await _load_account_note_out(db, int(note.id))
    return ApiResponse(
        data=AccountNoteOut.model_validate(hydrated_note or note),
        message=(
            "帖子超出当前策略设置的时间范围，已跳过同步"
            if skipped
            else ("帖子详情同步完成" if synced else "帖子详情未返回可用数据，已保留原有内容")
        ),
    )


@router.post("/account-notes/{note_id}/sync-engagement-stats")
async def sync_account_note_engagement_stats(
    note_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = XHSService(db)
    try:
        note, synced = await service.sync_account_note_engagement_stats(
            current_user,
            note_id,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=400, detail=str(e))
    hydrated_note = await _load_account_note_out(db, int(note.id))
    return ApiResponse(
        data=AccountNoteOut.model_validate(hydrated_note or note),
        message=("互动数据同步完成" if synced else "创作中心未匹配到这条帖子，已保留原有数据"),
    )


@router.post("/report/refresh")
async def refresh_report_cache(
    report_type: str = Query(..., pattern="^(simple|standard|creative|simple_note|standard_note)$"),
    account_id: str | None = Query(default=None),
    account_name: str | None = Query(default=None),
    start_date: str | None = Query(default=None),
    end_date: str | None = Query(default=None),
    days: int = Query(default=30, ge=1, le=180),
    current_user: User = Depends(require_admin),
):
    job = _new_job(
        "report_refresh",
        environment_id=None,
        report_type=report_type,
        account_id=account_id,
        account_name=account_name,
        start_date=start_date,
        end_date=end_date,
        days=days,
    )
    history_run_id = await create_report_refresh_run_safely(
        job_id=str(job["job_id"]),
        source="manual",
        requested_by_user_id=int(current_user.id),
        request_config={
            "report_types": [report_type],
            "account_id": account_id,
            "account_name": account_name,
            "start_date": start_date,
            "end_date": end_date,
            "days": days,
        },
    )
    if history_run_id:
        job["history_run_id"] = history_run_id
    asyncio.create_task(
        _run_report_refresh_job(
            job["job_id"],
            report_type=report_type,
            account_id=account_id,
            account_name=account_name,
            start_date=start_date,
            end_date=end_date,
            days=days,
            history_run_id=history_run_id,
        )
    )
    return ApiResponse(data=job, message="报表缓存刷新任务已开始")


@router.get("/report/refresh-jobs/{job_id}")
async def get_report_refresh_job(
    job_id: str,
    current_user: User = Depends(require_admin),
):
    job = XHS_BACKGROUND_JOBS.get(job_id)
    if not job or job.get("job_type") != "report_refresh":
        raise HTTPException(status_code=404, detail="报表刷新任务不存在")
    return ApiResponse(data=job)


@router.get("/report/export")
async def export_report(
    report_type: str = Query(..., pattern="^(simple|standard|creative|simple_note|standard_note)$"),
    account_id: str | None = Query(default=None),
    start_date: str | None = Query(default=None),
    end_date: str | None = Query(default=None),
    days: int = Query(default=30, ge=1, le=180),
    ai_origin_filter: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = XHSService(db)
    data = await service.get_jg_report_cached(
        report_type=report_type,
        account_id=account_id,
        start_date=start_date,
        end_date=end_date,
        days=days,
        creative_ai_filter=ai_origin_filter,
        include_all_rows=True,
    )

    wb = Workbook()
    ws = wb.active
    if report_type == "simple":
        ws.title = "简单投按计划"
        export_columns = REPORT_EXPORT_COLUMNS
    elif report_type == "standard":
        ws.title = "标准投按计划"
        export_columns = REPORT_EXPORT_COLUMNS
    elif report_type == "simple_note":
        ws.title = "简单投笔记报表"
        export_columns = EASY_NOTE_REPORT_EXPORT_COLUMNS
    elif report_type == "standard_note":
        ws.title = "标准投笔记报表"
        export_columns = STANDARD_NOTE_REPORT_EXPORT_COLUMNS
    else:
        ws.title = "创意报表"
        export_columns = CREATIVE_REPORT_EXPORT_COLUMNS

    ws.append([label for label, _ in export_columns])
    sorted_rows = sorted(
        data.get("rows") or [],
        key=lambda row: (
            str((row or {}).get("time") or ""),
            str((row or {}).get("creative_name") or (row or {}).get("campaign_name") or ""),
            str((row or {}).get("creative_id") or (row or {}).get("campaign_id") or ""),
        ),
        reverse=True,
    )
    for row in sorted_rows:
        ws.append([_export_value(row, key) for _, key in export_columns])

    output = BytesIO()
    wb.save(output)
    output.seek(0)
    filename = f"xhs_{report_type}_{account_id or 'all'}_{data.get('start_date')}_{data.get('end_date')}.xlsx"
    return StreamingResponse(
        output,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/report/import-tokens")
async def import_report_tokens(
    file_path: str = Query(..., description="xls绝对路径"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    service = XHSService(db)
    data = await service.import_report_tokens_from_xls(file_path)
    return ApiResponse(data=data, message="token导入完成")


@router.get("/posts/{post_id}")
async def get_post(
    post_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取帖子详情"""
    service = XHSService(db)
    post = await service.get_post(post_id, current_user)
    if not post:
        raise HTTPException(status_code=404, detail="帖子不存在")

    return ApiResponse(data=PostOut.model_validate(post))


@router.delete("/posts/{post_id}")
async def delete_post(
    post_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """删除本地未发布帖子记录。"""
    service = XHSService(db)
    post = await service.get_post(post_id, current_user)
    if not post:
        raise HTTPException(status_code=404, detail="帖子不存在")

    if post.status == "success":
        raise HTTPException(status_code=400, detail="已发布帖子暂不支持管理编辑/删除")

    await service.delete_post(post)
    return ApiResponse(data={"post_id": post_id}, message="删除成功")


@router.patch("/posts/{post_id}")
async def update_post(
    post_id: int,
    req: PostUpdateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """编辑未发布帖子管理信息。"""
    service = XHSService(db)
    post = await service.get_post(post_id, current_user)
    if not post:
        raise HTTPException(status_code=404, detail="帖子不存在")

    if post.status == "success":
        raise HTTPException(status_code=400, detail="已发布帖子暂不支持管理编辑/删除")

    try:
        updated = await service.update_post(
            post=post,
            title=req.title,
            content=req.content,
            tags=req.tags,
            ai_origin_type=req.ai_origin_type,
            scheduled_at=req.scheduled_at,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return ApiResponse(data=PostOut.model_validate(updated), message="保存成功")


@router.post("/posts/{post_id}/cancel")
async def cancel_post(
    post_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """取消待发布任务。"""
    service = XHSService(db)
    post = await service.get_post(post_id, current_user)
    if not post:
        raise HTTPException(status_code=404, detail="帖子不存在")
    try:
        updated = await service.cancel_scheduled_post(post)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return ApiResponse(data=PostOut.model_validate(updated), message="已取消任务")


@router.post("/posts/{post_id}/publish-now")
async def publish_post_now(
    post_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """立即执行待发布任务。"""
    service = XHSService(db)
    post = await service.get_post(post_id, current_user)
    if not post:
        raise HTTPException(status_code=404, detail="帖子不存在")
    try:
        updated = await service.run_scheduled_post_now(post)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except RuntimeError as e:
        logger.warning(f"立即发布任务异常: post_id={post_id}, error={e}")
        refreshed = await service.get_post(post_id, current_user)
        return ApiResponse(
            code=1,
            data=PostOut.model_validate(refreshed) if refreshed else None,
            message=str(e) or "立即发布失败，请稍后重试",
        )
    except Exception as e:
        logger.error(f"立即发布任务接口异常: post_id={post_id}, error={e}", exc_info=True)
        refreshed = await service.get_post(post_id, current_user)
        return ApiResponse(
            code=1,
            data=PostOut.model_validate(refreshed) if refreshed else None,
            message="立即发布失败，请检查环境或稍后重试",
        )
    return ApiResponse(data=PostOut.model_validate(updated), message="已触发立即发布")


@router.get("/posts/{post_id}/stats")
async def sync_post_stats(
    post_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """手动同步单个帖子数据"""
    service = XHSService(db)
    post = await service.get_post(post_id, current_user)
    if not post:
        raise HTTPException(status_code=404, detail="帖子不存在")

    sync_result = await service.sync_single_post_verbose(post)
    if not sync_result.success:
        if sync_result.reason == "post_deleted":
            return ApiResponse(
                data=PostStatsOut(
                    post_id=post.id,
                    feed_id=post.feed_id,
                    like_count=post.like_count,
                    comment_count=post.comment_count,
                    collect_count=post.collect_count,
                    share_count=post.share_count,
                    view_count=post.view_count,
                    status=post.status,
                    sync_reason=sync_result.reason,
                    last_synced_at=post.last_synced_at,
                ),
                message="帖子已删除，状态已更新为已删除",
            )
        return ApiResponse(
            code=1,
            data=PostStatsOut(
                post_id=post.id,
                feed_id=post.feed_id,
                like_count=post.like_count,
                comment_count=post.comment_count,
                collect_count=post.collect_count,
                share_count=post.share_count,
                view_count=post.view_count,
                status=post.status,
                sync_reason=sync_result.reason,
                last_synced_at=post.last_synced_at,
            ),
            message=sync_result.message or "同步失败",
        )

    return ApiResponse(
        data=PostStatsOut(
            post_id=post.id,
            feed_id=post.feed_id,
            like_count=post.like_count,
            comment_count=post.comment_count,
            collect_count=post.collect_count,
            share_count=post.share_count,
            view_count=post.view_count,
            status=post.status,
            sync_reason=sync_result.reason,
            last_synced_at=post.last_synced_at,
        ),
        message="同步成功",
    )


@router.post("/internal/sync-environments")
async def worker_sync_environments(
    db: AsyncSession = Depends(get_db),
    _: None = Depends(require_xhs_worker_token),
):
    service = XHSService(db)
    count = await service.sync_environments_from_yundeng()
    return ApiResponse(data={"synced_count": count}, message="环境同步完成")


@router.post("/internal/sync-all-posts")
async def worker_sync_all_posts(
    db: AsyncSession = Depends(get_db),
    _: None = Depends(require_xhs_worker_token),
):
    service = XHSService(db)
    count = await service.sync_all_posts()
    return ApiResponse(data={"synced_count": count}, message="帖子同步完成")


@router.post("/internal/account-notes/sync")
async def worker_sync_account_notes(
    environment_id: int | None = Query(default=None),
    scrape_environment_id: int | None = Query(default=None),
    scrape_environment_ids: str | None = Query(default=None),
    sync_account_limit: int | None = Query(default=None, ge=1, le=1000),
    runner_account_assignments: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    _: None = Depends(require_xhs_worker_token),
):
    service = XHSService(db)
    result = await service.sync_account_notes(
        user=None,
        environment_id=environment_id,
        scrape_environment_id=scrape_environment_id,
        scrape_environment_ids=scrape_environment_ids,
        sync_account_limit=sync_account_limit,
        runner_account_assignments=runner_account_assignments,
        limit_per_env=60,
    )
    return ApiResponse(data=result, message="账号帖子同步完成")


@router.post("/internal/account-notes/sync-details")
async def worker_sync_account_note_details(
    environment_id: int | None = Query(default=None),
    target_note_ids: str | None = Query(default=None),
    scrape_environment_id: int | None = Query(default=None),
    scrape_environment_ids: str | None = Query(default=None),
    sync_mode: str = Query(default="all"),
    sync_limit: int | None = Query(default=None, ge=1, le=1000),
    sync_limit_per_runner: int | None = Query(default=None, ge=1, le=60),
    pause_seconds_min: float | None = Query(default=None, ge=0, le=900),
    pause_seconds_max: float | None = Query(default=None, ge=0, le=900),
    max_post_age_days: int | None = Query(default=None, ge=0, le=3650),
    db: AsyncSession = Depends(get_db),
    _: None = Depends(require_xhs_worker_token),
):
    service = XHSService(db)
    result = await service.sync_existing_account_note_stats(
        environment_id=environment_id,
        target_note_ids=target_note_ids,
        scrape_environment_id=scrape_environment_id,
        scrape_environment_ids=scrape_environment_ids,
        sync_mode=sync_mode,
        sync_limit=sync_limit,
        sync_limit_per_runner=sync_limit_per_runner,
        pause_seconds_min=pause_seconds_min,
        pause_seconds_max=pause_seconds_max,
        max_post_age_days=max_post_age_days,
    )
    return ApiResponse(data=result, message="账号帖子数据同步完成")


@router.get("/internal/report-token")
async def worker_fetch_report_token(
    account_id: str = Query(..., min_length=1),
    db: AsyncSession = Depends(get_db),
    _: None = Depends(require_xhs_worker_token),
):
    service = XHSService(db)
    token = await service._fetch_report_token(account_id, allow_remote=False)
    return ApiResponse(
        data={"account_id": account_id, "has_token": bool(token)},
        message="报表 token 获取成功",
    )


@router.post("/internal/posts/{post_id}/execute")
async def worker_execute_post(
    post_id: int,
    db: AsyncSession = Depends(get_db),
    _: None = Depends(require_xhs_worker_token),
):
    service = XHSService(db)
    post = await service.execute_post_by_id_for_worker(post_id)
    return ApiResponse(
        data=PublishOut(
            post_id=post.id,
            feed_id=post.feed_id,
            status=post.status,
            scheduled_at=post.scheduled_at,
        ),
        message="发布执行完成",
    )


@router.post("/internal/posts/{post_id}/edit")
async def worker_edit_post(
    post_id: int,
    req: WorkerEditRequest,
    db: AsyncSession = Depends(get_db),
    _: None = Depends(require_xhs_worker_token),
):
    result = await db.execute(select(XHSPost).where(XHSPost.id == post_id))
    post = result.scalar_one_or_none()
    if not post:
        raise HTTPException(status_code=404, detail="帖子不存在")
    service = XHSService(db)
    updated = await service.remote_edit_published_post(post, req.title, req.content, req.tags)
    return ApiResponse(data=PostOut.model_validate(updated), message="编辑成功")


@router.post("/internal/posts/{post_id}/delete")
async def worker_delete_post(
    post_id: int,
    db: AsyncSession = Depends(get_db),
    _: None = Depends(require_xhs_worker_token),
):
    result = await db.execute(select(XHSPost).where(XHSPost.id == post_id))
    post = result.scalar_one_or_none()
    if not post:
        raise HTTPException(status_code=404, detail="帖子不存在")
    service = XHSService(db)
    updated = await service.remote_delete_published_post(post)
    return ApiResponse(data=PostOut.model_validate(updated), message="删除成功")


@router.post("/internal/posts/{post_id}/sync-stats")
async def worker_sync_post_stats(
    post_id: int,
    db: AsyncSession = Depends(get_db),
    _: None = Depends(require_xhs_worker_token),
):
    result = await db.execute(select(XHSPost).where(XHSPost.id == post_id))
    post = result.scalar_one_or_none()
    if not post:
        raise HTTPException(status_code=404, detail="帖子不存在")
    service = XHSService(db)
    sync_result = await service.sync_single_post_verbose(post)
    if not sync_result.success:
        raise HTTPException(status_code=400, detail=sync_result.message or "同步失败")
    await db.refresh(post)
    return ApiResponse(data=PostOut.model_validate(post), message="同步成功")
