"""Explicit report restrictions shared by copy, pre-generation plan and OCR.

No new global blacklist. Cases without publication_constraints keep their old
behavior. Never rewrite money or regenerate anything inside these helpers.
"""
from __future__ import annotations
import re
from decimal import Decimal, InvalidOperation
from typing import Any

AMOUNT = r"(?:[¥￥]\s*\d[\d,]*(?:\.\d+)?(?:\s*(?:万元|万|元))?|\d[\d,]*(?:\.\d+)?\s*(?:万元|万|元|w|%|％))"
LOCAL = r"(?:地方(?:性)?补贴|省补|市补|区补|地方置换(?:补贴)?|置换更新(?:补贴)?)"
CATEGORY_BOUNDARY = re.compile(r"国补|报废|指导价|厂家|本品|选装|金融|保险|购置税|上牌")


def money(value: str) -> Decimal | None:
    match = re.search(r"\d[\d,]*(?:\.\d+)?", value)
    if not match:
        return None
    try:
        return Decimal(match.group().replace(',', '')) * (10000 if re.search(r"万|w", value, re.I) else 1)
    except InvalidOperation:
        return None


def policy_constraints_instruction(case: dict[str, Any]) -> str:
    rules = (case.get('publication_constraints') or {}).get('rules') or []
    if not rules:
        return ''
    return '当前政策的公开使用边界（仅修正对应事实槽，不新增段落、价格列或版式）：\n' + '\n'.join('- ' + str(rule) for rule in rules)


def policy_constraint_errors(text: str, case: dict[str, Any]) -> list[str]:
    constraints = case.get('publication_constraints') or {}
    if not constraints:
        return []
    errors = []
    banned = [str(word) for word in constraints.get('explicit_banned_terms') or [] if str(word) in text]
    if banned:
        errors.append('当前政策明确禁止的表述：' + '、'.join(banned))
    if re.search(r'报废(?:更新|补贴|价格)|置换更新(?:补贴)?', text):
        errors.append('对外政策只使用“国补”和“省补”口径，不使用报废更新或置换更新口径')
    if constraints.get('hide_local_subsidy_amounts'):
        if re.search(AMOUNT + r'\s*(?:的)?' + LOCAL, text, re.I):
            errors.append('当前政策不允许在线上展示地方补贴金额、比例或补贴后价格')
        # Scan the labelled amount only. A nearby *different* price category
        # (e.g. 地方补贴可了解；指导价6.39万元) must not become a false positive.
        for label in re.finditer(LOCAL, text):
            tail = text[label.end():label.end() + 45]
            tail = re.split(r'[。；;！!?？]', tail, maxsplit=1)[0]
            next_category = CATEGORY_BOUNDARY.search(tail)
            if next_category:
                tail = tail[:next_category.start()]
            if re.search(AMOUNT, tail, re.I):
                errors.append('当前政策不允许在线上展示地方补贴金额、比例或补贴后价格')
                break
    if constraints.get('new_vehicle_no_benefit_discount') and re.search(
        r'综合(?:权益|价值)[^。；;\n]{0,10}优惠|综合优惠|优惠(?:权益|价值)', text
    ):
        errors.append('新车型综合价值只能表述为综合权益或综合权益价值，不能包装成优惠')
    if constraints.get('new_vehicle_no_stock'):
        for match in re.finditer(r'有现车|现车可提|现车即提|现车秒提|现车随提', text):
            if not re.search(r'没有|无|不|未|暂无|没$', text[max(0, match.start() - 6):match.start()]):
                errors.append('当前政策不允许宣传新车型门店有现车可提')
    if constraints.get('no_trial_gift_amount') and re.search(r'(?:试驾礼|试驾赠礼|到店试驾礼)[^。；;\n]{0,14}' + AMOUNT, text, re.I):
        errors.append('当前政策不允许在线上展示试驾礼具体金额')
    ceiling = money(str(case.get('packaged_benefit_value') or ''))
    if ceiling is not None:
        for m in re.finditer(r'综合(?:权益(?:价值|优惠)?|价值)[^\d¥￥。\n]{0,10}(' + AMOUNT + ')', text, re.I):
            value = money(m.group(1))
            if value is not None and value > ceiling:
                errors.append('综合权益金额超过当前车型报告标注值，不能重复叠加包装')
    for pair in constraints.get('mutually_exclusive_benefits') or []:
        if pair['left'] in text and pair['right'] in text and not re.search(r'二选一|择一|不(?:可|能)?(?:同时|叠加|同享)|不能同享', text):
            errors.append(f"{pair['left']}与{pair['right']}互斥，同时列出时必须保留二选一条件")
    if constraints.get('finance_cash_stacking_unconfirmed') and re.search(r'0息|零息|贴息|金融', text) and re.search(r'现金优惠|现金减免|限时限量优惠', text):
        for match in re.finditer(r'叠加|同时享受|一起享|双享', text):
            prefix = text[max(0, match.start() - 12):match.start()]
            if not re.search(r'不|未确认|能否|是否|待确认|需确认', prefix):
                errors.append('报告未确认金融与现金优惠可以同享，不能作叠加承诺')
    if constraints.get('has_reported_landing_estimates'):
        for match in re.finditer(r'落地(?:价)?[^\d¥￥。；;\n]{0,8}(' + AMOUNT + ')', text, re.I):
            context = text[max(0, match.start() - 32):match.end() + 32]
            if not re.search(r'估算|测算', context):
                errors.append('报告落地价只能作为测算/估算引用，不能写成实际成交承诺')
            value = money(match.group(1))
            estimate_values = {money(str(row.get('estimated_national_scrappage_on_road_price') or '')) for row in case.get('quote_rows') or []}
            net_values = {money(str(row.get(field) or '')) for row in case.get('quote_rows') or []
                          for field in ('national_scrappage_after_price', 'provincial_trade_in_after_price')}
            if value in net_values and value not in estimate_values:
                errors.append('国补后价格不是报告测算落地价，不能混用价格类别')
    return list(dict.fromkeys(errors))
