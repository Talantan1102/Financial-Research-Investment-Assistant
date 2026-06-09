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
_MULTITURN_GOLDEN = Path(__file__).resolve().parent / "golden" / "multiturn.jsonl"


def main(argv: list[str] | None = None) -> int:
    import logging

    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
    p = argparse.ArgumentParser(description="chatloop agent 行为评估")
    p.add_argument("--golden", default=str(_DEFAULT_GOLDEN))
    p.add_argument("--ci", action="store_true", help="确定性闸:noop k=1")
    p.add_argument("--offline", action="store_true", help="离线层:noop k 次 + pass^k")
    p.add_argument("--grounding", action="store_true", help="行为④:real dispatch + grounding 裁判")
    p.add_argument("--multiturn", action="store_true", help="多轮:模拟用户 × agent(spec § 5)")
    p.add_argument("--max-turns", type=int, default=5, help="多轮最大轮数")
    p.add_argument("--k", type=int, default=5, help="pass^k 次数(仅 --offline)")
    p.add_argument("--dispatch", choices=["noop", "real"], default="noop")
    p.add_argument("--judge-model", default="qwen-plus", help="grounding 裁判模型(独立于 SUT)")
    p.add_argument("--limit", type=int, default=0, help="只跑前 N 条(0=全部,调试用)")
    args = p.parse_args(argv)

    golden_path = Path(args.golden)
    if args.multiturn and args.golden == str(_DEFAULT_GOLDEN):
        golden_path = _MULTITURN_GOLDEN  # --multiturn 默认走多轮 golden
    scenarios = load_scenarios(golden_path)
    if args.limit > 0:
        scenarios = scenarios[: args.limit]

    if args.multiturn:
        return asyncio.run(_run_multiturn(scenarios, model=args.judge_model, max_turns=args.max_turns))

    if args.grounding:
        return asyncio.run(_run_grounding(scenarios, model=args.judge_model))

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


async def _run_grounding(scenarios: list, *, model: str) -> int:
    """行为④:real dispatch → 每个实质回答跑 grounding 裁判 → 报分 + 导出待标扩充集。"""
    import json

    from eval.chatloop.grounding_scorer import GroundingJudge, score_grounding_pass
    from eval.chatloop.scenario import VALID_DIFFICULTY
    from eval.chatloop.sut_runner import run_scenarios

    results = await run_scenarios(scenarios, dispatch_mode="real", k=1)
    by_case = {s.case_id: s for s in scenarios}
    judge = GroundingJudge(model=model)

    by_diff: dict[str, list[bool]] = defaultdict(list)
    rows: list[tuple] = []
    errors: list[tuple[str, str]] = []
    expansion: list[dict] = []
    for r in results:
        sc = by_case[r.case_id]
        if r.error:
            errors.append((r.case_id, r.error))
            continue
        res = await score_grounding_pass(r.response_text, r.evidence, judge)
        rows.append((r.case_id, sc.difficulty, res))
        by_diff[sc.difficulty].append(bool(res["pass"]))
        expansion.append(
            {
                "id": f"exp-{r.case_id}",
                "问题": sc.user_input,
                "证据": (r.evidence or "")[:1500],
                "回答": (r.response_text or "")[:1500],
                "label": "",
                "critique": "",
            }
        )

    scored = sum(len(v) for v in by_diff.values())
    passed = sum(sum(v) for v in by_diff.values())
    faiths = [res["faithfulness"] for _, _, res in rows]

    def _at(thr: float) -> str:
        c = sum(1 for f in faiths if f >= thr)
        return f"{c}/{scored} ({c / scored:.0%})" if scored else "—"

    poor = sum(1 for f in faiths if f <= 0.4)
    mean_faith = sum(faiths) / len(faiths) if faiths else 0.0
    print("# chatloop 评估 — 行为④ grounding(real dispatch,裁判 " + model + ")\n")
    print(f"- 评分 case:{scored}(另 {len(errors)} 例 SUT 报错)")
    print(f"- **严格通过率**(faith=1.0,所有 claim 都 ground):{_at(1.0)}")
    print(f"- **宽松通过率**(faith≥0.8,容忍少量合理 hedge):{_at(0.8)}")
    print(f"- 参考(faith≥0.6,大体 ground):{_at(0.6)}")
    print(f"- 平均 faith:{mean_faith:.2f};**真·无证据作答(faith≤0.4):{poor}/{scored}**")
    print("\n| 难度 | 严格通过/总 |\n|---|---|")
    for d in VALID_DIFFICULTY:
        v = by_diff.get(d, [])
        if v:
            print(f"| {d} | {sum(v)}/{len(v)} |")
    fails = [(c, d, res) for c, d, res in rows if not res["pass"]]
    if fails:
        print("\n## 未通过(疑似编/越证据)")
        for c, d, res in fails:
            print(f"- `{c}` [{d}]: faith={res['faithfulness']:.2f} abstain={res['abstain']}")
    if errors:
        print("\n## SUT 报错")
        for c, e in errors:
            print(f"- `{c}`: {e}")

    out_path = Path(__file__).resolve().parent / "calibration" / "grounding_expansion.jsonl"
    with out_path.open("w", encoding="utf-8") as f:
        f.write("// 真实 grounding 输出(real dispatch),供扩充校准集:填 label/critique。数据为 mock 行情口径。\n")
        for row in expansion:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(f"\n→ 已导出 {len(expansion)} 条待标扩充集:{out_path}")
    return 0


async def _run_multiturn(scenarios: list, *, model: str, max_turns: int) -> int:
    """多轮对话:模拟用户 × agent,打印 transcript(本切片只验能跑通)。"""
    from eval.chatloop.multiturn import run_multiturn

    results = await run_multiturn(scenarios, simulator_model=model, max_turns=max_turns)
    print(f"# chatloop 评估 — 多轮对话(模拟用户 {model},max_turns={max_turns})\n")
    for r in results:
        print(f"## {r['case_id']}  目标:{str(r.get('goal', ''))[:70]}")
        if r.get("error"):
            print(f"  [报错] {r['error']}\n")
            continue
        for i, t in enumerate(r["turns"], 1):
            tools = ("  | 工具:" + ",".join(t["tools"])) if t["tools"] else ""
            print(f"  [第{i}轮] 用户:{t['user']}")
            print(f"          助手:{str(t['assistant'])[:220]}{tools}")
        end = "用户喊停" if r.get("stopped_by_user") else "到轮数上限"
        print(f"  → 共 {len(r['turns'])} 轮({end})\n")
    n_turns = [len(r["turns"]) for r in results if not r.get("error")]
    if n_turns:
        print(f"- {len(results)} 个多轮场景,平均 {sum(n_turns) / len(n_turns):.1f} 轮/场景")
    return 0


if __name__ == "__main__":
    sys.exit(main())
