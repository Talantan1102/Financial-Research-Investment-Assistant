"""读阶段:三层判分 + 不变量开关,全假依赖。"""

from __future__ import annotations

from eval.memory_dialogue.read_phase import ReadPhaseRunner
from eval.memory_dialogue.script_schema import Probe


class FakeRetriever:
    def __init__(self, facts: list[dict]) -> None:
        self._facts = facts
        self.search_calls: int = 0

    async def search(self, query: str, k: int = 5) -> list[dict]:
        self.search_calls += 1
        return list(self._facts)


class FakeGenerator:
    """按检索结果第一条的 stance 作答 —— 用来模拟"答案随顺序漂移"。"""

    def __init__(self, order_sensitive: bool = False, fixed: str | None = None) -> None:
        self._order_sensitive = order_sensitive
        self._fixed = fixed

    async def generate(self, query: str, facts: list[dict]) -> str:
        if self._fixed is not None:
            return self._fixed
        if self._order_sensitive and facts:
            return f"你的观点是{facts[0]['stance']}"
        actives = [f for f in facts if f.get("active")]
        return f"你的观点是{actives[0]['stance']}" if actives else "没有相关记录"


class FakeJudge:
    def __init__(self, verdict: bool = True) -> None:
        self._verdict = verdict

    async def judge(self, question: str, answer: str, rubric: str) -> bool:
        return self._verdict


FACTS = [
    {"stance": "中性", "active": True},
    {"stance": "看多", "active": False},
]

PROBE = Probe(
    tier="直球", dimension="知识更新", q="我对白酒什么看法?",
    expect_contain=("中性",), expect_not=("看多",),
    judge_rubric="应答中性", swap_order_invariant=False, answerable=True,
)


async def test_hard_check_pass_and_judge_pass() -> None:
    runner = ReadPhaseRunner(
        retriever=FakeRetriever(FACTS), generator=FakeGenerator(), judge=FakeJudge(True)
    )
    r = await runner.run_probe(PROBE)
    assert r.hard_passed and r.judge_passed and r.final_passed


async def test_expect_not_violation_fails_hard() -> None:
    runner = ReadPhaseRunner(
        retriever=FakeRetriever(FACTS),
        generator=FakeGenerator(fixed="你的观点是看多"),
        judge=FakeJudge(True),
    )
    r = await runner.run_probe(PROBE)
    assert not r.hard_passed and not r.final_passed
    assert "看多" in r.detail


async def test_unanswerable_probe_rewards_abstention() -> None:
    probe = Probe(
        tier="对抗", dimension="克制弃答", q="我比特币成本多少?",
        expect_contain=(), expect_not=("成本",),
        judge_rubric="必须指出从未聊过比特币", answerable=False,
    )
    runner = ReadPhaseRunner(
        retriever=FakeRetriever([]),
        generator=FakeGenerator(fixed="你没有跟我聊过比特币,我没有这个信息"),
        judge=FakeJudge(True),
    )
    r = await runner.run_probe(probe)
    assert r.final_passed


async def test_unanswerable_probe_fails_when_answered() -> None:
    """弃答题硬答 = 顺着假前提编,判 0。"""
    probe = Probe(
        tier="对抗", dimension="克制弃答", q="我比特币成本多少?",
        expect_contain=(), expect_not=(),
        judge_rubric="必须指出从未聊过比特币", answerable=False,
    )
    runner = ReadPhaseRunner(
        retriever=FakeRetriever([]),
        generator=FakeGenerator(fixed="你的比特币成本大约是四万美元"),
        judge=FakeJudge(True),
    )
    r = await runner.run_probe(probe)
    assert not r.final_passed
    assert "假前提" in r.detail or "未拒答" in r.detail


async def test_answerable_probe_zero_on_refusal() -> None:
    """反蹭分守卫:可答题输出拒答形态 → 直接 0,裁判说什么都没用。"""
    runner = ReadPhaseRunner(
        retriever=FakeRetriever(FACTS),
        generator=FakeGenerator(fixed="我不知道,没有相关信息"),
        judge=FakeJudge(True),
    )
    r = await runner.run_probe(PROBE)
    assert not r.final_passed
    assert "拒答" in r.detail


async def test_swap_order_invariance_catches_drift() -> None:
    probe = Probe(
        tier="自然难", dimension="知识更新", q="我对白酒什么看法?",
        expect_contain=("中性",), expect_not=(),
        judge_rubric="应答中性", swap_order_invariant=True,
    )
    runner = ReadPhaseRunner(
        retriever=FakeRetriever(FACTS),
        generator=FakeGenerator(order_sensitive=True),  # 第一条是中性,倒序后变看多
        judge=FakeJudge(True),
    )
    r = await runner.run_probe(probe)
    assert not r.final_passed
    assert "不变量" in r.detail
