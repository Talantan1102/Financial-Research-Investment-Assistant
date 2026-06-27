"""Track B —— maas strong 采轨(夜跑)。独立进程,LLM_BASE_URL=token-plan maas。

设计(对齐 d4-overnight-goal):
- strong 教师(Phase 0 A/B 选出的冠军)对 train 采轨,收 SFT 干净轨迹。
- **intent 轮转** + 分片(SHARD 题/片) + 可续跑(每片 traj 落持久盘,已存在跳过) + 失败重试 1 次。
- **成本封顶**:按案题数封顶 —— max_cases = budget_cny / (k × cny_per_rollout)。
  cny_per_rollout 由 Phase 0 A/B 实测冠军模型得出(deepseek-v4-flash ~¥0.003,qwen3.7-max ~¥0.08),
  从命令行传入,避免按 trace 时间窗算钱被并发的 Track A(qwen3-8b)成本污染。
- 每片 trajectories_raw / judgements 各自落盘(分片 = 崩溃止血,runner 是整批结尾才 dump)。

用法(overnight launcher 以 nohup 起,LLM_BASE_URL 已指向 maas):
  PYTHONPATH=backend LLM_QWEN3_THINKING=on LLM_BASE_URL=<maas> \
  python -m eval.question_gen.overnight_track_b_strong --out <持久盘dir> \
    --model deepseek-v4-flash --k 5 --shard 100 --budget-cny 1290 --cny-per-rollout 0.003
"""

from __future__ import annotations

import argparse
import asyncio
import json
import time
from collections import defaultdict
from pathlib import Path

from eval.question_gen import case as case_mod
from eval.question_gen import runner
from eval.question_gen.overnight_track_a_base import intent_round_robin


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--candidate", type=Path, default=Path("eval/question_gen/data/train.jsonl"))
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--model", required=True)
    ap.add_argument("--k", type=int, default=5)
    ap.add_argument("--shard", type=int, default=100)
    ap.add_argument("--concurrency", type=int, default=24)
    ap.add_argument("--budget-cny", type=float, default=1290.0)
    ap.add_argument(
        "--cny-per-rollout",
        type=float,
        required=True,
        help="A/B 实测冠军模型单 rollout 成本,用于按题数封顶",
    )
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    # 成本封顶 → 最多采多少题
    max_cases = int(args.budget_cny / (args.k * max(args.cny_per_rollout, 1e-9)))
    cases = intent_round_robin(case_mod.load_jsonl(args.candidate))
    capped = cases[:max_cases]
    shards = [capped[i : i + args.shard] for i in range(0, len(capped), args.shard)]
    print(
        f"[TrackB] 教师={args.model} k={args.k} | 预算¥{args.budget_cny} ÷ "
        f"(k×¥{args.cny_per_rollout}/rollout) → 最多 {max_cases} 题 "
        f"(全集 {len(cases)}) → {len(shards)} 片 | out={args.out}",
        flush=True,
    )

    clean_total = 0
    for idx, shard in enumerate(shards):
        sdir = args.out / f"shard_{idx:02d}"
        traj_f = sdir / "trajectories_raw.jsonl"
        if traj_f.exists():
            n = len(traj_f.read_text().splitlines())
            print(f"[TrackB] 片{idx:02d} 已存在({n}轨迹),跳过(续跑)", flush=True)
            continue
        sdir.mkdir(parents=True, exist_ok=True)
        for attempt in (1, 2):
            t0 = time.perf_counter()
            try:
                await runner.run_passk(
                    shard,
                    k=args.k,
                    model=args.model,
                    concurrency=args.concurrency,
                    collect_dir=sdir,
                )
                rows = [json.loads(line) for line in traj_f.read_text().splitlines()]
                halt: dict[str, int] = defaultdict(int)
                for r in rows:
                    halt[r.get("halt_reason")] += 1
                clean = sum(
                    1
                    for r in rows
                    if r.get("halt_reason") == "natural" and (r.get("n_steps") or 99) <= 8
                )
                clean_total += clean
                dt = time.perf_counter() - t0
                print(
                    f"[TrackB] 片{idx:02d} ✅ {len(rows)}轨迹 halt={dict(halt)} "
                    f"干净={clean} {dt:.0f}s | 累计干净={clean_total}",
                    flush=True,
                )
                break
            except Exception as e:  # noqa: BLE001
                print(
                    f"[TrackB] 片{idx:02d} 第{attempt}次失败: {type(e).__name__}: {e}", flush=True
                )
                if attempt == 2:
                    print(f"[TrackB] 片{idx:02d} 两次失败,跳过", flush=True)
    print(f"[TrackB] 完成,累计干净轨迹 {clean_total}", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
