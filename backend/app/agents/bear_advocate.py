"""v1.x A5b: BearAdvocate — 被 prompt 灌"30% 看空立场",列 3-5 条看空论据。

设计跟 BullAdvocate 镜像,区别只在 prompt 立场 + 引 dcf_bear / outlier_diagnosis:
- round 1: 优先引 DCF bear scenario + outlier_diagnosis(打架信号)
- round 2: 看 bull_v1 后产 v2 + rebut_targets
- schema-constrained LLMService.chat (Pydantic-strict via AdvocateOutput)
- 失败 → return None(不 retry,DebateOrchestrator catch)
- sync API(沿用项目 critic_subagents / escalation_extractor 范式)

spec ref: 2026-05-16-v1.x-bull-bear-debate-design.md § 4 / § 6
"""

from __future__ import annotations

import logging
from typing import Any

from app.agents.base import Agent
from app.agents.debate_schemas import AdvocateOutput, format_valuation_block  # C62: shared SSOT
from app.agents.schemas import ResearchState, StepResult
from app.services.llm_response import Tier

__all__ = ["BearAdvocate"]

logger = logging.getLogger(__name__)


_PROMPT_ROUND_1 = """你是看空投资者(30% 看空立场), 专门为「{target}」找最有力的看空论据。

公司基本面 / 用户问题: {user_message}
{valuation_block}
你的任务:
1. 列 3-5 条看空论据(arguments), 每条必须引用具体数字 / 事实(不能凭感觉)
2. 重点引用 DCF bear / outlier_diagnosis(若已提供) / 估值打架信号
3. 自评最强一条(strongest_argument, ≤ 300 字符)
4. confidence: high / medium / low(你对自己论据的自信)

round 1: 你不看对手论据, 独立产出。rebut_targets 留空。

输出 AdvocateOutput JSON。"""


_PROMPT_ROUND_2 = """你是看空投资者(30% 看空立场), 为「{target}」做 round 2 论证。

公司基本面 / 用户问题: {user_message}
{valuation_block}
看多方第 1 轮论据(bull_v1):
{bull_v1_arguments}

bull_v1 自评最强论据: {bull_v1_strongest}

你的任务(round 2):
1. 修订 / 加强你的看空论据(arguments, 3-5 条)
2. 标注你反驳了 bull 的哪些条(rebut_targets, 引用 bull 论据原文片段, ≤ 5 条)
3. 自评 strongest_argument(≤ 300 字符)
4. confidence: high / medium / low

输出 AdvocateOutput JSON。"""


class BearAdvocate(Agent):
    """Bear-side LLM agent. fast tier. v1.x A5b 防叙事 hallucination 第二面。"""

    name = "BearAdvocate"
    model_tier: Tier = "fast"

    def step(self, state: ResearchState) -> StepResult:  # type: ignore[override]
        """sync step — 用 BearAdvocate 跑 round 1。

        DebateOrchestrator 调 advocate_round_1 / advocate_round_2 直接;
        本 step() 主要是满足 Agent ABC 约束 + 直接跑 round 1。
        """
        result = self.advocate_round_1(state)
        state_update: dict[str, Any] = {"_bear_v1": result} if result is not None else {}
        return StepResult(
            state_update=state_update,
            span_metadata={"agent": self.name, "round": 1},
        )

    def advocate_round_1(self, state: ResearchState) -> AdvocateOutput | None:
        """Round 1: independent bearish advocacy (不看 bull_v1)."""
        prompt = _PROMPT_ROUND_1.format(
            target=state.target_ts_code or "未知标的",
            user_message=state.user_message,
            valuation_block=format_valuation_block(state, side="bear"),
        )
        return self._call_llm(prompt, request_id=state.request_id)

    def advocate_round_2(
        self, state: ResearchState, bull_v1: AdvocateOutput
    ) -> AdvocateOutput | None:
        """Round 2: 看 bull_v1 后产 v2 + rebut_targets.

        positional second arg (跟 BullAdvocate.advocate_round_2 镜像 signature,
        DebateOrchestrator 用 asyncio.to_thread positional 调用)。
        """
        bull_args = "\n".join(f"- {a}" for a in bull_v1.arguments)
        prompt = _PROMPT_ROUND_2.format(
            target=state.target_ts_code or "未知标的",
            user_message=state.user_message,
            valuation_block=format_valuation_block(state, side="bear"),
            bull_v1_arguments=bull_args,
            bull_v1_strongest=bull_v1.strongest_argument,
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
                    logger.warning("BearAdvocate content parse fail: %s", e)
                    return None
            logger.warning("BearAdvocate unexpected response (no parsed, no content)")
            return None
        except Exception as e:  # noqa: BLE001
            logger.warning("BearAdvocate LLM call failed: %s", e)
            return None
