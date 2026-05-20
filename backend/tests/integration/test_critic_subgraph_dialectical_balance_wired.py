"""L1 — verify DialecticalBalanceScorer is actually wired into production critic flow.

防 A5a Task 13 (ValuationConsistencyScorer dead-code) + c5-injection-classifier-wired
同型 bug regression。

Scorer class + 5 unit test ship 后必须保证生产 wire 完整:
- app/router/research.py:scorers list 注册第 8 维
- app/orchestration/critic_subgraph.py Send fan-out 加 dialectical_balance node
- 后果若漏: critic_report.dimensions 生产永远没第 8 维, _writer_retry_router 的
  get_score("dialectical_balance") 永返 None → retry 新 trigger 全死路。
"""

from __future__ import annotations

from typing import Any

import pytest
from app.agents.base import Agent
from app.agents.critic import Critic
from app.agents.critic_subagents.conciseness import ConcisenessScorer
from app.agents.critic_subagents.coverage import CoverageScorer
from app.agents.critic_subagents.dialectical_balance import DialecticalBalanceScorer
from app.agents.critic_subagents.factuality import FactualityScorer
from app.agents.critic_subagents.input_context_scorer import (
    InputContextAppropriatenessScorer,
)
from app.agents.critic_subagents.insight import InsightScorer
from app.agents.critic_subagents.structure import StructureScorer
from app.agents.critic_subagents.valuation_consistency import ValuationConsistencyScorer
from app.agents.debate_schemas import AdvocateOutput, DebateTrace
from app.agents.schemas import CriticReport
from app.orchestration.critic_subgraph import build_critic_subgraph
from app.services.llm_mock_client import MockLLMClient
from app.services.llm_service import LLMService


def test_dialectical_balance_scorer_in_production_scorers_list() -> None:
    """DialecticalBalanceScorer 必须在 production scorers list (router/research.py)."""
    import app.router.research as research_module

    with open(research_module.__file__) as f:
        source = f.read()
    assert "DialecticalBalanceScorer" in source, (
        "DialecticalBalanceScorer 必须在 production scorers list (router/research.py)"
    )


def test_critic_subgraph_dispatches_dialectical_balance() -> None:
    """critic_subgraph Send fan-out 必须包含 dialectical_balance node."""
    import app.orchestration.critic_subgraph as cs_module

    with open(cs_module.__file__) as f:
        source = f.read()
    assert "DialecticalBalanceScorer" in source or "dialectical_balance" in source, (
        "critic_subgraph 必须 fan out dialectical_balance scorer"
    )


def _build_production_critic(llm: LLMService) -> Critic:
    """Mirror production scorers list (app/router/research.py:scorers).

    If this drifts from research.py the test fails — that's the point.
    """
    scorers: list[Agent] = [
        FactualityScorer(llm=llm),
        CoverageScorer(llm=llm),
        InsightScorer(llm=llm),
        StructureScorer(llm=llm),
        ConcisenessScorer(llm=llm),
        InputContextAppropriatenessScorer(llm=llm),
        ValuationConsistencyScorer(llm=llm),  # 第 7 scorer
        DialecticalBalanceScorer(llm=llm),  # 第 8 scorer — wire guard
    ]
    return Critic(llm=llm, scorers=scorers)


def _mk_advocate(args: list[str]) -> AdvocateOutput:
    return AdvocateOutput(arguments=args, strongest_argument=args[0], confidence="high")


