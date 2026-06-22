"""judge.py 纯函数确定性单测:手写数据,不依赖网络/DB/LLM。"""

from __future__ import annotations

from eval.question_gen.judge import hit_scalar, judge, nums


# ---- nums ----


def test_nums_mixed_percent_and_thousands():
    assert nums("涨跌幅 -10.63%,从 1,422.29 到 1,271.10") == [-10.63, 1422.29, 1271.10]


def test_nums_empty_when_no_digits():
    assert nums("没有任何数字的中文") == []


# ---- hit_scalar ----


def test_hit_scalar_abs_percent_sign_ignored():
    # gold -10.63,容差 abs 0.5;答案里的 -10.63 直接命中。
    assert hit_scalar("结果 -10.63%", -10.63, {"kind": "abs", "value": 0.5}) is True


def test_hit_scalar_abs_compares_by_absolute_value():
    # abs(10.70) - abs(-10.63) = 0.07 <= 0.5 -> 命中(正负号不影响)。
    assert hit_scalar("结果 10.70", -10.63, {"kind": "abs", "value": 0.5}) is True


def test_hit_scalar_rel_within_two_percent():
    # abs(19.86 - 19.79) = 0.07 <= 0.02 * 19.79 ≈ 0.396 -> 命中。
    assert hit_scalar("19.86", 19.79, {"kind": "rel", "value": 0.02}) is True


def test_hit_scalar_rel_mult_near_zero_hits():
    # 涨幅 -0.164% vs agent -0.16%:比"价格倍数"(0.99836 vs 0.9984),接近零不放大 → 命中。
    assert hit_scalar("近三个月涨幅 -0.16%", -0.164, {"kind": "rel_mult", "value": 0.005}) is True
    # 对照:纯相对误差会误杀(|0.16-0.164|/0.164 ≈ 2.4% > 0.5%)。
    assert hit_scalar("涨幅 -0.16%", -0.164, {"kind": "rel", "value": 0.005}) is False


def test_hit_scalar_rel_mult_large_keeps_precision_and_sign():
    # 大涨幅仍按倍数卡精度:gold 50%,agent 49.6% → 倍数 1.496 vs 1.5,相对差 0.27% <= 0.5% → 命中。
    assert hit_scalar("涨幅 49.6%", 50.0, {"kind": "rel_mult", "value": 0.005}) is True
    # 方向反了不命中:gold +50%,答案 -50%。
    assert hit_scalar("跌了 -50%", 50.0, {"kind": "rel_mult", "value": 0.005}) is False


def test_hit_scalar_miss_when_far():
    assert hit_scalar("结果 -8.0", -10.63, {"kind": "abs", "value": 0.5}) is False


# ---- judge: scalar ----


def test_judge_scalar_hit():
    assert judge(-10.63, "scalar", {"kind": "abs", "value": 0.5}, "结果 -10.63%", []) is True


def test_judge_scalar_miss():
    assert judge(-10.63, "scalar", {"kind": "abs", "value": 0.5}, "结果 -8.0", []) is False


# ---- judge: multi_scalar ----


def test_judge_multi_scalar_all_present():
    gold = {"回撤": 19.23, "波动": 19.86}
    answer = "回撤 19.23,波动 19.86"
    assert judge(gold, "multi_scalar", {"kind": "abs", "value": 0.1}, answer, []) is True


def test_judge_multi_scalar_one_missing():
    gold = {"回撤": 19.23, "波动": 19.86}
    answer = "只有回撤 19.23,波动没算"
    assert judge(gold, "multi_scalar", {"kind": "abs", "value": 0.1}, answer, []) is False


# ---- judge: ranking ----


def test_judge_ranking_correct_order():
    gold = [["茅台", 1], ["五粮液", 2]]
    answer = "第一茅台 第二五粮液"
    candidate = ["茅台", "五粮液", "泸州"]
    assert judge(gold, "ranking", {"kind": "abs", "value": 0.0}, answer, candidate) is True


def test_judge_ranking_wrong_order():
    gold = [["茅台", 1], ["五粮液", 2]]
    answer = "第一五粮液 第二茅台"
    candidate = ["茅台", "五粮液", "泸州"]
    assert judge(gold, "ranking", {"kind": "abs", "value": 0.0}, answer, candidate) is False


# ---- judge: set ----


def test_judge_set_empty_none_selected():
    gold: list = []
    answer = "四只全跌,没有满足的"
    candidate = ["茅台", "五粮液"]
    assert judge(gold, "set", {"kind": "abs", "value": 0.0}, answer, candidate) is True


def test_judge_set_single_selected():
    gold = ["茅台"]
    answer = "只有茅台满足条件"
    candidate = ["茅台", "五粮液"]
    assert judge(gold, "set", {"kind": "abs", "value": 0.0}, answer, candidate) is True
