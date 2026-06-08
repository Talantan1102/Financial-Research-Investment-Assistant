"""跑真 LLM 裁判对人工金标准,输出裁判-人类一致率(元评估落地第一项)。

用法(WSL fria-venv,真 dashscope):
    PYTHONPATH=. python -m eval.memory_dialogue.meta_eval.run_judge_agreement

读 judge_goldset.jsonl(人工标注的 question/answer/rubric/human_pass),对每条调
LiveJudge(fast 档,与读阶段同一裁判),与人工判定比,算一致率 + kappa + 混淆,
并逐条打印分歧(裁判漏判/误判),便于改判分 rubric。
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

from eval.memory_dialogue.meta_eval.judge_agreement import (
    JudgePair,
    compute_agreement,
    format_report,
)

GOLDSET = Path(__file__).parent / "judge_goldset.jsonl"


async def _run() -> int:
    from eval.memory_dialogue.live_deps import LiveJudge

    judge = LiveJudge()
    cases = [
        json.loads(line)
        for line in GOLDSET.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    pairs: list[JudgePair] = []
    disagreements: list[tuple[dict, bool]] = []
    for c in cases:
        llm_pass = await judge.judge(c["question"], c["answer"], c["rubric"])
        pairs.append(
            JudgePair(case_id=c["case_id"], human_pass=bool(c["human_pass"]), llm_pass=llm_pass)
        )
        if bool(c["human_pass"]) != llm_pass:
            disagreements.append((c, llm_pass))

    report = compute_agreement(pairs)
    print(format_report(report))
    if disagreements:
        print("\n分歧明细(改判分 rubric 的线索):")
        for c, llm_pass in disagreements:
            kind = "裁判漏判(人过它没过)" if c["human_pass"] else "裁判误判(人没过它放水)"
            print(f"  [{kind}] {c['case_id']} ({c['dimension']}): {c['note']}")
    return 0


def main() -> int:
    return asyncio.run(_run())


if __name__ == "__main__":
    sys.exit(main())
