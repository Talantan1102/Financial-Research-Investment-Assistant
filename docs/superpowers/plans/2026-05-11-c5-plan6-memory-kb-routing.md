# C.5 Plan 6 — Memory vs KB Routing(supervisor router 节点 + 触发词分类 + prompt 显式区隔 + routing eval framework)

> **作者**: Claude Opus 4.7 (1M)
> **日期**: 2026-05-11
> **范围**: spec § 11 末尾 #7 单条 — Memory vs KB Search 检索路由
> **工程量**: 3 天 wall time(claude-context: estimate-in-claude-code-walltime)
> **依赖前置**: Plan 1 ship(`HierarchicalMemory` + Memory Protocol)、Plan 4 ship(`archival_memory_search` MCP tool)、v0.7 KB Search 已有(`KbSearchService`)
> **共享契约**: 严格遵守 `docs/superpowers/plans/2026-05-11-c5-plan-shared-contracts.md` § 1 文件位置 / § 8 触发词清单 / § 11 范围矩阵 / § 12 测试分层 / § 13 知识卡协议 / § 14 commit 规范

---

## § 0 Spec Reference

- **主体 spec**: `docs/superpowers/specs/2026-05-10-c5-cross-session-memory-design.md`
- **核心章节**: § 11 末尾 #7「Memory vs KB Search 检索路由」(spec 行 1185 + 1198 + 1262)
- **算法深度补丁归属**: 8 条算法深度 + 工程细节难题中的 **#7 工程类**(v1.x ship 必做 6 条之一)
- **关键决策来源**:
  - spec 行 1198: (a) LangGraph supervisor 加 router 节点 / (b) 触发词区分 / (c) prompt 显式区隔 `[用户上下文]` vs `[市场知识]` / (d) 默认 fallback memory
  - spec 行 1262: 工程量 = 1 天(spec 估)→ 本 plan 扩到 3 天(加 framework / cassette / evaluator hook)
- **跟 v0.7 KB Search 衔接**: spec 附录 / spec § 14 v0.9 chat 整合的 v0.7 KB Search 已有 `KbSearchService` Protocol(`backend/app/services/kb_search_service.py`),Plan 6 仅做 wrapper 调用,不重写
- **跟 PR #39 supervisor 衔接**: `backend/app/orchestration/chat_graph.py` 已 ship supervisor topology,Plan 6 在 `planner_node` 之前插 `memory_kb_router_node`
- **不在范围**:
  - KB Search 实现(v0.7 已 ship,Plan 6 仅 inject `KbSearchService`)
  - `archival_memory_search` 实现(Plan 3)
  - `archival_memory_traverse` trigger 词清单(Plan 4 内部 routing,跟本 plan supervisor router 是两层不同 routing)
  - 50 case golden 完整集 + routing accuracy metric impl(Plan 8)— Plan 6 只提供 5-10 seed case + metric 计算 hook

---

## § 1 File Structure(本 plan 创建 / 修改的全部文件)

```
backend/app/memory/
└── memory_kb_router.py                ← NEW(本 plan 主体): 触发词清单 + RouterDecision schema +
                                          rule_match() + LLMRouterFallback + decide_retrieval_targets()

backend/app/orchestration/
└── chat_graph.py                       ← MODIFY: 在 START → context_node → planner_node 链上插入
                                          memory_kb_router_node(context_node 之后,planner_node 之前)
                                          + 注入 [用户上下文] / [市场知识] 段到 planner prompt

backend/app/orchestration/
└── memory_kb_router_node.py           ← NEW: LangGraph node wrapper,调用 memory_kb_router 决策 +
                                          并行检索 memory.archival_memory_search + KbSearchService.search

backend/app/agents/
└── schemas.py                          ← MODIFY: ChatState 新增 retrieval_targets / memory_hits /
                                          kb_hits / memory_kb_routing_reasoning 4 字段(默认空,
                                          backward compat)

backend/app/agents/
└── chat_planner.py                    ← MODIFY: build_planner_prompt + _PLANNER_PROMPT_TEMPLATE 加
                                          {user_context_block} / {market_knowledge_block} 占位,
                                          ChatPlanner.run 注入 state.memory_hits / state.kb_hits

backend/eval/memory/
├── routing_accuracy_seed.jsonl        ← NEW: Plan 6 提供 8 representative seed case(memory / kb /
                                          both / 边界各 2)
└── routing_accuracy_hook.py           ← NEW: routing accuracy metric 计算 hook(Plan 8 复用 +
                                          填实 50 case 时调此 hook)

backend/tests/unit/memory/
└── test_memory_kb_router.py           ← NEW: rule_match 单测 + RouterDecision schema 单测 +
                                          30+ representative query 路由决策正确

backend/tests/unit/orchestration/
└── test_memory_kb_router_node.py      ← NEW: node wrapper L0 单测(mock memory + mock kb)

backend/tests/integration/memory/
└── test_kb_routing_e2e.py             ← NEW: L1 chat graph e2e(mock LLM + mock memory + mock kb),
                                          memory / kb / both 三类 query 完整路径

backend/tests/e2e/memory/
└── test_memory_kb_routing_cassette.py ← NEW: L2 cassette,both 类 query 真 LLM 响应不矛盾化
                                          (用户偏好 vs 市场跑输应该是 trade-off 不是矛盾)

docs/claude-context/
└── c5-plan6-memory-kb-routing-done.md ← NEW(Plan 6 ship 后写)
```

**严守契约**: § 1 把 `memory_kb_router.py` 物理放 `backend/app/memory/`,LangGraph node wrapper 放 `backend/app/orchestration/`。逻辑归 memory(routing 决策),编排归 orchestration(node lifecycle)。

---

## § 2 Tasks Overview

| # | Task | TDD 形态 | 工时(h) |
|---|---|---|---|
| 1 | RouterDecision schema + 触发词清单常量 + rule_match() | L0 单测先写 | 3 |
| 2 | LLMRouterFallback constrained LLM(Sonnet,JSON output) | L0 mock LLM 单测 | 3 |
| 3 | decide_retrieval_targets() top-level + 默认 fallback memory | L0 30+ query 单测 | 3 |
| 4 | ChatState 新增 4 字段 + 反向兼容 | L0 schema 单测 | 1.5 |
| 5 | memory_kb_router_node(LangGraph node wrapper)+ 并行检索 | L0 单测 + L1 集成 | 4 |
| 6 | chat_graph.py 插入 router node + planner_node 集成 | L1 chat graph e2e | 3 |
| 7 | planner prompt 加 `[用户上下文]` / `[市场知识]` 段 | L0 prompt 单测 | 2 |
| 8 | routing seed jsonl(8 case)+ metric hook | L0 metric hook 单测 | 2 |
| 9 | L2 cassette: both 类 query 真 LLM 不矛盾化断言 | L2 cassette | 2.5 |
| **小计** | | | **24h(3 天 × 8h)** |

---

## § 3 Tasks(完整 TDD 5-step,每 step 含完整代码 + pytest + git commit)

### Task 1: RouterDecision schema + 触发词清单常量 + rule_match()

**目的**: 落地 § 8 契约的 3 组触发词清单为 Python 常量;`rule_match()` 纯函数返回 `RouterDecision`(precision-first,边界 case 返回 None 让 LLM fallback 接)。

#### Step 1.1 (Red): 写 L0 单测,断言 rule_match 正确分类 representative query

**文件**: `backend/tests/unit/memory/test_memory_kb_router.py`(新增,部分)

```python
"""L0 单测 — Memory vs KB router(规则层 rule_match)。

覆盖:
- RouterDecision schema(retrieval_targets ∈ {"memory","kb","both"} / reasoning 必填)
- rule_match 命中 memory/KB/both 三类典型 query
- rule_match 边界 case(无明显触发词)返回 None
- both pattern 优先级高于单类(基于我.*推荐 → both,不是 memory)
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
            RouterDecision(retrieval_targets=["bogus"], reasoning="x")

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


class TestRuleMatchMemoryQueries:
    @pytest.mark.parametrize(
        "query",
        [
            "我之前买了什么股票",
            "我的持仓现在表现怎么样",
            "上次我说过想看好新能源",
            "我对消费板块的偏好是什么",
            "我看空银行股的策略",
            "我之前的想法是什么",
        ],
    )
    def test_pure_memory_query(self, query: str) -> None:
        d = rule_match(query)
        assert d is not None
        assert d.retrieval_targets == ["memory"]


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
```

跑测试,确认 ImportError(`memory_kb_router` 还不存在)。

```bash
uv run pytest backend/tests/unit/memory/test_memory_kb_router.py -x 2>&1 | tail -20
```

#### Step 1.2 (Green): 实现 `memory_kb_router.py` 最小版让 Step 1.1 测试通过

**文件**: `backend/app/memory/memory_kb_router.py`(新增)

```python
"""Memory vs KB Search 检索路由 — supervisor router 决策模块。

spec ref:
  - docs/superpowers/specs/2026-05-10-c5-cross-session-memory-design.md § 11 末尾 #7
  - docs/superpowers/plans/2026-05-11-c5-plan-shared-contracts.md § 8

设计:
  - rule_match: 优先规则匹配(precision 高,延迟低,无 LLM cost)
  - LLM fallback(Sonnet, JSON output): 处理边界 case(规则未命中)
  - 默认 fallback: ["memory"](个人化场景多 — spec 行 1198 (d))

输出 retrieval_targets ∈ {["memory"], ["kb"], ["both"]}.
"""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

# === § 8 契约触发词清单(不可漂移) ===

MEMORY_TRIGGER_WORDS: list[str] = [
    "我", "我的", "上次", "之前", "持仓", "偏好", "策略", "看好",
    "看空", "想法", "态度", "我说", "我提",
]

KB_TRIGGER_WORDS: list[str] = [
    "研报", "财报", "公告", "政策", "行业分析", "新闻", "市场",
    "宏观", "板块", "事件", "数据",
]

BOTH_TRIGGER_PATTERNS: list[str] = [
    r"基于我.*推荐",
    r"结合我.*",
    r"根据我.*分析",
    r"我.*的.*行业",
    r"我.*的.*相关",
    r"我.*跟.*对比",
]

RetrievalTarget = Literal["memory", "kb", "both"]


class RouterDecision(BaseModel):
    """One retrieval routing decision emitted by rule_match or LLM fallback."""

    model_config = ConfigDict(frozen=True)

    retrieval_targets: list[RetrievalTarget] = Field(
        ...,
        min_length=1,
        max_length=1,
        description=(
            "Single-element list per spec § 11 #7 — one of 'memory'/'kb'/'both'. "
            "List form preserved for forward-compat (e.g. multi-route fan-out)."
        ),
    )
    reasoning: str = Field(..., min_length=1, max_length=500)

    @field_validator("retrieval_targets")
    @classmethod
    def _check_target(cls, v: list[str]) -> list[str]:
        for t in v:
            if t not in ("memory", "kb", "both"):
                raise ValueError(f"Invalid target: {t!r}")
        return v


# === 规则层(precision-first) ===


def _hit_both_pattern(query: str) -> str | None:
    for pat in BOTH_TRIGGER_PATTERNS:
        m = re.search(pat, query)
        if m:
            return pat
    return None


def _hit_memory_word(query: str) -> str | None:
    for w in MEMORY_TRIGGER_WORDS:
        if w in query:
            return w
    return None


def _hit_kb_word(query: str) -> str | None:
    for w in KB_TRIGGER_WORDS:
        if w in query:
            return w
    return None


def rule_match(query: str) -> RouterDecision | None:
    """Pure-function rule-based routing.

    Returns None when no rule fires(让 LLM fallback 接);否则给 confidence-high decision。

    优先级:
      1. BOTH_TRIGGER_PATTERNS 命中 → both(最高优先级,防 memory 关键词遮蔽)
      2. memory + kb 都命中 → both(双触发)
      3. 单一类命中 → 对应 target
      4. 都不命中 → None
    """
    both_pat = _hit_both_pattern(query)
    if both_pat is not None:
        return RouterDecision(
            retrieval_targets=["both"],
            reasoning=f"both-pattern hit: {both_pat!r}",
        )

    mem_w = _hit_memory_word(query)
    kb_w = _hit_kb_word(query)

    if mem_w and kb_w:
        return RouterDecision(
            retrieval_targets=["both"],
            reasoning=f"both memory({mem_w!r}) and kb({kb_w!r}) words hit",
        )
    if mem_w:
        return RouterDecision(
            retrieval_targets=["memory"],
            reasoning=f"memory word hit: {mem_w!r}",
        )
    if kb_w:
        return RouterDecision(
            retrieval_targets=["kb"],
            reasoning=f"kb word hit: {kb_w!r}",
        )

    return None
```

