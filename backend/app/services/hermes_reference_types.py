"""Shared primary-type rules for the Web picker and the Hermes source selector.

Deterministic source labels, not a claim of semantic model verification.
Explicit modes constrain selection; defaults retain the original complete pool.
"""
from __future__ import annotations
import re
import hashlib
from typing import Any

TAXONOMY_VERSION = 'reference-types-v3-layout'
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
    {'id': 'scene_poster', 'name': '场景主视觉海报', 'description': '实景中的汽车为主，配品牌、标题和少量说明', 'structure': '保留场景镜头、车位和原有文字；普通标题不算巨字版式', 'accent': 'blue'},
    {'id': 'studio_poster', 'name': '棚拍主视觉海报', 'description': '纯色、渐变或影棚背景，突出车身与光影', 'structure': '保留车辆比例、留白和文字层级；棚拍背景不覆盖报价等结构', 'accent': 'lavender'},
    {'id': 'headline_poster', 'name': '巨字创意海报', 'description': '巨型文字、书法或立体字成为画面主元素', 'structure': '保留文字与汽车的叠压、占比和字效；不因出现“大标题”就归类', 'accent': 'lavender'},
    {'id': 'price_highlight', 'name': '价格权益大字', 'description': '一个主价格或权益金额成为视觉焦点', 'structure': '保留主金额、单位及条件的小字层级；不是多个配置的报价表', 'accent': 'peach'},
    {'id': 'quote_table', 'name': '表格报价单', 'description': '多个配置以表头、行列、单元格排列价格', 'structure': '保留原表头、行列和条件备注，不把卡片强改成表格', 'accent': 'sand', 'requires_quote_data': True},
    {'id': 'quote_cards', 'name': '卡片报价单', 'description': '多个配置分卡或分块展示报价，不共用规整表头', 'structure': '保留卡片数量、形状、位置和每卡价格密度', 'accent': 'peach', 'requires_quote_data': True},
    {'id': 'photo_collage', 'name': '多图拼贴', 'description': '多个画面、细节图或照片卡片组合', 'structure': '保留拼图格数、边框、主次关系和文字位置', 'accent': 'sage'},
    {'id': 'note_poster', 'name': '手账便签风', 'description': '以纸张、便签、胶带或拍立得组织整张画面', 'structure': '保留纸张层叠、便签和手作布局；一处手写字不算手账', 'accent': 'peach'},
    {'id': 'feature_infographic', 'name': '参数配置图', 'description': '参数标注、配置图表或购车手册式信息长图', 'structure': '需有明确参数和配置结构；“性能海报”字样不算参数图', 'accent': 'blue'},
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
LEGACY_COPY = {'政策行情': {'policy_news', 'price_plan'}, '产品体验': {'drive_review', 'product_features', 'car_lifestyle'}, '选车对比': {'car_compare'}}
LEGACY_IMAGE = {'多配置报价单': {'quote_table', 'quote_cards'}, '文字营销海报': {'headline_poster', 'price_highlight', 'feature_infographic', 'photo_collage', 'note_poster'}, '实车场景图': {'scene_poster', 'studio_poster'}, '实车场景海报': {'scene_poster'}, '简约棚拍海报': {'studio_poster'}, '大字标题海报': {'headline_poster'}, '参数信息图': {'feature_infographic'}}

APPROVED_NOTE_SHA256 = '9e201b8d7cecb09aaf4e8a8bfcdc55245e02b6249ddd3b9915defde0a2147f35'


def approved_image_section(row: dict[str, Any], *, expected_sha: str = APPROVED_NOTE_SHA256) -> dict[str, Any]:
    """The previously approved #324/10 source view, shared by previews and Worker."""
    if str(row.get('id') or '') != '324' or row.get('source_section_title'):
        return row
    original = str(row.get('chinese') or row.get('chinese_example') or '')
    if hashlib.sha256(original.encode()).hexdigest() != expected_sha:
        return row
    start, end = '方案 10：潮流拼贴手账风（马卡龙色，年轻活力）', '💡 最终建议'
    if original.count(start) != 1 or original.count(end) != 1 or original.index(start) >= original.index(end):
        return row
    section = re.sub(r' (?=(?:粉色|蓝色|橙色|黄色)便利贴：)', '\n', original[original.index(start):original.index(end)].strip())
    return {**row, 'chinese': section, 'source_section_title': start,
            'source_full_original': original, 'source_full_sha256': expected_sha,
            'source_image_matches_section': False, 'source_slot_count': 6,
            'name': '提示词 #324 · 方案10 手账拼贴',
            'preview_note': '已批准的方案10原文节选；库内原图不对应这一方案，不借用其他图片展示。'}


