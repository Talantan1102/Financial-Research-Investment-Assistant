"""难度分层:按 pass-rate 把 eval 数据集分桶,筛出 GRPO 可学习区间。

可学习区间定义:0.2 ≤ pass_rate ≤ 0.8
  too_easy  : pass_rate > 0.8
  learnable : 0.2 ≤ pass_rate ≤ 0.8
  too_hard  : pass_rate < 0.2

用法:
  python -m eval.question_gen.difficulty_sort <dataset.jsonl> [model] [k]

输出写入 <dataset.jsonl>.parent/grpo_sort/<timestamp>/
  grpo_learnable.jsonl  — 可学习区间 case
  too_easy.jsonl        — 太简单
  too_hard.jsonl        — 太难
"""

from __future__ import annotations

import asyncio
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

# ── 纯函数:按 pass_rate 分桶 ──────────────────────────────────────────────────


def bucket_by_pass_rate(
    records: list[dict[str, Any]],
    low: float = 0.2,
    high: float = 0.8,
) -> dict[str, Any]:
    """把答案记录按 pass_rate 分为三桶,返回含摘要的结果字典。

    参数:
        records : 每条含 {case_id, pass_rate, difficulty, indicator} 的 dict 列表
        low     : 可学习下界(包含)
        high    : 可学习上界(包含)

    返回:
        {
          "learnable": [...],  # low <= pass_rate <= high
          "too_easy":  [...],  # pass_rate > high
          "too_hard":  [...],  # pass_rate < low
          "summary": {
            "learnable": int,
            "too_easy":  int,
            "too_hard":  int,
            "total":     int,
            "by_difficulty": {difficulty: {"learnable": int, "too_easy": int, "too_hard": int}},
            "by_indicator":  {indicator:  {"learnable": int, "too_easy": int, "too_hard": int}},
          }
        }
    """
    learnable: list[dict] = []
    too_easy: list[dict] = []
    too_hard: list[dict] = []

    # 细分统计
    by_difficulty: dict[str, dict[str, int]] = defaultdict(lambda: {"learnable": 0, "too_easy": 0, "too_hard": 0})
    by_indicator: dict[str, dict[str, int]] = defaultdict(lambda: {"learnable": 0, "too_easy": 0, "too_hard": 0})

    for rec in records:
        pr: float = rec["pass_rate"]
        diff: str = rec.get("difficulty", "")
        ind: str = rec.get("indicator", "")

        if pr > high:
            bucket = "too_easy"
            too_easy.append(rec)
        elif pr < low:
            bucket = "too_hard"
            too_hard.append(rec)
        else:
            bucket = "learnable"
            learnable.append(rec)

        by_difficulty[diff][bucket] += 1
        by_indicator[ind][bucket] += 1

    return {
        "learnable": learnable,
        "too_easy": too_easy,
        "too_hard": too_hard,
        "summary": {
            "learnable": len(learnable),
            "too_easy": len(too_easy),
            "too_hard": len(too_hard),
            "total": len(records),
            "by_difficulty": {k: dict(v) for k, v in sorted(by_difficulty.items())},
            "by_indicator": {k: dict(v) for k, v in sorted(by_indicator.items())},
        },
    }


# ── 主流程:跑 pass@k 后写三桶 jsonl ────────────────────────────────────────────


async def sort_dataset(
    dataset_path: Path | str,
    model: str = "qwen3-8b",
    k: int = 4,
    as_of: str = "20260612",
    out_dir: Path | str | None = None,
) -> dict[str, Any]:
    """加载题集,跑 pass@k,按 pass_rate 分桶,写三文件,返回 summary。

    输出目录默认为 dataset_path.parent/grpo_sort/。
    每桶文件中每行是原始 case dict(含 pass_rate / n_runs 附加字段)。
    """
    from eval.question_gen import case as case_mod
    from eval.question_gen.runner import run_passk

    dataset_path = Path(dataset_path)
    if out_dir is None:
        out_dir = dataset_path.parent / "grpo_sort"
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    cases = case_mod.load_jsonl(dataset_path)

    # 用临时路径落答案文件
    answers_path = out_dir / "_passk_answers_tmp.jsonl"
    await run_passk(
        cases,
        k=k,
        model=model,
        as_of=as_of,
        answers_path=answers_path,
    )

    # 读取 pass_rate 记录,建 case_id → rate 映射
    rate_by_id: dict[str, dict] = {}
    with answers_path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            rec = json.loads(line)
            rate_by_id[rec["case_id"]] = rec

    # 把 pass_rate / n_runs 附加回原始 case dict,构造完整记录
    import dataclasses

    full_records: list[dict] = []
    for c in cases:
        base = dataclasses.asdict(c)
        rate_rec = rate_by_id.get(c.case_id, {})
        base["pass_rate"] = rate_rec.get("pass_rate", 0.0)
        base["n_runs"] = rate_rec.get("n_runs", 0)
        full_records.append(base)

    result = bucket_by_pass_rate(full_records)

    # 写三桶文件
    _write_jsonl(result["learnable"], out_dir / "grpo_learnable.jsonl")
    _write_jsonl(result["too_easy"], out_dir / "too_easy.jsonl")
    _write_jsonl(result["too_hard"], out_dir / "too_hard.jsonl")

    summary = result["summary"]
    print(f"分桶完成 → {out_dir}")
    print(f"  可学习: {summary['learnable']}  太简单: {summary['too_easy']}  太难: {summary['too_hard']}")
    return summary


def _write_jsonl(records: list[dict], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for rec in records:
            f.write(json.dumps(rec, ensure_ascii=False, default=str) + "\n")


# ── __main__ ────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    _dataset = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("data/computation_cases.jsonl")
    _model = sys.argv[2] if len(sys.argv) > 2 else "qwen3-8b"
    _k = int(sys.argv[3]) if len(sys.argv) > 3 else 4

    asyncio.run(sort_dataset(_dataset, model=_model, k=_k))