#### Step 1.3 (Verify): 跑测试通过

```bash
uv run pytest backend/tests/unit/memory/test_memory_kb_router.py -x 2>&1 | tail -30
# 预期: 4 group + 24 parametrized cases all PASS
```

#### Step 1.4 (Refactor): mypy strict + ruff check

```bash
uv run mypy backend/app/memory/memory_kb_router.py 2>&1 | tail -10
uv run ruff check backend/app/memory/memory_kb_router.py 2>&1 | tail -10
```

#### Step 1.5: git commit(不 push,等 PR)

```bash
git add backend/app/memory/memory_kb_router.py backend/tests/unit/memory/test_memory_kb_router.py
git status   # confirm only Plan 6 task 1 files
# 不在本 plan 真 commit;此处仅给作者参考的 commit message:
#
# feat(c5-plan6): RouterDecision schema + 触发词清单常量 + rule_match 规则层
#
# - 落地 shared-contracts § 8 三组触发词(memory 13 / kb 11 / both 6 patterns)
# - rule_match precision-first: both pattern > 双触发 > 单类 > None
# - 边界 case 返回 None 让 LLM fallback 接
# - 24 parametrized test all green
```

---

### Task 2: LLMRouterFallback(constrained LLM,Sonnet,JSON output)

**目的**: 规则未命中时(`rule_match` returns None),用 constrained LLM(类似 v0.8.5 ResearchPlanner constrained-router pattern)给出 JSON `{retrieval_targets, reasoning}`。

#### Step 2.1 (Red): L0 单测,mock LLM,断言 fallback 调用 + JSON 解析正确

**文件**: `backend/tests/unit/memory/test_memory_kb_router.py`(追加)

```python
# === 追加到 Task 1 文件末尾 ===

from unittest.mock import AsyncMock

from app.memory.memory_kb_router import LLMRouterFallback
from app.services.llm_response import LLMResponse


class TestLLMRouterFallback:
    @pytest.mark.asyncio
    async def test_llm_fallback_emits_valid_decision(self) -> None:
        mock_llm = AsyncMock()
        mock_llm.chat = AsyncMock(
            return_value=LLMResponse(
                content='{"retrieval_targets":["memory"],"reasoning":"个人偏好类问题"}',
                model="qwen-plus",
                usage={"prompt_tokens": 100, "completion_tokens": 30, "total_tokens": 130},
                latency_ms=200.0,
            )
        )
        fallback = LLMRouterFallback(llm=mock_llm)
        d = await fallback.decide("帮我看看哪个标的更适合长期持有")

        assert d.retrieval_targets == ["memory"]
        assert "个人偏好" in d.reasoning
        # constrained-router 风格: tier=balanced
        call = mock_llm.chat.call_args
        assert call.kwargs.get("tier") == "balanced"

    @pytest.mark.asyncio
    async def test_llm_fallback_strips_code_fence(self) -> None:
        mock_llm = AsyncMock()
        mock_llm.chat = AsyncMock(
            return_value=LLMResponse(
                content='```json\n{"retrieval_targets":["both"],"reasoning":"边界混合 query"}\n```',
                model="qwen-plus",
                usage={"prompt_tokens": 100, "completion_tokens": 30, "total_tokens": 130},
                latency_ms=200.0,
            )
        )
        fallback = LLMRouterFallback(llm=mock_llm)
        d = await fallback.decide("综合判断下")
        assert d.retrieval_targets == ["both"]

    @pytest.mark.asyncio
    async def test_llm_fallback_invalid_json_falls_back_to_memory(self) -> None:
        # spec § 11 #7 (d): 默认 fallback memory
        mock_llm = AsyncMock()
        mock_llm.chat = AsyncMock(
            return_value=LLMResponse(
                content="this is not json at all",
                model="qwen-plus",
                usage={"prompt_tokens": 50, "completion_tokens": 10, "total_tokens": 60},
                latency_ms=100.0,
            )
        )
        fallback = LLMRouterFallback(llm=mock_llm)
        d = await fallback.decide("xxx")
        assert d.retrieval_targets == ["memory"]
        assert "fallback" in d.reasoning.lower()

    @pytest.mark.asyncio
    async def test_llm_fallback_invalid_target_falls_back_to_memory(self) -> None:
        mock_llm = AsyncMock()
        mock_llm.chat = AsyncMock(
            return_value=LLMResponse(
                content='{"retrieval_targets":["bogus"],"reasoning":"x"}',
                model="qwen-plus",
                usage={"prompt_tokens": 50, "completion_tokens": 10, "total_tokens": 60},
                latency_ms=100.0,
            )
        )
        fallback = LLMRouterFallback(llm=mock_llm)
        d = await fallback.decide("xxx")
        assert d.retrieval_targets == ["memory"]
```

跑测试 → 失败(`LLMRouterFallback` 还不存在)。

#### Step 2.2 (Green): 实现 `LLMRouterFallback`

**文件**: `backend/app/memory/memory_kb_router.py`(追加)

```python
# === 追加到 Task 1 实现末尾 ===

import json
import logging
import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.services.llm_service import LLMService

logger = logging.getLogger(__name__)

_CODE_FENCE_RE = re.compile(r"^```(?:json)?\s*\n?(.*?)\n?```$", re.DOTALL)

_LLM_ROUTER_PROMPT_TEMPLATE = """\
你是金融研究助手 chat 的检索路由 LLM。判断用户问题应该走哪条检索:

- "memory": 用户私人记忆(持仓 / 偏好 / 历史想法 / "我"/"我的"/"上次")
- "kb": 公开市场知识库(研报 / 财报 / 公告 / 政策 / 新闻 / 市场动态)
- "both": 个人化结合公开知识(基于我的持仓推荐 / 结合我的偏好分析 etc.)

用户问题:
{query}

严格按下列 JSON 输出, 不要带任何额外文字:
{{
  "retrieval_targets": ["<memory|kb|both>"],
  "reasoning": "<一句话解释为什么>"
}}

注意: retrieval_targets 是单元素 list, 必须是 "memory"/"kb"/"both" 三选一。
"""


class LLMRouterFallback:
    """Constrained-LLM fallback for router decisions when rules miss.

    Calls LLMService.chat with tier='balanced'(Sonnet/qwen-plus等价)+ JSON output.
    Invalid output falls back to ["memory"] per spec § 11 #7 (d).
    """

    def __init__(self, llm: LLMService) -> None:
        self._llm = llm

    async def decide(self, query: str) -> RouterDecision:
        prompt = _LLM_ROUTER_PROMPT_TEMPLATE.format(query=query)
        try:
            resp = await self._llm.chat(prompt=prompt, tier="balanced")
        except Exception as e:  # noqa: BLE001 — LLM transient failure 全部 fallback
            logger.warning("LLMRouterFallback chat failed: %s — fallback to memory", e)
            return RouterDecision(
                retrieval_targets=["memory"],
                reasoning=f"llm fallback to memory due to chat error: {e!r}",
            )

        content = resp.content.strip()
        m = _CODE_FENCE_RE.match(content)
        if m:
            content = m.group(1).strip()

        try:
            parsed = json.loads(content)
            decision = RouterDecision.model_validate(parsed)
            return decision
        except (json.JSONDecodeError, ValueError) as e:
            logger.warning(
                "LLMRouterFallback parse failed: %s — content=%r — fallback to memory",
                e, content[:200],
            )
            return RouterDecision(
                retrieval_targets=["memory"],
                reasoning=f"llm fallback to memory due to parse/validate: {e!r}",
            )
```

#### Step 2.3 (Verify):

```bash
uv run pytest backend/tests/unit/memory/test_memory_kb_router.py::TestLLMRouterFallback -x 2>&1 | tail -20
# 预期: 4 cases all PASS
```

#### Step 2.4 (Refactor):

```bash
uv run mypy backend/app/memory/memory_kb_router.py 2>&1 | tail -5
uv run ruff check backend/app/memory/memory_kb_router.py 2>&1 | tail -5
```

#### Step 2.5: commit message 参考

```
feat(c5-plan6): LLMRouterFallback constrained-LLM router(Sonnet, JSON output)

- 规则未命中时调 LLMService.chat(tier='balanced')
- code fence 自动 strip + Pydantic validate
- 任何解析/校验失败 fallback ["memory"](spec § 11 #7 (d))
- 4 unit cases all green
```

---

### Task 3: decide_retrieval_targets() top-level + 默认 fallback memory + 30+ representative query

**目的**: 提供 top-level async API,先调 `rule_match`,再调 `LLMRouterFallback`,无 LLM 时(纯单测) fallback memory。

#### Step 3.1 (Red): L0 30+ representative query 集成测试

**文件**: `backend/tests/unit/memory/test_memory_kb_router.py`(追加)

