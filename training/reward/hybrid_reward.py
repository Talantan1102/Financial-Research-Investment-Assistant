"""
Hybrid reward mixing rule-based and LLM judge rewards.

For semi-open tasks where part of the answer is verifiable
and part requires quality assessment.
"""

import asyncio
from typing import Dict, Any, Optional

from .rule_reward import RuleBasedReward
from .llm_judge_reward import LLMJudgeReward


class HybridReward:
    """
    混合评估：可验证部分用规则，质量部分用 LLM

    适用于半开放式任务
    """

    def __init__(
        self,
        tushare_client: Optional[Any] = None,
        llm_model: str = "gpt-4.1-2025-04-14",
        llm_api_key: Optional[str] = None,
        llm_base_url: Optional[str] = None,
    ):
        self.rule_reward = RuleBasedReward(tushare_client)
        self.llm_reward = LLMJudgeReward(llm_model, llm_api_key, llm_base_url)

    def calculate(
        self,
        trajectory: Dict[str, Any],
        seed_tags: Dict[str, Any],
    ) -> float:
        """
        计算混合奖励（同步入口）

        权重分配：
        - 可验证部分：40-60%
        - 质量评估：40-60%
        """
        weights = seed_tags.get(
            "reward_weights",
            {"accuracy": 0.4, "quality": 0.3, "efficiency": 0.2, "format": 0.1},
        )

        reward = 0.0

        # 1. 准确性奖励（规则）
        if seed_tags.get("verifiable"):
            accuracy_reward = self.rule_reward._calculate_accuracy(trajectory, seed_tags)
            reward += weights.get("accuracy", 0.4) * accuracy_reward

        # 2. 质量奖励（LLM）- 在同步入口中暂跳过，由外部异步调用时计算
        # quality_reward 的计算交给 async_calculate
        # 同步入口给默认 0.5
        reward += weights.get("quality", 0.3) * 0.5

        # 3. 效率奖励（规则）
        efficiency_reward = self.rule_reward._calculate_efficiency(trajectory, seed_tags)
        reward += weights.get("efficiency", 0.2) * efficiency_reward

        # 4. 格式奖励（规则）
        format_reward = self.rule_reward._calculate_format(trajectory)
        reward += weights.get("format", 0.1) * format_reward

        return max(0.0, min(1.0, reward))

    async def async_calculate(
        self,
        trajectory: Dict[str, Any],
        seed_tags: Dict[str, Any],
    ) -> float:
        """完整的异步混合奖励计算，包含 LLM judge"""
        weights = seed_tags.get(
            "reward_weights",
            {"accuracy": 0.4, "quality": 0.3, "efficiency": 0.2, "format": 0.1},
        )

        reward = 0.0

        # 1. 准确性奖励（规则）
        if seed_tags.get("verifiable"):
            accuracy_reward = self.rule_reward._calculate_accuracy(trajectory, seed_tags)
            reward += weights.get("accuracy", 0.4) * accuracy_reward

        # 2. 质量奖励（LLM）
        if "evaluation_criteria" in seed_tags:
            quality_reward = await self.llm_reward.calculate(trajectory, seed_tags)
            reward += weights.get("quality", 0.3) * quality_reward

        # 3. 效率奖励（规则）
        efficiency_reward = self.rule_reward._calculate_efficiency(trajectory, seed_tags)
        reward += weights.get("efficiency", 0.2) * efficiency_reward

        # 4. 格式奖励（规则）
        format_reward = self.rule_reward._calculate_format(trajectory)
        reward += weights.get("format", 0.1) * format_reward

        return max(0.0, min(1.0, reward))
