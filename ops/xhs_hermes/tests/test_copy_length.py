from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parents[1]))

from copy_length import brevity_instruction, copy_budget, copy_length_check, copy_lengths
from core import validate_copy


CASE = {"vehicle_model": "零跑A10", "policy_text": "价格按条件测算", "quote_rows": [
    {"configuration": f"配置{n}"} for n in range(4)
]}
TABLE = {"content": "全系价格\nA版10万元\nB版11万元\nC版12万元"}


def test_lengths_keep_inline_prose_and_separate_short_tags():
    assert copy_lengths("外观 #车[话题]# 记\n录") == {"body_chars": 4, "tag_chars": 7}
    assert copy_lengths("#" + "长" * 80 + "[话题]#")["body_chars"] == 86
    assert copy_lengths("#第一行\n第二行#")["body_chars"] > 0


def test_short_mother_is_not_expanded_and_has_no_minimum():
    b = copy_budget({"content": "颜色真好看"}, CASE)
    assert b["max_body_chars"] == 180
    assert b["preferred_body_chars"] == 144
    assert not copy_length_check("短一点。", None, CASE)["hard_errors"]
    assert copy_budget({"content": "色" * 800}, CASE)["max_body_chars"] == 280


def test_only_a_real_source_price_list_gets_a_row_allowance():
    assert copy_budget({"content": "价格表来啦，想看各配置报价的来看看"}, CASE)["kind"] == "focused_note"
    assert copy_budget(TABLE, CASE)["max_body_chars"] == 340
    case = deepcopy(CASE)
    case["quote_rows"] += [{"configuration": "配置4"}, {"configuration": "配置4"}, {}]
    assert copy_budget(TABLE, case)["max_body_chars"] == 380
    assert copy_budget(TABLE, {})["max_body_chars"] == 300


def test_draft_cannot_grant_itself_a_larger_budget_or_hide_body_in_tags():
    assert copy_length_check("长" * 300 + TABLE["content"], {"content": "观察外观"}, CASE)["hard_errors"]
    assert copy_length_check("#" + "长" * 300 + "[话题]#", None, CASE)["hard_errors"]
    assert copy_length_check("#零跑A10[话题]#" * 10, None, CASE)["hard_errors"]


def test_boundary_is_exact_and_whitespace_not_counted():
    assert not copy_length_check("字\n" * 180, None, CASE)["hard_errors"]
    assert copy_length_check("字\n" * 181, None, CASE)["hard_errors"]


def test_check_does_not_mutate_or_truncate_and_guidance_keeps_conditions():
    mother, case = deepcopy(TABLE), deepcopy(CASE)
    content = "按相应条件测算，不是成交承诺。" * 60
    original = (deepcopy(mother), deepcopy(case), content)
    result = copy_length_check(content, mother, case)
    assert result["hard_errors"]
    assert (mother, case, content) == original
    instruction = brevity_instruction(copy_budget(mother, case))
    for text in ("完整版本/价格行", "条件必须保留", "不能逐字截断", "没有最低字数"):
        assert text in instruction
    assert "表后只保留必要共同条件" in instruction
    assert "不再总结指导价区间" in instruction
    assert "这是报价表" not in brevity_instruction(copy_budget(None, case))


def test_brevity_and_optional_cta_only_apply_to_interpretive():
    mother = {"content": "观察外观。\n留【城市】\n#汽车[话题]#"}
    for level in ("replica", "light", "interpretive"):
        result = validate_copy(title="零跑A10外观", content="外" * 281 + "\n#汽车[话题]#",
                               mother=mother, case=CASE, adaptation_level=level)
        assert any("正文过长" in error for error in result["hard_errors"]) == (level == "interpretive")
        assert any("留资入口" in error for error in result["hard_errors"]) == (level != "interpretive")
    result = validate_copy(title="零跑A10外观", content="喜欢这个外观。\n#汽车[话题]#",
                           mother=mother, case=CASE, adaptation_level="interpretive")
    assert result["pass"], result


def test_real_hermes_tool_returns_and_enforces_the_same_budget(monkeypatch):
    plugin_path = Path(__file__).parents[1] / "hermes_home/plugins/xhs-copy-tools/__init__.py"
    spec = importlib.util.spec_from_file_location("copy_tools_brevity_test", plugin_path)
    plugin = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(plugin)
    mother = {"id": 1, "content": "外观记录"}
    monkeypatch.setattr(plugin, "_cases", lambda: {"test": CASE})
    monkeypatch.setattr(plugin, "_mothers", lambda: {1: mother})
    monkeypatch.setattr(plugin, "knowledge_for_case", lambda *args: {})
    for level in ("interpretive", "replica", "light"):
        monkeypatch.setenv("XHS_ADAPTATION_LEVEL", level)
        context = json.loads(plugin._handle_get_case({"case_id": "test", "mother_id": 1}))
        result = json.loads(plugin._handle_validate({
            "case_id": "test", "selected_mother_id": 1, "title": "零跑A10",
            "content": "外" * 181 + "\n#汽车[话题]#",
        }))
        assert context["success"] and result["success"]
        assert ("copy_budget" in context) == (level == "interpretive")
        if level == "interpretive":
            assert context["copy_budget"]["max_body_chars"] == result["fidelity"]["brevity"]["max_body_chars"]
            assert not result["pass"]
            assert "正文过长" in result["hard_errors"][0]
