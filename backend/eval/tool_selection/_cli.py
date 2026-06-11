"""共享 CLI 驱动 —— tool_selection 与 skill_trigger 两入口同构(Task 6.2)。

两个 eval_runner.py 都只是薄封装:给定 default_golden 路径 + 标题,调 ``run_cli``。
dry / live / strict 三态逻辑全在此处,零重复。
"""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from eval.tool_selection._core import (
    aggregate,
    assert_thresholds,
    format_dry_report,
    format_live_report,
    load_golden,
    score_case,
)


def _build_parser(default_golden: str, title: str) -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=f"{title}(spec § 5.2 评测换靶)")
    p.add_argument("--golden", default=default_golden, help="golden jsonl 路径")
    p.add_argument(
        "--live",
        action="store_true",
        help="跑真件 ChatLoopAgent + FakeNoopHub(≈ 45+ 次 LLM 调用);缺省走 dry(零 LLM)",
    )
    p.add_argument(
        "--strict",
        action="store_true",
        help="任一桶/指标低于阈值 exit 1(dry 模式下 schema 非法即由 load_golden fail-loud)",
    )
    return p


def run_cli(argv: list[str] | None, *, default_golden: str, title: str) -> int:
    args = _build_parser(default_golden, title).parse_args(argv)
    golden_path = Path(args.golden)

    # load_golden 本身 fail-loud:schema 非法 / id 重复 / bucket 越界 → ValueError。
    # 即便 dry 模式也先加载校验,故 dry+strict 等价于"schema gate"。
    cases = load_golden(golden_path)

    if not args.live:
        print(format_dry_report(cases, title))
        return 0

    # --- live 模式 ---
    return _run_live_blocking(cases, title, strict=args.strict)


def _run_live_blocking(cases: list, title: str, *, strict: bool) -> int:
    """在常驻 loop 上跑 live —— 不用 asyncio.run(根因同 chat_runner)。

    build_eval_singletons 起 MCP stdio 子进程,其 stdio_client/ClientSession 用 anyio
    task group,cancel scope 绑在进入它的 task 上,且 __aenter__ 被泄漏(不在同处
    __aexit__)。``asyncio.run`` 在主协程结束后会 _cancel_all_tasks + shutdown_asyncgens,
    把这个泄漏挂在 yield 处的 MCP stdio asyncgen 在 shutdown task 里 athrow →
    RuntimeError: "Attempted to exit cancel scope in a different task than it was entered
    in"(与 chat_runner 当年踩的 'MCP stdio asyncgen 关闭崩坏' 同根)。

    故沿用生产 worker 同款生命周期:常驻 loop + run_until_complete,**不** shutdown_asyncgens、
    **不** close —— 进程随即退出,OS 回收 MCP 子进程(与 worker SIGKILL 子进程一致)。
    """
    loop = asyncio.new_event_loop()
    return loop.run_until_complete(_run_live(cases, title, strict=strict))


async def _run_live(cases: list, title: str, *, strict: bool) -> int:
    # 真件 wiring 延迟到 live 分支再 import —— dry / 单测路径零重依赖(无 PG/MCP/LLM)。
    from eval.tool_selection._live import run_case_live
    from eval.tool_selection._live_deps import build_eval_singletons

    singletons = await build_eval_singletons()
    scores = []
    for i, case in enumerate(cases):
        tool_calls = await run_case_live(case, singletons, request_id=f"eval-{i}")
        score = score_case(case, tool_calls)
        scores.append(score)
        names = [tc["tool_name"] for tc in tool_calls]
        verdict = "PASS" if score.passed else "FAIL"
        # 逐 case 轨迹:看模型实际选了哪些工具(seq 评分受 search_tools 排除影响,
        # 故 PASS/FAIL 仅供参考,真行为看 seq 本身)。
        print(f"  [{verdict}] {case.case_id}: {case.user_input[:30]} -> {names}", flush=True)

    rep = aggregate(scores)
    failures = assert_thresholds(rep)
    print(format_live_report(rep, failures, title))
    return 1 if (strict and failures) else 0
