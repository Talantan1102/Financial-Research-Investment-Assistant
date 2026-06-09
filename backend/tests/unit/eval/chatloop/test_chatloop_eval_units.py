"""L0 纯函数测试:chatloop 评估的 scorer / passk / scenario(零 LLM,零 DB)。

元测试纪律(blueprint § 11):scorer 判定逻辑必须可独立验证,红灯能指出 scorer 对不对。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from eval.chatloop.passk import pass1_rate, pass_power_k, passk_rate
from eval.chatloop.scenario import load_scenarios
from eval.chatloop.scorers import score_advice, score_behavior, score_disclaimer, should_disclaim

# --- pass^k 纯函数 ----------------------------------------------------------


def test_passk_all_pass() -> None:
    out = pass_power_k({"c1": [True, True, True]})
    assert out["c1"].passk is True
    assert out["c1"].pass1 == pytest.approx(1.0)


def test_passk_one_fail_kills_passk() -> None:
    out = pass_power_k({"c1": [True, True, False]})
    assert out["c1"].passk is False
    assert out["c1"].pass1 == pytest.approx(2 / 3)


def test_passk_rates() -> None:
    out = pass_power_k({"a": [True, True], "b": [True, False]})
    assert passk_rate(out) == pytest.approx(0.5)  # only 'a' all-pass
    assert pass1_rate(out) == pytest.approx((1.0 + 0.5) / 2)


# --- 免责 / 方向性确定性检查 ------------------------------------------------


def test_disclaimer_present() -> None:
    assert score_disclaimer("茅台现价 1500 元。以上为信息与分析,仅供参考,不构成投资建议。") is True
    assert score_disclaimer("茅台现价 1500 元。") is False


def test_advice_violation() -> None:
    assert score_advice("我建议买入茅台") is True
    assert score_advice("现价 1500,数据来自行情工具。") is False
    assert score_advice("这只票稳赚不赔") is True


def test_should_disclaim_contextual() -> None:
    # 实质市场内容(含数字/估值词)→ 该带
    assert should_disclaim("茅台现价 1512 元") is True
    assert should_disclaim("隆基基本面承压") is True
    # 纯弃答 → 不该带
    assert should_disclaim("你没跟我聊过这个,我没有这个信息") is False
    # 纯闲聊(无数字无市场词)→ 不该带
    assert should_disclaim("这个我帮不上忙呢") is False


# --- score_behavior 委托 ----------------------------------------------------


def _scn(**kw):
    base = {
        "case_id": "t1",
        "category": "single_tool",
        "user_input": "茅台多少钱",
        "expected": {"first_tool": "get_stock_quote", "args_contains": {"ts_code": "600519.SH"}},
        "bucket": "金融数据",
        "difficulty": "直球",
    }
    base.update(kw)
    return base


def _load_one(tmp_path: Path, raw: dict):
    p = tmp_path / "g.jsonl"
    p.write_text(json.dumps(raw, ensure_ascii=False) + "\n", encoding="utf-8")
    return load_scenarios(p)[0]


def test_score_behavior_tool_pass(tmp_path: Path) -> None:
    sc = _load_one(tmp_path, _scn())
    bs = score_behavior(
        sc,
        [{"tool_name": "get_stock_quote", "args": {"ts_code": "600519.SH"}}],
        "现价 1500。不构成投资建议",
    )
    assert bs.tool_passed is True
    assert bs.disclaimer_present is True
    assert bs.is_abstain is False


def test_score_behavior_wrong_tool_fails(tmp_path: Path) -> None:
    sc = _load_one(tmp_path, _scn())
    bs = score_behavior(sc, [{"tool_name": "memory_search", "args": {}}], "x")
    assert bs.tool_passed is False
    assert "memory_search" in bs.tool_detail or "首选" in bs.tool_detail
    assert bs.disclaimer_present is False


def test_score_behavior_abstain_case(tmp_path: Path) -> None:
    sc = _load_one(
        tmp_path,
        _scn(
            case_id="t-abstain",
            expected={"first_tool": None, "not_tools": ["get_stock_quote"]},
            bucket="弃权",
            difficulty="对抗",
        ),
    )
    bs_ok = score_behavior(sc, [], "这超出我能查的范围。不构成投资建议")
    assert bs_ok.is_abstain is True
    assert bs_ok.tool_passed is True  # 正确弃权
    bs_bad = score_behavior(sc, [{"tool_name": "get_stock_quote", "args": {}}], "x")
    assert bs_bad.tool_passed is False  # 该弃权却调了


# --- schema fail-loud -------------------------------------------------------


def test_bad_difficulty_fails(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="difficulty"):
        _load_one(tmp_path, _scn(difficulty="超难"))


def test_missing_expected_fails(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="expected"):
        _load_one(tmp_path, _scn(expected={}))
