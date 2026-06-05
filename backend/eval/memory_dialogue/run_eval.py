"""CLI: 跑一段或全部脚本,输出维度 × 难度分数表。

用法(WSL fria-venv,真 PG + 真 LLM):
    python -m eval.memory_dialogue.run_eval --script eval/memory_dialogue/scripts/viewpoint-baijiu.yaml
    python -m eval.memory_dialogue.run_eval --all --report json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

from eval.memory_dialogue.scoring import build_score_table, format_score_table
from eval.memory_dialogue.script_schema import load_script

SCRIPTS_DIR = Path(__file__).parent / "scripts"


async def _run_one(script_path: Path) -> tuple[list, list]:
    from eval.memory_dialogue.live_deps import build_live_runners

    write_runner, read_runner = await build_live_runners()
    script = load_script(script_path)
    write_report = await write_runner.run(script)
    probe_results = [await read_runner.run_probe(p) for p in script.probes]
    return probe_results, write_report.results


def main(argv: list[str] | None = None) -> int:
    import logging

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    parser = argparse.ArgumentParser(description="对话流记忆评估 runner")
    parser.add_argument("--script", help="单段脚本 yaml 路径")
    parser.add_argument("--all", action="store_true", help="跑 scripts/ 全部")
    parser.add_argument("--report", choices=["text", "json"], default="text")
    args = parser.parse_args(argv)

    if not args.all and not args.script:
        parser.error("需要 --script <路径> 或 --all")

    paths = sorted(SCRIPTS_DIR.glob("*.yaml")) if args.all else [Path(args.script)]
    all_probes, all_writes = [], []
    for p in paths:
        probes, writes = asyncio.run(_run_one(p))
        all_probes.extend(probes)
        all_writes.extend(writes)

    table = build_score_table(all_probes, all_writes)
    # 红灯明细(fail loud:每个红灯必须能指出写侧还是读侧、库里实际长什么样)
    for w in all_writes:
        mark = "✓" if w.passed else "✗"
        print(f"[写侧 {mark}] session {w.after_session} 后 {w.check_type}: {w.detail}")
    for r in all_probes:
        mark = "✓" if r.final_passed else "✗"
        print(f"[读侧 {mark}] ({r.probe.dimension}/{r.probe.tier}) {r.probe.q}")
        print(f"    答: {r.answer[:160]}")
        print(f"    判: hard={r.hard_passed} judge={r.judge_passed} "
              f"invariance={r.invariance_passed} | {r.detail[:200]}")
    if args.report == "json":
        payload: dict[str, object] = {
            f"{d}|{t}": v for (d, t), v in table.cells.items()
        }
        payload["db_assertions"] = table.db_assertion_rate
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(format_score_table(table))
    return 0


if __name__ == "__main__":
    sys.exit(main())