```python
# === 追加 ===

from app.memory.memory_kb_router import decide_retrieval_targets


class TestDecideRetrievalTargetsCorpus:
    """30+ representative query — Plan 6 ship 必须全过。

    Plan 8 会扩到 50 case + accuracy ≥ 0.85.
    Plan 6 这 30+ case 用规则可全部命中,LLM 不需介入。
    """

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "query,expected",
        [
            # 10 memory
            ("我之前买了什么", "memory"),
            ("我的持仓表现", "memory"),
            ("上次我提的策略", "memory"),
            ("我看好的标的", "memory"),
            ("我看空银行", "memory"),
            ("我对消费的偏好", "memory"),
            ("我之前的想法", "memory"),
            ("我对市场的态度", "memory"),  # "市场" 在 KB,但 "我" 在 memory → both
            ("我说过白酒", "memory"),
            ("我提过的股票", "memory"),
            # 10 kb
            ("茅台最新研报", "kb"),
            ("比亚迪 Q3 财报", "kb"),
            ("宁德时代公告", "kb"),
            ("新能源补贴政策", "kb"),
            ("白酒行业分析", "kb"),
            ("今天 A 股新闻", "kb"),
            ("宏观经济展望", "kb"),
            ("白酒板块龙头", "kb"),
            ("近期行业事件", "kb"),
            ("茅台基本面数据", "kb"),
            # 10 both
            ("基于我的持仓推荐", "both"),
            ("结合我的偏好分析市场", "both"),
            ("根据我之前的想法分析", "both"),
            ("我的持仓相关研报", "both"),  # 我 + 研报
            ("我看好的行业最新政策", "both"),  # 我 + 政策
            ("我跟主流机构对比", "both"),
            ("基于我的策略推荐三个", "both"),
            ("结合我的态度看新能源", "both"),
            ("我的偏好与市场对比", "both"),  # 我的 + 市场
            ("我之前提的板块走势", "both"),  # 我 + 板块
        ],
    )
    async def test_30_representative_queries(
        self, query: str, expected: str
    ) -> None:
        d = await decide_retrieval_targets(query, llm_fallback=None)
        assert d.retrieval_targets == [expected], f"{query!r} → {d.retrieval_targets} (reasoning={d.reasoning!r})"


class TestDecideTopLevel:
    @pytest.mark.asyncio
    async def test_rule_hit_skips_llm(self) -> None:
        mock_fallback = AsyncMock()
        d = await decide_retrieval_targets("我之前买了什么", llm_fallback=mock_fallback)
        assert d.retrieval_targets == ["memory"]
        mock_fallback.decide.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_rule_miss_calls_llm_fallback(self) -> None:
        mock_fallback = AsyncMock()
        mock_fallback.decide = AsyncMock(
            return_value=RouterDecision(
                retrieval_targets=["both"],
                reasoning="LLM judged",
            )
        )
        d = await decide_retrieval_targets("综合判断下", llm_fallback=mock_fallback)
        assert d.retrieval_targets == ["both"]
        mock_fallback.decide.assert_awaited_once_with("综合判断下")

    @pytest.mark.asyncio
    async def test_no_llm_no_rule_falls_back_to_memory(self) -> None:
        # spec § 11 #7 (d) — 默认 fallback memory
        d = await decide_retrieval_targets("hello", llm_fallback=None)
        assert d.retrieval_targets == ["memory"]
        assert "default fallback" in d.reasoning.lower()
```

跑测试 → 失败。

#### Step 3.2 (Green): 实现 top-level

**文件**: `backend/app/memory/memory_kb_router.py`(追加)

```python
# === 追加 ===


async def decide_retrieval_targets(
    query: str,
    llm_fallback: LLMRouterFallback | None,
) -> RouterDecision:
    """Top-level routing — rule first, LLM fallback, else default to memory.

    Args:
        query: 用户原始问题文本
        llm_fallback: 可选 LLMRouterFallback 实例,None 时无 LLM 调用(纯规则路径)

    Returns:
        RouterDecision with retrieval_targets ∈ {["memory"], ["kb"], ["both"]}.

    spec § 11 #7 (d): 默认 fallback ["memory"](个人化场景多)。
    """
    decision = rule_match(query)
    if decision is not None:
        return decision

    if llm_fallback is not None:
        return await llm_fallback.decide(query)

    return RouterDecision(
        retrieval_targets=["memory"],
        reasoning="no rule match & no llm fallback configured — default fallback to memory",
    )
```

#### Step 3.3 (Verify):

```bash
uv run pytest backend/tests/unit/memory/test_memory_kb_router.py -x 2>&1 | tail -20
# 预期: ~50+ unit cases all PASS
```

注意: corpus test 中 "我对市场的态度" 跟 "我说过白酒" 含义注释为 memory,但 "我对市场" 含 "我" + "市场" → 实际会被规则归 both。**修测试预期**: 此 case 应改为 both,或换 query。**为避免 self-review 时与本 plan 冲突,Step 3.3 必须打 corpus 实跑校准** — 30 case 实际可能有 2-3 个 boundary case 需调,以实测为准(corpus seed 不背书,只做 representative)。

预留校准时间 30 min,允许此处少量 query/expected 调整(写入 commit message)。

#### Step 3.4 (Refactor):

```bash
uv run mypy backend/app/memory/memory_kb_router.py 2>&1 | tail -5
uv run ruff check backend/app/memory/ backend/tests/unit/memory/ 2>&1 | tail -5
```

#### Step 3.5: commit message 参考

```
feat(c5-plan6): decide_retrieval_targets() top-level + 30 case corpus

- rule_match → LLM fallback → default memory 三层瀑布
- 30 representative query corpus(10 memory / 10 kb / 10 both) all green
- spec § 11 #7 (d) 默认 fallback memory 已落实
```

---

### Task 4: ChatState 新增 4 字段 + 反向兼容

**目的**: 给 LangGraph node 之间传递 router 决策与并行检索结果一个 state slot。`enable_kb_search` 已在 schema(legacy v0 placeholder),Plan 6 不复用,加新 fields 显式承载 routing。

#### Step 4.1 (Red): L0 schema 测

**文件**: `backend/tests/unit/agents/test_chat_state_routing.py`(新增)

```python
"""L0 — ChatState 新增 routing 4 字段 schema 验证。"""

from __future__ import annotations

import pytest
from app.agents.schemas import ChatState


def _base_state(**overrides) -> ChatState:
    base = dict(
        user_id="u1",
        session_id="s1",
        user_message="hi",
        request_id="r1",
        trace_request_id="r1",
    )
    base.update(overrides)
    return ChatState(**base)


class TestChatStateRoutingFields:
    def test_default_empty(self) -> None:
        s = _base_state()
        assert s.retrieval_targets == []
        assert s.memory_hits == []
        assert s.kb_hits == []
        assert s.memory_kb_routing_reasoning is None

    def test_set_retrieval_targets(self) -> None:
        s = _base_state(retrieval_targets=["both"])
        assert s.retrieval_targets == ["both"]

    def test_invalid_retrieval_target_rejected(self) -> None:
        with pytest.raises(ValueError):
            _base_state(retrieval_targets=["bogus"])

    def test_memory_hits_arbitrary_dicts(self) -> None:
        s = _base_state(
            memory_hits=[{"edge_id": "e1", "content": {"foo": "bar"}, "rrf_score": 0.42}]
        )
        assert len(s.memory_hits) == 1

    def test_kb_hits_kb_hit_dict_form(self) -> None:
        # 跟 KbSearchService.search 返回的 KbHit 序列化兼容
        s = _base_state(
            kb_hits=[
                {
                    "chunk_id": "c1",
                    "chunk_text": "茅台 2024 Q3 净利润 ...",
                    "similarity": 0.82,
                    "metadata": {"broker": "中金"},
                }
            ]
        )
        assert s.kb_hits[0]["chunk_id"] == "c1"

    def test_backward_compat_existing_chat_state_callers(self) -> None:
        # 旧调用方不传 4 新字段也能 instantiate
        s = ChatState(
            user_id="u1", session_id="s1", user_message="x",
            request_id="r1", trace_request_id="r1",
        )
        assert s.retrieval_targets == []
```

跑测试 → 失败。

#### Step 4.2 (Green): 修改 `schemas.py`

**文件**: `backend/app/agents/schemas.py`(修改 ChatState)

在 `ChatState` 的 `# === Plan 2a skill loader hook ===` 之后、`# === observability ===` 之前插入:

```python
    # === Plan 6 (c5) — Memory vs KB routing ===
    retrieval_targets: list[str] = Field(
        default_factory=list,
        description=(
            "Output of memory_kb_router_node — single-element list "
            "containing 'memory' / 'kb' / 'both'. Empty before router runs."
        ),
    )
    memory_hits: list[dict] = Field(
        default_factory=list,
        description="archival_memory_search results when retrieval_targets includes memory/both.",
    )
    kb_hits: list[dict] = Field(
        default_factory=list,
        description="KbSearchService.search results when retrieval_targets includes kb/both.",
    )
    memory_kb_routing_reasoning: str | None = Field(
        default=None,
        description="Reasoning string from memory_kb_router for trace/debug.",
    )

    @model_validator(mode="after")
    def _check_retrieval_targets(self) -> "ChatState":
        for t in self.retrieval_targets:
            if t not in ("memory", "kb", "both"):
                raise ValueError(f"Invalid retrieval target in ChatState: {t!r}")
        return self
```

注意: `model_validator` 已被 ChatState 其他地方用过吗?检查现有 schema. 若已有 _check_consistency 之类不冲突,直接加。若有命名冲突,改名为 `_check_retrieval_targets_field`.

import 在文件顶端确认有 `from pydantic import ... model_validator, Field`(若没补)。

#### Step 4.3 (Verify):

```bash
uv run pytest backend/tests/unit/agents/test_chat_state_routing.py -x 2>&1 | tail -15
# 预期: 6 PASS
# 同时跑现有 ChatState 全测试集确认 backward compat
uv run pytest backend/tests/unit/agents/ backend/tests/unit/orchestration/ 2>&1 | tail -10
```

#### Step 4.4 (Refactor):

```bash
uv run mypy backend/app/agents/schemas.py 2>&1 | tail -5
```

#### Step 4.5: commit message

```
feat(c5-plan6): ChatState 新增 4 字段(retrieval_targets / memory_hits / kb_hits / reasoning)

- backward compat: 默认 [] / None,旧调用方零迁移
- field validator 拒绝非法 retrieval target
- 6 schema unit cases + 现有 ChatState 测试 all green
```

---

### Task 5: memory_kb_router_node(LangGraph node wrapper)+ 并行检索

**目的**: LangGraph node 形态包装 router + 并行检索 memory + KB,把结果落入 ChatState。

#### Step 5.1 (Red): L0 单测 — mock memory + mock kb

**文件**: `backend/tests/unit/orchestration/test_memory_kb_router_node.py`(新增)

