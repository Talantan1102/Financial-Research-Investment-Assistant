"""D4 打标 driver:base 分带(本地 sglang Qwen3-8B)+ 强模型采轨(token-plan qwen3.7-max)。

为什么单独写而不直接用 tag_cases.run_tagging:
  base 与 strong 走**不同 LLM 端点**(base=本地 sglang、strong=token-plan maas),
  而 LLM 客户端的 base_url 由 env(LLM_BASE_URL)在 build_llm_service_from_env 构造时读取。
  run_passk 每次调用内部都重建 singletons(含 llm)→ 故在两次 run_passk 之间切 env
  即可把 base/strong 分别路由到两个端点(同进程内合法,build 时读 env、_extra_body_for 请求时读 env)。

思考模式:全线 thinking-on(reasoning-RL 路线)。置 LLM_QWEN3_THINKING=on,
  使 adapter 对 qwen3* 不再发 enable_thinking=False,走模板默认 thinking-on(两端默认皆 on)。

产物:
  - manifest jsonl(build_manifest_rows 同 schema):{case_id,intent,n,pass_count,tags,reward_eligible,sft_clean_count}
  - collect_dir/trajectories_raw.jsonl(强模型干净轨迹,gold 物理隔离)
  - collect_dir/judgements.jsonl

用法:
  set -a; source ../.env; set +a            # 在 backend/ 下;maas key + tushare
  PYTHONPATH=backend LLM_QWEN3_THINKING=on \
  python -m eval.question_gen.run_d4_tagging \
    --candidate eval/question_gen/data/train.jsonl \
    --out eval/question_gen/data/manifest.jsonl \
    --collect eval/question_gen/data/traj \
    --n-base 8 --k-strong 5 --concurrency 32 \
    --limit 20            # 小规模验证;去掉则全量
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path

from eval.question_gen import case as case_mod
from eval.question_gen import cleanliness, runner, tag_cases

SGLANG_URL_DEFAULT = "http://127.0.0.1:30000/v1"


async def run_d4(
    *,
    candidate_path: Path,
    out_manifest: Path,
    collect_dir: Path,
    base_model: str,
    strong_model: str,
    sglang_url: str,
    maas_url: str,
    n_base: int,
    k_strong: int,
    concurrency: int,
    limit: int | None,
    ideal_steps_by_diff: dict[str, int] | None = None,
) -> dict:
    cases = case_mod.load_jsonl(candidate_path)
    if limit:
        cases = cases[:limit]
    by_id = {c.case_id: c for c in cases}
    print(
        f"[D4] {len(cases)} 题 | base={base_model}@sglang n={n_base} | "
        f"strong={strong_model}@maas k={k_strong} | concurrency={concurrency}",
        flush=True,
    )

    # 全线 thinking-on
    os.environ["LLM_QWEN3_THINKING"] = "on"

    # ── pass 1:base 分带(本地 sglang)──────────────────────────────────
    os.environ["LLM_BASE_URL"] = sglang_url
    print(f"[D4] pass1 base 分带 → {sglang_url}", flush=True)
    base = await runner.run_passk(cases, k=n_base, model=base_model, concurrency=concurrency)
    counts: dict[str, int] = base["per_case_counts"]
    print(f"[D4] pass1 完成 pass@{n_base}={base['pass_at_k']}", flush=True)

    # ── pass 2:强模型采轨(token-plan maas)─────────────────────────────
    os.environ["LLM_BASE_URL"] = maas_url
    print(f"[D4] pass2 强模型采轨 → {maas_url}", flush=True)
    await runner.run_passk(
        cases, k=k_strong, model=strong_model, concurrency=concurrency, collect_dir=collect_dir
    )

    # ── 数干净轨迹(halt 自然 ∧ 步数≤桶理想)────────────────────────────
    clean: dict[str, int] = {}
    traj_path = collect_dir / "trajectories_raw.jsonl"
    with traj_path.open(encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            traj = json.loads(line)
            ideal = (ideal_steps_by_diff or {}).get(by_id[traj["case_id"]].difficulty, 8)
            if cleanliness.is_clean(traj, ideal_steps=ideal):
                clean[traj["case_id"]] = clean.get(traj["case_id"], 0) + 1

    # ── 组装 + 落盘 ──────────────────────────────────────────────────
    rows = tag_cases.build_manifest_rows(counts, n_base, clean, cases)
    tag_cases.dump_manifest(rows, out_manifest)
    print(f"[D4] manifest 落盘 {out_manifest}({len(rows)} 行)", flush=True)

    # 概览
    from collections import Counter

    labels = Counter(r["tags"]["label"] for r in rows)
    in_rl = sum(r["tags"]["in_rl"] for r in rows)
    prime = sum(r["tags"]["prime"] for r in rows)
    clean_total = sum(r["sft_clean_count"] for r in rows)
    print(
        f"[D4] 分带: {dict(labels)} | in_rl={in_rl} prime={prime} | 干净轨迹合计={clean_total}",
        flush=True,
    )
    return {"base": base, "rows": rows, "labels": dict(labels)}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--candidate", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--collect", required=True, type=Path)
    ap.add_argument("--base-model", default="qwen3-8b")
    ap.add_argument("--strong-model", default="qwen3.7-max")
    ap.add_argument("--sglang-url", default=SGLANG_URL_DEFAULT)
    ap.add_argument("--maas-url", default=os.environ.get("LLM_BASE_URL", ""))
    ap.add_argument("--n-base", type=int, default=8)
    ap.add_argument("--k-strong", type=int, default=5)
    ap.add_argument("--concurrency", type=int, default=32)
    ap.add_argument("--limit", type=int, default=None)
    args = ap.parse_args()

    if not args.maas_url:
        raise SystemExit("maas-url 为空:请先 source ../.env(需要 LLM_BASE_URL),或显式传 --maas-url")

    asyncio.run(
        run_d4(
            candidate_path=args.candidate,
            out_manifest=args.out,
            collect_dir=args.collect,
            base_model=args.base_model,
            strong_model=args.strong_model,
            sglang_url=args.sglang_url,
            maas_url=args.maas_url,
            n_base=args.n_base,
            k_strong=args.k_strong,
            concurrency=args.concurrency,
            limit=args.limit,
        )
    )


if __name__ == "__main__":
    main()
