"""generator/runner 纯函数单测(_scale / _candidate_names / _aggregate)。

async generate()/run_passk() 是真 tushare/真 agent 集成,由离线跑验证,不进 CI。
"""

from __future__ import annotations

from eval.question_gen import generator, runner
from eval.question_gen.case import ComputationCase


def _case(cid: str, diff: str, ind: str, stocks: list[str] | None = None) -> ComputationCase:
    return ComputationCase(
        case_id=cid,
        intent="stock_study",
        difficulty=diff,
        question="q",
        stocks=stocks or ["600519.SH"],
        indicator=ind,
        window="1y",
        gold=1.0,
        gold_shape="scalar",
        tolerance={},
        meta={},
    )


def test_scale_pct_vs_corr() -> None:
    # %-指标 ×100 存百分数;相关不变
    assert generator._scale("涨幅", -0.1063) == -10.63
    assert generator._scale("回撤", 0.1923) == 19.23
    assert generator._scale("相关", 0.7678) == 0.7678


def test_candidate_names_resolves_and_skips_unknown() -> None:
    assert runner._candidate_names(_case("x", "简单", "涨幅", ["600519.SH"])) == ["贵州茅台"]
    assert runner._candidate_names(
        _case("y", "中等", "相关", ["600519.SH", "000858.SZ"])
    ) == ["贵州茅台", "五粮液"]
    # 未知 ts_code 被跳过,不抛
    assert runner._candidate_names(_case("z", "简单", "涨幅", ["BAD.XX"])) == []


def test_aggregate_buckets_and_passk() -> None:
    cases = [
        _case("a", "简单", "涨幅"),
        _case("b", "简单", "涨幅"),
        _case("c", "复杂", "涨幅"),
    ]
    # c 第二次 run 命中 → pass@k = any 应为 True
    per_run = {"a": [True], "b": [False], "c": [False, True]}
    res = runner._aggregate(cases, per_run)
    assert res["pass_at_k"] == {"pass": 2, "total": 3, "rate": round(2 / 3, 3)}
    assert res["by_bucket"]["简单/涨幅"] == {"pass": 1, "total": 2, "rate": 0.5}
    assert res["by_bucket"]["复杂/涨幅"] == {"pass": 1, "total": 1, "rate": 1.0}
    assert res["per_case"]["c"] is True
