"""chatloop 评估 CLI(blueprint § 12)。

用法(WSL fria-venv,真 PG + MCP + LLM;前缀 source ../.env):
    # dry(零 LLM,CI 可跑):校验 schema + 场景构成
    python -m eval.chatloop.run_eval

    # 确定性闸(noop,首轮选择 + 免责;每 case 1 次)
    python -m eval.chatloop.run_eval --ci

    # 离线 live(noop k 次 + pass^k 连胜率)
    python -m eval.chatloop.run_eval --offline --k 5
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from collections import defaultdict
from pathlib import Path

from eval.chatloop.report import format_dry, format_scorecard
from eval.chatloop.scenario import load_scenarios

_DEFAULT_GOLDEN = Path(__file__).resolve().parent / "golden" / "scenarios.jsonl"


def main(argv: list[str] | None = None) -> int:
    import logging

    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
    p = argparse.ArgumentParser(description="chatloop agent 行为评估")
    p.add_argument("--golden", default=str(_DEFAULT_GOLDEN))
    p.add_argument("--ci", action="store_true", help="确定性闸:noop k=1")
    p.add_argument("--offline", action="store_true", help="离线层:noop k 次 + pass^k")
    p.add_argument("--k", type=int, default=5, help="pass^k 次数(仅 --offline)")
    p.add_argument("--dispatch", choices=["noop", "real"], default="noop")
    args = p.parse_args(argv)

    scenarios = load_scenarios(Path(args.golden))

    if not args.ci and not args.offline:
        by_diff: dict[str, int] = defaultdict(int)
        by_bucket: dict[str, int] = defaultdict(int)
        for s in scenarios:
            by_diff[s.difficulty] += 1
            by_bucket[s.bucket] += 1
        print(format_dry(len(scenarios), dict(by_diff), dict(by_bucket)))
        return 0

    k = args.k if args.offline else 1
    return asyncio.run(_run(scenarios, k=k, dispatch=args.dispatch, offline=args.offline))


async def _run(scenarios: list, *, k: int, dispatch: str, offline: bool) -> int:
    from eval.chatloop.passk import pass_power_k
    from eval.chatloop.scorers import BehaviorScore, score_behavior
    from eval.chatloop.sut_runner import run_scenarios
    from eval.tool_selection._core import is_abstain_case

    results = await run_scenarios(scenarios, dispatch_mode=dispatch, k=k)

    runs_by_case: dict[str, list] = defaultdict(list)
    for r in results:
        runs_by_case[r.case_id].append(r)

    scores: list[BehaviorScore] = []
    errors: list[tuple[str, str]] = []
    per_run_pass: dict[str, list[bool]] = {}

    for sc in scenarios:
        runs = runs_by_case.get(sc.case_id, [])
        run_pass: list[bool] = []
        rep: BehaviorScore | None = None
        for r in runs:
            if r.error:
                run_pass.append(False)
                errors.append((f"{sc.case_id}#{r.run_idx}", r.error))
                continue
            bs = score_behavior(sc, r.tool_calls, r.response_text)
            run_pass.append(bs.tool_passed)
            if rep is None:
                rep = bs
        if rep is None:  # 全部 run 报错 —— 合成一条失败行
            rep = BehaviorScore(
                case_id=sc.case_id,
                bucket=sc.bucket,
                difficulty=sc.difficulty,
                is_abstain=is_abstain_case(sc.to_ts_case()),
                tool_passed=False,
                tool_detail="SUT 全程报错",
                disclaimer_present=False,
                disclaimer_required=False,
                advice_violation=False,
            )
        scores.append(rep)
        per_run_pass[sc.case_id] = run_pass

    passk = pass_power_k(per_run_pass) if (offline and k > 1) else None
    title = "chatloop 评估 — 离线 live(pass^k)" if offline else "chatloop 评估 — 确定性闸(noop)"
    print(format_scorecard(scores, title=title, passk=passk, errors=errors or None))
    return 0


if __name__ == "__main__":
    sys.exit(main())
