"""L0 单测 — Memory vs KB router(规则层 rule_match)。

覆盖:
- RouterDecision schema(retrieval_targets ∈ {"memory","kb","both"} / reasoning 必填)
- rule_match 命中 memory/KB/both 三类典型 query
- rule_match 边界 case(无明显触发词)返回 None
- both pattern 优先级高于单类(基于我.*推荐 → both,不是 memory)

§ 8 触发词清单一字不漂移(契约锁死, 实施 subagent 不得改动)。
"""

from __future__ import annotations

import pytest
from app.memory.memory_kb_router import (
    BOTH_TRIGGER_PATTERNS,
    KB_TRIGGER_WORDS,
    MEMORY_TRIGGER_WORDS,
    RouterDecision,
    rule_match,
)


class TestRouterDecisionSchema:
    def test_valid_targets(self) -> None:
        d = RouterDecision(retrieval_targets=["memory"], reasoning="hit memory triggers")
        assert d.retrieval_targets == ["memory"]
        assert d.reasoning

    def test_invalid_target_rejected(self) -> None:
        with pytest.raises(ValueError):
            RouterDecision(retrieval_targets=["bogus"], reasoning="x")  # type: ignore[list-item]

    def test_reasoning_required(self) -> None:
        with pytest.raises(ValueError):
            RouterDecision(retrieval_targets=["memory"], reasoning="")


class TestTriggerWordContracts:
    """严守 shared-contracts § 8 — 不可漂移。"""

    def test_memory_trigger_words(self) -> None:
        # spec § 11 #7 + shared-contracts § 8 锁死的清单
        assert "我" in MEMORY_TRIGGER_WORDS
        assert "我的" in MEMORY_TRIGGER_WORDS
        assert "上次" in MEMORY_TRIGGER_WORDS
        assert "之前" in MEMORY_TRIGGER_WORDS
        assert "持仓" in MEMORY_TRIGGER_WORDS
        assert "偏好" in MEMORY_TRIGGER_WORDS
        assert "策略" in MEMORY_TRIGGER_WORDS
        assert "看好" in MEMORY_TRIGGER_WORDS
        assert "看空" in MEMORY_TRIGGER_WORDS
        assert "想法" in MEMORY_TRIGGER_WORDS
        assert "态度" in MEMORY_TRIGGER_WORDS

    def test_kb_trigger_words(self) -> None:
        assert "研报" in KB_TRIGGER_WORDS
        assert "财报" in KB_TRIGGER_WORDS
        assert "公告" in KB_TRIGGER_WORDS
        assert "政策" in KB_TRIGGER_WORDS
        assert "行业分析" in KB_TRIGGER_WORDS
        assert "新闻" in KB_TRIGGER_WORDS
        assert "市场" in KB_TRIGGER_WORDS
        assert "宏观" in KB_TRIGGER_WORDS
        assert "板块" in KB_TRIGGER_WORDS
        assert "事件" in KB_TRIGGER_WORDS
        assert "数据" in KB_TRIGGER_WORDS

    def test_both_patterns_present(self) -> None:
        assert any("基于我" in p and "推荐" in p for p in BOTH_TRIGGER_PATTERNS)
        assert any("结合我" in p for p in BOTH_TRIGGER_PATTERNS)
        assert any("根据我" in p and "分析" in p for p in BOTH_TRIGGER_PATTERNS)
        assert any("我.*的.*行业" in p for p in BOTH_TRIGGER_PATTERNS)
        assert any("我.*的.*相关" in p for p in BOTH_TRIGGER_PATTERNS)
        assert any("我.*跟.*对比" in p for p in BOTH_TRIGGER_PATTERNS)


class TestRuleMatchMemoryQueries:
    @pytest.mark.parametrize(
        "query",
        [
            "我之前买了什么股票",
            "我的持仓现在表现怎么样",
            "上次我说过想看好新能源",  # 含 "上次" + "我说" + "看好" 全 memory
            "我对消费板块的偏好是什么",  # 含 "板块"(kb) + "我"/"偏好"(memory) → both
            "我看空银行股的策略",
            "我之前的想法是什么",
        ],
    )
    def test_pure_memory_query(self, query: str) -> None:
        d = rule_match(query)
        assert d is not None
        # Note: 部分含 KB 触发词的 query 实际是 both, 此 parametrize 仅断言 rule_match 命中, 不强制单类
        # 让 boundary 校准走 corpus test (Task 3)
        assert d.retrieval_targets[0] in ("memory", "both")


class TestRuleMatchPureMemoryStrict:
    """这些 query 严格只走 memory(无任何 kb 触发词)。"""

    @pytest.mark.parametrize(
        "query",
        [
            "我之前买了什么股票",
            "我的持仓现在表现怎么样",
            "我看空银行股的策略",
            "我之前的想法是什么",
            "我说过白酒",
        ],
    )
    def test_pure_memory_strict(self, query: str) -> None:
        d = rule_match(query)
        assert d is not None
        assert d.retrieval_targets == ["memory"], (
            f"{query!r} expected memory but got {d.retrieval_targets} ({d.reasoning})"
        )


