"""难度分桶纯函数单测 — 不打真模型/tushare/PG。

覆盖:
  1. bucket_by_pass_rate 基本分桶逻辑(0.0→too_hard, 1.0→too_easy, 中间→learnable)
  2. summary 计数正确
  3. 边界值:0.2 和 0.8 恰好落 learnable
  4. by_difficulty / by_indicator 细分统计
  5. _dump_answers 已包含 pass_rate 和 n_runs 字段
"""

import json
from collections import defaultdict
from pathlib import Path

import pytest

from eval.question_gen.difficulty_sort import bucket_by_pass_rate
from eval.question_gen.runner import _dump_answers
from eval.question_gen.case import ComputationCase


# ── helpers ──────────────────────────────────────────────────────────────────


def _rec(case_id: str, pass_rate: float, difficulty: str = "简单", indicator: str = "interval_return") -> dict:
    return {
        "case_id": case_id,
        "pass_rate": pass_rate,
        "difficulty": difficulty,
        "indicator": indicator,
    }


def _make_case(case_id: str = "c1") -> ComputationCase:
    return ComputationCase(
        case_id=case_id,
        intent="区间收益",
        difficulty="简单",
        question="茅台过去一年涨了多少?",
        stocks=["600519.SH"],
        indicator="interval_return",
        window="2025-06-22~2026-06-22",
        gold=1.23,
        gold_shape="scalar",
        tolerance={"rel": 0.01},
    )


# ── bucket_by_pass_rate: 基本分桶 ─────────────────────────────────────────────


def test_bucket_basic_five_rates():
    """pass_rates [0.0, 0.25, 0.5, 0.75, 1.0] 分桶正确。"""
    records = [
        _rec("a", 0.0),   # too_hard
        _rec("b", 0.25),  # learnable
        _rec("c", 0.5),   # learnable
        _rec("d", 0.75),  # learnable
        _rec("e", 1.0),   # too_easy
    ]
    res = bucket_by_pass_rate(records)

    too_hard_ids = {r["case_id"] for r in res["too_hard"]}
    learnable_ids = {r["case_id"] for r in res["learnable"]}
    too_easy_ids = {r["case_id"] for r in res["too_easy"]}

    assert too_hard_ids == {"a"}
    assert learnable_ids == {"b", "c", "d"}
    assert too_easy_ids == {"e"}


def test_bucket_summary_counts():
    """summary 中各桶计数和 total 与列表长度一致。"""
    records = [
        _rec("a", 0.0),
        _rec("b", 0.25),
        _rec("c", 0.5),
        _rec("d", 0.75),
        _rec("e", 1.0),
    ]
    res = bucket_by_pass_rate(records)
    s = res["summary"]
    assert s["too_hard"] == 1
    assert s["learnable"] == 3
    assert s["too_easy"] == 1
    assert s["total"] == 5
    # summary 与实际列表长度一致
    assert s["learnable"] == len(res["learnable"])
    assert s["too_easy"] == len(res["too_easy"])
    assert s["too_hard"] == len(res["too_hard"])


# ── 边界值:0.2 和 0.8 ────────────────────────────────────────────────────────


def test_bucket_boundary_exactly_low():
    """pass_rate == 0.2 (= low) 应落 learnable(闭区间)。"""
    records = [_rec("x", 0.2)]
    res = bucket_by_pass_rate(records)
    assert len(res["learnable"]) == 1
    assert len(res["too_hard"]) == 0
    assert len(res["too_easy"]) == 0


def test_bucket_boundary_exactly_high():
    """pass_rate == 0.8 (= high) 应落 learnable(闭区间)。"""
    records = [_rec("x", 0.8)]
    res = bucket_by_pass_rate(records)
    assert len(res["learnable"]) == 1
    assert len(res["too_hard"]) == 0
    assert len(res["too_easy"]) == 0


def test_bucket_boundary_just_below_low():
    """pass_rate = 0.19 (< 0.2) → too_hard。"""
    records = [_rec("x", 0.19)]
    res = bucket_by_pass_rate(records)
    assert len(res["too_hard"]) == 1
    assert len(res["learnable"]) == 0


def test_bucket_boundary_just_above_high():
    """pass_rate = 0.81 (> 0.8) → too_easy。"""
    records = [_rec("x", 0.81)]
    res = bucket_by_pass_rate(records)
    assert len(res["too_easy"]) == 1
    assert len(res["learnable"]) == 0


# ── summary 细分统计 ──────────────────────────────────────────────────────────


def test_bucket_by_difficulty_breakdown():
    """by_difficulty 细分计数正确。"""
    records = [
        _rec("a", 0.1, difficulty="简单"),   # too_hard
        _rec("b", 0.5, difficulty="简单"),   # learnable
        _rec("c", 0.9, difficulty="中等"),   # too_easy
        _rec("d", 0.3, difficulty="中等"),   # learnable
    ]
    res = bucket_by_pass_rate(records)
    s = res["summary"]

    assert s["by_difficulty"]["简单"]["too_hard"] == 1
    assert s["by_difficulty"]["简单"]["learnable"] == 1
    assert s["by_difficulty"]["中等"]["too_easy"] == 1
    assert s["by_difficulty"]["中等"]["learnable"] == 1


