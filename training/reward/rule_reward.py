"""
Rule-based reward calculation for verifiable tasks.

Computes accuracy, efficiency, and format rewards based on seed tags.
"""

import re
from typing import Dict, List, Any, Optional

from .ground_truth_cache import GroundTruthCache


class RuleBasedReward:
    """基于规则的奖励计算（用于可验证任务）"""

    def __init__(self, tushare_client: Optional[Any] = None):
        self.tushare = tushare_client
        self._ground_truth_cache = GroundTruthCache()

    def calculate(self, trajectory: Dict[str, Any], seed_tags: Dict[str, Any]) -> float:
        """
        计算规则奖励

        Args:
            trajectory: 模型生成的轨迹字典
            seed_tags: 种子标签

        Returns:
            总奖励 (0-1)
        """
        weights = seed_tags.get(
            "reward_weights",
            {"accuracy": 0.6, "efficiency": 0.3, "format": 0.1},
        )

        reward = 0.0

        # 1. 准确性奖励
        if seed_tags.get("verifiable"):
            accuracy_reward = self._calculate_accuracy(trajectory, seed_tags)
            reward += weights.get("accuracy", 0.6) * accuracy_reward

        # 2. 效率奖励
        efficiency_reward = self._calculate_efficiency(trajectory, seed_tags)
        reward += weights.get("efficiency", 0.3) * efficiency_reward

        # 3. 格式奖励
        format_reward = self._calculate_format(trajectory)
        reward += weights.get("format", 0.1) * format_reward

        return max(0.0, min(1.0, reward))

    def _calculate_accuracy(self, trajectory: Dict[str, Any], seed_tags: Dict[str, Any]) -> float:
        """计算准确性奖励"""
        verifiable_fields = seed_tags.get("verifiable_fields", [])
        if not verifiable_fields:
            return 1.0

        total_weight = sum(f.get("weight", 1.0) for f in verifiable_fields)
        if total_weight == 0:
            return 1.0

        accuracy_score = 0.0
        for field_config in verifiable_fields:
            field_name = field_config["field"]
            weight = field_config.get("weight", 1.0)
            tolerance = field_config.get("tolerance", 0.01)

            predicted = self._extract_field_value(trajectory, field_name)
            ground_truth = self._get_ground_truth(seed_tags, field_name)

            if predicted is not None and ground_truth is not None:
                try:
                    p_val = float(predicted)
                    g_val = float(ground_truth)
                    if abs(p_val - g_val) <= tolerance:
                        accuracy_score += weight / total_weight
                except (ValueError, TypeError):
                    if str(predicted).strip() == str(ground_truth).strip():
                        accuracy_score += weight / total_weight

        return accuracy_score

    def _calculate_efficiency(self, trajectory: Dict[str, Any], seed_tags: Dict[str, Any]) -> float:
        """计算效率奖励"""
        tools_used = trajectory.get("tools_used", [])
        turns = trajectory.get("turns", [])
        tool_count = len(tools_used)
        min_tools = seed_tags.get("min_tools", 1)
        max_tools = seed_tags.get("max_tools", 10)
        expected_turns = seed_tags.get("expected_turns", 3)
        actual_turns = len(turns)

        # 工具数量评分
        if min_tools <= tool_count <= max_tools:
            tool_score = 1.0
        elif tool_count < min_tools:
            tool_score = 0.5 + 0.5 * (tool_count / min_tools) if min_tools > 0 else 0.0
        else:
            tool_score = max(0.0, 1.0 - (tool_count - max_tools) * 0.05)

        # 轮次评分
        if actual_turns <= expected_turns:
            turn_score = 1.0
        else:
            turn_score = max(0.5, 1.0 - (actual_turns - expected_turns) * 0.1)

        return (tool_score + turn_score) / 2.0

    def _calculate_format(self, trajectory: Dict[str, Any]) -> float:
        """计算格式奖励"""
        score = 0.0
        answer = trajectory.get("final_answer", "")
        turns = trajectory.get("turns", [])

        # 检查是否有结构化的推理过程
        if turns:
            has_reasoning = any(
                turn.get("reasoning", "").strip() for turn in turns
            )
            if has_reasoning:
                score += 0.5
        elif "<reasoning>" in answer or "分析" in answer or "步骤" in answer:
            score += 0.5

        # 检查是否有明确结论
        if "<answer>" in answer or "结论" in answer or "总结" in answer or "答案是" in answer:
            score += 0.5
        elif answer and len(answer) > 10:
            score += 0.3  # 有内容但无明显结论标记

        return score

    def _get_ground_truth(self, seed_tags: Dict[str, Any], field_name: str) -> Any:
        """获取 ground truth（带缓存）"""
        stock_code = seed_tags.get("stock_code", "")
        cache_key = seed_tags.get("cache_key", f"{stock_code}_{field_name}")

        cached = self._ground_truth_cache.get(stock_code or cache_key, field_name)
        if cached is not None:
            return cached

        # TODO: 从 API 获取 ground truth
        # 当前 MVP 阶段，优先依赖 seed_tags 中直接嵌入的 ground_truth
        # 如果 seed_tags 包含 ground_truth 字段则直接返回
        ground_truth_map = seed_tags.get("ground_truth", {})
        if field_name in ground_truth_map:
            value = ground_truth_map[field_name]
            self._ground_truth_cache.set(stock_code or cache_key, field_name, value)
            return value

        return None

    def _extract_field_value(self, trajectory: Dict[str, Any], field_name: str) -> Any:
        """从轨迹中提取字段值"""
        # 1. 从最终回答中提取数值
        answer = trajectory.get("final_answer", "")

        # 尝试匹配 field_name + value 的模式
        patterns = [
            rf"{re.escape(field_name)}[:：\s]*([0-9]+\.?[0-9]*)",
            rf"{re.escape(field_name)}[:：\s]*(.+?)(?:\\n|$)",
        ]
        for pattern in patterns:
            match = re.search(pattern, answer, re.IGNORECASE)
            if match:
                return match.group(1).strip()

        # 2. 从 tool results 中递归搜索
        for turn in trajectory.get("turns", []):
            tool_result = turn.get("tool_result")
            if tool_result is None:
                continue
            value = self._extract_from_nested(tool_result, field_name)
            if value is not None:
                return value

        return None

    def _extract_from_nested(self, data: Any, field_name: str) -> Any:
        """递归从嵌套数据中按 field_name 提取值"""
        if isinstance(data, dict):
            for key, value in data.items():
                if key.lower() == field_name.lower():
                    return value
            for value in data.values():
                found = self._extract_from_nested(value, field_name)
                if found is not None:
                    return found
        elif isinstance(data, list):
            for item in data:
                found = self._extract_from_nested(item, field_name)
                if found is not None:
                    return found
        return None
