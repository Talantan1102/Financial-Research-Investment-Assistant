"""CLI:消融区分度实跑 — 完整版 vs 削弱版,逐 cell 出 separable 判定。

元评估第四步(区分度)的实跑入口。研报《元评估 · 怎么论证评估体系可信》要求:
不止有 separable 工具,要真跑一个故意削弱的系统,验证评估能把它和完整版拉开。

用法(WSL fria-venv,真 PG + 真 LLM):
    # 读侧消融:空检索器,验证可答题掉分、克制弃答不掉分
    python -m eval.memory_dialogue.meta_eval.run_ablation --script <path> --ablation read
    # 写侧消融:无冲突消解,验证 old_invalidated/链完整类断言掉分
    python -m eval.memory_dialogue.meta_eval.run_ablation --all --ablation write

每个脚本完整版、削弱版各跑一次(各自新建独立 user,互不污染)。
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path
from typing import Any

from eval.memory_dialogue.ablation import (
    format_separability_report,
    separability_report,
)
from eval.memory_dialogue.script_schema import load_script

SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"

_ABLATION_KNOBS: dict[str, dict[str, bool]] = {
    "read": {"read_empty_retriever": True},
    "write": {"write_no_conflict_judge": True},
    "both": {"read_empty_retriever": True, "write_no_conflict_judge": True},
}


async def _run_one(
    script_path: Path, knobs: dict[str, bool], *, skip_read: bool = False
) -> tuple[list[Any], list[Any]]:
    from eval.memory_dialogue.live_deps import build_live_runners

    write_runner, read_runner = await build_live_runners(**knobs)
    script = load_script(script_path)
    write_report = await write_runner.run(script)
    # 写侧消融时读 probe 与结论无关,--skip-read 跳过省一半 LLM
    probes = [] if skip_read else [await read_runner.run_probe(p) for p in script.probes]
    return probes, write_report.results


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    parser = argparse.ArgumentParser(description="对话流记忆评估 — 消融区分度实跑")
    parser.add_argument("--script", help="单段脚本 yaml 路径")
    parser.add_argument("--all", action="store_true", help="跑 scripts/ 全部")
    parser.add_argument("--glob", help="脚本名 glob 子集,如 'viewpoint-*'(相对 scripts/)")
    parser.add_argument(
        "--ablation",
        choices=["read", "write", "both"],
        default="read",
        help="削弱方式:read=空检索器 / write=无冲突消解 / both",
    )
    parser.add_argument(
        "--skip-read", action="store_true", help="跳过读 probe(写侧消融时省一半 LLM)"
    )
    args = parser.parse_args(argv)
    if not args.all and not args.script and not args.glob:
        parser.error("需要 --script <路径> 或 --all 或 --glob <pattern>")

    if args.glob:
        paths = sorted(SCRIPTS_DIR.glob(f"{args.glob}.yaml"))
    elif args.all:
        paths = sorted(SCRIPTS_DIR.glob("*.yaml"))
    else:
        paths = [Path(args.script)]
    knobs = _ABLATION_KNOBS[args.ablation]

    full_probes: list[Any] = []
    full_writes: list[Any] = []
    abl_probes: list[Any] = []
    abl_writes: list[Any] = []
    for p in paths:
        fp, fw = asyncio.run(_run_one(p, {}, skip_read=args.skip_read))
        full_probes.extend(fp)
        full_writes.extend(fw)
        ap, aw = asyncio.run(_run_one(p, knobs, skip_read=args.skip_read))
        abl_probes.extend(ap)
        abl_writes.extend(aw)

    report = separability_report(full_probes, full_writes, abl_probes, abl_writes)
    print(f"\n消融方式:{args.ablation}({knobs})\n")
    print(format_separability_report(report))
    return 0


if __name__ == "__main__":
    sys.exit(main())
