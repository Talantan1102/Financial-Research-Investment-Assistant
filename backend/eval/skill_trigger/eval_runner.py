"""技能触发离线评测 CLI(Task 6.2,spec § 3.4 技能触发评测)。

与 ``eval.tool_selection.eval_runner`` 同构 —— 共享 ``eval.tool_selection._cli.run_cli``
核心,只换默认 golden 路径与标题。golden 行 schema 完全一致(额外可带 skill 字段标注
目标技能),评分/指标/报告复用同一套(load_skill 是否选对 = 工具选择的一个子问题)。

用法(cwd = backend/):
    # dry(默认,零 LLM):校验 golden schema + 打印分桶/类目统计
    python -m eval.skill_trigger.eval_runner

    # live(联调阶段):跑首轮选择,看"该装载没装载 / 不该装载误装载"
    python -m eval.skill_trigger.eval_runner --live --strict

成本标注:--live 跑一次整套 golden ≈ 一次一调,总量随 golden 条数线性增长。
本任务不在 6.2 跑 --live;6.2 只保证 dry 模式 + 单测绿。
"""
from __future__ import annotations

import sys
from pathlib import Path

from eval.tool_selection._cli import run_cli

# 默认 golden 路径:相对本模块文件解析成绝对,cwd 无关。
_DEFAULT_GOLDEN = str(Path(__file__).resolve().parent / "golden.jsonl")
_TITLE = "技能触发离线评测"


def main(argv: list[str] | None = None) -> int:
    return run_cli(argv, default_golden=_DEFAULT_GOLDEN, title=_TITLE)


if __name__ == "__main__":
    sys.exit(main())
