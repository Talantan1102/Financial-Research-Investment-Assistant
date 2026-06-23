"""_dump_trajectories 纯函数单测 — 不启动 agent/MCP/PG。

红线:trajectories_raw.jsonl 绝不含 gold / passed。
互补:judgements.jsonl 由 _dump_answers 生成,它才是 gold 的唯一归宿。
"""

import json
from collections import defaultdict
from pathlib import Path

from eval.question_gen.case import ComputationCase
from eval.question_gen.runner import _dump_answers, _dump_trajectories

# ── helpers ──────────────────────────────────────────────────────────────────


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


# ── _dump_trajectories ────────────────────────────────────────────────────────


def test_dump_trajectories_has_messages_and_no_gold(tmp_path: Path):
    """RED LINE: trajectories 文件只含轨迹字段,gold/passed 绝不出现。"""
    records = [
        {
            "case_id": "c1",
            "model": "deepseek-v4-flash",
            "messages": [
                {"role": "user", "content": "q"},
                {"role": "assistant", "content": "a"},
            ],
            "n_steps": 3,
            "halt_reason": "natural",
        }
    ]
    p = tmp_path / "trajectories_raw.jsonl"
    _dump_trajectories(records, p)

    rows = [json.loads(line) for line in p.read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 1
    row = rows[0]
    # 正确字段存在
    assert row["messages"][0]["content"] == "q"
    assert row["n_steps"] == 3
    assert row["halt_reason"] == "natural"
    assert row["model"] == "deepseek-v4-flash"
    assert row["case_id"] == "c1"
    # 红线:绝无 gold / passed
    assert "gold" not in row, "trajectories 文件泄漏了 gold — RED LINE 违反"
    assert "passed" not in row, "trajectories 文件泄漏了 passed — RED LINE 违反"


def test_dump_trajectories_multiple_records(tmp_path: Path):
    """多条记录全部写入,顺序保持。"""
    records = [
        {"case_id": f"c{i}", "model": "m", "messages": [], "n_steps": i, "halt_reason": "natural"}
        for i in range(5)
    ]
    p = tmp_path / "traj.jsonl"
    _dump_trajectories(records, p)
    rows = [json.loads(line) for line in p.read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 5
    assert [r["n_steps"] for r in rows] == list(range(5))


def test_dump_trajectories_creates_parent_dir(tmp_path: Path):
    """parent.mkdir 被调用,深层目录自动创建。"""
    p = tmp_path / "a" / "b" / "traj.jsonl"
    _dump_trajectories(
        [{"case_id": "x", "model": "m", "messages": [], "n_steps": 0, "halt_reason": None}], p
    )
    assert p.exists()


def test_dump_trajectories_empty(tmp_path: Path):
    """空列表写出空文件(0 行)。"""
    p = tmp_path / "empty.jsonl"
    _dump_trajectories([], p)
    assert p.read_text(encoding="utf-8") == ""


# ── _dump_answers (judgements 侧,互补验证) ───────────────────────────────────


def test_dump_answers_contains_gold(tmp_path: Path):
    """judgements 文件是 gold 的唯一归宿 — 它必须包含 gold 和 passed。"""
    c = _make_case("c1")
    per_run: dict = defaultdict(list)
    per_run["c1"] = [True]
    answers = {"c1": "1.23"}

    p = tmp_path / "judgements.jsonl"
    _dump_answers([c], per_run, answers, p, model="test-model")

    rows = [json.loads(line) for line in p.read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 1
    row = rows[0]
    # judgements 必须有 gold 和 passed
    assert "gold" in row, "judgements 文件缺 gold"
    assert "passed" in row, "judgements 文件缺 passed"
    assert row["gold"] == 1.23
    assert row["passed"] is True
    assert row["answer"] == "1.23"
    assert row["model"] == "test-model"
    # 但 messages/n_steps/halt_reason 不在 judgements
    assert "messages" not in row
    assert "n_steps" not in row


def test_gold_isolation_complementary(tmp_path: Path):
    """互补验证:轨迹文件无 gold,判定文件有 gold — 两者严格互斥。"""
    traj_records = [
        {
            "case_id": "c1",
            "model": "m",
            "messages": [{"role": "user", "content": "问"}],
            "n_steps": 2,
            "halt_reason": "max_steps",
        }
    ]
    traj_p = tmp_path / "trajectories_raw.jsonl"
    _dump_trajectories(traj_records, traj_p)
    traj_row = json.loads(traj_p.read_text(encoding="utf-8").splitlines()[0])

    c = _make_case("c1")
    per_run: dict = defaultdict(list)
    per_run["c1"] = [False]
    judgements_p = tmp_path / "judgements.jsonl"
    _dump_answers([c], per_run, {}, judgements_p, model="m")
    judge_row = json.loads(judgements_p.read_text(encoding="utf-8").splitlines()[0])

    # 轨迹 — 无 gold/passed
    assert "gold" not in traj_row
    assert "passed" not in traj_row
    # 判定 — 有 gold/passed
    assert "gold" in judge_row
    assert "passed" in judge_row
    # 判定 — 无 messages(不含轨迹)
    assert "messages" not in judge_row