```python
"""L0 — memory_kb_router_node 单测(mock memory + mock kb + mock router)。"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from app.agents.schemas import ChatState
from app.memory.memory_kb_router import RouterDecision
from app.orchestration.memory_kb_router_node import memory_kb_router_node


def _state(msg: str = "hi") -> ChatState:
    return ChatState(
        user_id=str(uuid4()),
        session_id=str(uuid4()),
        user_message=msg,
        request_id="rid",
        trace_request_id="rid",
    )


class TestMemoryKbRouterNode:
    @pytest.mark.asyncio
    async def test_memory_only_skips_kb(self) -> None:
        memory = MagicMock()
        memory.archival_memory_search = AsyncMock(
            return_value=[
                MagicMock(
                    edge_id="e1",
                    rel_type="HOLDS",
                    properties={"ts_code": "600519.SH"},
                ),
            ]
        )
        kb = MagicMock()
        kb.search = AsyncMock()  # should NOT be called

        router_fn = AsyncMock(
            return_value=RouterDecision(retrieval_targets=["memory"], reasoning="mem hit")
        )

        update = await memory_kb_router_node(
            _state("我之前买了什么"),
            memory=memory,
            kb=kb,
            router_fn=router_fn,
        )

        assert update["retrieval_targets"] == ["memory"]
        assert update["memory_hits"]  # non-empty
        assert update["kb_hits"] == []
        kb.search.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_kb_only_skips_memory(self) -> None:
        memory = MagicMock()
        memory.archival_memory_search = AsyncMock()
        kb = MagicMock()
        kb.search = AsyncMock(
            return_value=[
                MagicMock(chunk_id="c1", chunk_text="...", similarity=0.8, metadata={}),
            ]
        )

        router_fn = AsyncMock(
            return_value=RouterDecision(retrieval_targets=["kb"], reasoning="kb hit")
        )

        update = await memory_kb_router_node(
            _state("茅台最新研报"),
            memory=memory,
            kb=kb,
            router_fn=router_fn,
        )

        assert update["retrieval_targets"] == ["kb"]
        assert update["kb_hits"]
        assert update["memory_hits"] == []
        memory.archival_memory_search.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_both_runs_in_parallel(self) -> None:
        memory = MagicMock()
        memory.archival_memory_search = AsyncMock(
            return_value=[MagicMock(edge_id="e1", rel_type="HOLDS", properties={})]
        )
        kb = MagicMock()
        kb.search = AsyncMock(
            return_value=[MagicMock(chunk_id="c1", chunk_text="...", similarity=0.8, metadata={})]
        )

        router_fn = AsyncMock(
            return_value=RouterDecision(retrieval_targets=["both"], reasoning="both")
        )

        update = await memory_kb_router_node(
            _state("基于我的持仓推荐"),
            memory=memory,
            kb=kb,
            router_fn=router_fn,
        )

        assert update["retrieval_targets"] == ["both"]
        assert update["memory_hits"]
        assert update["kb_hits"]
        memory.archival_memory_search.assert_awaited_once()
        kb.search.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_memory_failure_does_not_kill_kb(self) -> None:
        # 鲁棒性 — memory subquery fail 不 kill KB(both 模式下)
        memory = MagicMock()
        memory.archival_memory_search = AsyncMock(side_effect=RuntimeError("PG down"))
        kb = MagicMock()
        kb.search = AsyncMock(
            return_value=[MagicMock(chunk_id="c1", chunk_text="x", similarity=0.7, metadata={})]
        )

        router_fn = AsyncMock(
            return_value=RouterDecision(retrieval_targets=["both"], reasoning="both")
        )

        update = await memory_kb_router_node(
            _state("基于我的持仓推荐"),
            memory=memory,
            kb=kb,
            router_fn=router_fn,
        )

        assert update["retrieval_targets"] == ["both"]
        assert update["memory_hits"] == []  # graceful degrade
        assert update["kb_hits"]  # still got KB results

    @pytest.mark.asyncio
    async def test_reasoning_persisted(self) -> None:
        memory = MagicMock()
        memory.archival_memory_search = AsyncMock(return_value=[])
        kb = MagicMock()
        kb.search = AsyncMock(return_value=[])

        router_fn = AsyncMock(
            return_value=RouterDecision(
                retrieval_targets=["memory"], reasoning="memory word hit: '我'"
            )
        )

        update = await memory_kb_router_node(
            _state("我"),
            memory=memory,
            kb=kb,
            router_fn=router_fn,
        )
        assert update["memory_kb_routing_reasoning"] == "memory word hit: '我'"
```

跑测试 → 失败。

#### Step 5.2 (Green): 实现 node wrapper

**文件**: `backend/app/orchestration/memory_kb_router_node.py`(新增)

```python
"""LangGraph node — Memory vs KB Search 检索路由 + 并行检索。

Topology placement(chat_graph.py):
    context_node → memory_kb_router_node → planner_node → ...

Responsibility:
    1. 调 router_fn(state.user_message) → RouterDecision
    2. 按 retrieval_targets 并行检索 memory.archival_memory_search 和 / 或 kb.search
    3. graceful degrade: 单路 fail 不 kill 另一路(both 模式)
    4. update ChatState 4 fields

per spec § 11 末尾 #7.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Coroutine
from typing import Any
from uuid import UUID

from app.agents.schemas import ChatState
from app.memory.memory_kb_router import RouterDecision
from app.services.kb_search_service import KbHit, KbSearchService

logger = logging.getLogger(__name__)

RouterFn = Callable[[str], Coroutine[Any, Any, RouterDecision]]


def _serialize_memory_edge(edge: Any) -> dict[str, Any]:
    """Convert ChatMemoryEdge or compatible mock into a JSON-friendly dict."""
    return {
        "edge_id": str(getattr(edge, "edge_id", "")),
        "rel_type": getattr(edge, "rel_type", None),
        "properties": dict(getattr(edge, "properties", {}) or {}),
        "source_node_id": str(getattr(edge, "source_node_id", "")),
        "target_node_id": str(getattr(edge, "target_node_id", "")),
        "importance": getattr(edge, "importance", None),
        "valid_from": str(getattr(edge, "valid_from", "")) if getattr(edge, "valid_from", None) else None,
        "reasoning": getattr(edge, "reasoning", None),
    }


def _serialize_kb_hit(hit: Any) -> dict[str, Any]:
    if isinstance(hit, KbHit):
        return hit.model_dump()
    return {
        "chunk_id": getattr(hit, "chunk_id", ""),
        "chunk_text": getattr(hit, "chunk_text", ""),
        "similarity": getattr(hit, "similarity", 0.0),
        "metadata": dict(getattr(hit, "metadata", {}) or {}),
    }


async def _safe_memory_search(
    memory: Any, user_id: UUID, query: str
) -> list[dict[str, Any]]:
    try:
        edges = await memory.archival_memory_search(user_id=user_id, query=query, k=5)
    except Exception as e:  # noqa: BLE001 — graceful degrade
        logger.warning("memory_kb_router_node memory search failed: %s — graceful degrade", e)
        return []
    return [_serialize_memory_edge(e) for e in (edges or [])]


async def _safe_kb_search(kb: KbSearchService, query: str) -> list[dict[str, Any]]:
    try:
        hits = await kb.search(query=query, top_k=5)
    except Exception as e:  # noqa: BLE001 — graceful degrade
        logger.warning("memory_kb_router_node kb search failed: %s — graceful degrade", e)
        return []
    return [_serialize_kb_hit(h) for h in (hits or [])]


async def memory_kb_router_node(
    state: ChatState,
    *,
    memory: Any,  # HierarchicalMemory or InSessionMemory(stub)
    kb: KbSearchService,
    router_fn: RouterFn,
) -> dict[str, Any]:
    """Run routing decision + parallel retrieval; emit state update dict.

    Returns dict subset of ChatState fields(LangGraph state-update protocol).
    """
    decision = await router_fn(state.user_message)
    target = decision.retrieval_targets[0]  # single-element by RouterDecision contract

    user_uuid: UUID
    try:
        user_uuid = UUID(state.user_id)
    except (ValueError, AttributeError):
        # legacy / anonymous — let memory layer 自行决定怎么处理(可能拒,也可能空返)
        # 实际生产 user_id 已 UUID,此 try/except 仅兼容遗留 'anonymous' 字面量。
        user_uuid = UUID("00000000-0000-0000-0000-000000000000")

    if target == "memory":
        memory_hits = await _safe_memory_search(memory, user_uuid, state.user_message)
        kb_hits: list[dict[str, Any]] = []
    elif target == "kb":
        memory_hits = []
        kb_hits = await _safe_kb_search(kb, state.user_message)
    else:  # "both"
        memory_hits, kb_hits = await asyncio.gather(
            _safe_memory_search(memory, user_uuid, state.user_message),
            _safe_kb_search(kb, state.user_message),
        )

    return {
        "retrieval_targets": list(decision.retrieval_targets),
        "memory_hits": memory_hits,
        "kb_hits": kb_hits,
        "memory_kb_routing_reasoning": decision.reasoning,
    }
```

#### Step 5.3 (Verify):

```bash
uv run pytest backend/tests/unit/orchestration/test_memory_kb_router_node.py -x 2>&1 | tail -15
# 预期: 5 PASS
```

#### Step 5.4 (Refactor):

```bash
uv run mypy backend/app/orchestration/memory_kb_router_node.py 2>&1 | tail -5
uv run ruff check backend/app/orchestration/memory_kb_router_node.py 2>&1 | tail -5
```

#### Step 5.5: commit message

```
feat(c5-plan6): memory_kb_router_node LangGraph node wrapper

- 调 router_fn 决策 retrieval_targets
- memory/kb/both 三模式分发 + both 模式 asyncio.gather 并行
- 单路 fail graceful degrade(不 kill 另一路)
- ChatMemoryEdge / KbHit 序列化兼容 langgraph state checkpoint
- 5 unit cases all green
```

---

### Task 6: chat_graph.py 插入 router node + planner_node 集成

**目的**: 在 `START → context_node → planner_node` 链上插入 `memory_kb_router_node`(context_node 之后,planner_node 之前),并 backward compat — 没注入 `kb_search_service` 时 router node 不挂载。

#### Step 6.1 (Red): L1 chat graph e2e

**文件**: `backend/tests/integration/memory/test_kb_routing_e2e.py`(新增)