def positive_layout_text(value: str) -> str:
    """Remove local exclusions/comparisons, not the following positive instruction.

    Match layout instructions only. A color splice, paved joint, CTA, font name
    or a discarded style must never establish a different composition.
    """
    text = re.sub(r'[*`]', '', str(value or ''))
    text = re.sub(r'(?:区别|不同于|区分于|和原图)[^。；;\n]{0,90}?(?:风格|版式|配色)[^。；;\n]{0,15}(?:区分开|不同)?', '', text)
    text = re.sub(r'(?:不要|不得|禁止|不使用|不采用|不再|不是|并非|不包含|避免|取消|去掉|去除|摒弃|移除|无(?!衬线|缝))[^，,。；;\n]{0,100}', '', text)
    # --neg / negative lists can be followed by a newly added positive text block.
    text = re.sub(r'(?:负面(?:提示)?词[^：:]*[：:]|--neg)[\s\S]*?(?=文字排版|【文字|\n\s*##|$)', '', text)
    return text


def image_layout_analysis(row: dict[str, Any]) -> dict[str, Any]:
    raw = str(row.get('chinese') or row.get('chinese_example') or '')
    text = positive_layout_text(raw)
    # Whole prompts with multiple complete compositions are not one precise type.
    alternatives = re.findall(r'方案\s*\d+\s*[：:]\s*[^。\n]{0,40}(?:风|海报|美学)', raw)
    if len(alternatives) > 1 and not row.get('source_section_title'):
        return {'type': None, 'reason': '包含多个完整方案，不能把其中一种风格套到整条母版', 'style_tags': [], 'requires_quote_data': False}

    def has(pattern: str) -> bool:
        return re.search(pattern, text, re.I) is not None

    styles = []
    scene = has(r'汽车场景|街景|街道|户外|外景|展厅|停车场|公路|马路|路面|山路|海边|营地|庭院|雪山|湖畔|湖面|湖泊|湖水|湖边|芦苇|山脉|山峰|山顶|远山|城市夜景|森林|沙漠|荒漠|戈壁|建筑|门店|道路')
    studio = has(r'棚拍|影棚|摄影棚|纯色(?:墙面|背景)|渐变.{0,10}(?:背景|底色)|纯白.{0,8}背景|无缝背景|柔光箱|背景.{0,12}(?:纯色|渐变)')
    if scene:
        styles.append('场景')
    if studio:
        styles.append('棚拍 / 渐变')
    if has(r'毛笔|书法|国风|国潮|水墨'):
        styles.append('书法 / 国风')

    pricing = has(r'指导价|裸车价|落地价|补贴价|提车价|报价|价格|优惠|国补|月供|权益|万元起|万起|利息|免息')
    trims = len(set(re.findall(r'\d{3,4}\s*(?:版\s*)?(?:舒享|悦享|智享|智驾|激光雷达|尊享|智尊|Plus|Pro|Max)|(?:舒享|悦享|智享|旗舰|豪华|尊享)版', text, re.I)))
    quote = pricing and (trims >= 2 or has(r'(?:多个|多款|各|四|五|4|5)(?:个|款|行|种)?(?:车型|配置|版本)|多配置|多版本|车型版本|配置价格表|多行车系配置'))
    table = has(r'表头|单元格|(?:价格|报价|车型).{0,12}表格|表格.{0,18}(?:配置|版本|指导价)|[三四五六3456]列.{0,10}(?:报价|数据|表格)|报价列表|配置价格表')
    cards = has(r'(?:卡片|卡块|竖卡|圆形便利贴|价格卡|报价卡)')
    note = has(r'手[账帐](?:便签|拼贴|风格|风)|笔记本.{0,12}(?:纸张|拼贴)|(?:撕纸|纸张|便利贴|便签)(?:风格|风海报|拼贴)|(?:便签|便利贴)(?:风|式)')
    if has(r'(?:手机|微信)聊天界面|左右分栏气泡对话|聊天截图\s*(?:or|或)\s*表格'):
        category, reason = None, '聊天界面或多种备选结构，不能当作普通报价海报'
    elif has(r'购车手册|全系标配') and has(r'基础参数|参数表格') and len(re.findall(r'续航|轴距|扭矩|功率|电池|零百|加速|座舱', text)) >= 3:
        category, reason = 'feature_infographic', '参数、标配和版本差异组成购车手册，不是简单报价单'
    elif row.get('source_section_title') and note:
        category, reason = 'note_poster', '已批准的独立手账方案：纸张、胶带、便签承载内容'
    elif note:
        category, reason = 'note_poster', '手账、纸张或便签构成整体版式，不是局部字体装饰'
    elif quote and table:
        category, reason = 'quote_table', '存在配置报价内容以及实际表头、行列或单元格'
    elif quote and cards:
        category, reason = 'quote_cards', '多个配置的价格分别放入独立卡片，并非照片拼贴'
    elif has(r'(?:[二三四五六九234569]宫格|多图|拼图).{0,14}(?:照片|摄影|画面|细节图)|(?:照片|图片|多图|细节图).{0,10}(?:拼贴|拼图|拼接|组合)|(?:三|四|3|4)张.{0,8}(?:小图|照片)|照片墙|多图拼贴|四宫格照片|照片卡片'):
        category, reason = 'photo_collage', '画面含多个独立照片或细节画面，不是地面、字体拼接'
    elif has(r'引线标注|标注线|尺寸线|参数标注|卖点标注|箭头标注') or (has(r'参数(?:信息图|信息卡|模块|区)|信息图') and len(re.findall(r'续航|轴距|车长|车宽|扭矩|功率|电池容量|零百|加速', text)) >= 2):
        category, reason = 'feature_infographic', '明确绘制参数块或指向车辆的标注，不只是在标题提到性能'
    elif has(r'表格|表头') and not quote:
        category, reason = None, '其他信息表格，不冒充购车报价、主价格或汽车主视觉'
    elif quote:
        category, reason = None, '有多配置价格，但没有明确对应已定义版式的布局依据'
    elif has(r'(?:超大|巨大|巨型|加粗|醒目|核心|放大)[^。；;\n]{0,35}数字[^。；;\n]{0,25}\d|(?:核心价格|主价格|价格醒目|大数字价格|主金额|价格区域居中)') and pricing:
        category, reason = 'price_highlight', '一组主价格或权益金额是视觉焦点，没有多配置报价结构'
    elif has(r'大字报|文字海报|文字为主|巨(?:型|大|幅)[^。；;\n]{0,16}(?:字|文字)|(?:文字|大字|书法字).{0,12}(?:车辆后方|车身后方|背景装饰)|字(?:号|体)占画面(?:高度|宽度)[：: ]*(?:[2-9]\d)%') or (len(text) < 100 and has(r'超大标题|巨幅标题')):
        category, reason = 'headline_poster', '巨型文字或字效本身承担构图，不是常规车型标题'
    elif has(r'表格'):
        category, reason = None, '有其他信息表格，但不是已定义的配置报价或参数结构'
    elif scene and not has(r'(?:封闭式|全封闭).{0,14}(?:棚|穹顶)'):
        category, reason = 'scene_poster', '独立汽车主视觉置于实景环境，标题和少量说明辅助'
    elif studio or has(r'极简|简约|留白|背景|底色'):
        category, reason = 'studio_poster', '单车搭配设计背景与常规文字，没有更强的结构化版式'
    else:
        category, reason = None, '提示词没有足够的明确版式依据，保留在默认素材池，不硬归类'
    return {'type': category, 'reason': reason, 'style_tags': styles, 'requires_quote_data': bool(quote)}

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
    return image_layout_analysis(row)['type']

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
                   (classifier(row) == 'multi_config_quote') == image_layout_analysis(row)['requires_quote_data']
                   or (classify_image(row) == 'note_poster' and row.get('source_section_title'))]
    return matched

def validate_type(kind: str, requested: str | None) -> None:
    matching_pool([], kind, requested)


def type_requires_quote_data(requested: str | None) -> bool:
    return requested == '多配置报价单' or any(d.get('requires_quote_data') and requested in {d['id'], d['name']} for d in IMAGE_TYPES)
