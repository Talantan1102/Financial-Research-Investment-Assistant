"""把 Track B 采轨产物组装成 SFT 训练数据(数据生成最终交付物)。

筛选 = 干净 ∧ 正确:halt_reason=='natural' ∧ n_steps≤ideal ∧ passed==True。
  - 干净:过程不撞闸/不打转,步数≤理想 → 教 8B 高效工具使用。
  - 正确:该条轨迹自身答对(过 run_python gate 的 ok)→ 不喂错误示范。
每 case 限 --max-per-case 条(默认 2),避免易题刷屏、保意图多样。

输出 sft_train.jsonl:{case_id, intent, model, n_steps, messages}。messages 即多轮
工具使用对话(user→assistant tool_calls→tool 结果→…→final answer),直接喂 SFT。

用法:
  PYTHONPATH=backend python -m eval.question_gen.overnight_assemble_sft \
    --strong eval/question_gen/data/d4_overnight/strong \
    --candidate eval/question_gen/data/train.jsonl \
    --out eval/question_gen/data/d4_overnight/sft_train.jsonl --ideal 8 --max-per-case 2
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path

from eval.question_gen import case as case_mod


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--strong", type=Path, required=True)
    ap.add_argument("--candidate", type=Path, default=Path("eval/question_gen/data/train.jsonl"))
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--ideal", type=int, default=8)
    ap.add_argument("--max-per-case", type=int, default=2)
    # 质量审计确认的脏 case(叙事幻觉/答案错):oracle passed=True 但人工/agent 复核不合格。
    # 逐 case 剔除(逗号分隔 case_id 子串)。见 sft-quality-audit workflow 结论。
    ap.add_argument(
        "--exclude-cases",
        default="qg-双指标-600871.SH-1y-2884",
        help="逗号分隔,命中子串的 case 整个剔除(确认的幻觉/错答样本)",
    )
    args = ap.parse_args()
    exclude = [s for s in args.exclude_cases.split(",") if s.strip()]

    intent_of = {c.case_id: c.intent for c in case_mod.load_jsonl(args.candidate)}

    stats = defaultdict(int)
    missing_passed = 0
    per_case: dict[str, int] = defaultdict(int)
    by_intent: dict[str, int] = defaultdict(int)
    out_rows = []
    for f in sorted(args.strong.glob("shard_*/trajectories_raw.jsonl")):
        for line in f.read_text().splitlines():
            if not line.strip():
                continue
            r = json.loads(line)
            stats["total"] += 1
            if any(x in r["case_id"] for x in exclude):
                stats["excluded_dirty"] += 1
                continue
            if "passed" not in r:
                missing_passed += 1
            is_clean = r.get("halt_reason") == "natural" and (r.get("n_steps") or 99) <= args.ideal
            is_pass = bool(r.get("passed"))
            if not (is_clean and is_pass):
                continue
            cid = r["case_id"]
            if per_case[cid] >= args.max_per_case:
                stats["dropped_over_cap"] += 1
                continue
            per_case[cid] += 1
            intent = intent_of.get(cid, "?")
            by_intent[intent] += 1
            out_rows.append(
                {
                    "case_id": cid,
                    "intent": intent,
                    "model": r.get("model"),
                    "n_steps": r.get("n_steps"),
                    "messages": r["messages"],
                }
            )
            stats["kept"] += 1

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8") as w:
        for row in out_rows:
            w.write(json.dumps(row, ensure_ascii=False) + "\n")

    print(f"[SFT 组装] 扫描轨迹 {stats['total']} 条")
    if missing_passed:
        print(f"  ⚠ {missing_passed} 条缺 passed 字段(改前采的,当不正确丢弃)")
    if stats.get("excluded_dirty"):
        print(f"  剔除审计确认脏样本(幻觉/错答): {stats['excluded_dirty']} 条 (case: {exclude})")
    print(
        f"  保留(干净∧正确,每case≤{args.max_per_case}) = {stats['kept']} 条 "
        f"| 超额丢弃 {stats['dropped_over_cap']} | 覆盖 {len(per_case)} 题"
    )
    print(f"  per-intent: {dict(by_intent)}")
    print(f"  → 写出 {args.out} ({stats['kept']} 行)")


if __name__ == "__main__":
    main()