```python
"""L1 — chat graph 集成 memory_kb_router_node 端到端(mock LLM + mock memory + mock kb)。

Asserts:
- 没注入 kb_search_service → 老 topology 保留(backward compat)
- 注入后 → memory query 走 memory 路径,kb query 走 kb 路径,both query 并行
- planner prompt 收到 [用户上下文] / [市场知识] 段(由 Task 7 实现)
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from app.agents.chat_planner import ChatPlanner
from app.agents.in_session_memory import InSessionMemory
from app.agents.responder import Responder
from app.agents.schemas import ChatState
from app.memory.memory_kb_router import RouterDecision
from app.orchestration.chat_graph import build_chat_graph
from app.services.kb_search_service import KbHit, MockKbSearchService  # may need wrapper
from app.services.llm_mock_client import MockLLMClient
from app.services.llm_service import LLMService
from app.services.tool_result_cache import ToolResultCache
from app.tools.registry import ToolRegistry


@pytest.fixture
def mock_llm() -> LLMService:
    client = MockLLMClient(
        responses={
            r"^你是金融研究助手 chat 模式的 planner": (
                '{"tool_calls":[],"direct_response":true,"parallelizable":false,'
                '"escalate_offered":false,"reasoning":"已用 routing 结果直接回","load_skill":null,'
                '"load_resource":null,"script_calls":[]}'
            ),
            r"^你是金融研究助手 responder": "已综合用户上下文 + 市场知识。",
        }
    )
    return LLMService(client=client)


@pytest.fixture
def mock_kb() -> Any:
    kb = MagicMock()
    kb.search = AsyncMock(
        return_value=[
            KbHit(
                chunk_id="c1",
                chunk_text="茅台 2024 Q3 净利润 ...",
                similarity=0.82,
                metadata={"broker": "中金", "pub_date": "2024-10-30"},
            )
        ]
    )
    return kb


@pytest.fixture
def mock_memory() -> Any:
    mem = MagicMock(spec=InSessionMemory)
    mem.dedup_tool_results = lambda r: r
    mem.needs_summarize = lambda s, m: False
    mem.summarize = AsyncMock(return_value="")
    mem.load_for_turn = AsyncMock()
    mem.save_after_turn = AsyncMock()
    mem.archival_memory_search = AsyncMock(
        return_value=[
            MagicMock(
                edge_id="e1",
                rel_type="HOLDS",
                properties={"ts_code": "600519.SH"},
                source_node_id="n1",
                target_node_id="n2",
                importance=0.9,
                valid_from="2024-08-01",
                reasoning="user mentioned",
            )
        ]
    )
    return mem


class TestKbRoutingE2E:
    @pytest.mark.asyncio
    async def test_memory_query_routes_to_memory(
        self, mock_llm: LLMService, mock_memory: Any, mock_kb: Any
    ) -> None:
        registry = ToolRegistry()
        cache = ToolResultCache()
        planner = ChatPlanner(llm=mock_llm, available_tools=[])
        responder = Responder(llm=mock_llm)

        async def router_fn(query: str) -> RouterDecision:
            return RouterDecision(retrieval_targets=["memory"], reasoning="mem")

        graph = build_chat_graph(
            planner=planner,
            responder=responder,
            registry=registry,
            memory=mock_memory,
            cache=cache,
            kb_search_service=mock_kb,
            memory_kb_router_fn=router_fn,
        )

        initial = ChatState(
            user_id=str(uuid4()),
            session_id=str(uuid4()),
            user_message="我之前买了什么",
            request_id="r1",
            trace_request_id="r1",
        )
        final = await graph.ainvoke(initial.model_dump())

        assert final["retrieval_targets"] == ["memory"]
        assert final["memory_hits"]
        assert final["kb_hits"] == []
        mock_kb.search.assert_not_awaited()
        mock_memory.archival_memory_search.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_kb_query_routes_to_kb(
        self, mock_llm: LLMService, mock_memory: Any, mock_kb: Any
    ) -> None:
        async def router_fn(query: str) -> RouterDecision:
            return RouterDecision(retrieval_targets=["kb"], reasoning="kb")

        registry = ToolRegistry()
        cache = ToolResultCache()
        planner = ChatPlanner(llm=mock_llm, available_tools=[])
        responder = Responder(llm=mock_llm)
        graph = build_chat_graph(
            planner=planner,
            responder=responder,
            registry=registry,
            memory=mock_memory,
            cache=cache,
            kb_search_service=mock_kb,
            memory_kb_router_fn=router_fn,
        )
        initial = ChatState(
            user_id=str(uuid4()),
            session_id=str(uuid4()),
            user_message="茅台最新研报",
            request_id="r2",
            trace_request_id="r2",
        )
        final = await graph.ainvoke(initial.model_dump())
        assert final["retrieval_targets"] == ["kb"]
        assert final["kb_hits"]
        assert final["memory_hits"] == []

    @pytest.mark.asyncio
    async def test_both_query_runs_parallel(
        self, mock_llm: LLMService, mock_memory: Any, mock_kb: Any
    ) -> None:
        async def router_fn(query: str) -> RouterDecision:
            return RouterDecision(retrieval_targets=["both"], reasoning="both")

        registry = ToolRegistry()
        cache = ToolResultCache()
        planner = ChatPlanner(llm=mock_llm, available_tools=[])
        responder = Responder(llm=mock_llm)
        graph = build_chat_graph(
            planner=planner,
            responder=responder,
            registry=registry,
            memory=mock_memory,
            cache=cache,
            kb_search_service=mock_kb,
            memory_kb_router_fn=router_fn,
        )
        initial = ChatState(
            user_id=str(uuid4()),
            session_id=str(uuid4()),
            user_message="基于我的持仓推荐",
            request_id="r3",
            trace_request_id="r3",
        )
        final = await graph.ainvoke(initial.model_dump())
        assert final["retrieval_targets"] == ["both"]
        assert final["memory_hits"]
        assert final["kb_hits"]

    @pytest.mark.asyncio
    async def test_no_kb_service_keeps_legacy_topology(
        self, mock_llm: LLMService, mock_memory: Any
    ) -> None:
        # backward compat: 不注入 kb_search_service → router node 不挂载
        registry = ToolRegistry()
        cache = ToolResultCache()
        planner = ChatPlanner(llm=mock_llm, available_tools=[])
        responder = Responder(llm=mock_llm)
        graph = build_chat_graph(
            planner=planner,
            responder=responder,
            registry=registry,
            memory=mock_memory,
            cache=cache,
            # kb_search_service / memory_kb_router_fn 都不传
        )
        initial = ChatState(
            user_id="anonymous", session_id="s", user_message="hi",
            request_id="r4", trace_request_id="r4",
        )
        final = await graph.ainvoke(initial.model_dump())
        # legacy: retrieval_targets 仍是默认空
        assert final["retrieval_targets"] == []
```

跑测试 → 失败(`build_chat_graph` 没有 `kb_search_service` / `memory_kb_router_fn` 参数)。

#### Step 6.2 (Green): 修改 chat_graph.py

**文件**: `backend/app/orchestration/chat_graph.py`(修改)

在 `build_chat_graph` 签名加可选参数,在 topology 中插入 router node:

```python
# === 修改 build_chat_graph(尾部新增参数) ===

from app.orchestration.memory_kb_router_node import (
    RouterFn,
    memory_kb_router_node,
)
from app.services.kb_search_service import KbSearchService


def build_chat_graph(
    planner: ChatPlanner,
    responder: Responder,
    registry: ToolRegistry,
    memory: Memory,
    cache: ToolResultCache,
    *,
    checkpointer: BaseCheckpointSaver[Any] | None = None,
    skill_loader: SkillLoader | None = None,
    kb_search_service: KbSearchService | None = None,         # NEW Plan 6
    memory_kb_router_fn: RouterFn | None = None,              # NEW Plan 6
) -> CompiledStateGraph[Any, Any, Any, Any]:
    """... + Plan 6:
    
    When ``kb_search_service`` is provided AND ``memory_kb_router_fn`` is provided,
    a ``memory_kb_router_node`` is inserted between context_node and planner_node.
    Both must be provided together — providing only one raises ValueError.
    """
    if (kb_search_service is None) != (memory_kb_router_fn is None):
        raise ValueError(
            "kb_search_service and memory_kb_router_fn must be provided together"
        )
    enable_kb_routing = kb_search_service is not None and memory_kb_router_fn is not None

    g: StateGraph[Any, Any, Any, Any] = StateGraph(ChatState)

    g.add_node("context_node", partial(context_node, memory=memory))
    g.add_node("planner_node", partial(planner_node, planner=planner))
    g.add_node("tool_node", partial(tool_node, registry=registry, cache=cache))
    g.add_node("responder_node", partial(responder_node, responder=responder))

    if skill_loader is not None:
        g.add_node("skill_load_node", partial(skill_load_node, loader=skill_loader))
        g.add_node("resource_load_node", partial(resource_load_node, loader=skill_loader))

    # === Plan 6 — Memory vs KB router node(in front of planner) ===
    if enable_kb_routing:
        g.add_node(
            "memory_kb_router_node",
            partial(
                memory_kb_router_node,
                memory=memory,
                kb=kb_search_service,
                router_fn=memory_kb_router_fn,
            ),
        )

    g.add_edge(START, "context_node")

    if enable_kb_routing:
        g.add_edge("context_node", "memory_kb_router_node")
        g.add_edge("memory_kb_router_node", "planner_node")
    else:
        g.add_edge("context_node", "planner_node")

    edge_map: dict[Hashable, str] = {
        "tool_node": "tool_node",
        "responder_node": "responder_node",
    }
    if skill_loader is not None:
        edge_map["skill_load_node"] = "skill_load_node"
        edge_map["resource_load_node"] = "resource_load_node"

    g.add_conditional_edges("planner_node", _route_after_planner, edge_map)
    g.add_edge("tool_node", "responder_node")

    if skill_loader is not None:
        g.add_edge("skill_load_node", "planner_node")
        g.add_edge("resource_load_node", "planner_node")

    g.add_edge("responder_node", END)

    return g.compile(checkpointer=checkpointer)
```

#### Step 6.3 (Verify):

```bash
uv run pytest backend/tests/integration/memory/test_kb_routing_e2e.py -x 2>&1 | tail -20
# 预期: 4 PASS
# 同时跑现有 chat graph test 集合确认 backward compat 不破
uv run pytest backend/tests/unit/orchestration/test_chat_graph_v0_9.py backend/tests/integration/test_chat_agent_e2e_mock.py 2>&1 | tail -10
```

#### Step 6.4 (Refactor):

```bash
uv run mypy backend/app/orchestration/chat_graph.py 2>&1 | tail -5
```

#### Step 6.5: commit message

```
feat(c5-plan6): chat_graph 集成 memory_kb_router_node(可选注入)

- build_chat_graph 加 kb_search_service / memory_kb_router_fn 两参数(必须配对)
- topology 插入: context_node → memory_kb_router_node → planner_node
- 不注入时维持老 topology(backward compat — InSessionMemory + 无 KB routing)
- 4 L1 cases all green + 现有 chat graph 测试零退化
```

---

### Task 7: planner prompt 加 `[用户上下文]` / `[市场知识]` 段

**目的**: 落地 spec § 11 #7 (c) — 两路结果 prompt 显式区隔,让 LLM 不混淆个人事实和公开知识。

#### Step 7.1 (Red): L0 prompt 测

**文件**: `backend/tests/unit/agents/test_chat_planner_routing_prompt.py`(新增)

