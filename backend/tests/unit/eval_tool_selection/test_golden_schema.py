"""工具选择 / 技能触发 golden 的 schema 校验 + 加载器 fail-loud(Task 6.2)。

参照 eval_memory_dialogue/test_script_schema.py 的同类测试风格:合法 golden 全字段
类型化,非法 golden fail-loud(必填缺失 / expected 空 / bucket 越界 / case_id 重复)。

额外守护(spec § 3.4 "防拼错"):skill_trigger golden 里所有 load_skill 正例的
args.name **必须**在真实 SkillLoader 清单内 —— 读真件 SkillLoader 对照,
新技能加进 skills_root 后该断言自动扩容。
"""

from __future__ import annotations

from pathlib import Path

import pytest
from eval.tool_selection._core import (
    VALID_BUCKETS,
    GoldenCase,
    aggregate,
    is_abstain_case,
    load_golden,
    score_case,
)

pytestmark = pytest.mark.unit

# golden 路径(repo 根相对路径解析成绝对)
_REPO_ROOT = Path(__file__).resolve().parents[4]
_TS_GOLDEN = _REPO_ROOT / "backend" / "eval" / "tool_selection" / "golden.jsonl"
_SK_GOLDEN = _REPO_ROOT / "backend" / "eval" / "skill_trigger" / "golden.jsonl"

# 条数下限(spec § 5.2 / § 3.2 追加):
#   tool_selection ≥ 24(8 金融 + memory/kb 互斥 + 升级正反 + 延迟搜 + 弃权);
#   skill_trigger:spec 规划口径是"7 技能 × ≥3 = 21+",但当前 skills_root **只有 1 个
#   真实技能**(financial_research,见 SKILL.md / SkillLoader 实测)。本任务是离线
#   评测、不创建技能,故按真实清单落地:financial_research 多措辞正例 + 近似负例,
#   下限取 15(待新技能落地后随 golden 追加抬高)。
_TS_FLOOR = 24
_SK_FLOOR = 15


# --- 真实技能清单(防拼错对照源)-------------------------------------------


def _real_skill_names() -> set[str]:
    """读真件 SkillLoader,返回 skills_root 下的真实技能 name 集合。"""
    from app.skills.skill_loader import SkillLoader

    skills_root = _REPO_ROOT / "backend" / "app" / "skills"
    loader = SkillLoader(skills_root=skills_root)
    return {m.name for m in loader.load_l1()}


# --- 加载器:合法 golden 全字段类型化 --------------------------------------


def test_tool_selection_golden_loads_and_floors() -> None:
    cases = load_golden(_TS_GOLDEN)
    assert len(cases) >= _TS_FLOOR, f"tool_selection golden 应 ≥ {_TS_FLOOR} 条,实得 {len(cases)}"
    assert all(isinstance(c, GoldenCase) for c in cases)
    # case_id 唯一(load_golden 已 fail-loud,这里再断言一次)
    ids = [c.case_id for c in cases]
    assert len(ids) == len(set(ids))


def test_skill_trigger_golden_loads_and_floors() -> None:
    cases = load_golden(_SK_GOLDEN)
    assert len(cases) >= _SK_FLOOR, f"skill_trigger golden 应 ≥ {_SK_FLOOR} 条,实得 {len(cases)}"


def test_buckets_within_enum() -> None:
    for path in (_TS_GOLDEN, _SK_GOLDEN):
        for c in load_golden(path):
            assert c.bucket in VALID_BUCKETS, f"{c.case_id}: bucket {c.bucket!r} 越界"


def test_expected_has_at_least_one_key() -> None:
    for path in (_TS_GOLDEN, _SK_GOLDEN):
        for c in load_golden(path):
            assert c.expected, f"{c.case_id}: expected 不能为空"


def test_abstain_classification_present() -> None:
    """tool_selection 含弃权 case(first_tool=null)与升级弃权 case(仅 not_tools)。"""
    cases = load_golden(_TS_GOLDEN)
    abstain = [c for c in cases if is_abstain_case(c)]
    assert len(abstain) >= 2, "tool_selection 应至少有 2 条弃权 case"
    # 升级弃权:expected 含 not_tools 且不含正向 first_tool
    esc_neg = [c for c in cases if c.expected.get("not_tools") and "first_tool" not in c.expected]
    assert esc_neg, "应有仅 not_tools 的升级弃权 case"


def test_sequence_cases_present() -> None:
    """延迟工具该搜先搜:tools_sequence_contains 以 search_tools 开头。"""
    cases = load_golden(_TS_GOLDEN)
    seq_cases = [c for c in cases if "tools_sequence_contains" in c.expected]
    assert len(seq_cases) >= 2, "应至少有 2 条延迟工具序列 case"
    for c in seq_cases:
        seq = c.expected["tools_sequence_contains"]
        assert seq[0] == "search_tools", f"{c.case_id}: 序列应以 search_tools 开头"


# --- 技能 golden 的 load_skill name 全在真实清单内 -------------------------


def test_skill_trigger_load_skill_names_are_real() -> None:
    real = _real_skill_names()
    assert real, "SkillLoader 未发现任何真实技能,清单对照失效"
    cases = load_golden(_SK_GOLDEN)
    load_skill_cases = [
        c for c in cases if c.expected.get("first_tool") == "load_skill"
    ]
    assert load_skill_cases, "skill_trigger 应有 load_skill 正例"
    for c in load_skill_cases:
        name = c.expected.get("args_contains", {}).get("name")
        assert name is not None, f"{c.case_id}: load_skill 正例须在 args_contains 给 name"
        assert name in real, (
            f"{c.case_id}: 技能名 {name!r} 不在真实清单 {sorted(real)} 内(防拼错)"
        )
        # skill 字段(若给)应与 args.name 一致
        if c.skill is not None:
            assert c.skill == name, f"{c.case_id}: skill 字段 {c.skill!r} 与 args.name {name!r} 不符"


