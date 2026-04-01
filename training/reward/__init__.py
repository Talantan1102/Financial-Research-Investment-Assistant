"""
AgentFlowReward - unified reward entry point for GRPO training.

This module implements the reward calculation for verltraining pipelines.
Usage:
    reward_fn = AgentFlowReward(config)
    rewards = reward_fn(prompts, responses, metadata)
"""

import asyncio
from typing import Dict, List, Any, Optional

import numpy as np

from .parser import ToolCallParser
from .trajectory_executor import TrajectoryExecutor
from .rule_reward import RuleBasedReward
from .llm_judge_reward import LLMJudgeReward
from .hybrid_reward import HybridReward


class AgentFlowReward:
    """
    Unified reward function for AgentFlow GRPO training.

    Interface compatible with verl `reward_fn(prompts, responses, metadata) -> np.ndarray`.
    """

    def __init__(
        self,
        sandbox_server_url: str = "http://127.0.0.1:18890",
        sandbox_config_path: Optional[str] = None,
        resource_types: Optional[List[str]] = None,
        resource_init_configs: Optional[Dict[str, Dict[str, Any]]] = None,
        llm_model: str = "gpt-4.1-2025-04-14",
        llm_api_key: Optional[str] = None,
        llm_base_url: Optional[str] = None,
        max_turns: int = 20,
    ):
        self.executor = TrajectoryExecutor(
            sandbox_server_url=sandbox_server_url,
            sandbox_config_path=sandbox_config_path,
            resource_types=resource_types,
            resource_init_configs=resource_init_configs,
            max_turns=max_turns,
        )
        self.rule_reward = RuleBasedReward()
        self.llm_reward = LLMJudgeReward(llm_model, llm_api_key, llm_base_url)
        self.hybrid_reward = HybridReward(
            llm_model=llm_model,
            llm_api_key=llm_api_key,
            llm_base_url=llm_base_url,
        )
        self.parser = ToolCallParser()

    def __call__(
        self,
        prompts: List[str],
        responses: List[str],
        metadata: List[Dict[str, Any]],
    ) -> np.ndarray:
        """
        Compute rewards for a batch of responses.

        Args:
            prompts: List of prompt strings (unused but kept for verl compatibility).
            responses: List of model-generated response strings.
            metadata: List of metadata dicts, each must contain `tags` key with seed tags.

        Returns:
            np.ndarray of shape (len(responses),) with reward values in [0, 1].
        """
        rewards = []
        for response, meta in zip(responses, metadata):
            reward = self._compute_single(response, meta)
            rewards.append(reward)
        return np.array(rewards, dtype=np.float32)

    def _compute_single(self, response: str, metadata: Dict[str, Any]) -> float:
        """Compute reward for a single response."""
        # 1. Replay trajectory through sandbox
        trajectory = self.executor.execute_sync(response, metadata)

        # If execution failed and no tool calls were parsed, we can still
        # give partial credit for format if there's a final answer.
        seed_tags = metadata.get("tags", {})
        verifiable = seed_tags.get("verifiable", False)
        verification_method = seed_tags.get("verification_method", "api")

        # 2. Route to appropriate reward calculator
        if verifiable and verification_method in ["api", "compute"]:
            return self.rule_reward.calculate(trajectory, seed_tags)
        elif verifiable and verification_method == "hybrid":
            # In batch CPU context we use synchronous fallback (LLM judge skipped)
            # For full async evaluation, use async_compute_batch below.
            return self.hybrid_reward.calculate(trajectory, seed_tags)
        else:
            # Open-ended: synchronous fallback returns 0.5 when no LLM client configured
            # For full async evaluation, use async_compute_batch below.
            loop = asyncio.new_event_loop()
            try:
                return loop.run_until_complete(
                    self.llm_reward.calculate(trajectory, seed_tags)
                )
            except Exception:
                return 0.5
            finally:
                loop.close()

    async def async_compute_batch(
        self,
        prompts: List[str],
        responses: List[str],
        metadata: List[Dict[str, Any]],
    ) -> np.ndarray:
        """
        Async batch computation with full LLM judge support.

        This is preferred when running in an async context (e.g., Ray actor).
        """
        tasks = [
            self._async_compute_single(response, meta)
            for response, meta in zip(responses, metadata)
        ]
        rewards = await asyncio.gather(*tasks)
        return np.array(rewards, dtype=np.float32)

    async def _async_compute_single(
        self, response: str, metadata: Dict[str, Any]
    ) -> float:
        """Async single reward computation."""
        trajectory = await self.executor.execute(response, metadata)
        seed_tags = metadata.get("tags", {})
        verifiable = seed_tags.get("verifiable", False)
        verification_method = seed_tags.get("verification_method", "api")

        if verifiable and verification_method in ["api", "compute"]:
            return self.rule_reward.calculate(trajectory, seed_tags)
        elif verifiable and verification_method == "hybrid":
            return await self.hybrid_reward.async_calculate(trajectory, seed_tags)
        else:
            return await self.llm_reward.calculate(trajectory, seed_tags)


__all__ = [
    "AgentFlowReward",
    "ToolCallParser",
    "TrajectoryExecutor",
    "RuleBasedReward",
    "LLMJudgeReward",
    "HybridReward",
]
