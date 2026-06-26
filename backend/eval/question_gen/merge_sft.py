"""合并三源 SFT → 全局按 case_id 去重(每题≤2)→ 最终 sft_train.jsonl。

源(顺序=去重优先级):consolidated(修后工具,优先)> strong_6i 健康 > stock_study。
重叠 84 题:同 case_id 在多源都有干净轨迹,全局截 ≤2 防过采样。stock_study 意图不重叠。
"""
import json, collections
from pathlib import Path

D = Path("eval/question_gen/data/d4_overnight")
SOURCES = [D/"_tmp_consolidated.jsonl", D/"_tmp_6i.jsonl", D/"sft_stock_study.jsonl"]
MAX_PER_CASE = 2

cap = collections.Counter()
by_intent = collections.Counter()
cases = set()
out = []
for src in SOURCES:
    if not src.exists():
        continue
    for line in src.read_text().splitlines():
        if not line.strip():
            continue
        r = json.loads(line)
        cid = r["case_id"]
        if cap[cid] >= MAX_PER_CASE:
            continue
        cap[cid] += 1
        cases.add(cid)
        by_intent[r.get("intent", "?")] += 1
        out.append(r)

outf = D/"sft_train.jsonl"
outf.write_text("".join(json.dumps(r, ensure_ascii=False)+"\n" for r in out))
print(f"最终 SFT: {len(out)} 条,覆盖 {len(cases)} 题 → {outf}")
print("per-intent 条数:")
for it, n in by_intent.most_common():
    print(f"  {it:22s} {n}")
