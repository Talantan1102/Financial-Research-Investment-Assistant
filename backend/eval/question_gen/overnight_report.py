"""夜跑晨间报告:聚合 Track A 分带 + Track B 干净轨迹 + 成本。

用法:
  PYTHONPATH=backend python -m eval.question_gen.overnight_report \
    --base eval/question_gen/data/d4_overnight/base \
    --strong eval/question_gen/data/d4_overnight/strong
成本:从 PG trace_spans 按 model 聚合 cost_cny(需 POSTGRES_* env)。
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path


def load_base(base_dir: Path) -> dict:
    rows = []
    for f in sorted(base_dir.glob("manifest_shard_*.jsonl")):
        rows += [json.loads(line) for line in f.read_text().splitlines() if line.strip()]
    by_label: dict[str, int] = defaultdict(int)
    by_intent_label: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    in_rl = prime = 0
    for r in rows:
        lab = r["tags"]["label"]
        by_label[lab] += 1
        by_intent_label[r["intent"]][lab] += 1
        in_rl += r["tags"]["in_rl"]
        prime += r["tags"]["prime"]
    return {
        "n": len(rows),
        "by_label": dict(by_label),
        "by_intent": {k: dict(v) for k, v in by_intent_label.items()},
        "in_rl": in_rl,
        "prime": prime,
    }


def load_strong(strong_dir: Path) -> dict:
    traj = clean = clean_correct = passed = 0
    halt: dict[str, int] = defaultdict(int)
    shards = 0
    for f in sorted(strong_dir.glob("shard_*/trajectories_raw.jsonl")):
        shards += 1
        for line in f.read_text().splitlines():
            if not line.strip():
                continue
            r = json.loads(line)
            traj += 1
            halt[r.get("halt_reason")] += 1
            is_clean = r.get("halt_reason") == "natural" and (r.get("n_steps") or 99) <= 8
            is_pass = bool(r.get("passed"))
            clean += is_clean
            passed += is_pass
            clean_correct += is_clean and is_pass  # SFT 可用:干净 ∧ 正确
    return {
        "shards": shards,
        "traj": traj,
        "clean": clean,
        "passed": passed,
        "clean_correct": clean_correct,
        "halt": dict(halt),
    }


def cost_by_model() -> dict:
    try:
        from app.core.database import SessionLocal
        from sqlalchemy import text

        with SessionLocal() as s:
            rows = s.execute(
                text(
                    "select metadata->>'model' m, count(*) n, "
                    "round(sum((metadata->>'cost_cny')::numeric),3) cost "
                    "from trace_spans where metadata ? 'model' group by 1 order by cost desc nulls last"
                )
            ).all()
        return {(r[0] or "?"): {"spans": r[1], "cost_cny": float(r[2] or 0)} for r in rows}
    except Exception as e:  # noqa: BLE001
        return {"error": str(e)}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", type=Path, required=True)
    ap.add_argument("--strong", type=Path, required=True)
    args = ap.parse_args()

    base = load_base(args.base) if args.base.exists() else {"n": 0}
    strong = load_strong(args.strong) if args.strong.exists() else {"traj": 0}
    cost = cost_by_model()

    print("=" * 60)
    print("D4 夜跑晨间报告")
    print("=" * 60)
    print(f"\n[Track A · base 分带] 覆盖 {base.get('n', 0)}/3200 题")
    print(f"  分带: {base.get('by_label')}")
    print(f"  in_rl(可训)={base.get('in_rl')} prime={base.get('prime')}")
    print("  per-intent:")
    for it, labs in (base.get("by_intent") or {}).items():
        print(f"    {it}: {labs}")
    tj = max(strong.get("traj", 1), 1)
    print(f"\n[Track B · strong 采轨] {strong.get('shards', 0)} 片")
    print(
        f"  轨迹={strong.get('traj', 0)} 正确={strong.get('passed', 0)} 干净(natural≤8)={strong.get('clean', 0)}"
    )
    print(
        f"  ★ SFT 可用(干净∧正确)={strong.get('clean_correct', 0)} ({strong.get('clean_correct', 0) / tj * 100:.0f}%)"
    )
    print(f"  halt={strong.get('halt')}")
    print("\n[成本 by model]")
    for m, v in cost.items():
        if isinstance(v, dict):
            print(f"  {m}: {v.get('spans')} spans ¥{v.get('cost_cny')}")
        else:
            print(f"  {m}: {v}")
    print("=" * 60)


if __name__ == "__main__":
    main()
