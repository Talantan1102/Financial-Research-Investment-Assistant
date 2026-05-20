"""L1 — Guard test: ValuationConsistencyScorer is actually wired into production critic flow.

防 dead-code regression(同型 c5 injection_classifier 死代码教训 — 见
docs/claude-context/c5-injection-classifier-wired.md)。

Scorer class + 10 unit test 早就 ship (commit e77a1cd) 但生产 wire 缺失:
- app/router/research.py:scorers list 漏注册第 7 维
- app/orchestration/critic_subgraph.py Send fan-out 没加 valuation_consistency
- 后果: critic_report.dimensions 生产永远没第 7 维, _writer_retry_router 的
  get_score("valuation_consistency") 永返 None → retry 新 trigger 全死路。

本 test 通过端到端跑 critic_subgraph (production build path) 验证:
  1. valuation_consistency 维度真出现在 critic_report.dimensions
  2. valuation_analysis 注入到 _CriticSubState 后能传到 scorer.step
  3. scorer 真在 _planner_router fan-out 名单里
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
from app.agents.investment_dd_schema import (
    OutlierDiagnosis,
    ValuationAnalysis,
    ValuationModel,
)
from app.agents.schemas import CriticReport
from app.orchestration.critic_subgraph import build_critic_subgraph
from app.services.llm_mock_client import MockLLMClient
from app.services.llm_service import LLMService


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
        ValuationConsistencyScorer(llm=llm),  # 第 7 scorer — wire guard
        DialecticalBalanceScorer(llm=llm),  # 第 8 scorer (v1.x A5b)
    ]
    return Critic(llm=llm, scorers=scorers)


@pytest.mark.asyncio
async def test_valuation_consistency_dim_present_when_consistent(
    mock_llm_client: MockLLMClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Production critic_subgraph yields critic_report with valuation_consistency dim.

    Scenario: consistent + narrative 提及"一致" → scorer returns 9.0.
    """
    monkeypatch.setenv("LLM_MODE", "mock")
    svc = LLMService(client=mock_llm_client)
    critic = _build_production_critic(svc)
    sub_app = build_critic_subgraph(critic)

    va = ValuationAnalysis(
        narrative="PE 与 DCF 估值一致,均落于 1500-1800 元区间。",
        active_models=[ValuationModel.PE, ValuationModel.DCF],
        valuation_consistency="consistent",
    )

    initial: dict[str, Any] = {
        "user_id": "u",
        "session_id": "s",
        "user_message": "m",
        "request_id": "req-vc-wire-1",
        "report_markdown": "# 估值\nPE 与 DCF 估值一致,均落于 1500-1800 元区间。",
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
        "valuation_analysis": va,
    }
    final = await sub_app.ainvoke(initial)
    report = final["critic_report"]
    assert isinstance(report, CriticReport)

    # Critical wire guard — dimension MUST appear in production critic_report.
    vc_score = report.get_score("valuation_consistency")
    assert vc_score is not None, (
        "valuation_consistency dimension missing from critic_report. "
        "Likely cause: ValuationConsistencyScorer not registered in "
        "router/research.py:scorers OR critic_subgraph._planner_router."
    )
    assert vc_score == 9.0, f"consistent + narrative 提一致 → 9.0, got {vc_score}"

    # All 8 dims now present (v1.x A5b)
    assert len(report.dimensions) == 8


@pytest.mark.asyncio
async def test_valuation_consistency_dim_present_when_severe_with_diagnosis(
    mock_llm_client: MockLLMClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Production critic_subgraph routes diagnosis narrative to scorer correctly.

    Scenario: severe + diagnosis.narrative in report → 9.0 (scorer 真读到 va.outlier_diagnosis).
    """
    monkeypatch.setenv("LLM_MODE", "mock")
    svc = LLMService(client=mock_llm_client)
    critic = _build_production_critic(svc)
    sub_app = build_critic_subgraph(critic)

    diagnosis = OutlierDiagnosis(
        outlier_model=ValuationModel.DCF,
        likely_cause="永续增长率偏高",
        confidence="high",
        recommended_action="trust_consensus",
        narrative="DCF 给出 5000 偏离 PE 1500,主因永续增长率假设过乐观。",
    )
    va = ValuationAnalysis(
        narrative="4 lens cross-check 严重不一致。",
        active_models=[ValuationModel.PE, ValuationModel.PB, ValuationModel.DCF],
        valuation_consistency="severe",
        outlier_diagnosis=diagnosis,
    )

    report_md = (
        "# 估值\n4 lens cross-check 严重不一致:PE 1500, DCF 5000。"
        "DCF 给出 5000 偏离 PE 1500,主因永续增长率假设过乐观。"
    )
    initial: dict[str, Any] = {
        "user_id": "u",
        "session_id": "s",
        "user_message": "m",
        "request_id": "req-vc-wire-2",
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
        "valuation_analysis": va,
    }
    final = await sub_app.ainvoke(initial)
    report = final["critic_report"]

    vc_score = report.get_score("valuation_consistency")
    assert vc_score is not None, "valuation_consistency dimension wire broken"
    assert vc_score == 9.0, (
        f"severe + diagnosis 引用 → 9.0 (scorer 真读到 va.outlier_diagnosis), got {vc_score}"
    )


@pytest.mark.asyncio
async def test_valuation_consistency_retry_trigger_wire(
    mock_llm_client: MockLLMClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """severe + diagnosis 存在但 narrative 未引用 → 3.0 < 7.0 retry threshold.

    本 test 验证 retry edge 的输入端真接通:critic_report.get_score("valuation_consistency")
    在生产 wire 后真返低分,_writer_retry_router 能拿到信号触发 retry。
    """
    monkeypatch.setenv("LLM_MODE", "mock")
    svc = LLMService(client=mock_llm_client)
    critic = _build_production_critic(svc)
    sub_app = build_critic_subgraph(critic)

    diagnosis = OutlierDiagnosis(
        outlier_model=ValuationModel.DCF,
        likely_cause="永续增长率偏高",
        confidence="high",
        recommended_action="trust_consensus",
        narrative="DCF 给出 5000 偏离 PE 1500,主因永续增长率假设过乐观。",
    )
    va = ValuationAnalysis(
        narrative="4 lens cross-check 严重不一致。",
        active_models=[ValuationModel.PE, ValuationModel.DCF],
        valuation_consistency="severe",
        outlier_diagnosis=diagnosis,
    )

    initial: dict[str, Any] = {
        "user_id": "u",
        "session_id": "s",
        "user_message": "m",
        "request_id": "req-vc-wire-3",
        # narrative 故意未引用 diagnosis.narrative
        "report_markdown": "# 估值\n茅台估值 1500-1800 元区间,推荐持有。",
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
        "valuation_analysis": va,
    }
    final = await sub_app.ainvoke(initial)
    report = final["critic_report"]

    vc_score = report.get_score("valuation_consistency")
    assert vc_score is not None
    # < 7.0 触发 _writer_retry_router 第 7 维 trigger
    assert vc_score < 7.0, (
        f"severe + 掩盖 diagnosis → score < 7.0 才能触发 retry, got {vc_score}. "
        "若 score >= 7.0 则 retry edge 的 valuation_consistency trigger 形同虚设。"
    )
    assert vc_score == 3.0
