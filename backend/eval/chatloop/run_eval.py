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
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from eval.chatloop.report import format_dry, format_outcome_scorecard, format_scorecard
from eval.chatloop.scenario import Scenario, load_scenarios
from eval.chatloop.scorers import BehaviorScore, PaperTradingOutcomeScore

if TYPE_CHECKING:
    from eval.chatloop.sut_runner import SutResult

_DEFAULT_GOLDEN = Path(__file__).resolve().parent / "golden" / "scenarios.jsonl"
_MULTITURN_GOLDEN = Path(__file__).resolve().parent / "golden" / "multiturn.jsonl"


@dataclass(frozen=True)
class EvaluationBatch:
    behavior_scores: list[BehaviorScore]
    outcome_scores: dict[str, list[PaperTradingOutcomeScore]]
    per_run_pass: dict[str, list[bool]]
    errors: list[tuple[str, str]]


def score_evaluation_results(
    scenarios: list[Scenario],
    results: list[SutResult],
    *,
    offline: bool,
    k: int,
) -> EvaluationBatch:
    """Apply both routing and terminal-state scoring to every formal run."""
    del offline, k
    from eval.chatloop.scorers import (
        PaperTradingOutcomeScorer,
        WatchlistOutcomeScorer,
        score_behavior,
    )
    from eval.tool_selection._core import is_abstain_case

    runs_by_case: dict[str, list[SutResult]] = defaultdict(list)
    for result in results:
        runs_by_case[result.case_id].append(result)
    behavior_scores: list[BehaviorScore] = []
    outcome_scores: dict[str, list[PaperTradingOutcomeScore]] = defaultdict(list)
    per_run_pass: dict[str, list[bool]] = {}
    errors: list[tuple[str, str]] = []
    for scenario in scenarios:
        run_pass: list[bool] = []
        representative: BehaviorScore | None = None
        for result in runs_by_case.get(scenario.case_id, []):
            if result.error:
                run_pass.append(False)
                errors.append((f"{scenario.case_id}#{result.run_idx}", result.error))
                continue
            behavior = score_behavior(scenario, result.tool_calls, result.response_text)
            representative = representative or behavior
            outcome_passed = True
            if scenario.outcome is not None:
                scorer = (
                    WatchlistOutcomeScorer()
                    if scenario.outcome["type"] == "watchlist"
                    else PaperTradingOutcomeScorer()
                )
                outcome_score = scorer.score(
                    scenario.outcome,
                    result.tool_calls,
                    result.database_state,
                    result.run_state,
                )
                outcome_scores[scenario.case_id].append(outcome_score)
                outcome_passed = outcome_score.passed
            run_pass.append(behavior.tool_passed and outcome_passed)
        if representative is None:
            representative = BehaviorScore(
                case_id=scenario.case_id,
                bucket=scenario.bucket,
                difficulty=scenario.difficulty,
                is_abstain=is_abstain_case(scenario.to_ts_case()),
                tool_passed=False,
                tool_detail="SUT 全程报错或没有返回结果",
                disclaimer_present=False,
                disclaimer_required=False,
                advice_violation=False,
            )
        behavior_scores.append(representative)
        per_run_pass[scenario.case_id] = run_pass or [False]
    return EvaluationBatch(
        behavior_scores=behavior_scores,
        outcome_scores=dict(outcome_scores),
        per_run_pass=per_run_pass,
        errors=errors,
    )