@pytest.mark.asyncio
async def test_dialectical_balance_dim_present_when_both_sides_mentioned(
    mock_llm_client: MockLLMClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Production critic_subgraph yields critic_report with dialectical_balance dim.

    Scenario: bull/bear 双方各 >=2 条 argument 出现在 narrative → 9.0.
    """
    monkeypatch.setenv("LLM_MODE", "mock")
    svc = LLMService(client=mock_llm_client)
    critic = _build_production_critic(svc)
    sub_app = build_critic_subgraph(critic)

    bull = _mk_advocate(["品牌护城河 30 年", "ROE 30% 稳定", "提价权强"])
    bear = _mk_advocate(["PE 接近历史高位", "反腐影响", "年轻人不喝白酒"])
    trace = DebateTrace(
        bull_v1=bull,
        bear_v1=bear,
        bull_v2=bull,
        bear_v2=bear,
        total_cost_cny=0.0,
        total_latency_ms=0,
        rounds_completed=2,
    )
    report_md = (
        "# § 6\n看多: 品牌护城河 30 年 + ROE 30% 稳定。"
        " 看空: PE 接近历史高位 + 反腐影响。 推荐: 持有。"
    )
    initial: dict[str, Any] = {
        "user_id": "u",
        "session_id": "s",
        "user_message": "m",
        "request_id": "req-db-wire-1",
        "report_markdown": report_md,
        "insights": [],
        "plan": None,
        "tool_results": [],
        "collected_scores": [],
        "target_ts_code": "600519.SH",
        "client_total_aum": 10_000_000.0,
        "client_existing_position": None,
        "investment_objective": "balanced",
        "investment_horizon": "medium_term",
        "risk_tolerance": "moderate",
        "valuation_analysis": None,
        "debate_trace": trace,
    }
    final = await sub_app.ainvoke(initial)
    report = final["critic_report"]
    assert isinstance(report, CriticReport)

    db_score = report.get_score("dialectical_balance")
    assert db_score is not None, (
        "dialectical_balance dimension missing from critic_report. "
        "Likely cause: DialecticalBalanceScorer not registered in "
        "router/research.py:scorers OR critic_subgraph._planner_router."
    )
    assert db_score == 9.0, f"双向 >=2 → 9.0, got {db_score}"

    # All 8 dims now present
    assert len(report.dimensions) == 8


@pytest.mark.asyncio
async def test_dialectical_balance_retry_trigger_wire(
    mock_llm_client: MockLLMClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """one-sided narrative + 双方 args 都 >=2 → 3.0 < 7.0 retry threshold.

    本 test 验证 retry edge 输入端真接通:critic_report.get_score("dialectical_balance")
    生产 wire 后真返低分,_writer_retry_router 拿到信号触发 retry。
    """
    monkeypatch.setenv("LLM_MODE", "mock")
    svc = LLMService(client=mock_llm_client)
    critic = _build_production_critic(svc)
    sub_app = build_critic_subgraph(critic)

    bull = _mk_advocate(["品牌护城河 30 年", "ROE 30% 稳定", "提价权强"])
    bear = _mk_advocate(["PE 接近历史高位", "反腐影响", "年轻人不喝白酒"])
    trace = DebateTrace(
        bull_v1=bull,
        bear_v1=bear,
        bull_v2=bull,
        bear_v2=bear,
        total_cost_cny=0.0,
        total_latency_ms=0,
        rounds_completed=2,
    )
    # narrative 只提 bull 的 3 条,完全没提 bear → 3.0 (掩盖看空)
    report_md = "# § 6\n看多论据: 品牌护城河 30 年 + ROE 30% 稳定 + 提价权强。 推荐: 买入。"
    initial: dict[str, Any] = {
        "user_id": "u",
        "session_id": "s",
        "user_message": "m",
        "request_id": "req-db-wire-2",
        "report_markdown": report_md,
        "insights": [],
        "plan": None,
        "tool_results": [],
        "collected_scores": [],
        "target_ts_code": "600519.SH",
        "client_total_aum": 10_000_000.0,
        "client_existing_position": None,
        "investment_objective": "balanced",
        "investment_horizon": "medium_term",
        "risk_tolerance": "moderate",
        "valuation_analysis": None,
        "debate_trace": trace,
    }
    final = await sub_app.ainvoke(initial)
    report = final["critic_report"]

    db_score = report.get_score("dialectical_balance")
    assert db_score is not None, "dialectical_balance dimension wire broken"
    assert db_score < 7.0, f"one-sided narrative → score < 7.0 才能触发 retry, got {db_score}."
    assert db_score == 3.0