def test_bucket_by_indicator_breakdown():
    """by_indicator 细分计数正确。"""
    records = [
        _rec("a", 0.0, indicator="interval_return"),  # too_hard
        _rec("b", 0.5, indicator="interval_return"),  # learnable
        _rec("c", 0.5, indicator="pe_ratio"),         # learnable
        _rec("d", 1.0, indicator="pe_ratio"),         # too_easy
    ]
    res = bucket_by_pass_rate(records)
    s = res["summary"]

    assert s["by_indicator"]["interval_return"]["too_hard"] == 1
    assert s["by_indicator"]["interval_return"]["learnable"] == 1
    assert s["by_indicator"]["pe_ratio"]["learnable"] == 1
    assert s["by_indicator"]["pe_ratio"]["too_easy"] == 1


# ── 自定义 low/high 阈值 ─────────────────────────────────────────────────────


def test_bucket_custom_thresholds():
    """自定义 low=0.3, high=0.7 时边界正确。"""
    records = [
        _rec("a", 0.2),   # too_hard (< 0.3)
        _rec("b", 0.3),   # learnable (== 0.3)
        _rec("c", 0.7),   # learnable (== 0.7)
        _rec("d", 0.8),   # too_easy (> 0.7)
    ]
    res = bucket_by_pass_rate(records, low=0.3, high=0.7)
    assert {r["case_id"] for r in res["too_hard"]} == {"a"}
    assert {r["case_id"] for r in res["learnable"]} == {"b", "c"}
    assert {r["case_id"] for r in res["too_easy"]} == {"d"}


# ── 空列表 ────────────────────────────────────────────────────────────────────


def test_bucket_empty_records():
    """空输入 → 三桶均空,total=0。"""
    res = bucket_by_pass_rate([])
    assert res["learnable"] == []
    assert res["too_easy"] == []
    assert res["too_hard"] == []
    assert res["summary"]["total"] == 0


# ── _dump_answers 现在包含 pass_rate 和 n_runs ────────────────────────────────


def test_dump_answers_includes_pass_rate_and_n_runs(tmp_path: Path):
    """_dump_answers 记录中必须含 pass_rate(比率)和 n_runs(运行次数)。"""
    c = _make_case("c1")
    per_run: dict = defaultdict(list)
    per_run["c1"] = [True, False, True, True]  # 3/4 = 0.75

    p = tmp_path / "answers.jsonl"
    _dump_answers([c], per_run, {"c1": "1.23"}, p, model="test-model")

    rows = [json.loads(line) for line in p.read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 1
    row = rows[0]

    # 新字段存在
    assert "pass_rate" in row, "_dump_answers 记录缺 pass_rate"
    assert "n_runs" in row, "_dump_answers 记录缺 n_runs"

    # 值正确
    assert row["n_runs"] == 4
    assert abs(row["pass_rate"] - 0.75) < 1e-6

    # 原有字段仍在
    assert row["case_id"] == "c1"
    assert row["difficulty"] == "简单"
    assert row["indicator"] == "interval_return"
    assert row["gold"] == 1.23
    assert row["gold_shape"] == "scalar"
    assert row["passed"] is True
    assert row["answer"] == "1.23"
    assert row["model"] == "test-model"


def test_dump_answers_pass_rate_all_fail(tmp_path: Path):
    """全部失败时 pass_rate=0.0, passed=False。"""
    c = _make_case("c2")
    per_run: dict = defaultdict(list)
    per_run["c2"] = [False, False]

    p = tmp_path / "answers2.jsonl"
    _dump_answers([c], per_run, {}, p)

    row = json.loads(p.read_text(encoding="utf-8").splitlines()[0])
    assert row["pass_rate"] == 0.0
    assert row["n_runs"] == 2
    assert row["passed"] is False


def test_dump_answers_pass_rate_all_pass(tmp_path: Path):
    """全部通过时 pass_rate=1.0, passed=True。"""
    c = _make_case("c3")
    per_run: dict = defaultdict(list)
    per_run["c3"] = [True, True, True]

    p = tmp_path / "answers3.jsonl"
    _dump_answers([c], per_run, {"c3": "ok"}, p)

    row = json.loads(p.read_text(encoding="utf-8").splitlines()[0])
    assert row["pass_rate"] == 1.0
    assert row["n_runs"] == 3
    assert row["passed"] is True


def test_dump_answers_single_run(tmp_path: Path):
    """k=1 时 n_runs=1,pass_rate 只有 0.0 或 1.0。"""
    c = _make_case("c4")
    per_run: dict = defaultdict(list)
    per_run["c4"] = [True]

    p = tmp_path / "answers4.jsonl"
    _dump_answers([c], per_run, {}, p)

    row = json.loads(p.read_text(encoding="utf-8").splitlines()[0])
    assert row["n_runs"] == 1
    assert row["pass_rate"] == 1.0