def test_skill_trigger_has_positives_and_near_miss_negatives() -> None:
    """每个真实技能 ≥3 正例(spec § 3.4 含 near-miss 负例)。"""
    cases = load_golden(_SK_GOLDEN)
    pos = [c for c in cases if c.expected.get("first_tool") == "load_skill"]
    neg = [c for c in cases if "load_skill" in (c.expected.get("not_tools") or [])]
    assert len(pos) >= 3, "应至少 3 条 load_skill 正例(对齐每技能 ≥3 口径)"
    assert len(neg) >= 1, "应至少 1 条 near-miss 负例(not_tools 含 load_skill)"


# --- 加载器 fail-loud ------------------------------------------------------


def _write(tmp_path: Path, *lines: str) -> Path:
    p = tmp_path / "g.jsonl"
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return p


def test_missing_required_field_fails_loud(tmp_path: Path) -> None:
    p = _write(tmp_path, '{"case_id": "x", "category": "single_tool", "user_input": "q"}')
    with pytest.raises(ValueError, match="缺失必填字段"):
        load_golden(p)


def test_empty_expected_fails_loud(tmp_path: Path) -> None:
    p = _write(
        tmp_path,
        '{"case_id": "x", "category": "single_tool", "user_input": "q",'
        ' "expected": {}, "bucket": "金融数据"}',
    )
    with pytest.raises(ValueError, match="至少含一键"):
        load_golden(p)


def test_invalid_bucket_fails_loud(tmp_path: Path) -> None:
    p = _write(
        tmp_path,
        '{"case_id": "x", "category": "single_tool", "user_input": "q",'
        ' "expected": {"first_tool": "get_news"}, "bucket": "乱填的桶"}',
    )
    with pytest.raises(ValueError, match="bucket"):
        load_golden(p)


def test_duplicate_case_id_fails_loud(tmp_path: Path) -> None:
    line = (
        '{"case_id": "dup", "category": "single_tool", "user_input": "q",'
        ' "expected": {"first_tool": "get_news"}, "bucket": "金融数据"}'
    )
    p = _write(tmp_path, line, line)
    with pytest.raises(ValueError, match="重复"):
        load_golden(p)


def test_empty_file_fails_loud(tmp_path: Path) -> None:
    p = _write(tmp_path, "// only a comment")
    with pytest.raises(ValueError, match="无有效 case"):
        load_golden(p)


def test_bad_json_line_fails_loud(tmp_path: Path) -> None:
    p = _write(tmp_path, "{not json}")
    with pytest.raises(ValueError, match="不是合法 JSON"):
        load_golden(p)


# --- 评分逻辑(纯函数,无 LLM)---------------------------------------------


def _case(expected: dict, bucket: str = "金融数据") -> GoldenCase:
    return GoldenCase(
        case_id="t", category="single_tool", user_input="q", expected=expected, bucket=bucket
    )


def test_score_first_tool_and_args_match() -> None:
    c = _case({"first_tool": "get_stock_quote", "args_contains": {"ts_code": "600519.SH"}})
    ok = score_case(c, [{"tool_name": "get_stock_quote", "args": {"ts_code": "600519.SH"}}])
    assert ok.passed
    wrong_args = score_case(c, [{"tool_name": "get_stock_quote", "args": {"ts_code": "000001.SZ"}}])
    assert not wrong_args.passed
    wrong_tool = score_case(c, [{"tool_name": "get_financial_statements", "args": {}}])
    assert not wrong_tool.passed


def test_score_abstain() -> None:
    c = _case({"first_tool": None}, bucket="弃权")
    assert score_case(c, []).passed
    assert not score_case(c, [{"tool_name": "get_news", "args": {}}]).passed


def test_score_not_tools() -> None:
    c = _case({"first_tool": "get_stock_quote", "not_tools": ["offer_deep_research"]}, bucket="升级")
    assert score_case(c, [{"tool_name": "get_stock_quote", "args": {}}]).passed
    bad = score_case(
        c,
        [
            {"tool_name": "get_stock_quote", "args": {}},
            {"tool_name": "offer_deep_research", "args": {}},
        ],
    )
    assert not bad.passed


def test_score_sequence_subsequence() -> None:
    c = _case({"tools_sequence_contains": ["search_tools", "compare_stocks"]})
    # search_tools 已被 SUT 排除,但序列断言走 names —— 这里模拟 names 含两者按序
    ok = score_case(
        c,
        [
            {"tool_name": "search_tools", "args": {}},
            {"tool_name": "compare_stocks", "args": {}},
        ],
    )
    assert ok.passed
    out_of_order = score_case(
        c,
        [
            {"tool_name": "compare_stocks", "args": {}},
            {"tool_name": "search_tools", "args": {}},
        ],
    )
    assert not out_of_order.passed


def test_aggregate_rel_irrel_split() -> None:
    rel_pass = score_case(_case({"first_tool": "get_news"}), [{"tool_name": "get_news", "args": {}}])
    rel_fail = score_case(_case({"first_tool": "get_news"}), [])
    irrel_pass = score_case(_case({"first_tool": None}, bucket="弃权"), [])
    rep = aggregate([rel_pass, rel_fail, irrel_pass])
    assert rep.rel_total == 2 and rep.rel_pass == 1
    assert rep.irrel_total == 1 and rep.irrel_pass == 1
    assert rep.rel_acc == 0.5
    assert rep.irrel_acc == 1.0
