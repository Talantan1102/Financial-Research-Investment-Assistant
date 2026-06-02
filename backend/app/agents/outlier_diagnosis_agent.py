"""v1.x A5a: OutlierDiagnosisAgent.

severe cross-check divergence (CV > 30%) 时由 Analyst sub-step (Task 15) 触发。
输入 4 模型数字 + 各 model 的关键假设 + 公司基本面 narrative,
输出 OutlierDiagnosis (哪个 lens 最偏离 / 假设错在哪 / 信心 / 推荐动作 / 客户视角 narrative)。

设计原则(spec § 7.4):
- 仅在 severe 时调用(consistent / moderate 时 caller 不调)
- 失败 → return None (不 retry,避免 loop)
- schema-constrained LLM call (Pydantic-strict via LLMService.chat schema=OutlierDiagnosis)
- sync API (沿用项目 critic_subagents / escalation_extractor 范式)

spec ref: 2026-05-16-v1.x-multi-valuation-cross-check-design.md § 7
"""

from __future__ import annotations

import json
import logging

from app.agents.investment_dd_schema import OutlierDiagnosis
from app.services.llm_service import LLMService

__all__ = ["OutlierDiagnosisAgent"]

logger = logging.getLogger(__name__)


_PROMPT_TEMPLATE = """你是资深尽调研究员,专门诊断多模型估值不一致(cross-check divergence)的成因。

公司:{company_narrative}

各 lens 计算结果:
{valuations_block}

各模型关键假设:
{assumptions_block}

你的任务:
1. 找出最偏离 consensus 的 lens(outlier_model: pe / pb / ev_ebitda / dcf)
2. 诊断 outlier 的关键假设错在哪(likely_cause, ≤300 字符)
3. 评估你的诊断有多大把握(confidence: high / medium / low)
4. 推荐处理动作(recommended_action):
   - trust_consensus: 信另外几个 lens,outlier 应忽略
   - flag_uncertainty: 报告里 flag 给用户决定
   - recompute_assumption: 调整假设重算(本期不实施,留 v1.x++)
5. 写给客户的 narrative(≤500 字符):用大白话讲清打架原因 + 建议

输出 OutlierDiagnosis JSON。"""


class OutlierDiagnosisAgent:
    """LLM-based outlier diagnostician for severe valuation cross-check divergence."""

    def __init__(self, *, llm: LLMService) -> None:
        self._llm = llm

    def diagnose(
        self,
        valuations: dict[str, float],
        assumptions: dict[str, dict[str, float]],
        company_narrative: str,
        request_id: str | None = None,  # C26: span linkage to the originating request
    ) -> OutlierDiagnosis | None:
        """severe divergence diagnostic. 返 None on any LLM failure (不 retry)."""
        prompt = _PROMPT_TEMPLATE.format(
            company_narrative=company_narrative,
            valuations_block=json.dumps(valuations, ensure_ascii=False, indent=2),
            assumptions_block=json.dumps(assumptions, ensure_ascii=False, indent=2),
        )

        try:
            response = self._llm.chat(
                prompt=prompt,
                schema=OutlierDiagnosis,
                tier="balanced",
                request_id=request_id,
            )
            # LLMService 自动 parse Pydantic schema 进 .parsed
            parsed = response.parsed
            if isinstance(parsed, OutlierDiagnosis):
                return parsed
            # Fallback: parse content 字符串
            if response.content:
                try:
                    return OutlierDiagnosis.model_validate_json(response.content)
                except Exception as e:  # noqa: BLE001
                    logger.warning("OutlierDiagnosisAgent: content parse fail: %s", e)
                    return None
            logger.warning("OutlierDiagnosisAgent: unexpected response (no parsed, no content)")
            return None
        except Exception as e:  # noqa: BLE001
            logger.warning("OutlierDiagnosisAgent LLM call failed: %s", e)
            return None
