"""读阶段执行器 — 检索 + 生成 + 三层判分 + 不变量开关。

判分次序(spec 判分纪律):
1. 字符串硬校验(expect_contain / expect_not)——确定性,必过
2. 弃答纪律:可答题输出拒答形态直接 0(反蹭分);弃答题要求拒答形态在场
3. LLM 裁判按 rubric 判 0/1
不变量开关:检索结果倒序重生成,两轨都必须过硬校验,否则判"答案随顺序漂移"。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from eval.memory_dialogue.script_schema import Probe

# 拒答形态:出现任一即视为"这次回答是在拒答/弃答"
REFUSAL_MARKERS = (
    "不知道",
    "没有相关",
    "没有这个信息",
    "无法回答",
    "没聊过",
    "没有跟我聊过",
    "没提过",
    "没说过",
)


class RetrieverProtocol(Protocol):
    async def search(self, query: str, k: int = 5) -> list[Any]: ...


class GeneratorProtocol(Protocol):
    async def generate(self, query: str, facts: list[Any]) -> str: ...


class JudgeProtocol(Protocol):
    async def judge(self, question: str, answer: str, rubric: str) -> bool: ...


@dataclass(frozen=True)
class ProbeResult:
    probe: Probe
    answer: str
    hard_passed: bool
    judge_passed: bool
    invariance_passed: bool
    final_passed: bool
    detail: str


def _hard_check(answer: str, probe: Probe) -> tuple[bool, str]:
    missing = [c for c in probe.expect_contain if c not in answer]
    leaked = [c for c in probe.expect_not if c in answer]
    if missing or leaked:
        return False, f"硬校验失败: 缺 {missing} / 不该出现 {leaked}"
    return True, "硬校验通过"


def _is_refusal(answer: str) -> bool:
    return any(m in answer for m in REFUSAL_MARKERS)


class ReadPhaseRunner:
    def __init__(
        self,
        retriever: RetrieverProtocol,
        generator: GeneratorProtocol,
        judge: JudgeProtocol,
        k: int = 5,
    ) -> None:
        self._retriever = retriever
        self._generator = generator
        self._judge = judge
        self._k = k

    async def run_probe(self, probe: Probe) -> ProbeResult:
        facts = await self._retriever.search(probe.q, k=self._k)
        answer = await self._generator.generate(probe.q, facts)

        hard_ok, hard_detail = _hard_check(answer, probe)
        refusal = _is_refusal(answer)

        # 弃答纪律(先于裁判,确定性)
        if probe.answerable and refusal:
            return ProbeResult(
                probe,
                answer,
                hard_passed=False,
                judge_passed=False,
                invariance_passed=True,
                final_passed=False,
                detail=f"可答题输出拒答形态(反蹭分判 0): {answer!r}",
            )
        if not probe.answerable and not refusal:
            return ProbeResult(
                probe,
                answer,
                hard_passed=hard_ok,
                judge_passed=False,
                invariance_passed=True,
                final_passed=False,
                detail=f"弃答题未拒答(疑似顺着假前提编): {answer!r}",
            )

        judge_ok = await self._judge.judge(probe.q, answer, probe.judge_rubric)

        invariance_ok, inv_detail = True, ""
        if probe.swap_order_invariant and facts:
            answer_swapped = await self._generator.generate(probe.q, list(reversed(facts)))
            swapped_ok, _ = _hard_check(answer_swapped, probe)
            if not swapped_ok:
                invariance_ok = False
                inv_detail = f";不变量失败: 倒序后答 {answer_swapped!r}(答案随检索顺序漂移)"

        final = hard_ok and judge_ok and invariance_ok
        return ProbeResult(
            probe,
            answer,
            hard_passed=hard_ok,
            judge_passed=judge_ok,
            invariance_passed=invariance_ok,
            final_passed=final,
            detail=hard_detail + inv_detail,
        )
