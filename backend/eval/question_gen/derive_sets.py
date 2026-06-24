# backend/eval/question_gen/derive_sets.py
"""manifest → eval / SFT / RL 三套派生。

spec: docs/superpowers/specs/2026-06-24-eval-data-distribution-design.md §5
- rl_train = tags.in_rl ∧ reward_eligible(丢端点 + 仅奖励轨)
- sft = sft_clean_count>0,每题≤per_case_cap、每 intent≤per_job_cap
- eval 来自评测股独立生成(不依赖 manifest)
红线:RL/SFT 用的训练股 ∩ 评测股 = ∅;SFT 轨迹本体无 gold(轨迹来自 runner collect,本模块只选 case)。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from eval.question_gen import case as case_mod


def select_rl_ids(manifest: list[dict[str, Any]]) -> set[str]:
    """RL 候选 case_id:进带(in_rl) ∧ 可奖励(reward_eligible)。"""
    return {
        r["case_id"]
        for r in manifest
        if r.get("tags", {}).get("in_rl") and r.get("reward_eligible")
    }


def select_sft(
    manifest: list[dict[str, Any]], *, per_case_cap: int = 2, per_job_cap: int = 100
) -> list[dict[str, Any]]:
    """SFT 选择:每题≤per_case_cap 条、每 intent 总数≤per_job_cap。返回 [{case_id,intent,take}]。"""
    picked: list[dict[str, Any]] = []
    used: dict[str, int] = {}
    for r in manifest:
        cc = r.get("sft_clean_count", 0)
        if cc <= 0:
            continue
        intent = r.get("intent", "?")
        u = used.get(intent, 0)
        if u >= per_job_cap:
            continue
        take = min(cc, per_case_cap, per_job_cap - u)
        if take <= 0:
            continue
        picked.append({"case_id": r["case_id"], "intent": intent, "take": take})
        used[intent] = u + take
    return picked


def assert_stock_disjoint(
    train_cases: list[case_mod.ComputationCase], eval_cases: list[case_mod.ComputationCase]
) -> None:
    """训练股 ∩ 评测股必须为空,否则泄漏 raise。"""
    tr = {s for c in train_cases for s in c.stocks}
    ev = {s for c in eval_cases for s in c.stocks}
    overlap = tr & ev
    if overlap:
        raise AssertionError(f"训练股与评测股相交(泄漏):{sorted(overlap)[:5]}")


def write_sets(
    candidate_cases: list[case_mod.ComputationCase],
    manifest: list[dict[str, Any]],
    eval_cases: list[case_mod.ComputationCase],
    out_dir: Path,
    *,
    per_case_cap: int = 2,
    per_job_cap: int = 100,
) -> dict[str, int]:
    """派生三套落盘:rl_train.jsonl / eval.jsonl / sft_selection.jsonl。返回各套计数。"""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    assert_stock_disjoint(candidate_cases, eval_cases)
    rl_ids = select_rl_ids(manifest)
    rl_cases = [c for c in candidate_cases if c.case_id in rl_ids]
    case_mod.dump_jsonl(rl_cases, out_dir / "rl_train.jsonl")
    case_mod.dump_jsonl(eval_cases, out_dir / "eval.jsonl")
    sft = select_sft(manifest, per_case_cap=per_case_cap, per_job_cap=per_job_cap)
    with (out_dir / "sft_selection.jsonl").open("w", encoding="utf-8") as f:
        for row in sft:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    return {"rl": len(rl_cases), "eval": len(eval_cases), "sft": sum(p["take"] for p in sft)}


__all__ = ["select_rl_ids", "select_sft", "assert_stock_disjoint", "write_sets"]
