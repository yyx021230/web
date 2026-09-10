from __future__ import annotations

import json
import random
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core import (  # noqa: E402
    QUOTE_TABLE_TYPE,
    STANDARD_TEMPLATE_TYPE,
    copy_content_type,
    image_ocr_errors,
    normalize_structure,
    prompt_template_type,
    safe_prompt_pool,
    sanitize_copy,
    select_diverse_rows,
    validate_copy,
    validate_image_plan,
)
from run_daily_8x5 import (  # noqa: E402
    BatchAlreadyRunning,
    BatchRunLock,
    build_tasks,
    select_account_tasks,
    validate_policy_dates,
)
from policy_sync import parse_report, sync_policy  # noqa: E402


POLICY_FIXTURE = """<!doctype html><html><head><title>policy report</title></head><body>
<div class="report-section" id="a05">
  <div class="report-title">Leapmotor A05 <span>compact EV</span></div>
  <div class="report-subtitle">2026 model</div>
  <div class="benefit-banner"><span class="value">CNY 10,680</span></div>
  <table><thead><tr><th>车型</th><th>官方指导价</th><th>国补后价格</th><th>省补后价格</th><th>本月权益</th></tr></thead>
  <tbody>
    <tr><td>405 Base<span>EV</span></td><td>63900</td><td>56232</td><td>58788</td><td><span class="item">color benefit 2000</span><span class="item">2026year8month11day special 5000</span></td></tr>
    <tr><td>510 Pro<span>EV</span></td><td>75900</td><td>66792</td><td>69828</td></tr>
  </tbody></table>
</div></body></html>""".encode()


class CoreTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.case = json.loads((ROOT / "config" / "cases.json").read_text(encoding="utf-8"))["a05-current"]

    def test_daily_contract_is_exactly_8x5(self) -> None:
        config = json.loads((ROOT / "config" / "daily_8x5.json").read_text(encoding="utf-8"))
        tasks = build_tasks(config)
        self.assertEqual(40, len(tasks))
        self.assertEqual(40, len({row["key"] for row in tasks}))
        self.assertEqual({5}, {sum(row["account_id"] == account["id"] for row in tasks) for account in config["accounts"]})

    def test_single_account_scope_keeps_exactly_five_posts(self) -> None:
        config = json.loads((ROOT / "config" / "daily_8x5.json").read_text(encoding="utf-8"))
        tasks = select_account_tasks(build_tasks(config), 6)
        self.assertEqual(5, len(tasks))
        self.assertEqual({6}, {row["account_id"] for row in tasks})

    def test_expired_policy_is_fail_closed(self) -> None:
        tasks = [{"case_id": "old"}]
        cases = {"old": {"policy_deadline": "2026-08-31"}}
        with self.assertRaises(RuntimeError):
            validate_policy_dates(tasks, cases, "2026-09-02", False)

    def test_policy_report_drives_quote_rows_and_effective_month(self) -> None:
        source = POLICY_FIXTURE.replace(b"2026year8month11day", "2026年8月11日".encode())
        cases, metadata = parse_report(
            source,
            source_url="https://example.test/policy.html",
            batch_date="2026-09-03",
        )
        case = cases["a05-current"]
        self.assertEqual("2026-09-30", case["policy_deadline"])
        self.assertEqual("9月底前", case["public_deadline"])
        self.assertTrue(case["allow_multi_config_quote"])
        self.assertEqual(2, len(case["quote_rows"]))
        self.assertEqual("63900", case["quote_rows"][0]["official_guide_price"])
        self.assertNotIn("8月11日", case["policy_text"])
        self.assertEqual(1, len(metadata["excluded_day_specific_facts"]["a05-current"]))

    def test_policy_report_must_change_at_month_boundary(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            settings = root / "policy_source.json"
            settings.write_text(json.dumps({
                "content_url": "https://example.test/policy.html",
                "minimum_case_count": 1,
                "required_case_ids": ["a05-current"],
            }), encoding="utf-8")
            with mock.patch("policy_sync.download", return_value=POLICY_FIXTURE):
                sync_policy(
                    settings_path=settings,
                    cases_path=root / "cases.json",
                    batch_date="2026-09-03",
                    cache_dir=root / "cache",
                )
                with self.assertRaisesRegex(RuntimeError, "not updated"):
                    sync_policy(
                        settings_path=settings,
                        cases_path=root / "cases.json",
                        batch_date="2026-10-01",
                        cache_dir=root / "cache",
                    )

    def test_only_explicit_banned_terms_are_replaced(self) -> None:
        title, body, changes = sanitize_copy("查底价", "私信我，现代化门店也能了解")
        self.assertEqual("查💰", title)
        self.assertIn("💌", body)
        self.assertIn("现代化", body)
        self.assertEqual(2, len(changes))

    def test_structure_normalization_removes_model_and_numbers(self) -> None:
        left = normalize_structure("9月比亚迪海豹06新政\n留【城市】", ["比亚迪海豹06"])
        right = normalize_structure("8月零跑A05新政\n留【城市】", ["零跑A05"])
        self.assertEqual(left, right)

    def test_free_modifier_does_not_invent_unconditional_warranty(self) -> None:
        title, body, changes = sanitize_copy(
            "购车权益", "四项终身免费质保（限首任车主且非营运），免费咨询"
        )
        self.assertEqual(title, "购车权益")
        self.assertEqual(body, "四项终身质保（限首任车主且非营运），咨询")
        self.assertNotIn("不设门槛", body)
        self.assertEqual(changes, [{"field": "content", "from": "免费", "to": ""}])
        self.assertEqual(sanitize_copy(title, body)[:2], (title, body))

    def test_random_window_selects_unique_and_diverse_rows(self) -> None:
        pool = [
            {"id": 1, "title": "A", "content": "同一开头 同一正文 留【城市】"},
            {"id": 2, "title": "B", "content": "同一开头 同一正文 留【城市】"},
            {"id": 3, "title": "C", "content": "完全不同的生活场景 先看需求 留【城市】"},
            {"id": 4, "title": "D", "content": "金融方案怎么选 分步骤说明 留【城市】"},
        ]
        rows = select_diverse_rows(
            pool,
            count=3,
            historical_texts_by_account={1: ["同一开头 同一正文 留【城市】"]},
            task_account_ids=[1, 1, 1],
            vehicle_terms=[],
            candidate_window=4,
            rng=random.Random(7),
        )
        self.assertEqual(3, len({row["id"] for row in rows}))
        self.assertIn(3, {row["id"] for row in rows[:2]})

    def test_selection_does_not_repeat_the_same_structure_under_different_ids(self) -> None:
        class NoShuffleRandom:
            @staticmethod
            def shuffle(_value) -> None:
                return None

            @staticmethod
            def random() -> float:
                return 0.5

        pool = [
            {"id": 1, "title": "同一标题", "content": "同一正文\n留【城市】"},
            {"id": 2, "title": "同一标题", "content": "同一正文\n留【城市】"},
            {"id": 3, "title": "另一种标题", "content": "先讲用车场景\n再留【城市】"},
        ]
        rows = select_diverse_rows(
            pool,
            count=2,
            historical_texts_by_account={1: []},
            task_account_ids=[1, 1],
            vehicle_terms=[],
            candidate_window=1,
            rng=NoShuffleRandom(),
        )
        self.assertEqual(2, len({row["structure_id"] for row in rows}))
        self.assertTrue(any(row["selection_note"] == "expanded_for_diversity" for row in rows))

    def test_prompt_pool_keeps_text_and_rejects_quote_table_without_policy(self) -> None:
        common = "小红书汽车海报，画面构图清楚，文字标题分层，字体清晰，" + "背景与车辆说明。" * 25
        rows = [
            {"id": 1, "chinese": common + "主标题「近期行情」副标题「城市+车型」", "image_url": "/a.png"},
            {"id": 2, "chinese": common + "价格表，主标题「车型报价」副标题「配置表」", "image_url": "/b.png"},
            {"id": 3, "chinese": common + "无文字，仅车辆", "image_url": "/c.png"},
        ]
        self.assertEqual([1], [row["id"] for row in safe_prompt_pool(rows, allow_quote_table=False)])

    def test_prompt_pool_rejects_multi_vehicle_card_wording(self) -> None:
        common = "小红书汽车海报，画面构图清楚，文字标题分层，字体清晰，" + "背景与车辆说明。" * 25
        rows = [
            {
                "id": 1,
                "chinese": common + "四款车型价格四宫格模块，主标题「近期行情」副标题「车型方案」",
                "image_url": "/a.png",
            },
            {
                "id": 2,
                "chinese": common + "下方4组车型信息卡片，主标题「近期行情」副标题「车型方案」",
                "image_url": "/b.png",
            },
        ]
        self.assertEqual([], safe_prompt_pool(rows, allow_quote_table=False))

    def test_quote_type_requires_actual_configuration_price_rows(self) -> None:
        self.assertEqual(
            STANDARD_TEMPLATE_TYPE,
            copy_content_type("报价单已更新，留【城市】了解"),
        )
        self.assertEqual(
            QUOTE_TABLE_TYPE,
            copy_content_type(
                "405舒享版｜¥63,900｜按条件测算¥56,232\n"
                "510悦享版｜¥75,900｜按条件测算¥66,792"
            ),
        )
        self.assertEqual(
            QUOTE_TABLE_TYPE,
            prompt_template_type(
                "汽车报价海报，4宫格下方为两列表格：车型版本、裸车价，"
                "包含530舒享版、530智享版、605智享版、605激光雷达版"
            ),
        )

    def test_quote_prompt_can_keep_more_than_nine_visible_text_slots(self) -> None:
        cells = " ".join(f"“单元格{i}”" for i in range(1, 13))
        source = (
            "竖版汽车报价海报，文字与字体分层，配置价格表；"
            "405舒享版：¥63,900；510悦享版：¥75,900；" + cells + "；背景与构图说明。" * 10
        )
        rows = [{"id": 8, "chinese": source, "image_url": "/quote.png"}]
        selected = safe_prompt_pool(rows, allow_quote_table=True)
        self.assertEqual(1, len(selected))
        self.assertEqual(QUOTE_TABLE_TYPE, selected[0]["template_type"])
        self.assertGreater(selected[0]["source_slot_count"], 9)

    def test_quote_image_plan_accepts_traceable_twelve_slot_table(self) -> None:
        blocks = [
            "零跑A05", "配置价格参考", "车型", "官方指导价", "条件测算价",
            "405舒享版", "¥63,900", "¥56,232", "510悦享版", "¥75,900", "¥66,792", "按相应条件测算",
        ]
        source = "；".join(blocks)
        plan = {
            "adapted_prompt": "零跑A05报价海报；" + "；".join(f"“{value}”" for value in blocks),
            "text_blocks": blocks,
            "slot_mappings": [
                {"source": value, "output": value, "action": "保留或最小替换"}
                for value in blocks
            ],
            "source_slot_count": 12,
            "selected_prompt_original": source,
            "template_type": QUOTE_TABLE_TYPE,
        }
        copy = {
            "title": "零跑A05近期看车笔记",
            "content": "空间和日常使用感受都值得到店看看\n留【城市+零跑A05】\n#零跑A05[话题]#",
        }
        self.assertEqual([], validate_image_plan(plan, copy, self.case))

    def test_quote_ocr_allows_registered_policy_rows_absent_from_copy(self) -> None:
        errors = image_ocr_errors(
            [
                {"text": "零跑A05 405舒享版 ¥63,900", "confidence": 0.99},
                {"text": "510悦享版 ¥75,900", "confidence": 0.99},
            ],
            copy={"title": "零跑A05看车笔记", "content": "留【城市+零跑A05】"},
            case=self.case,
            expected_text_blocks=["405舒享版", "¥63,900", "510悦享版", "¥75,900"],
            allow_policy_facts=True,
        )
        self.assertEqual([], errors)

    def test_ocr_requires_planned_quote_amounts_to_be_visible(self) -> None:
        errors = image_ocr_errors(
            [{"text": "零跑A05 405舒享版", "confidence": 0.99}],
            copy={"title": "零跑A05", "content": "405舒享版指导价¥63,900；510S指导价¥90,900"},
            case=self.case,
            expected_text_blocks=["405舒享版", "¥63,900", "510S", "¥90,900"],
        )
        self.assertTrue(any("未完整识别计划金额" in value for value in errors))
        self.assertTrue(any("未完整识别计划配置名" in value for value in errors))

    def test_copy_validator_requires_final_topics_and_preserved_lead(self) -> None:
        mother = {"title": "示例", "content": "先了解\n留【城市】\n#买车[话题]#"}
        valid = validate_copy(
            title="零跑A05近期消息",
            content="先了解\n留【城市+零跑A05】\n#零跑A05[话题]#",
            mother=mother,
            case=self.case,
        )
        self.assertTrue(valid["pass"], valid)
        invalid = validate_copy(
            title="零跑A05近期消息",
            content="先了解\n#零跑A05[话题]#\n最后补一句",
            mother=mother,
            case=self.case,
        )
        self.assertFalse(invalid["pass"])

    def test_copy_validator_blocks_repeated_unknown_fact_placeholders(self) -> None:
        mother = {"title": "示例", "content": "参数速览\n续航参数\n动力参数\n留【城市】\n#买车[话题]#"}
        result = validate_copy(
            title="零跑A05参数速览",
            content=(
                "参数速览\n续航以官方发布为准\n动力以官方信息为准\n"
                "留【城市】\n#零跑A05[话题]#"
            ),
            mother=mother,
            case=self.case,
        )
        self.assertFalse(result["pass"])
        self.assertTrue(any("占位语" in value for value in result["hard_errors"]))

    def test_copy_validator_allows_one_normal_official_qualifier(self) -> None:
        mother = {"title": "示例", "content": "指导价说明\n留【城市】\n#买车[话题]#"}
        result = validate_copy(
            title="零跑A05指导价说明",
            content="指导价以官方为准\n留【城市】\n#零跑A05[话题]#",
            mother=mother,
            case=self.case,
        )
        self.assertTrue(result["pass"], result)

    def test_image_plan_cannot_force_policy_amount_absent_from_copy(self) -> None:
        plan = {
            "adapted_prompt": "零跑A05海报，主标题“近期行情”，副标题“1000元权益”",
            "text_blocks": ["近期行情", "1000元权益"],
            "slot_mappings": [
                {"source": "近期行情", "output": "近期行情", "action": "保留"},
                {"source": "旧权益", "output": "1000元权益", "action": "最小替换"},
            ],
            "source_slot_count": 2,
        }
        errors = validate_image_plan(
            plan,
            {"title": "零跑A05近期行情", "content": "留【城市】了解"},
            self.case,
        )
        self.assertTrue(any("未登记金额" in value for value in errors), errors)

    def test_image_plan_preserves_source_slot_density(self) -> None:
        blocks = [f"文字{index}" for index in range(1, 6)]
        plan = {
            "adapted_prompt": "零跑A05海报，" + "，".join(f"“{value}”" for value in blocks),
            "text_blocks": blocks,
            "slot_mappings": [
                {"source": f"旧文字{index}", "output": value, "action": "最小替换"}
                for index, value in enumerate(blocks, start=1)
            ],
            "source_slot_count": 8,
        }
        errors = validate_image_plan(
            plan,
            {"title": "零跑A05近期消息", "content": "普通说明"},
            self.case,
        )
        self.assertTrue(any("删减过多" in value for value in errors), errors)

    def test_image_plan_requires_traceable_source_slots(self) -> None:
        plan = {
            "adapted_prompt": "零跑A05海报，文字“近期行情”，文字“城市可询”",
            "selected_prompt_original": "母图海报，文字“原主标题”，文字“原副标题”",
            "text_blocks": ["近期行情", "城市可询"],
            "slot_mappings": [
                {"source": "模型虚构槽一", "output": "近期行情", "action": "最小替换"},
                {"source": "模型虚构槽二", "output": "城市可询", "action": "最小替换"},
            ],
            "source_slot_count": 2,
        }
        errors = validate_image_plan(
            plan,
            {"title": "零跑A05近期行情", "content": "城市可询"},
            self.case,
        )
        self.assertTrue(any("无法在母版中定位" in value for value in errors), errors)

    def test_batch_lock_blocks_duplicate_process_for_same_date(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir = Path(directory) / "2026-09-03"
            with BatchRunLock(run_dir):
                with self.assertRaises(BatchAlreadyRunning):
                    with BatchRunLock(run_dir):
                        pass

    def test_ocr_blocks_only_confident_hard_fact(self) -> None:
        copy = {"title": "零跑A05近期行情", "content": "指导价6.39万起\n留【城市】"}
        low_confidence = image_ocr_errors(
            [{"text": "其他车型9.99万", "confidence": 0.2}], copy=copy, case=self.case
        )
        self.assertEqual([], low_confidence)
        hard = image_ocr_errors(
            [{"text": "零跑A05 9.99万", "confidence": 0.99}], copy=copy, case=self.case
        )
        self.assertTrue(any("未登记金额" in value for value in hard), hard)

    def test_ocr_keeps_low_confidence_amounts_in_hard_fact_audit(self) -> None:
        copy = {"title": "零跑A05近期行情", "content": "指导价6.39万起\n留【城市】"}
        errors = image_ocr_errors(
            [{"text": "零跑A05 9.99万", "confidence": 0.3}], copy=copy, case=self.case
        )
        self.assertTrue(any("未登记金额" in value for value in errors), errors)


if __name__ == "__main__":
    unittest.main()