def _record_run(
    *,
    mode: str,
    metrics: list[dict],
    started_at,  # datetime
    golden_path: Path,
    case_count: int,
    dispatch: str | None = None,
    k: int | None = None,
    max_steps: int | None = None,
    max_turns: int | None = None,
    judge_model: str | None = None,
    simulator_model: str | None = None,
    thresholds: dict | None = None,
    status: str = "ok",
) -> None:
    """落库:run 配置(含采样/耗时/成本/git_sha/prompt_sha)+ 指标行。失败不炸评估。"""
    from datetime import datetime

    try:
        from app.services.tier_router import V0_DEFAULT_MODEL

        from eval.chatloop.recorder import (
            ChatloopEvalRecorder,
            git_sha,
            new_run_id,
            now_iso,
            prompt_sha,
        )

        rec = ChatloopEvalRecorder()
        dur_ms = int((datetime.now() - started_at).total_seconds() * 1000)
        cost, tokens = rec.cost_tokens_since(started_at)
        sampling: dict = {
            "sut": {
                "temperature": "provider-default",
                "top_p": "provider-default",
                "top_k": "provider-default",
            }
        }
        if judge_model:
            sampling["judge"] = {"temperature": 0.0, "top_p": "default", "top_k": "default"}
        if simulator_model:
            sampling["simulator"] = {"temperature": 0.4, "top_p": "default", "top_k": "default"}
        run = {
            "run_id": new_run_id(),
            "created_at": now_iso(),
            "git_sha": git_sha(),
            "mode": mode,
            "dispatch": dispatch,
            "sut_model": V0_DEFAULT_MODEL,
            "judge_model": judge_model,
            "simulator_model": simulator_model,
            "k": k,
            "max_steps": max_steps,
            "max_turns": max_turns,
            "golden_file": str(golden_path),
            "case_count": case_count,
            "system_prompt_sha": prompt_sha(),
            "thresholds_json": thresholds,
            "sampling_json": sampling,
            "duration_ms": dur_ms,
            "cost_cny": cost,
            "total_tokens": tokens,
            "status": status,
            "config_json": {
                "mode": mode,
                "dispatch": dispatch,
                "k": k,
                "max_steps": max_steps,
                "max_turns": max_turns,
                "judge_model": judge_model,
                "simulator_model": simulator_model,
                "golden": str(golden_path),
            },
        }
        rid = rec.record(run, metrics)
        cost_str = (
            f"成本 ¥{cost:.4f}/{tokens}tok" if cost is not None else "成本 best-effort 未取到"
        )
        print(f"\n→ 已落库 run_id={rid}(git {run['git_sha']},耗时 {dur_ms}ms,{cost_str})")
        try:  # 刷新看板数据源(blueprint § 9"读"半)
            from eval.chatloop.export_dashboard import export_history

            export_history()
        except Exception as ee:  # noqa: BLE001
            print(f"  (看板导出 best-effort 失败:{type(ee).__name__})")
    except Exception as e:  # noqa: BLE001 — 落库失败不破坏评估输出
        print(f"\n→ ⚠️ 落库失败(非致命):{type(e).__name__}: {e}")


def main(argv: list[str] | None = None) -> int:
    import logging

    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
    effective_argv = list(sys.argv[1:] if argv is None else argv)
    if "--business" in effective_argv:
        from eval.chatloop.business_cli import run_business_cli

        return run_business_cli(effective_argv).exit_code
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
    args = p.parse_args(effective_argv)

    golden_path = Path(args.golden)
    if args.multiturn and args.golden == str(_DEFAULT_GOLDEN):
        golden_path = _MULTITURN_GOLDEN  # --multiturn 默认走多轮 golden
    scenarios = load_scenarios(golden_path)
    if args.limit > 0:
        scenarios = scenarios[: args.limit]

    if args.multiturn:
        return asyncio.run(
            _run_multiturn(
                scenarios, model=args.judge_model, max_turns=args.max_turns, golden_path=golden_path
            )
        )

    if args.grounding:
        return asyncio.run(
            _run_grounding(scenarios, model=args.judge_model, golden_path=golden_path)
        )

    if not args.ci and not args.offline:
        by_diff: dict[str, int] = defaultdict(int)
        by_bucket: dict[str, int] = defaultdict(int)
        for s in scenarios:
            by_diff[s.difficulty] += 1
            by_bucket[s.bucket] += 1
        print(format_dry(len(scenarios), dict(by_diff), dict(by_bucket)))
        return 0

    k = args.k if args.offline else 1
    return asyncio.run(
        _run(scenarios, k=k, dispatch=args.dispatch, offline=args.offline, golden_path=golden_path)
    )


