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
    return asyncio.run(_run_live(cases, title, strict=args.strict))


async def _run_live(cases: list, title: str, *, strict: bool) -> int:
    # 真件 wiring 延迟到 live 分支再 import —— dry / 单测路径零重依赖(无 PG/MCP/LLM)。
    from eval.tool_selection._live import run_case_live
    from eval.tool_selection._live_deps import build_eval_singletons

    singletons = await build_eval_singletons()
    scores = []
    for i, case in enumerate(cases):
        tool_calls = await run_case_live(case, singletons, request_id=f"eval-{i}")
        scores.append(score_case(case, tool_calls))

    rep = aggregate(scores)
    failures = assert_thresholds(rep)
    print(format_live_report(rep, failures, title))
    return 1 if (strict and failures) else 0
