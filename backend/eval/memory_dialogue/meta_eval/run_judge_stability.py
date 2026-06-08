"""跑真 LLM 裁判重测一致性(元评估落地第三项)。

用法:PYTHONPATH=. python -m eval.memory_dialogue.meta_eval.run_judge_stability [k]
对 judge_goldset.jsonl 每条让 LiveJudge 判 k 次(默认 3),看判定翻不翻。
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

from eval.memory_dialogue.meta_eval.judge_stability import (
    compute_stability,
    format_stability,
)

GOLDSET = Path(__file__).parent / "judge_goldset.jsonl"


async def _run(k: int) -> int:
    from eval.memory_dialogue.live_deps import LiveJudge

    judge = LiveJudge()
    cases = [
        json.loads(line)
        for line in GOLDSET.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    repeats: list[list[bool]] = []
    for c in cases:
        verdicts = [await judge.judge(c["question"], c["answer"], c["rubric"]) for _ in range(k)]
        repeats.append(verdicts)
    print(format_stability(compute_stability(repeats), repeats=k))
    return 0


def main() -> int:
    k = int(sys.argv[1]) if len(sys.argv) > 1 else 3
    return asyncio.run(_run(k))


if __name__ == "__main__":
    sys.exit(main())