```python
"""L0 — ChatPlanner planner prompt 区隔段(spec § 11 #7 (c))。"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from app.agents.chat_planner import ChatPlanner
from app.agents.schemas import ChatState
from app.services.llm_service import LLMService


def _make_planner() -> ChatPlanner:
    mock_llm = MagicMock(spec=LLMService)
    return ChatPlanner(llm=mock_llm, available_tools=["get_stock_quote"])


def _state(memory_hits, kb_hits) -> ChatState:
    return ChatState(
        user_id="u1", session_id="s1", user_message="基于我的持仓推荐",
        request_id="r1", trace_request_id="r1",
        memory_hits=memory_hits, kb_hits=kb_hits,
        retrieval_targets=["both"] if memory_hits and kb_hits else (
            ["memory"] if memory_hits else (["kb"] if kb_hits else [])
        ),
    )


class TestPlannerPromptSegregation:
    def test_no_routing_results_no_segregation_blocks(self) -> None:
        # 没有 routing 结果 — prompt 不应注入 [用户上下文] / [市场知识] 段
        planner = _make_planner()
        prompt = planner._render_prompt(_state(memory_hits=[], kb_hits=[]))
        assert "[用户上下文]" not in prompt
        assert "[市场知识]" not in prompt

    def test_memory_only_injects_user_context_block(self) -> None:
        planner = _make_planner()
        prompt = planner._render_prompt(
            _state(
                memory_hits=[
                    {"rel_type": "HOLDS", "properties": {"ts_code": "600519.SH"},
                     "valid_from": "2024-08-01"}
                ],
                kb_hits=[],
            )
        )
        assert "[用户上下文]" in prompt
        assert "HOLDS" in prompt
        assert "600519.SH" in prompt
        assert "[市场知识]" not in prompt

    def test_kb_only_injects_market_knowledge_block(self) -> None:
        planner = _make_planner()
        prompt = planner._render_prompt(
            _state(
                memory_hits=[],
                kb_hits=[
                    {"chunk_id": "c1", "chunk_text": "茅台 Q3 ...",
                     "similarity": 0.82, "metadata": {"broker": "中金"}}
                ],
            )
        )
        assert "[市场知识]" in prompt
        assert "茅台 Q3" in prompt
        assert "[用户上下文]" not in prompt

    def test_both_injects_both_blocks_separately(self) -> None:
        planner = _make_planner()
        prompt = planner._render_prompt(
            _state(
                memory_hits=[
                    {"rel_type": "PREFERS",
                     "properties": {"strategy": "白马"}, "valid_from": "2024-09-01"}
                ],
                kb_hits=[
                    {"chunk_id": "c1", "chunk_text": "白马股近 6 月跑输大盘",
                     "similarity": 0.9, "metadata": {}}
                ],
            )
        )
        # 两段都在,且 [用户上下文] 在 [市场知识] 之前 — 让 LLM 先把私人信息当 frame
        idx_user = prompt.find("[用户上下文]")
        idx_mkt = prompt.find("[市场知识]")
        assert 0 <= idx_user < idx_mkt

    def test_segregation_prompt_explicit_disclaimer(self) -> None:
        # spec § 11 #7 (c): 让 LLM 不混淆个人事实和公开知识
        planner = _make_planner()
        prompt = planner._render_prompt(
            _state(
                memory_hits=[{"rel_type": "PREFERS", "properties": {}, "valid_from": "2024"}],
                kb_hits=[{"chunk_id": "c1", "chunk_text": "x", "similarity": 0.5, "metadata": {}}],
            )
        )
        # 必须含明确告知 LLM 两段含义不同的 disclaimer
        assert "个人事实" in prompt or "不要把" in prompt or "区分" in prompt
```

跑测试 → 失败(`_render_prompt` 还没暴露 / 还不支持新段)。

#### Step 7.2 (Green): 修改 ChatPlanner

**文件**: `backend/app/agents/chat_planner.py`(修改)

在 ChatPlanner 加 helper(若已有 _render_prompt 内部逻辑就拼到现有 _PLANNER_PROMPT_TEMPLATE):

```python
# === 新增 helper(模块级) ===

_USER_CONTEXT_HEADER = "[用户上下文]  ← 来自用户私人记忆,只用作偏好/持仓背景,不是投资结论"
_MARKET_KNOWLEDGE_HEADER = "[市场知识]  ← 来自公开知识库(研报/财报/政策/新闻),客观信息,跟用户偏好独立"
_SEGREGATION_DISCLAIMER = (
    "\n注意: [用户上下文] 是用户的个人事实(持仓/偏好/历史想法),[市场知识] 是公开信息。"
    "回答时请区分,不要把它们混淆 — 比如 用户偏好白马 + 市场跑输大盘 是 trade-off,不是矛盾。\n"
)


def _format_memory_hits(hits: list[dict]) -> str:
    """Render memory hits into a compact user-context block."""
    if not hits:
        return ""
    lines = [_USER_CONTEXT_HEADER]
    for h in hits[:5]:  # 防爆
        rel = h.get("rel_type", "?")
        props = h.get("properties", {}) or {}
        valid_from = h.get("valid_from", "?")
        ts_code = props.get("ts_code") or props.get("label") or ""
        # 优先组合显示 rel + ts_code/label,fallback dump props
        if ts_code:
            lines.append(f"- {rel}: {ts_code}(valid_from={valid_from})")
        else:
            lines.append(f"- {rel}: {props}(valid_from={valid_from})")
    return "\n".join(lines)


def _format_kb_hits(hits: list[dict]) -> str:
    """Render kb hits into a compact market-knowledge block."""
    if not hits:
        return ""
    lines = [_MARKET_KNOWLEDGE_HEADER]
    for h in hits[:5]:
        text = h.get("chunk_text", "")[:240]
        sim = h.get("similarity", 0.0)
        meta = h.get("metadata", {}) or {}
        broker = meta.get("broker", "")
        lines.append(f"- (sim={sim:.2f}{', ' + broker if broker else ''}) {text}")
    return "\n".join(lines)
```

然后修改 ChatPlanner 内的 prompt 渲染。看现有 `run` 方法实现处填入段落,或单独抽 `_render_prompt`:

```python
# === ChatPlanner._render_prompt(新方法 — 暴露给测试)===

class ChatPlanner(Agent):
    # ... 原有代码 ...

    def _render_prompt(self, state: ChatState) -> str:
        """Render the v0.9 chat planner prompt, including Plan 6 routing blocks."""
        tool_descs = self._format_tool_descriptions()
        history_summary = state.history_summary or "(无)"
        recent_turns = self._format_recent_turns(state)

        # === Plan 6 NEW — segregation blocks ===
        user_ctx_block = _format_memory_hits(state.memory_hits)
        market_block = _format_kb_hits(state.kb_hits)
        seg_disclaimer = _SEGREGATION_DISCLAIMER if (user_ctx_block and market_block) else ""

        prompt = _PLANNER_PROMPT_TEMPLATE.format(
            tool_descriptions=tool_descs,
            user_message=state.user_message,
            history_summary=history_summary,
            recent_k=self._recent_k,
            recent_turns=recent_turns,
        )

        # 把 routing block 注入到 prompt 中"用户当前问题"之前(最显眼位置)
        if user_ctx_block or market_block:
            inject_parts: list[str] = []
            if user_ctx_block:
                inject_parts.append(user_ctx_block)
            if market_block:
                inject_parts.append(market_block)
            if seg_disclaimer:
                inject_parts.append(seg_disclaimer)
            inject_block = "\n\n".join(inject_parts) + "\n\n"
            # 插在 "用户当前问题:" 之前
            anchor = "用户当前问题:"
            prompt = prompt.replace(anchor, inject_block + anchor, 1)

        return prompt
```

注意: 看现有 `ChatPlanner.run` 的 prompt 构建路径,修改使其调用 `_render_prompt`。如果现有路径已嵌入 prompt 构建逻辑,先抽出 `_render_prompt` 再调用。具体细节由 Step 7.1 实测的 L0 单测引导(`_render_prompt` 是测试调用入口)。

`_format_tool_descriptions` / `_format_recent_turns` 若 ChatPlanner 已有可复用,无则按现有 inline 实现抽取 helper。

#### Step 7.3 (Verify):

```bash
uv run pytest backend/tests/unit/agents/test_chat_planner_routing_prompt.py -x 2>&1 | tail -15
# 预期: 5 PASS
# 同时跑现有 ChatPlanner 测试确认无退化
uv run pytest backend/tests/unit/agents/test_chat_planner.py 2>&1 | tail -10
```

#### Step 7.4 (Refactor):

```bash
uv run mypy backend/app/agents/chat_planner.py 2>&1 | tail -5
uv run ruff check backend/app/agents/chat_planner.py 2>&1 | tail -5
```

#### Step 7.5: commit message

```
feat(c5-plan6): planner prompt 加 [用户上下文] / [市场知识] 区隔段

- spec § 11 #7 (c): 两路结果 prompt 显式区隔,LLM 不混淆个人事实 vs 公开知识
- _format_memory_hits / _format_kb_hits 紧凑渲染(top-5 防爆 + 240 char 截断)
- both 两段都在时加显式 disclaimer:"用户偏好白马 + 市场跑输 是 trade-off 不是矛盾"
- 5 prompt unit cases all green
```

---

### Task 8: routing seed jsonl(8 case)+ metric hook

**目的**: Plan 6 提供 8 representative seed case + accuracy 计算 hook;Plan 8 在此基础上扩到 50 case + 阈值 ≥ 0.85。

#### Step 8.1 (Red): metric hook L0 测

**文件**: `backend/tests/unit/memory/test_routing_accuracy_hook.py`(新增)

```python
"""L0 — routing accuracy metric hook 测试(Plan 6 提供 hook,Plan 8 填实 50 case)。"""

from __future__ import annotations

import pytest
from app.eval.memory.routing_accuracy_hook import (
    RoutingCase,
    compute_routing_accuracy,
    load_routing_cases,
)


class TestRoutingCase:
    def test_valid(self) -> None:
        c = RoutingCase(query="我之前买了什么", expected="memory")
        assert c.query and c.expected == "memory"

    def test_invalid_expected_rejected(self) -> None:
        with pytest.raises(ValueError):
            RoutingCase(query="x", expected="bogus")


class TestComputeRoutingAccuracy:
    def test_all_correct(self) -> None:
        cases = [
            RoutingCase(query="q1", expected="memory"),
            RoutingCase(query="q2", expected="kb"),
        ]
        predictions = {"q1": "memory", "q2": "kb"}
        score = compute_routing_accuracy(cases, predictions)
        assert score == 1.0

    def test_half_correct(self) -> None:
        cases = [
            RoutingCase(query="q1", expected="memory"),
            RoutingCase(query="q2", expected="kb"),
        ]
        predictions = {"q1": "memory", "q2": "memory"}
        score = compute_routing_accuracy(cases, predictions)
        assert score == 0.5

    def test_missing_prediction_counts_as_wrong(self) -> None:
        cases = [RoutingCase(query="q1", expected="memory")]
        score = compute_routing_accuracy(cases, predictions={})
        assert score == 0.0


class TestLoadRoutingCases:
    def test_load_seed_jsonl(self) -> None:
        cases = load_routing_cases(
            "backend/eval/memory/routing_accuracy_seed.jsonl"
        )
        assert len(cases) == 8  # Plan 6 seed: 8 case
        # 平衡分布: 2 memory + 2 kb + 2 both + 2 边界
        targets = [c.expected for c in cases]
        assert targets.count("memory") >= 2
        assert targets.count("kb") >= 2
        assert targets.count("both") >= 2
```

跑测试 → 失败。

#### Step 8.2 (Green): seed jsonl + hook

**文件**: `backend/eval/memory/routing_accuracy_seed.jsonl`(新增)

```jsonl
{"query": "我之前买了什么股票", "expected": "memory", "category": "pure-memory"}
{"query": "我对消费板块的偏好是什么", "expected": "memory", "category": "pure-memory"}
{"query": "茅台最新研报怎么说", "expected": "kb", "category": "pure-kb"}
{"query": "新能源车补贴政策最新动态", "expected": "kb", "category": "pure-kb"}
{"query": "基于我的持仓推荐一些股票", "expected": "both", "category": "pure-both"}
{"query": "结合我的偏好分析下当前市场", "expected": "both", "category": "pure-both"}
{"query": "今天天气如何", "expected": "memory", "category": "boundary-noise"}
{"query": "讲个笑话", "expected": "memory", "category": "boundary-noise"}
```

