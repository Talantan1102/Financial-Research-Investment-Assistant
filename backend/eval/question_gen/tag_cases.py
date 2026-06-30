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


async def run_tagging(
    candidate_path: Path | str,
    out_manifest: Path | str,
    base_model: str,
    strong_model: str,
    collect_dir: Path | str,
    *,
    n_base: int = 8,
    k_strong: int = 5,
    ideal_steps_by_diff: dict[str, int] | None = None,
) -> None:
    """[live, 编排逻辑单测覆盖] 基座 N 次出 per_case_counts(分带),强模型 k 次 collect 出
    干净轨迹数(第二道闸),经 build_manifest_rows 组装 → dump_manifest。

    Args:
        candidate_path: 候选题 jsonl
        out_manifest: 输出 manifest jsonl
        base_model: 基座(应 = RL 基座同一份权重,分带才准)
        strong_model: 强模型(采 SFT 种子轨迹)
        collect_dir: 强模型轨迹采集目录(gold 物理隔离)
        n_base: 基座采样次数(分带分母)
        k_strong: 强模型采样次数
        ideal_steps_by_diff: 难度→理想步数;缺的难度 fallback 8 步
    """
    from eval.question_gen import cleanliness, runner

    cases = case_mod.load_jsonl(Path(candidate_path))
    by_id = {c.case_id: c for c in cases}

    # 1) 基座 N 次 → 每题通过次数(分带)
    base = await runner.run_passk(cases, k=n_base, model=base_model)
    counts: dict[str, int] = base["per_case_counts"]

    # 2) 强模型 k 次采集轨迹(gold 隔离写盘)
    collect_dir = Path(collect_dir)
    await runner.run_passk(cases, k=k_strong, model=strong_model, collect_dir=collect_dir)

    # 3) 数每题干净轨迹(halt 自然 ∧ 步数≤桶理想)
    clean: dict[str, int] = {}
    with (collect_dir / "trajectories_raw.jsonl").open(encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            traj = json.loads(line)
            ideal = (ideal_steps_by_diff or {}).get(by_id[traj["case_id"]].difficulty, 8)
            if cleanliness.is_clean(traj, ideal_steps=ideal):
                clean[traj["case_id"]] = clean.get(traj["case_id"], 0) + 1

    # 4) 组装 + 落盘
    rows = build_manifest_rows(counts, n_base, clean, cases)
    dump_manifest(rows, Path(out_manifest))


__all__ = ["build_manifest_rows", "dump_manifest", "run_tagging"]
