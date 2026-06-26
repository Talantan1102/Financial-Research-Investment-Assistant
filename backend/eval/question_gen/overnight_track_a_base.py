"""Track A —— GPU base 分带(夜跑)。独立进程,LLM_BASE_URL=本地 sglang。

设计(对齐 d4-overnight-goal):
- 全量 train 3200 @ n=NBASE,**intent 轮转**排序(每片均匀覆盖 9 类,不会只跑完
  stock_study 就天亮),分片(SHARD 题/片)。
- **可续跑**:每片产物 manifest_shard_XX.jsonl 落持久盘,已存在则跳过 → 杀了重启接着跑。
- 每片失败重试 1 次再跳过(夜跑无人值守,单片 OOM 不拖垮全局)。
- base 只算 pass@k 分带(sft_clean_count=0,留 Track B strong 采轨填)。

用法(由 overnight launcher 以 nohup 起,LLM_BASE_URL 已指向 sglang):
  PYTHONPATH=backend LLM_QWEN3_THINKING=on LLM_BASE_URL=http://127.0.0.1:30000/v1 \
  python -m eval.question_gen.overnight_track_a_base --out <持久盘dir> --n-base 8 --shard 100
"""
from __future__ import annotations
import argparse, asyncio, json, time
from collections import defaultdict
from pathlib import Path

from eval.question_gen import case as case_mod, runner, tag_cases


def intent_round_robin(cases: list) -> list:
    """按 intent 轮转交织:every 9 连续 ≈ 每类一个 → 任意前缀都均匀覆盖各 intent。"""
    by_intent: dict[str, list] = defaultdict(list)
    for c in cases:
        by_intent[c.intent].append(c)
    queues = list(by_intent.values())
    out = []
    while any(queues):
        for q in queues:
            if q:
                out.append(q.pop(0))
    return out


async def run_shard(shard_cases: list, *, n_base: int, model: str, concurrency: int,
                    out_path: Path) -> dict:
    base = await runner.run_passk(shard_cases, k=n_base, model=model, concurrency=concurrency)
    counts: dict[str, int] = base["per_case_counts"]
    rows = tag_cases.build_manifest_rows(counts, n_base, {}, shard_cases)  # clean={} → sft_clean_count=0
    tag_cases.dump_manifest(rows, out_path)
    labels: dict[str, int] = defaultdict(int)
    for r in rows:
        labels[r["tags"]["label"]] += 1
    return {"rows": len(rows), "labels": dict(labels), "pass_at_k": base.get("pass_at_k")}


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--candidate", type=Path,
                    default=Path("eval/question_gen/data/train.jsonl"))
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--n-base", type=int, default=8)
    ap.add_argument("--shard", type=int, default=100)
    ap.add_argument("--concurrency", type=int, default=48)
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    cases = intent_round_robin(case_mod.load_jsonl(args.candidate))
    shards = [cases[i:i + args.shard] for i in range(0, len(cases), args.shard)]
    print(f"[TrackA] {len(cases)} 题 → {len(shards)} 片 × {args.shard} | n={args.n_base} "
          f"conc={args.concurrency} | out={args.out}", flush=True)

    done_labels: dict[str, int] = defaultdict(int)
    for idx, shard in enumerate(shards):
        out_path = args.out / f"manifest_shard_{idx:02d}.jsonl"
        if out_path.exists():
            print(f"[TrackA] 片{idx:02d} 已存在,跳过(续跑)", flush=True)
            continue
        for attempt in (1, 2):
            t0 = time.perf_counter()
            try:
                res = await run_shard(shard, n_base=args.n_base, model="qwen3-8b",
                                      concurrency=args.concurrency, out_path=out_path)
                dt = time.perf_counter() - t0
                for k, v in res["labels"].items():
                    done_labels[k] += v
                print(f"[TrackA] 片{idx:02d} ✅ {res['rows']}题 {res['labels']} "
                      f"pass@{args.n_base}={res['pass_at_k']} {dt:.0f}s | 累计{dict(done_labels)}",
                      flush=True)
                break
            except Exception as e:  # noqa: BLE001
                print(f"[TrackA] 片{idx:02d} 第{attempt}次失败: {type(e).__name__}: {e}", flush=True)
                if attempt == 2:
                    print(f"[TrackA] 片{idx:02d} 两次失败,跳过", flush=True)
    print(f"[TrackA] 全部完成,累计分带 {dict(done_labels)}", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
