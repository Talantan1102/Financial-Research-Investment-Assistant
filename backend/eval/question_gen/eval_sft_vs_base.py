"""SFT vs base 的 pass@1@oracle 对照评估 —— 出"base X% → SFT Y%、逐意图"表。

两段用法(模型由 env LLM_BASE_URL 指向的 sglang 决定,本脚本只跑题+判分+聚合):

  # 1) 起 sglang serve base,跑一遍存 json
  LLM_BASE_URL=http://127.0.0.1:30000/v1 LLM_QWEN3_THINKING=on \
    PYTHONPATH=backend python -m eval.question_gen.eval_sft_vs_base run \
    --tag base --out /root/eval_base.json --sample 135

  # 2) 起 sglang serve SFT(同端口换权重 / 或另端口),跑一遍存 json
  LLM_BASE_URL=http://127.0.0.1:30000/v1 LLM_QWEN3_THINKING=on \
    PYTHONPATH=backend python -m eval.question_gen.eval_sft_vs_base run \
    --tag sft --out /root/eval_sft.json --sample 135

  # 3) 打印对照表
  PYTHONPATH=backend python -m eval.question_gen.eval_sft_vs_base table \
    /root/eval_base.json /root/eval_sft.json

抽样:按 intent 分层、固定 seed,保证 base/sft 跑的是同一批题(可复现、可比)。
--sample 0 表示全量 638 题。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import random
from collections import defaultdict
from pathlib import Path

from eval.question_gen import case, runner

_VAL = Path("backend/eval/question_gen/data/val.jsonl")
_SEED = 17


def _stratified(cases: list, n: int) -> list:
    """按 intent 分层抽样到约 n 条;n<=0 返回全量。固定 seed 可复现。"""
    if n <= 0 or n >= len(cases):
        return cases
    by_intent: dict[str, list] = defaultdict(list)
    for c in cases:
        by_intent[c.intent].append(c)
    rng = random.Random(_SEED)
    per = max(1, n // len(by_intent))
    out = []
    for intent, group in sorted(by_intent.items()):
        g = sorted(group, key=lambda c: c.case_id)
        rng.shuffle(g)
        out.extend(g[:per])
    return sorted(out, key=lambda c: c.case_id)


def _by_intent(cases: list, per_case: dict[str, bool]) -> dict[str, dict]:
    by_id = {c.case_id: c for c in cases}
    buckets: dict[str, dict] = defaultdict(lambda: {"pass": 0, "total": 0})
    for cid, passed in per_case.items():
        intent = by_id[cid].intent
        buckets[intent]["total"] += 1
        if passed:
            buckets[intent]["pass"] += 1
    return {
        k: {**v, "rate": round(v["pass"] / v["total"], 3) if v["total"] else 0.0}
        for k, v in sorted(buckets.items())
    }


async def _run(tag: str, out: Path, n: int, k: int, concurrency: int) -> None:
    cases = _stratified(case.load_jsonl(_VAL), n)
    print(f"[{tag}] 跑 {len(cases)} 题 (k={k}, concurrency={concurrency})")
    res = await runner.run_passk(cases, k=k, concurrency=concurrency)
    payload = {
        "tag": tag,
        "n": len(cases),
        "case_ids": [c.case_id for c in cases],
        "overall": res["pass_at_k"],
        "by_intent": _by_intent(cases, res["per_case"]),
        "per_case": res["per_case"],
    }
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2))
    print(f"[{tag}] overall pass@{k} = {res['pass_at_k']['rate']} → {out}")


def _table(base_path: Path, sft_path: Path) -> None:
    b = json.loads(base_path.read_text())
    s = json.loads(sft_path.read_text())
    # 一致性:两边应跑同一批题
    same = set(b["case_ids"]) == set(s["case_ids"])
    intents = sorted(set(b["by_intent"]) | set(s["by_intent"]))
    print(f"\n样本对齐: {'✅ 同一批题' if same else '⚠️ 题集不一致,慎比'}  (base n={b['n']}, sft n={s['n']})\n")
    print(f"{'intent':<22} {'base':>12} {'sft':>12} {'Δ':>8}")
    print("-" * 56)
    for it in intents:
        bb = b["by_intent"].get(it, {})
        ss = s["by_intent"].get(it, {})
        br = bb.get("rate", 0.0); sr = ss.get("rate", 0.0)
        bt = f"{br:.0%}({bb.get('pass',0)}/{bb.get('total',0)})"
        st = f"{sr:.0%}({ss.get('pass',0)}/{ss.get('total',0)})"
        print(f"{it:<22} {bt:>12} {st:>12} {sr - br:>+7.0%}")
    print("-" * 56)
    bo = b["overall"]; so = s["overall"]
    bor, sor = bo["rate"], so["rate"]
    bt = f"{bor:.0%}({bo['pass']}/{bo['total']})"
    st = f"{sor:.0%}({so['pass']}/{so['total']})"
    print(f"{'总计':<22} {bt:>12} {st:>12} {sor - bor:>+7.0%}")


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--tag", required=True)
    r.add_argument("--out", type=Path, required=True)
    r.add_argument("--sample", type=int, default=135)
    r.add_argument("--k", type=int, default=1)
    r.add_argument("--concurrency", type=int, default=6)
    t = sub.add_parser("table")
    t.add_argument("base", type=Path)
    t.add_argument("sft", type=Path)
    args = ap.parse_args()
    if args.cmd == "run":
        asyncio.run(_run(args.tag, args.out, args.sample, args.k, args.concurrency))
    else:
        _table(args.base, args.sft)


if __name__ == "__main__":
    main()
