"""Shared primary-type rules for the Web picker and the Hermes source selector.

Deterministic source labels, not a claim of semantic model verification.
Explicit modes constrain selection; defaults retain the original complete pool.
"""
from __future__ import annotations
import re
from typing import Any

TAXONOMY_VERSION = 'reference-types-v2'
COPY_TYPES = [
    {'id': 'policy_news', 'name': '政策快讯', 'description': '政策更新、权益汇总与活动通知', 'structure': '消息开场 → 权益条目 → 行动引导', 'accent': 'lavender'},
    {'id': 'price_plan', 'name': '价格方案', 'description': '购车预算、月供与价格条件说明', 'structure': '价格切入 → 条件/方案 → 询价引导', 'accent': 'peach'},
    {'id': 'car_compare', 'name': '选车对比', 'description': '版本选择、差异比较与选购建议', 'structure': '选择难题 → 差异对照 → 适用建议', 'accent': 'blue'},
    {'id': 'buying_guide', 'name': '购车攻略', 'description': '购车步骤、避坑清单与经验整理', 'structure': '问题引入 → 经验清单 → 实用提醒', 'accent': 'sage'},
    {'id': 'drive_review', 'name': '试驾测评', 'description': '驾驶感受、优缺点与体验记录', 'structure': '体验结论 → 感受/优缺点 → 选择建议', 'accent': 'sand'},
    {'id': 'product_features', 'name': '配置亮点', 'description': '空间、续航、座舱等产品卖点', 'structure': '产品亮点 → 特点展开 → 用途说明', 'accent': 'blue'},
    {'id': 'car_lifestyle', 'name': '用车生活', 'description': '通勤、家庭、出游等生活化分享', 'structure': '生活场景 → 用车感受 → 互动收尾', 'accent': 'peach'},
]
IMAGE_TYPES = [
    {'id': 'headline_poster', 'name': '大字标题海报', 'description': '醒目标题 + 汽车主体，突出一句核心信息', 'structure': '保留大标题比例、车位和底部小字', 'accent': 'lavender'},
    {'id': 'quote_table', 'name': '多配置报价单', 'description': '同一车型多个配置的价格对照', 'structure': '保留表格列、报价卡位和条件备注；需完整配置价格', 'accent': 'sand'},
    {'id': 'feature_infographic', 'name': '参数信息图', 'description': '车辆 + 参数标注、卖点信息卡', 'structure': '保留标注位置、信息层级和图文比例', 'accent': 'blue'},
    {'id': 'photo_collage', 'name': '多图拼贴', 'description': '多个画面、细节图或照片卡片组合', 'structure': '保留拼图格数、边框、主次关系和文字位置', 'accent': 'sage'},
    {'id': 'scene_poster', 'name': '实车场景海报', 'description': '街景、户外、展厅等场景，配合原有文字', 'structure': '保留镜头、车辆占比和文字排版，轻改场景', 'accent': 'blue'},
    {'id': 'note_poster', 'name': '手账便签风', 'description': '手写标记、纸张、便签与贴纸质感', 'structure': '保留纸张层叠、手写层级和装饰标签', 'accent': 'peach'},
    {'id': 'studio_poster', 'name': '简约棚拍海报', 'description': '纯色或渐变背景、棚拍光影与简洁排版', 'structure': '保留留白、光影、车身位置和标题层级', 'accent': 'lavender'},
]
COPY_CUES = {
    'car_compare': r'对比|怎么选|如何选|选哪|[vV][sS]|区别|横评',
    'buying_guide': r'避坑|攻略|注意事项|购车流程|提车流程|经验总结|经验分享|买车指南|别踩|误区',
    'drive_review': r'试驾(?!礼)|驾驶感受|测评|评测|操控体验|开了一|开了.{0,5}(?:天|周|月)|优缺点|小不足|一言难尽',
    'price_plan': r'月供|首付|预算|落地价|报价|价格|多少钱|划算|免息|按揭|[0-9].{0,3}万.{0,3}(?:拿下|入手)',
    'policy_news': r'新政|政策|补贴|权益|福利|优惠|购车礼|限时|活动|更新|内部消息',
    'product_features': r'配置|参数|续航|空间|座椅|后排|智驾|座舱|轴距|快充|亮点|芯片',
    'car_lifestyle': r'通勤|出游|露营|自驾|周末|生活|日常|旅行|家庭|少女心|大女主|颜值|提车日记',
}
IMAGE_CUES = {
    'quote_table': r'多配置|配置价格表|多版本报价|车型版本|配置对比|报价列表|价格明细|(?:配置|版本).{0,12}(?:表格|报价单)|(?:表格|报价单).{0,12}(?:配置|版本)',
    'note_poster': r'手账|手帐|笔记本|笔记风|便签(?:风|式|拼贴|海报)|撕纸(?:风|拼贴)|纸张拼贴|便利贴(?:风|拼贴)|方格纸(?:背景|底纹)|格子纸(?:背景|底纹)',
    'photo_collage': r'拼贴|拼图|拼接|照片墙|多图|[二三四五六九234569]宫格|细节小图|照片卡片',
    'feature_infographic': r'信息图|参数标注|引线标注|标注线|性能参数|技术参数|配置参数|卖点标注|箭头标注',
    'headline_poster': r'大字报|文字海报|超大(?:标题|文字|字体)|巨[大幅]标题|大标题|大号.{0,5}(?:字体|标题)|文字为主|标题占.{0,5}(?:%|％)',
    'scene_poster': r'街景|街道|户外|展厅|停车场|公路|山路|海边|营地|城市夜景|城市道路|建筑背景',
    'studio_poster': r'棚拍|纯色背景|渐变背景|纯白背景|摄影棚|极简|留白|无缝背景|简约',
}
LEGACY_COPY = {'政策行情': {'policy_news', 'price_plan'}, '产品体验': {'drive_review', 'product_features', 'car_lifestyle'}, '选车对比': {'car_compare'}}
LEGACY_IMAGE = {'多配置报价单': {'quote_table'}, '文字营销海报': {'headline_poster', 'feature_infographic', 'photo_collage', 'note_poster'}, '实车场景图': {'scene_poster', 'studio_poster'}}