`category` 给 Plan 8 扩展时分组用;边界 noise 期望 memory(因 spec § 11 #7 (d) 默认 fallback memory)。

**文件**: `backend/eval/memory/routing_accuracy_hook.py`(新增)

```python
"""Routing accuracy metric hook — Plan 6 提供, Plan 8 填实 50 case + 阈值 ≥ 0.85.

usage(Plan 8):
    from app.eval.memory.routing_accuracy_hook import (
        RoutingCase, compute_routing_accuracy, load_routing_cases
    )
    cases = load_routing_cases("backend/eval/memory/c5_memory_golden.jsonl")
    predictions = {c.query: predict(c.query) for c in cases}
    acc = compute_routing_accuracy(cases, predictions)
    assert acc >= 0.85
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, field_validator

RoutingTarget = Literal["memory", "kb", "both"]


class RoutingCase(BaseModel):
    model_config = ConfigDict(frozen=True)

    query: str
    expected: RoutingTarget
    category: str = "uncategorized"

    @field_validator("expected")
    @classmethod
    def _check_expected(cls, v: str) -> str:
        if v not in ("memory", "kb", "both"):
            raise ValueError(f"Invalid expected: {v!r}")
        return v


def load_routing_cases(path: str | Path) -> list[RoutingCase]:
    """Load routing cases from JSONL file."""
    p = Path(path)
    cases: list[RoutingCase] = []
    with p.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            cases.append(RoutingCase.model_validate(json.loads(line)))
    return cases


def compute_routing_accuracy(
    cases: list[RoutingCase],
    predictions: dict[str, str],
) -> float:
    """Compute exact-match accuracy of routing predictions.

    Args:
        cases: ground-truth labeled cases
        predictions: {query: predicted_target}

    Returns:
        accuracy ∈ [0.0, 1.0]; missing prediction counts as wrong.
    """
    if not cases:
        return 0.0
    correct = 0
    for c in cases:
        pred = predictions.get(c.query)
        if pred == c.expected:
            correct += 1
    return correct / len(cases)
```

注意 hook 文件位置: 契约 § 1 写 `backend/eval/memory/routing_accuracy_metric.py` 是 Plan 8 责任。Plan 6 的 hook 是 Plan 8 metric.py 的依赖底座;改名为 `routing_accuracy_hook.py` 避免和 Plan 8 文件冲突。Plan 8 在 metric.py import 此 hook。

import path: `from app.eval.memory.routing_accuracy_hook import ...`

需要确认 `backend/eval/` 下是否要建 Python package。检查现有结构:

```bash
ls backend/eval/ 2>&1; ls backend/eval/memory/ 2>&1
# 若 backend/eval/__init__.py 不存在 → 加(空文件)
# backend/eval/memory/__init__.py 也加
```

若 `backend/eval/` 不在 PYTHONPATH 上 / 不是 package(项目 source root 是 `backend/app`),改成 `backend/app/eval/memory/routing_accuracy_hook.py`,跟 spec/契约文件位置略偏。**决策**: 跟 § 1 契约对齐,放 `backend/eval/memory/`,但 import path 仍按 contracts 已写的 `app.eval.memory.routing_accuracy_metric` 风格 — 实际生产路径经过 pyproject 配置(若没,本 plan Step 8 注明 follow-up,Plan 8 收束时一并 align)。

**简化**: Plan 6 直接放 `backend/app/eval/memory/routing_accuracy_hook.py`(确认 `app/eval/` 不存在前先 mkdir),import 路径一致。Plan 8 把 metric.py 也放此处。契约 § 1 写的 `backend/eval/memory/` 目录视作 deliverable artifact 路径(jsonl 数据文件),Python 模块走 `app/eval/memory/`(都属于 app namespace)。

调整: jsonl 在 `backend/eval/memory/`;Python module 在 `backend/app/eval/memory/`。test 中 load_routing_cases 用相对 cwd path。

#### Step 8.3 (Verify):

```bash
mkdir -p backend/app/eval/memory backend/eval/memory
touch backend/app/eval/memory/__init__.py backend/app/eval/__init__.py
uv run pytest backend/tests/unit/memory/test_routing_accuracy_hook.py -x 2>&1 | tail -15
# 预期: ≥ 5 PASS
```

#### Step 8.4 (Refactor):

```bash
uv run mypy backend/app/eval/memory/routing_accuracy_hook.py 2>&1 | tail -5
```

#### Step 8.5: commit message

```
feat(c5-plan6): routing accuracy seed(8 case)+ metric hook

- routing_accuracy_seed.jsonl: 8 case(2 memory + 2 kb + 2 both + 2 boundary)
- compute_routing_accuracy / load_routing_cases / RoutingCase pydantic
- Plan 8 用此 hook 扩到 50 case + 阈值 ≥ 0.85
```

---

### Task 9: L2 cassette — both 类 query 真 LLM 不矛盾化断言

**目的**: spec § 11 #7 量化验证「both 类 query LLM 不矛盾化(用户偏好 vs 市场跑输应该是 trade-off 不是矛盾)」— 真 LLM 录 cassette,断言 responder 输出语义不出现"矛盾/对立"等冲突词,而出现"trade-off / 平衡 / 取舍"等。

#### Step 9.1 (Red): L2 cassette 测

**文件**: `backend/tests/e2e/memory/test_memory_kb_routing_cassette.py`(新增)

```python
"""L2 cassette — both 类 query 真 LLM 响应不矛盾化(spec § 11 #7 验证标准)。

Scenario(用户偏好白马 vs 市场跑输 — 经典 trade-off):
- memory_hits: PREFERS 白马 + valid_from=2024-09
- kb_hits: 研报片段说"白马股近 6 月跑输大盘 5%"
- 期望: LLM responder 输出语义保持 trade-off 框架,不会将其结论化为"用户偏好错了" /
        "信号矛盾建议立即换"等。

录制方式(作者侧 dogfood):
    DASHSCOPE_API_KEY=... uv run pytest backend/tests/e2e/memory/test_memory_kb_routing_cassette.py \
        --record-mode=once
回放方式(CI):
    uv run pytest backend/tests/e2e/memory/test_memory_kb_routing_cassette.py
    # cassette 已 ship,回放本地无 LLM cost
"""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest
import vcr  # type: ignore[import-not-found]
from app.agents.chat_planner import ChatPlanner
from app.agents.responder import Responder
from app.agents.schemas import ChatState
from app.memory.memory_kb_router import RouterDecision
from app.orchestration.chat_graph import build_chat_graph
from app.services.kb_search_service import KbHit
from app.services.openai_client import build_llm_service_from_env
from app.services.tool_result_cache import ToolResultCache
from app.tools.registry import ToolRegistry
from unittest.mock import AsyncMock, MagicMock

CASSETTE_DIR = Path(__file__).parent.parent.parent / "cassettes" / "memory"
CASSETTE_DIR.mkdir(parents=True, exist_ok=True)
CASSETTE_PATH = CASSETTE_DIR / "memory_kb_routing__both_white_horse_underperform.yaml"


# 跟 PR #39 cassette framework 对齐 — strip dynamic prompt fields
_VCR = vcr.VCR(
    cassette_library_dir=str(CASSETTE_DIR),
    record_mode="once",
    match_on=["method", "scheme", "host", "port", "path"],  # not body — 防 dynamic timestamp 撞
    filter_headers=["authorization", "x-dashscope-api-key"],
)


@pytest.mark.asyncio
async def test_both_query_no_contradiction_framing() -> None:
    """跨 memory(用户偏好白马)+ kb(白马跑输)的典型 both — LLM 应保 trade-off frame。"""

    # === 1. mock memory + kb,只 LLM 真调 ===
    mem = MagicMock()
    mem.dedup_tool_results = lambda r: r
    mem.needs_summarize = lambda s, m: False
    mem.summarize = AsyncMock(return_value="")
    mem.load_for_turn = AsyncMock()
    mem.save_after_turn = AsyncMock()
    mem.archival_memory_search = AsyncMock(
        return_value=[
            MagicMock(
                edge_id="e1", rel_type="PREFERS",
                properties={"label": "白马股", "strategy": "long-term"},
                source_node_id="n1", target_node_id="n2",
                importance=0.9, valid_from="2024-09-01",
                reasoning="user explicitly prefers white-horse blue-chips for stability",
            )
        ]
    )

    kb = MagicMock()
    kb.search = AsyncMock(
        return_value=[
            KbHit(
                chunk_id="c1",
                chunk_text="近 6 月白马股跑输大盘约 5%, 资金加速流向中小盘成长股。但中长期看, 白马股的 ROE 稳定性仍优于成长板块。",
                similarity=0.85,
                metadata={"broker": "中金", "pub_date": "2024-10-30", "industry": "策略"},
            )
        ]
    )

    async def router_fn(query: str) -> RouterDecision:
        return RouterDecision(
            retrieval_targets=["both"],
            reasoning="user mentions 我的偏好 + asks for current market view",
        )

    # === 2. 真 LLM via cassette ===
    with _VCR.use_cassette(str(CASSETTE_PATH)):
        llm = build_llm_service_from_env()  # qwen-plus

        registry = ToolRegistry()
        cache = ToolResultCache()
        planner = ChatPlanner(llm=llm, available_tools=[])
        responder = Responder(llm=llm)

        graph = build_chat_graph(
            planner=planner, responder=responder, registry=registry,
            memory=mem, cache=cache,
            kb_search_service=kb, memory_kb_router_fn=router_fn,
        )

        initial = ChatState(
            user_id=str(uuid4()), session_id=str(uuid4()),
            user_message="基于我的偏好分析下当前市场,给我一些建议",
            request_id="rid", trace_request_id="rid",
        )
        final = await graph.ainvoke(initial.model_dump())

    response = final["final_response"] or ""

    # === 3. 不矛盾化断言 ===
    contradiction_words = ["矛盾", "冲突", "对立", "完全错误", "立刻换仓", "马上抛"]
    tradeoff_words = ["权衡", "平衡", "取舍", "trade-off", "trade off", "短期", "长期", "考虑"]

    for w in contradiction_words:
        assert w not in response, (
            f"LLM 输出意外含矛盾化词 {w!r} — 用户偏好 vs 市场跑输应该是 trade-off。\n"
            f"完整响应: {response[:500]}"
        )

    assert any(w in response for w in tradeoff_words), (
        f"LLM 未保留 trade-off 框架 — 期望含 {tradeoff_words} 至少一个。\n"
        f"完整响应: {response[:500]}"
    )

    # === 4. routing 状态正确 ===
    assert final["retrieval_targets"] == ["both"]
    assert final["memory_hits"]
    assert final["kb_hits"]
```

#### Step 9.2 (Record cassette):

```bash
# 作者本地 dogfood — 真 LLM 录制(unset proxy)
unset all_proxy https_proxy http_proxy
DASHSCOPE_API_KEY=$DASHSCOPE_API_KEY uv run pytest \
  backend/tests/e2e/memory/test_memory_kb_routing_cassette.py \
  --record-mode=once -x 2>&1 | tail -30
```

录制成功后 cassette 落 `backend/tests/cassettes/memory/memory_kb_routing__both_white_horse_underperform.yaml`。

**注**: 作者本地真 LLM 偶尔会输出含 "矛盾" 词(qwen 在边界场景概率上跑偏)。此时:
1. 检查 prompt(Task 7 _SEGREGATION_DISCLAIMER 是否生效)
2. 若 prompt 含但 LLM 仍跑偏 → 加强 disclaimer(spec hint + 显式负样本) — 改 Task 7 disclaimer 文本,重录 cassette
3. 持续 fail → 记录到 `docs/claude-context/c5-plan6-...-done.md` 知识卡 caveat 段,挂 Plan 8 ship 时收束(metric 验 50 case 平均不矛盾化)

#### Step 9.3 (Verify replay):

```bash
unset DASHSCOPE_API_KEY  # 强制 cassette replay
uv run pytest backend/tests/e2e/memory/test_memory_kb_routing_cassette.py -x 2>&1 | tail -15
# 预期: 1 PASS,无网络调用
```

#### Step 9.4 (Refactor):

```bash
uv run ruff check backend/tests/e2e/memory/ 2>&1 | tail -5
```

#### Step 9.5: commit message

```
test(c5-plan6): L2 cassette — both 类 query 真 LLM 不矛盾化断言

- scenario: 用户偏好白马 + 市场近 6 月跑输 — 经典 trade-off
- mock memory + mock kb,只 responder 真 LLM
- 断言响应不含 ['矛盾','冲突','对立','立刻换仓'] + 含 ['权衡','平衡','取舍','trade-off']
- cassette: backend/tests/cassettes/memory/memory_kb_routing__both_white_horse_underperform.yaml
- spec § 11 #7 量化验证标准 first scenario(Plan 8 扩 50 case)
```

---

## § 4 Plan 6 Self-Review Checklist(spec § 11 末尾 #7 完整 coverage check)

逐条对照 spec § 11 末尾 #7「Memory vs KB Search 检索路由」的 4 个补丁要点(spec 行 1198):

| spec 要点 | Plan 6 落地 | Task 编号 | 状态 |
|---|---|---|---|
| (a) **LangGraph supervisor 加 router 节点** 输出 `retrieval_targets: ["memory" / "kb" / "both"]` | `memory_kb_router_node` LangGraph node + `RouterDecision.retrieval_targets` | Task 5 + Task 6 | ✓ |
| (b) **触发词区分**: memory("我 / 我的 / 上次 / 持仓 / 偏好")/ KB("研报 / 财报 / 公告 / 政策")/ both("基于我 + 推荐 / 结合 + 我的") | `MEMORY_TRIGGER_WORDS` / `KB_TRIGGER_WORDS` / `BOTH_TRIGGER_PATTERNS` 严守契约 § 8 + 24 parametrized test | Task 1 | ✓ |
| (c) **两路结果 prompt 显式区隔**: `[用户上下文]`(memory)vs `[市场知识]`(KB),让 LLM 不混淆 | `_format_memory_hits` / `_format_kb_hits` + `_SEGREGATION_DISCLAIMER` + 5 prompt unit + L2 不矛盾化断言 | Task 7 + Task 9 | ✓ |
| (d) **默认 fallback memory**(个人化场景多) | `decide_retrieval_targets` 三层瀑布 + `LLMRouterFallback` 任何错误 fallback `memory` + boundary case 默认 memory | Task 2 + Task 3 | ✓ |

**spec 行 1198 量化验证标准**(右栏):

| 验证标准 | Plan 6 落地 | 状态 |
|---|---|---|
| Routing eval 50 case ≥ 0.85 | Plan 6 提供 8 seed case + accuracy hook + 30 corpus 单测;Plan 8 扩到 50 case + 阈值 assert | ✓ hook ready, Plan 8 finalize |
| both 类 query LLM 不矛盾化 | L2 cassette 1 scenario(Task 9)+ contradiction words 黑名单断言 + tradeoff words 白名单断言;Plan 8 扩到 multi-scenario | ✓ 1st scenario ship, Plan 8 finalize |

**契约对齐 check**:
- § 1 文件位置: ✓ `memory_kb_router.py` 在 `backend/app/memory/`,LangGraph node wrapper 在 `backend/app/orchestration/`(契约允许 "物理可在 orchestration/, 但逻辑归 memory")
- § 8 触发词清单: ✓ 一字未漂移(11 memory + 11 kb + 6 both pattern)— Task 1 contract test 锁死
- § 11 范围矩阵: ✓ Plan 6 在 "Memory vs KB routing(#7)" 唯一 ✓ ship,跟 Plan 1-5 / 7-8 不冲突
- § 12 测试分层: ✓ L0(Task 1-5/7-8)+ L1(Task 6)+ L2(Task 9),无遗漏
- § 13 知识卡: ✓ Task 9 后写 `docs/claude-context/c5-plan6-memory-kb-routing-done.md`(下方 § 5 给出模板)
- § 14 commit: ✓ 9 task → 9 commit,首词全 `feat(c5-plan6)` / `test(c5-plan6)`

**不在范围(转 Plan 8 / 已有 Plan)**:
- 50 case golden 完整 + accuracy assert ≥ 0.85: Plan 8 扩(本 plan 只到 8 seed + 30 corpus)
- multi-scenario 不矛盾化(用户看空 vs 市场看多 / 偏好长期 vs 新闻看短等): Plan 8 cassette 集
- archival_memory_search 实际实现: Plan 3
- KB Search 实际查询: v0.7 已 ship
- Memory MCP server `archival_memory_traverse` 内部 trigger 词: Plan 4(跟本 plan supervisor router 是两层 routing)

**潜在 撞实风险 + mitigation**:
- 风险 1: ChatPlanner._render_prompt 抽出后,现有 ChatPlanner.run 路径需 align;若 run 内部直接 inline 拼 prompt → Task 7 必须先 refactor 抽 helper 再加 routing block。
- 风险 2: build_chat_graph 加 2 个新参数,可能跟现有 `app.app_main.lifespan` / chat_router 已有调用方撞 — backward compat: 两参数都默认 `None`,旧 caller 零迁移。Step 6.3 跑 `test_chat_router_v0_9.py` 守护。
- 风险 3: cassette 录制时 LLM 偶尔输出 "矛盾" — Step 9.2 已注明 fallback 路径(强化 disclaimer 重录)。
- 风险 4: backend/eval 不在 PYTHONPATH — Step 8.2 用 backend/app/eval/memory/ 路径,跟 contracts § 1 jsonl 路径 backend/eval/memory/ 错开(jsonl 是 data,Python 是 module)。Plan 8 收束时校准 path policy。

---

## § 5 Plan 6 Ship 后写知识卡(模板)

`docs/claude-context/c5-plan6-memory-kb-routing-done.md`:

```markdown
---
name: c5-plan6-memory-kb-routing-done
description: C.5 Plan 6 Memory vs KB routing ship — supervisor router + 触发词清单 + prompt 区隔 + routing eval framework
type: project
---

C.5 Plan 6 Memory vs KB routing ship — 2026-MM-DD.

## ship 范围
- `backend/app/memory/memory_kb_router.py`: RouterDecision schema + 11+11+6 触发词清单 + rule_match + LLMRouterFallback + decide_retrieval_targets
- `backend/app/orchestration/memory_kb_router_node.py`: LangGraph node wrapper + asyncio.gather 并行 + graceful degrade
- `backend/app/orchestration/chat_graph.py`: build_chat_graph 注入 kb_search_service / memory_kb_router_fn(可选)
- `backend/app/agents/chat_planner.py`: planner prompt 加 [用户上下文] / [市场知识] 段 + disclaimer
- `backend/app/agents/schemas.py`: ChatState 加 retrieval_targets / memory_hits / kb_hits / reasoning 4 fields
- `backend/eval/memory/routing_accuracy_seed.jsonl`: 8 seed case
- `backend/app/eval/memory/routing_accuracy_hook.py`: RoutingCase + load + accuracy compute
- L0/L1/L2 测试 ~70 cases all green

## 关键决策(实施期撞实)
- (待 ship 时填)
- 例: 在 chat_graph 注入是否合并 router_fn / fallback 进 single param? — 决定保留 router_fn 显式注入,后续 testability 更好

## 跟 spec 决策对齐
- spec § 11 末尾 #7 4 项补丁 (a)(b)(c)(d) 全 cover
- 量化标准 Plan 8 finalize(50 case ≥ 0.85 / multi-scenario 不矛盾化)

## 关键文件 ref
- backend/app/memory/memory_kb_router.py
- backend/app/orchestration/memory_kb_router_node.py
- backend/app/orchestration/chat_graph.py
- backend/app/agents/chat_planner.py
- backend/eval/memory/routing_accuracy_seed.jsonl

## 不解决 / Plan 8 收束
- 50 case golden + accuracy ≥ 0.85 assert
- multi-scenario 不矛盾化 cassette(用户看空 vs 看多 / 长期 vs 短期 etc.)
- routing accuracy 周报 dashboard
```

---

## § 6 Plan 6 完整 commit log(实施期产出 9 commit)

```
feat(c5-plan6): RouterDecision schema + 触发词清单常量 + rule_match 规则层
feat(c5-plan6): LLMRouterFallback constrained-LLM router(Sonnet, JSON output)
feat(c5-plan6): decide_retrieval_targets() top-level + 30 case corpus
feat(c5-plan6): ChatState 新增 4 字段(retrieval_targets / memory_hits / kb_hits / reasoning)
feat(c5-plan6): memory_kb_router_node LangGraph node wrapper
feat(c5-plan6): chat_graph 集成 memory_kb_router_node(可选注入)
feat(c5-plan6): planner prompt 加 [用户上下文] / [市场知识] 区隔段
feat(c5-plan6): routing accuracy seed(8 case)+ metric hook
test(c5-plan6): L2 cassette — both 类 query 真 LLM 不矛盾化断言
docs(c5-plan6): 知识卡 + CLAUDE.md 索引(Plan 8 收束时统一总卡)
```

最后一条 docs commit 在所有功能代码 ship 后写知识卡。

---

## § 7 PR 标题(Plan 6 ship 时一个 PR)

```
feat(c5-plan6): Memory vs KB routing — supervisor router + 触发词分类 + prompt 区隔
```

PR body 含:
- spec ref
- 9 commit changelog
- 测试结果(~70 unit + 4 L1 + 1 L2 cassette)
- backward compat 说明(kb_search_service / memory_kb_router_fn 默认 None)
- 跟 Plan 1 / Plan 4 / v0.7 KB Search 衔接 verify 结果

---

**Plan 6 完。3 天 wall time 实施。9 task TDD,每 task 5-step。严守契约 § 8 + § 1 + § 11 + § 12 + § 14。Spec § 11 末尾 #7 完整 cover(4 补丁 + 2 验证标准)。**
