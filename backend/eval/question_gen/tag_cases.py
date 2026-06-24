# backend/eval/question_gen/tag_cases.py
"""打标编排:基座通过次数 + 强模型干净轨迹数 → manifest 行。

spec: docs/superpowers/specs/2026-06-24-eval-data-distribution-design.md §4
纯组装(build_manifest_rows/dump_manifest)单测覆盖;run_tagging 跑模型属 live(runbook 调,不测)。
manifest 行 schema:{case_id, intent, n, pass_count, tags{label,in_rl,prime}, reward_eligible, sft_clean_count}
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from eval.question_gen import band
from eval.question_gen import case as case_mod

_REWARD_SHAPES = ("scalar", "multi_scalar")  # ranking/set 不进奖励


def build_manifest_rows(
    counts: dict[str, int],
    n: int,
    clean_counts: dict[str, int],
    cases: list[case_mod.ComputationCase],
) -> list[dict[str, Any]]:
    """组装 manifest 行。counts/clean_counts 缺的 case 按 0 计。"""
    rows: list[dict[str, Any]] = []
    for c in cases:
        k = counts.get(c.case_id, 0)
        tag = band.classify(k, n=n)
        rows.append(
            {
                "case_id": c.case_id,
                "intent": c.intent,
                "n": n,
                "pass_count": k,
                "tags": {"label": tag.label, "in_rl": tag.in_rl, "prime": tag.prime},
                "reward_eligible": c.gold_shape in _REWARD_SHAPES,
                "sft_clean_count": clean_counts.get(c.case_id, 0),
            }
        )
    return rows


def dump_manifest(rows: list[dict[str, Any]], path: Path) -> None:
    """manifest 落盘 jsonl(每行一题)。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


async def run_tagging(*args: Any, **kwargs: Any) -> None:
    """[live, 不进单测] 跑基座 N=8 出 per_case_counts + 强模型 k=5 collect 出干净轨迹数,
    经 build_manifest_rows 组装 → dump_manifest。具体编排见 plan §Phase2 runbook;
    复用 runner.run_passk(k=8, model=base) 的 per_case_counts 与 (k=5, collect_dir=) 的轨迹。
    """
    raise NotImplementedError("run_tagging 是 live 编排,见 plan §Phase2 runbook")


__all__ = ["build_manifest_rows", "dump_manifest", "run_tagging"]