def classify_copy(row: dict[str, Any]) -> str | None:
    title, body = str(row.get('title') or ''), str(row.get('content') or '')
    # Other industries coexist in the library; topic tags and generic CTA lines
    # must not define the primary automotive content type.
    title = re.sub(r'#[^\s#]+#?', '', title)
    body = re.sub(r'#[^\s#]+#?', '', body)
    if not re.search(r'汽车|买车|购车|车价|新车|提车|车友|车主|座舱|轿车|SUV|MPV|电车|新能源|试驾|车机|续航|零跑|比亚迪|吉利|特斯拉|小米|五菱|长安|宝马|奔驰|奥迪|理想[Ll][0-9]', title + body, re.I):
        return None
    if re.search(r'(?:\d+[+\-]){3,}\d+', title):
        return 'price_plan'
    body_cues = {**COPY_CUES, 'drive_review': r'驾驶感受|测评|评测|操控体验|开了一|开了.{0,5}(?:天|周|月)|优缺点|小不足|试驾(?:体验|感受|分享|记录)'}
    scores = {key: (5 if re.search(pattern, title) else 0) + min(3, len(re.findall(body_cues[key], body))) for key, pattern in COPY_CUES.items()}
    best = max(scores, key=scores.get)
    return best if scores[best] else None

def classify_image(row: dict[str, Any], classifier=None) -> str | None:
    text = str(row.get('chinese') or row.get('chinese_example') or '')
    positive = re.sub(r'(?:不要|不得|禁止|不使用|不采用|避免)[^。；;\n]{0,60}', '', text)
    if row.get('source_section_title') and re.search(IMAGE_CUES['note_poster'], positive):
        return 'note_poster'
    for key, pattern in IMAGE_CUES.items():
        # A handwritten/brush font or one small CTA label is not a notebook
        # composition. Require a layout/style cue, not a decorative word.
        if re.search(pattern, positive):
            return key
    return None

def matching_pool(rows: list[dict[str, Any]], kind: str, requested: str | None, classifier=None) -> list[dict[str, Any]]:
    if not requested or requested in {'跟随母文结构', '跟随母图结构', 'auto'}:
        return rows
    definitions = COPY_TYPES if kind == 'copy' else IMAGE_TYPES
    aliases = LEGACY_COPY if kind == 'copy' else LEGACY_IMAGE
    allowed = aliases.get(requested) or {d['id'] for d in definitions if requested in {d['id'], d['name']}}
    if not allowed:
        raise ValueError(f'不支持的{kind}类型：{requested}')
    classify = classify_copy if kind == 'copy' else classify_image
    matched = [row for row in rows if classify(row) in allowed]
    # The production quote guard may further narrow the shared source labels.
    # Never admit an unrecognised quote layout into a non-quote request.
    if kind == 'image' and classifier:
        matched = [row for row in matched if
                   (classifier(row) == 'multi_config_quote') == (classify_image(row) == 'quote_table')
                   or (classify_image(row) == 'note_poster' and row.get('source_section_title'))]
    return matched

def validate_type(kind: str, requested: str | None) -> None:
    matching_pool([], kind, requested)
