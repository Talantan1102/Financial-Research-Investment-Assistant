"""批量跑分:对题集每道跑真 agent × k 次,judge 判,按 difficulty×indicator 分桶 pass@k。

spec: docs/superpowers/specs/2026-06-17-question-gen-mvp-design.md
复用 eval.chatloop.sut_runner 的 in-process agent 驱动(MCPClient.from_subprocess + ToolLoop,
修过 cancel-scope),注入 reference_date 让 agent 的「近一年」落到与生成时同一窗口;
asyncio.Semaphore 并发提速(共享一个 MCP subprocess + singletons)。
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path
from typing import Any

from eval.question_gen import case, judge, judge_llm, stock_pool

logger = logging.getLogger(__name__)

_EVAL_USER_ID = "00000000-0000-4000-8000-000000000001"


def _as_of_date(as_of: str) -> date:
    return date(int(as_of[:4]), int(as_of[4:6]), int(as_of[6:8]))


def _candidate_names(c: case.ComputationCase) -> list[str]:
    out = []
    for ts in c.stocks:
        with contextlib.suppress(KeyError):
            out.append(stock_pool.get(ts).name)
    return out


def trace_has_run_python(messages: list) -> bool:
    """扫执行轨迹(OpenAI 格式 messages)判断是否真出现过 run_python 工具调用。

    工具名的权威来源是 assistant 消息的 ``tool_calls[].function.name``
    (见 app/chatloop/state.py apply_step);本仓的 tool 结果消息只带
    role/tool_call_id/content、不带 name(apply_results),故主路径走 assistant 侧。
    为 robust 起见,同时兼容 tool-role 消息带 ``name`` 字段的 OpenAI 变体,
    且对脏数据(非 dict / 缺键 / None)一律静默判 False,绝不抛异常。
    """
    if not messages:
        return False
    for msg in messages:
        if not isinstance(msg, dict):
            continue
        # 主路径:assistant.tool_calls[].function.name == "run_python"
        tool_calls = msg.get("tool_calls")
        if isinstance(tool_calls, list):
            for tc in tool_calls:
                if not isinstance(tc, dict):
                    continue
                fn = tc.get("function")
                if isinstance(fn, dict) and fn.get("name") == "run_python":
                    return True
        # 兼容变体:tool-role 消息直接带 name 字段
        if msg.get("role") == "tool" and msg.get("name") == "run_python":
            return True
    return False


def judge_with_gate(c: case.ComputationCase, ok: bool, messages: list) -> bool:
    """判分第二门:难档自算意图(requires_run_python)须轨迹真见 run_python。

    ``ok`` 是 judge(数值/结构口径)已算出的初判。第二门只在
    ``c.requires_run_python`` 时附加"轨迹见 run_python"约束:数字对但靠心算/蒙
    (轨迹无 run_python)→ 判未过,拦假阳。requires_run_python=False 时门透明,
    直接返回 ok。ranking/set 与 scalar 两条判分路都复用此函数。
    """
    return ok and (trace_has_run_python(messages) if c.requires_run_python else True)


async def run_passk(
    cases: list[case.ComputationCase],
    *,
    k: int = 1,
    concurrency: int = 6,
    as_of: str = "20260612",  # 钉到已落定交易日(非"今天"):窗口不含移动/未回填的近端 bar → gold 可复现
    max_steps: int = 28,  # 放宽:让 5 股排序/筛选这类重活有余量,把"预算天花板"从能力测量里剥掉(生产仍 12)
    # 预算闸也必须抬:生产默认 max_cny=0.1/max_tokens=120k 是「单轮对话要便宜」的护栏,
    # 漏到 eval 会先于 max_steps 触发 —— qwen3.7-max thinking 单调用 ~¥0.027,3-4 步就烧到
    # ¥0.1 → halt_reason=budget,轨迹卡在第 4 步(实测 247 条 237 条如此)。抬到让 max_steps
    # 成为唯一 binding 闸:28 步 × ~¥0.03 ≈ ¥0.84,故 cny=2.0 / tokens=600k 留足余量。
    max_cny: float = 2.0,
    max_tokens: int = 600_000,
    model: str | None = None,
    answers_path: Path | None = None,
    collect_dir: Path | None = None,
) -> dict[str, Any]:
    """跑 cases × k,返回 {pass1, by_bucket, per_case};answers_path 给则落盘答案供离线重判。

    collect_dir 给则开启采集模式:
      - 关闭 context downgrade(保留完整工具输出供 SFT)
      - 写 collect_dir/trajectories_raw.jsonl(仅含轨迹,无 gold)
      - 写 collect_dir/judgements.jsonl(含 gold,与轨迹文件物理隔离)
    """
    from app.app_main import _sqlalchemy_async_pg_url
    from app.chatloop.context import ContextDeps
    from app.chatloop.eval_agent import ChatLoopAgent
    from app.chatloop.gates import GateConfig
    from app.chatloop.loop import ToolLoop
    from app.chatloop.state import ChatLoopState
    from app.chatloop.system_prompt import CHAT_SYSTEM_PROMPT
    from app.chatloop.worker_wiring import build_heavy_singletons
    from app.services.mcp_client import MCPClient
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from eval.tool_selection._live import build_real_hub

    collect = collect_dir is not None

    engine = create_async_engine(_sqlalchemy_async_pg_url(), future=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    sem = asyncio.Semaphore(concurrency)
    per_run: dict[str, list[bool]] = defaultdict(list)  # case_id -> [k 次 pass]
    answers: dict[str, str] = {}  # case_id -> 末次 agent 答案(供离线重判)
    trajectories: list[dict] = []

    # 钉基准日给 MCP 数据工具:子进程继承本 env,透明把"取最新/当前"截到 ≤as_of
    # (模型不可见,见 app/mcp_server/_as_of.py)。须在起子进程前设。
    import os as _os

    from app.mcp_server._as_of import ENV as _AS_OF_ENV

    _os.environ[_AS_OF_ENV] = as_of

    try:
        async with MCPClient.from_subprocess(profile="chat_tools") as mcp_client:
            singletons = await build_heavy_singletons(
                session_factory=session_factory, mcp_client=mcp_client
            )
            deps = ContextDeps(
                system_prompt=CHAT_SYSTEM_PROMPT,
                skill_listing=singletons.skill_listing,
                reference_date=_as_of_date(as_of),
                # Decision B:采集模式也用推理同款阈值(降级开着)——轨迹形态 = 推理时
                # data_refs 短引用形态,避免训练(整串内联)/推理(短引用)分布错位。
                # 见 docs/research/2026-06-22-sft-warmstart-plan.md 决策 B。
                downgrade_char_threshold=1320,
            )
            complete = judge_llm.make_complete()  # 复杂档(排序/筛选)LLM 抽取判分

            async def run_one(
                c: case.ComputationCase, run_idx: int
            ) -> tuple[str, bool, str, dict | None]:
                rid = f"qg-{c.case_id}-{run_idx}"
                async with sem:
                    try:
                        state = ChatLoopState(
                            user_id=_EVAL_USER_ID,
                            session_id=rid,
                            request_id=rid,
                            messages=[{"role": "user", "content": c.question}],
                        )
                        toolloop = ToolLoop(
                            llm=singletons.llm,
                            tool_hub=build_real_hub(singletons),
                            context_deps=deps,
                            gate_cfg=GateConfig(
                                max_steps=max_steps, max_cny=max_cny, max_tokens=max_tokens
                            ),
                            model=model,
                        )
                        final = await toolloop.run(state)
                        answer = final.final_response or ChatLoopAgent._last_assistant_content(
                            final
                        )
                        if c.gold_shape in ("ranking", "set"):
                            ok = await judge_llm.judge_structured(
                                c, answer or "", complete=complete
                            )
                        else:
                            ok = judge.judge(
                                c.gold, c.gold_shape, c.tolerance, answer or "", _candidate_names(c)
                            )
                        # 判分第二门:难档自算意图须轨迹真见 run_python(拦心算/蒙数假阳)。
                        # 缺 run_python 而被拦下时记一行诊断,方便分析(不改 _dump_answers 字段)。
                        gated = judge_with_gate(c, bool(ok), final.messages)
                        if ok and not gated:
                            logger.info(
                                "case %s run %d gate_blocked: 数字命中但轨迹无 run_python",
                                c.case_id,
                                run_idx,
                            )
                        ok = gated
                        # 采集模式:从 final 提取轨迹 slim dict。不含 gold(隔离),但**存
                        # passed**(逐条正确性,过 run_python gate 后的 ok)—— SFT 要筛
                        # "干净 ∧ 正确"的轨迹,passed 是 bool 质量标记非 gold 值,不算泄漏。
                        # 缺它只能靠 judgements 的 per-case pass_rate 近似,选不出具体哪条对。
                        traj: dict | None = None
                        if collect:
                            traj = {
                                "case_id": c.case_id,
                                "model": model,
                                "messages": final.messages,
                                "n_steps": final.step,
                                "halt_reason": final.halt_reason,
                                "passed": bool(ok),
                                "prompt_tokens": final.prompt_tokens_total,
                                "completion_tokens": final.completion_tokens_total,
                                "cached_tokens": final.cached_tokens_total,
                                "budget_cny": final.budget_spent_cny,
                                "reasoning_present": any(
                                    m.get("reasoning_content") for m in final.messages
                                ),
                            }
                        return (c.case_id, bool(ok), answer or "", traj)
                    except Exception:  # noqa: BLE001 — per-case 隔离
                        logger.exception("case %s run %d 失败", c.case_id, run_idx)
                        return (c.case_id, False, "", None)

            tasks = [run_one(c, i) for c in cases for i in range(k)]
            total = len(tasks)
            n_pass = 0
            tag = model or "default"
            is_tty = sys.stderr.isatty()
            for done, fut in enumerate(asyncio.as_completed(tasks), start=1):
                cid, ok, ans, traj = await fut
                per_run[cid].append(ok)
                if ans:
                    answers[cid] = ans
                if traj is not None:
                    trajectories.append(traj)
                n_pass += int(ok)
                # 进度:终端用 \r 实时刷新;非终端(写日志)每 10 题一行,带模型名区分对比跑
                if is_tty:
                    print(
                        f"\r[{tag}] {done}/{total} 通过 {n_pass}",
                        end="",
                        file=sys.stderr,
                        flush=True,
                    )
                elif done % 10 == 0 or done == total:
                    print(f"[{tag}] 进度 {done}/{total} 通过 {n_pass}", file=sys.stderr, flush=True)
            if is_tty:
                print("", file=sys.stderr)
    finally:
        await engine.dispose()

    if answers_path is not None:
        _dump_answers(cases, per_run, answers, answers_path, model)
    # 采集模式:轨迹与判定写入独立文件(物理隔离 gold)
    if collect:
        assert collect_dir is not None  # mypy narrowing
        collect_dir.mkdir(parents=True, exist_ok=True)
        _dump_trajectories(trajectories, collect_dir / "trajectories_raw.jsonl")
        _dump_answers(cases, per_run, answers, collect_dir / "judgements.jsonl", model)
    return _aggregate(cases, per_run)


def _aggregate(cases: list[case.ComputationCase], per_run: dict[str, list[bool]]) -> dict[str, Any]:
    by_id = {c.case_id: c for c in cases}
    per_case: dict[str, bool] = {cid: any(runs) for cid, runs in per_run.items()}  # pass@k
    per_case_counts: dict[str, int] = {
        cid: sum(runs) for cid, runs in per_run.items()
    }  # k 次过几次
    buckets: dict[tuple[str, str], list[bool]] = defaultdict(list)
    for cid, passed in per_case.items():
        if cid not in by_id:  # 容错:只想要 counts 时可传空 cases,不 KeyError
            continue
        c = by_id[cid]
        buckets[(c.difficulty, c.indicator)].append(passed)
    by_bucket = {
        f"{diff}/{ind}": {"pass": sum(v), "total": len(v), "rate": round(sum(v) / len(v), 3)}
        for (diff, ind), v in sorted(buckets.items())
    }
    n = len(per_case)
    n_passed = sum(per_case.values())
    return {
        "pass_at_k": {"pass": n_passed, "total": n, "rate": round(n_passed / n, 3) if n else 0.0},
        "by_bucket": by_bucket,
        "per_case": per_case,
        "per_case_counts": per_case_counts,
    }


def _compare_table(per_model: dict[str, dict]) -> dict:
    """{model: run_passk 结果} → {models, buckets, rows{model: {总分, 各桶 rate}}}。"""
    buckets = sorted({b for r in per_model.values() for b in r["by_bucket"]})
    rows: dict[str, dict] = {}
    for m, r in per_model.items():
        row: dict[str, float | None] = {"总分": r["pass_at_k"]["rate"]}
        for b in buckets:
            row[b] = r["by_bucket"].get(b, {}).get("rate")
        rows[m] = row
    return {"models": list(per_model), "buckets": buckets, "rows": rows}


async def run_compare(
    cases: list[case.ComputationCase],
    models: list[str],
    *,
    k: int = 1,
    concurrency: int = 5,
    as_of: str = "20260612",
) -> dict:
    """对每个 model 跑一遍 run_passk,汇成"模型×桶"对比表。"""
    per_model: dict[str, dict] = {}
    for m in models:
        per_model[m] = await run_passk(cases, k=k, concurrency=concurrency, as_of=as_of, model=m)
    return _compare_table(per_model)


def _dump_answers(
    cases: list[case.ComputationCase],
    per_run: dict[str, list[bool]],
    answers: dict[str, str],
    path: Path,
    model: str | None = None,
) -> None:
    """落盘 {case_id, difficulty, indicator, gold_shape, gold, passed, pass_rate, n_runs, answer, model} 供离线重判。"""
    by_id = {c.case_id: c for c in cases}
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for cid, runs in per_run.items():
            c = by_id[cid]
            n_runs = len(runs)
            rec = {
                "case_id": cid,
                "difficulty": c.difficulty,
                "indicator": c.indicator,
                "gold_shape": c.gold_shape,
                "gold": c.gold,
                "passed": any(runs),
                "pass_rate": round(sum(runs) / n_runs, 4) if n_runs else 0.0,
                "n_runs": n_runs,
                "answer": answers.get(cid, ""),
                "model": model,
            }
            f.write(json.dumps(rec, ensure_ascii=False, default=str) + "\n")


def _dump_trajectories(records: list[dict], path: Path) -> None:
    """落盘轨迹 jsonl(每行一条记录)。

    records 只含 {case_id, model, messages, n_steps, halt_reason} — 严禁混入 gold/passed。
    path 的父目录自动创建。
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for rec in records:
            f.write(json.dumps(rec, ensure_ascii=False, default=str) + "\n")


