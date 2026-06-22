"""ComputationCase schema + jsonl 读写单测(纯函数确定性,手写数据)。"""

from __future__ import annotations

from pathlib import Path

import pytest
from eval.question_gen.case import ComputationCase, dump_jsonl, load_jsonl


def _set_case() -> ComputationCase:
    """gold_shape='set' 且 gold=[] 空集 —— 边界。"""
    return ComputationCase(
        case_id="comp-001",
        intent="筛选",
        difficulty="复杂",
        question="过去一年跑赢茅台的有哪些?",
        stocks=["600519.SH", "000858.SZ"],
        indicator="interval_return",
        window="2025-06-17~2026-06-17",
        gold=[],
        gold_shape="set",
        tolerance={"rel": 0.01},
        meta={"source": "manual"},
    )


def _scalar_case() -> ComputationCase:
    return ComputationCase(
        case_id="comp-002",
        intent="区间收益",
        difficulty="简单",
        question="茅台过去一年涨了多少?",
        stocks=["600519.SH"],
        indicator="interval_return",
        window="2025-06-17~2026-06-17",
        gold=1.23,
        gold_shape="scalar",
        tolerance={"rel": 0.01},
    )


def test_round_trip(tmp_path: Path) -> None:
    cases = [_set_case(), _scalar_case()]
    path = tmp_path / "cases.jsonl"
    dump_jsonl(cases, path)
    loaded = load_jsonl(path)
    assert loaded == cases  # frozen dataclass 逐字段相等
    # 显式核几个承重字段,确保 gold/gold_shape 没被串
    assert loaded[0].gold == [] and loaded[0].gold_shape == "set"
    assert loaded[1].gold == 1.23 and loaded[1].gold_shape == "scalar"
    assert loaded[0].meta == {"source": "manual"}
    assert loaded[1].meta == {}  # 默认空 dict


def test_duplicate_case_id_raises(tmp_path: Path) -> None:
    path = tmp_path / "dup.jsonl"
    dump_jsonl([_scalar_case()], path)
    # 手写一行重复 case_id 追加
    dup_line = (
        '{"case_id": "comp-002", "intent": "区间收益", "difficulty": "简单", '
        '"question": "再问一遍", "stocks": ["600519.SH"], "indicator": "interval_return", '
        '"window": "2025-06-17~2026-06-17", "gold": 9.9, "gold_shape": "scalar", '
        '"tolerance": {"rel": 0.01}, "meta": {}}'
    )
    with path.open("a", encoding="utf-8") as fh:
        fh.write(dup_line + "\n")
    with pytest.raises(ValueError):
        load_jsonl(path)


def test_empty_file_raises(tmp_path: Path) -> None:
    path = tmp_path / "empty.jsonl"
    path.write_text("", encoding="utf-8")
    with pytest.raises(ValueError):
        load_jsonl(path)


def test_all_comment_file_raises(tmp_path: Path) -> None:
    path = tmp_path / "comments.jsonl"
    path.write_text("// 全是注释\n\n// 还是注释\n", encoding="utf-8")
    with pytest.raises(ValueError):
        load_jsonl(path)


def test_missing_path_raises(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        load_jsonl(tmp_path / "does-not-exist.jsonl")