async def _run(
    scenarios: list[Scenario],
    *,
    k: int,
    dispatch: str,
    offline: bool,
    golden_path: Path,
    runner: Any | None = None,
    record: bool = True,
) -> int:
    from datetime import datetime

    from eval.chatloop.passk import pass_power_k
    from eval.chatloop.sut_runner import run_scenarios

    started_at = datetime.now()
    selected_runner = runner or run_scenarios
    results = await selected_runner(scenarios, dispatch_mode=dispatch, k=k)
    batch = score_evaluation_results(scenarios, results, offline=offline, k=k)
    scores = batch.behavior_scores
    errors = batch.errors
    per_run_pass = batch.per_run_pass

    passk = pass_power_k(per_run_pass) if (offline and k > 1) else None
    title = "chatloop 评估 — 离线 live(pass^k)" if offline else "chatloop 评估 — 确定性闸(noop)"
    print(format_scorecard(scores, title=title, passk=passk, errors=errors or None))
    if batch.outcome_scores:
        print(format_outcome_scorecard(batch.outcome_scores))

    # --- 落库 ---
    from eval.chatloop.passk import pass1_rate, passk_rate
    from eval.tool_selection._core import IRRELACC_THRESHOLD, RELACC_THRESHOLD

    layer = "offline" if offline else "ci"
    rel = [s for s in scores if not s.is_abstain]
    abst = [s for s in scores if s.is_abstain]
    dreq = [s for s in scores if s.disclaimer_required]

    def _m(beh: str, met: str, num: int, den: int) -> dict:
        return {
            "behavior": beh,
            "layer": layer,
            "metric": met,
            "value": (num / den) if den else None,
            "numerator": num,
            "denominator": den,
        }

    metrics = [
        _m("routing_tool", "RelAcc", sum(s.tool_passed for s in rel), len(rel)),
        _m("abstain", "IrrelAcc", sum(s.tool_passed for s in abst), len(abst)),
        _m("policy", "disclaimer_compliance", sum(s.disclaimer_present for s in dreq), len(dreq)),
        _m("policy", "advice_violations", sum(s.advice_violation for s in scores), len(scores)),
    ]
    flattened_outcomes = [score for values in batch.outcome_scores.values() for score in values]
    if flattened_outcomes:
        metrics.append(
            _m(
                "state_change",
                "outcome_pass",
                sum(score.passed for score in flattened_outcomes),
                len(flattened_outcomes),
            )
        )
    if passk:
        metrics.append(
            {
                "behavior": "reliability",
                "layer": "offline",
                "metric": "passk",
                "value": passk_rate(passk),
                "numerator": sum(1 for v in passk.values() if v.passk),
                "denominator": len(passk),
            }
        )
        metrics.append(
            {
                "behavior": "reliability",
                "layer": "offline",
                "metric": "pass1",
                "value": pass1_rate(passk),
                "numerator": None,
                "denominator": None,
            }
        )
    if record:
        _record_run(
            mode=("offline" if offline else "ci"),
            metrics=metrics,
            started_at=started_at,
            golden_path=golden_path,
            case_count=len(scenarios),
            dispatch=dispatch,
            k=k,
            max_steps=(None if offline else 1),
            thresholds={"RelAcc": RELACC_THRESHOLD, "IrrelAcc": IRRELACC_THRESHOLD},
            status=("ok" if all(all(values) for values in per_run_pass.values()) else "failed"),
        )
    return 0 if all(all(values) for values in per_run_pass.values()) else 1