async def _main(jsonl: Path, k: int, concurrency: int) -> None:
    cases = case.load_jsonl(jsonl)
    answers_path = jsonl.parent / "passk_answers.jsonl"
    res = await run_passk(cases, k=k, concurrency=concurrency, answers_path=answers_path)
    print(f"=== pass@{k}: {res['pass_at_k']} ===")
    for bucket, v in res["by_bucket"].items():
        print(f"  {bucket:24s} {v['pass']}/{v['total']}  ({v['rate']})")


async def _main_compare(jsonl: Path, k: int, concurrency: int, models: list[str]) -> None:
    cases = case.load_jsonl(jsonl)
    t = await run_compare(cases, models, k=k, concurrency=concurrency)
    buckets = t["buckets"]
    # 表头
    header = f"{'模型':<20s}  {'总分':>6s}" + "".join(f"  {b:>14s}" for b in buckets)
    print(header)
    print("-" * len(header))
    for m in t["models"]:
        row = t["rows"][m]
        cols = f"{m:<20s}  {row['总分']:>6.3f}"
        for b in buckets:
            v = row[b]
            cols += f"  {v:>14.3f}" if v is not None else f"  {'N/A':>14s}"
        print(cols)


if __name__ == "__main__":
    import sys

    _path = (
        Path(sys.argv[1])
        if len(sys.argv) > 1
        else (Path(__file__).resolve().parent / "data" / "computation_cases.jsonl")
    )
    _k = int(sys.argv[2]) if len(sys.argv) > 2 else 1
    _conc = int(sys.argv[3]) if len(sys.argv) > 3 else 6

    if "--compare" in sys.argv:
        _idx = sys.argv.index("--compare")
        _models = sys.argv[_idx + 1].split(",")
        asyncio.run(_main_compare(_path, _k, _conc, _models))
    else:
        asyncio.run(_main(_path, _k, _conc))
