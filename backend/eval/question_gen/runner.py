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


async def run_passk(
    cases: list[case.ComputationCase],
    *,
    k: int = 1,
    concurrency: int = 6,
    as_of: str = "20260612",  # 钉到已落定交易日(非"今天"):窗口不含移动/未回填的近端 bar → gold 可复现
    max_steps: int = 28,  # 放宽:让 5 股排序/筛选这类重活有余量,把"预算天花板"从能力测量里剥掉(生产仍 12)
    answers_path: Path | None = None,
) -> dict[str, Any]:
    """跑 cases × k,返回 {pass1, by_bucket, per_case};answers_path 给则落盘答案供离线重判。"""
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

    engine = create_async_engine(_sqlalchemy_async_pg_url(), future=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    sem = asyncio.Semaphore(concurrency)
    per_run: dict[str, list[bool]] = defaultdict(list)  # case_id -> [k 次 pass]
    answers: dict[str, str] = {}  # case_id -> 末次 agent 答案(供离线重判)

    try:
        async with MCPClient.from_subprocess(profile="chat_tools") as mcp_client:
            singletons = await build_heavy_singletons(
                session_factory=session_factory, mcp_client=mcp_client
            )
            deps = ContextDeps(
                system_prompt=CHAT_SYSTEM_PROMPT,
                skill_listing=singletons.skill_listing,
                reference_date=_as_of_date(as_of),
            )
            complete = judge_llm.make_complete()  # 复杂档(排序/筛选)LLM 抽取判分

            async def run_one(c: case.ComputationCase, run_idx: int) -> tuple[str, bool, str]:
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
                            gate_cfg=GateConfig(max_steps=max_steps),
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
                        return (c.case_id, bool(ok), answer or "")
                    except Exception:  # noqa: BLE001 — per-case 隔离
                        logger.exception("case %s run %d 失败", c.case_id, run_idx)
                        return (c.case_id, False, "")

            tasks = [run_one(c, i) for c in cases for i in range(k)]
            for fut in asyncio.as_completed(tasks):
                cid, ok, ans = await fut
                per_run[cid].append(ok)
                if ans:
                    answers[cid] = ans
    finally:
        await engine.dispose()

    if answers_path is not None:
        _dump_answers(cases, per_run, answers, answers_path)
    return _aggregate(cases, per_run)


def _aggregate(cases: list[case.ComputationCase], per_run: dict[str, list[bool]]) -> dict[str, Any]:
    by_id = {c.case_id: c for c in cases}
    per_case: dict[str, bool] = {cid: any(runs) for cid, runs in per_run.items()}  # pass@k
    buckets: dict[tuple[str, str], list[bool]] = defaultdict(list)
    for cid, passed in per_case.items():
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
    }


def _dump_answers(
    cases: list[case.ComputationCase],
    per_run: dict[str, list[bool]],
    answers: dict[str, str],
    path: Path,
) -> None:
    """落盘 {case_id, difficulty, indicator, gold_shape, gold, passed, answer} 供离线重判。"""
    by_id = {c.case_id: c for c in cases}
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for cid, runs in per_run.items():
            c = by_id[cid]
            rec = {
                "case_id": cid,
                "difficulty": c.difficulty,
                "indicator": c.indicator,
                "gold_shape": c.gold_shape,
                "gold": c.gold,
                "passed": any(runs),
                "answer": answers.get(cid, ""),
            }
            f.write(json.dumps(rec, ensure_ascii=False, default=str) + "\n")


async def _main(jsonl: Path, k: int, concurrency: int) -> None:
    cases = case.load_jsonl(jsonl)
    answers_path = jsonl.parent / "passk_answers.jsonl"
    res = await run_passk(cases, k=k, concurrency=concurrency, answers_path=answers_path)
    print(f"=== pass@{k}: {res['pass_at_k']} ===")
    for bucket, v in res["by_bucket"].items():
        print(f"  {bucket:24s} {v['pass']}/{v['total']}  ({v['rate']})")


if __name__ == "__main__":
    import sys

    _path = (
        Path(sys.argv[1])
        if len(sys.argv) > 1
        else (Path(__file__).resolve().parent / "data" / "computation_cases.jsonl")
    )
    _k = int(sys.argv[2]) if len(sys.argv) > 2 else 1
    _conc = int(sys.argv[3]) if len(sys.argv) > 3 else 6
    asyncio.run(_main(_path, _k, _conc))
