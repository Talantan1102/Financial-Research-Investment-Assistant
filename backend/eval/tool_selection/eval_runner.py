"""工具选择离线评测 CLI(Task 6.2,spec § 5.2 评测换靶)。

用法(cwd = backend/,与 eval.memory.eval_runner 同口径;eval 是 backend/ 下顶层包):
    # dry(默认,零 LLM,CI 可跑):只校验 golden schema + 打印分桶/类目统计
    python -m eval.tool_selection.eval_runner

    # strict dry(PR gate):schema 任一非法即 fail-loud exit 1
    python -m eval.tool_selection.eval_runner --strict

    # live(联调阶段,≈ 45+ 次 LLM 调用):构造真件 ChatLoopAgent + FakeNoopHub,
    #   跑首轮工具选择,输出 RelAcc / IrrelAcc / 分桶准确率 markdown 总表
    python -m eval.tool_selection.eval_runner --live --strict

成本标注:--live 跑一次整套 golden ≈ 45+ 次 LLM 调用(普通 case 1 圈 + 序列 case 2 圈)。
本任务**不在 6.2 跑 --live**(联调阶段由控制器跑);6.2 只保证 dry 模式 + 单测绿。

模块化:核心逻辑在 ``eval.tool_selection._core``(golden loader / 评分 / 聚合 / 报告),
技能触发 CLI(``eval.skill_trigger.eval_runner``)共享同一核心 + ``run_cli`` 入口。
"""

from __future__ import annotations

import sys
from pathlib import Path

from eval.tool_selection._cli import run_cli

# 默认 golden 路径:相对本模块文件解析成绝对,cwd 无关(repo 根 / backend/ 都能跑)。
_DEFAULT_GOLDEN = str(Path(__file__).resolve().parent / "golden.jsonl")
_TITLE = "工具选择离线评测"


def main(argv: list[str] | None = None) -> int:
    return run_cli(argv, default_golden=_DEFAULT_GOLDEN, title=_TITLE)


if __name__ == "__main__":
    sys.exit(main())