async def _run_grounding(scenarios: list, *, model: str, golden_path: Path) -> int:
    """行为④:real dispatch → 每个实质回答跑 grounding 裁判 → 报分 + 导出待标扩充集。"""
    import json
    from datetime import datetime

    from eval.chatloop.grounding_scorer import GroundingJudge, score_grounding_pass
    from eval.chatloop.scenario import VALID_DIFFICULTY
    from eval.chatloop.sut_runner import run_scenarios

    started_at = datetime.now()
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
        f.write(
            "// 真实 grounding 输出(real dispatch),供扩充校准集:填 label/critique。数据为 mock 行情口径。\n"
        )
        for row in expansion:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(f"\n→ 已导出 {len(expansion)} 条待标扩充集:{out_path}")

    # --- 落库 ---
    strict = sum(1 for f in faiths if f >= 1.0)
    lenient = sum(1 for f in faiths if f >= 0.8)
    metrics = [
        {
            "behavior": "grounding",
            "layer": "offline",
            "metric": "strict_faith",
            "value": (strict / scored) if scored else None,
            "numerator": strict,
            "denominator": scored,
        },
        {
            "behavior": "grounding",
            "layer": "offline",
            "metric": "lenient_faith_0.8",
            "value": (lenient / scored) if scored else None,
            "numerator": lenient,
            "denominator": scored,
        },
    ]
    _record_run(
        mode="grounding",
        metrics=metrics,
        started_at=started_at,
        golden_path=golden_path,
        case_count=len(scenarios),
        dispatch="real",
        judge_model=model,
        status=("partial" if errors else "ok"),
        thresholds={"strict_faith": 1.0, "lenient_faith": 0.8},
    )
    return 0


async def _run_multiturn(scenarios: list, *, model: str, max_turns: int, golden_path: Path) -> int:
    """多轮对话:模拟用户 × agent,打印 transcript + 评分(目标达成/政策/效率)。"""
    from datetime import datetime

    from eval.chatloop.multiturn import MultiTurnJudge, run_multiturn, score_multiturn

    started_at = datetime.now()
    results = await run_multiturn(scenarios, simulator_model=model, max_turns=max_turns)
    by_case = {s.case_id: s for s in scenarios}
    judge = MultiTurnJudge(model=model)
    print(f"# chatloop 评估 — 多轮对话(模拟用户+裁判 {model},max_turns={max_turns})\n")
    scores: list[dict] = []
    for r in results:
        print(f"## {r['case_id']}  目标:{str(r.get('goal', ''))[:70]}")
        if r.get("error"):
            print(f"  [报错] {r['error']}\n")
            continue
        for i, t in enumerate(r["turns"], 1):
            tools = ("  | 工具:" + ",".join(t["tools"])) if t["tools"] else ""
            print(f"  [第{i}轮] 用户:{t['user']}")
            print(f"          助手:{str(t['assistant'])[:200]}{tools}")
        end = "用户喊停" if r.get("stopped_by_user") else "到轮数上限"
        sm = await score_multiturn(by_case[r["case_id"]], r["turns"], judge)
        scores.append(sm)
        print(
            f"  → {len(r['turns'])} 轮({end})| 目标达成:{'✓' if sm['goal_met'] else '✗'}"
            f"({sm['goal_reason'][:40]})| 方向性违例:{sm['advice_violations']}"
            f"| 免责 {sm['disclaimer_ok']}/{sm['disclaimer_req']} | 工具 {sm['total_tools']}\n"
        )
    if scores:
        n = len(scores)
        goal = sum(s["goal_met"] for s in scores)
        adv = sum(s["advice_violations"] for s in scores)
        print(f"- **目标达成率**:{goal}/{n}")
        print(f"- 跨轮方向性违例:{adv} 例")
        print(
            f"- 用户主动喊停:{sum(1 for r in results if r.get('stopped_by_user'))}/{len(results)}(其余顶到轮数上限)"
        )
        print(
            f"- 平均 {sum(s['turns'] for s in scores) / n:.1f} 轮、{sum(s['total_tools'] for s in scores) / n:.0f} 工具/场景"
        )
        # --- 落库 ---
        metrics = [
            {
                "behavior": "multiturn",
                "layer": "offline",
                "metric": "goal_met",
                "value": goal / n,
                "numerator": goal,
                "denominator": n,
            },
            {
                "behavior": "multiturn",
                "layer": "offline",
                "metric": "advice_violations",
                "value": float(adv),
                "numerator": adv,
                "denominator": n,
            },
        ]
        _record_run(
            mode="multiturn",
            metrics=metrics,
            started_at=started_at,
            golden_path=golden_path,
            case_count=len(scenarios),
            dispatch="real",
            max_turns=max_turns,
            judge_model=model,
            simulator_model=model,
            status=("partial" if any(r.get("error") for r in results) else "ok"),
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
