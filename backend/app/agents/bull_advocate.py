"""v1.x A5b: BullAdvocate — 被 prompt 灌"30% 看多立场",列 3-5 条看多论据。

设计原则(spec § 4 / § 6):
- 走 fast tier(低复杂度 list-generation task)
- round 1 不看对方;round 2 看 bear_v1 后产 v2 + rebut_targets
- schema-constrained LLMService.chat (Pydantic-strict via AdvocateOutput)
- 失败 → return None(不 retry,DebateOrchestrator catch)
- sync API(沿用项目 critic_subagents / escalation_extractor / outlier_diagnosis 范式)

spec ref: 2026-05-16-v1.x-bull-bear-debate-design.md § 4 / § 6
"""

from __future__ import annotations

import logging
from typing import Any

from app.agents.base import Agent
from app.agents.debate_schemas import AdvocateOutput
from app.agents.schemas import ResearchState, StepResult
from app.services.llm_response import Tier

__all__ = ["BullAdvocate"]

logger = logging.getLogger(__name__)


def _format_valuation_block(state: ResearchState) -> str:
    """state.valuation_analysis 已有时,把估值数字注入 prompt;否则返 empty."""
    va = state.valuation_analysis
    if va is None:
        return ""
    lines: list[str] = []
    if va.pe_value is not None:
        lines.append(f"  - PE 理论价: {va.pe_value:,.2f}")
    if va.dcf_base is not None:
        lines.append(f"  - DCF base: {va.dcf_base:,.2f}")
    if va.dcf_bull is not None:
        lines.append(f"  - DCF bull: {va.dcf_bull:,.2f}")
    if va.dcf_bear is not None:
        lines.append(f"  - DCF bear: {va.dcf_bear:,.2f}")
    if va.outlier_diagnosis is not None:
        lines.append(f"  - outlier diagnosis: {va.outlier_diagnosis.narrative}")
    if not lines:
        return ""
    return "\n估值数据(A5a cross-check):\n" + "\n".join(lines) + "\n"


_PROMPT_ROUND_1 = """你是看多投资者(30% 看多立场), 专门为「{target}」找最有力的看多论据。

公司基本面 / 用户问题: {user_message}
{valuation_block}
你的任务:
1. 列 3-5 条看多论据(arguments), 每条必须引用具体数字 / 事实(不能凭感觉)
2. 重点引用 PE / DCF bull / 估值数据(若已提供)
3. 自评最强一条(strongest_argument, ≤ 300 字符)
4. confidence: high / medium / low(你对自己论据的自信)

round 1: 你不看对手论据, 独立产出。rebut_targets 留空。

输出 AdvocateOutput JSON。"""


_PROMPT_ROUND_2 = """你是看多投资者(30% 看多立场), 为「{target}」做 round 2 论证。

公司基本面 / 用户问题: {user_message}
{valuation_block}
看空方第 1 轮论据(bear_v1):
{bear_v1_arguments}

bear_v1 自评最强论据: {bear_v1_strongest}

你的任务(round 2):
1. 修订 / 加强你的看多论据(arguments, 3-5 条)
2. 标注你反驳了 bear 的哪些条(rebut_targets, 引用 bear 论据原文片段, ≤ 5 条)
3. 自评 strongest_argument(≤ 300 字符)
4. confidence: high / medium / low

输出 AdvocateOutput JSON。"""


class BullAdvocate(Agent):
    """Bull-side LLM agent. fast tier. v1.x A5b 防叙事 hallucination 第一面。"""

    name = "BullAdvocate"
    model_tier: Tier = "fast"

    def step(self, state: ResearchState) -> StepResult:  # type: ignore[override]
        """sync step — 用 BullAdvocate 跑 round 1。

        DebateOrchestrator 调 advocate_round_1 / advocate_round_2 直接;
        本 step() 主要是满足 Agent ABC 约束 + 直接跑 round 1。
        """
        result = self.advocate_round_1(state)
        state_update: dict[str, Any] = {"_bull_v1": result} if result is not None else {}
        return StepResult(
            state_update=state_update,
            span_metadata={"agent": self.name, "round": 1},
        )

    def advocate_round_1(self, state: ResearchState) -> AdvocateOutput | None:
        """Round 1: independent advocacy (不看 bear_v1)."""
        prompt = _PROMPT_ROUND_1.format(
            target=state.target_ts_code or "未知标的",
            user_message=state.user_message,
            valuation_block=_format_valuation_block(state),
        )
        return self._call_llm(prompt, request_id=state.request_id)

    def advocate_round_2(
        self, state: ResearchState, bear_v1: AdvocateOutput
    ) -> AdvocateOutput | None:
        """Round 2: 看 bear_v1 后产 v2 + rebut_targets.

        positional second arg (跟 BearAdvocate.advocate_round_2 镜像 signature,
        DebateOrchestrator 用 asyncio.to_thread positional 调用)。
        """
        bear_args = "\n".join(f"- {a}" for a in bear_v1.arguments)
        prompt = _PROMPT_ROUND_2.format(
            target=state.target_ts_code or "未知标的",
            user_message=state.user_message,
            valuation_block=_format_valuation_block(state),
            bear_v1_arguments=bear_args,
            bear_v1_strongest=bear_v1.strongest_argument,
        )
        return self._call_llm(prompt, request_id=state.request_id)

    def _call_llm(self, prompt: str, request_id: str) -> AdvocateOutput | None:
        try:
            response = self._llm.chat(
                prompt=prompt,
                tier=self.model_tier,
                schema=AdvocateOutput,
                request_id=request_id,
            )
            parsed = response.parsed
            if isinstance(parsed, AdvocateOutput):
                return parsed
            if response.content:
                try:
                    return AdvocateOutput.model_validate_json(response.content)
                except Exception as e:  # noqa: BLE001
                    logger.warning("BullAdvocate content parse fail: %s", e)
                    return None
            logger.warning("BullAdvocate unexpected response (no parsed, no content)")
            return None
        except Exception as e:  # noqa: BLE001
            logger.warning("BullAdvocate LLM call failed: %s", e)
            return None