class TestRuleMatchKbQueries:
    @pytest.mark.parametrize(
        "query",
        [
            "茅台最新研报怎么说",
            "比亚迪 2024 Q3 财报数据",
            "宁德时代最近有什么公告",
            "新能源车补贴政策最新动态",
            "白酒行业分析报告",
            "今天 A 股市场新闻",
        ],
    )
    def test_pure_kb_query(self, query: str) -> None:
        d = rule_match(query)
        assert d is not None
        assert d.retrieval_targets == ["kb"]


class TestRuleMatchBothQueries:
    @pytest.mark.parametrize(
        "query",
        [
            "基于我的持仓推荐一些股票",
            "结合我的偏好分析下当前市场",
            "根据我之前提的策略分析",
            "我的持仓相关的政策有什么",
            "我看好的行业最近研报怎么说",
            "我跟主流机构的看法对比",
        ],
    )
    def test_both_query(self, query: str) -> None:
        d = rule_match(query)
        assert d is not None
        assert d.retrieval_targets == ["both"]


class TestRuleMatchBoundary:
    @pytest.mark.parametrize(
        "query",
        [
            "今天天气如何",
            "你好",
            "讲个笑话",
            "tell me about 机器学习",
        ],
    )
    def test_no_trigger_returns_none(self, query: str) -> None:
        # 边界 — 让 LLM fallback 接,不强行规则给答案
        assert rule_match(query) is None

    def test_both_pattern_beats_pure_memory(self) -> None:
        # 防 both pattern 被 memory 关键词遮蔽
        d = rule_match("基于我的持仓推荐")
        assert d is not None
        assert d.retrieval_targets == ["both"]


# =====================================================================
# Task 2 — LLMRouterFallback 测试 (constrained-LLM, JSON output, fallback memory)
# =====================================================================


class _FakeRawCompletion:
    """Satisfies ChatCompletionRaw — content / prompt_tokens / completion_tokens."""

    def __init__(self, content: str, prompt_tokens: int = 100, completion_tokens: int = 30):
        self.content = content
        self.prompt_tokens = prompt_tokens
        self.completion_tokens = completion_tokens


class _StubLLMService:
    """Stub LLMService — captures last chat() call kwargs and returns a canned LLMResponse.

    LLMService.chat is sync (returns LLMResponse, not awaitable). We only need
    .content of the response in LLMRouterFallback, so we return a SimpleNamespace-like
    object with a .content attribute.
    """

    def __init__(self, content: str, raise_exc: BaseException | None = None) -> None:
        self._content = content
        self._raise_exc = raise_exc
        self.call_kwargs: dict[str, object] = {}

    def chat(self, prompt: str, tier: str = "fast", **kwargs: object) -> object:
        self.call_kwargs = {"prompt": prompt, "tier": tier, **kwargs}
        if self._raise_exc is not None:
            raise self._raise_exc
        return _FakeRawCompletion(content=self._content)


class TestLLMRouterFallback:
    async def test_llm_fallback_emits_valid_decision(self) -> None:
        from app.memory.memory_kb_router import LLMRouterFallback

        llm = _StubLLMService(
            content='{"retrieval_targets":["memory"],"reasoning":"个人偏好类问题"}'
        )
        fallback = LLMRouterFallback(llm=llm)  # type: ignore[arg-type]
        d = await fallback.decide("帮我看看哪个标的更适合长期持有")

        assert d.retrieval_targets == ["memory"]
        assert "个人偏好" in d.reasoning
        # constrained-router 风格: tier=balanced
        assert llm.call_kwargs.get("tier") == "balanced"

    async def test_llm_fallback_strips_code_fence(self) -> None:
        from app.memory.memory_kb_router import LLMRouterFallback

        llm = _StubLLMService(
            content='```json\n{"retrieval_targets":["both"],"reasoning":"边界混合 query"}\n```'
        )
        fallback = LLMRouterFallback(llm=llm)  # type: ignore[arg-type]
        d = await fallback.decide("综合判断下")
        assert d.retrieval_targets == ["both"]

    async def test_llm_fallback_invalid_json_falls_back_to_memory(self) -> None:
        # spec § 11 末尾 #7 (d): 默认 fallback memory
        from app.memory.memory_kb_router import LLMRouterFallback

        llm = _StubLLMService(content="this is not json at all")
        fallback = LLMRouterFallback(llm=llm)  # type: ignore[arg-type]
        d = await fallback.decide("xxx")
        assert d.retrieval_targets == ["memory"]
        assert "fallback" in d.reasoning.lower()

    async def test_llm_fallback_invalid_target_falls_back_to_memory(self) -> None:
        from app.memory.memory_kb_router import LLMRouterFallback

        llm = _StubLLMService(content='{"retrieval_targets":["bogus"],"reasoning":"x"}')
        fallback = LLMRouterFallback(llm=llm)  # type: ignore[arg-type]
        d = await fallback.decide("xxx")
        assert d.retrieval_targets == ["memory"]
        assert "fallback" in d.reasoning.lower()

    async def test_llm_fallback_chat_exception_falls_back_to_memory(self) -> None:
        # 任何 LLMService.chat 异常 → fallback memory
        from app.memory.memory_kb_router import LLMRouterFallback

        llm = _StubLLMService(content="", raise_exc=RuntimeError("api down"))
        fallback = LLMRouterFallback(llm=llm)  # type: ignore[arg-type]
        d = await fallback.decide("xxx")
        assert d.retrieval_targets == ["memory"]
        assert "fallback" in d.reasoning.lower()
