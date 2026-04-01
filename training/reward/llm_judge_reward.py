"""
LLM judge reward for open-ended tasks.

Uses an external LLM to score trajectory quality on evaluation criteria.
"""

import json
from typing import Dict, List, Any, Optional

import openai


class LLMJudgeReward:
    """大模型评判奖励（用于开放式任务）"""

    def __init__(
        self,
        model: str = "gpt-4.1-2025-04-14",
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
    ):
        self.model = model
        self.client = None
        if api_key and base_url:
            self.client = openai.AsyncOpenAI(api_key=api_key, base_url=base_url)

    async def calculate(
        self,
        trajectory: Dict[str, Any],
        seed_tags: Dict[str, Any],
    ) -> float:
        """
        计算 LLM 评判奖励

        Args:
            trajectory: 模型生成的轨迹字典
            seed_tags: 种子标签

        Returns:
            总奖励 (0-1)
        """
        criteria = seed_tags.get("evaluation_criteria", [])
        if not criteria:
            return 1.0

        if self.client is None:
            # Fallback: return neutral score when LLM client not configured
            return 0.5

        prompt = self._build_judge_prompt(trajectory, seed_tags)

        try:
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": "你是一个严格的评判专家，请客观评估回答质量。",
                    },
                    {"role": "user", "content": prompt},
                ],
                temperature=0.0,
                response_format={"type": "json_object"},
            )
            result = json.loads(response.choices[0].message.content)
        except Exception:
            return 0.5

        total_score = 0.0
        total_weight = 0.0

        for criterion in criteria:
            if isinstance(criterion, dict):
                dim_name = criterion["dimension"]
                weight = criterion.get("weight", 1.0 / len(criteria))
            else:
                dim_name = str(criterion)
                weight = 1.0 / len(criteria)

            scores_map = result.get("scores", {})
            score = scores_map.get(dim_name, scores_map.get(dim_name.replace(" ", ""), 5))
            total_score += (score / 10.0) * weight
            total_weight += weight

        return total_score / total_weight if total_weight > 0 else 0.5

    def _build_judge_prompt(
        self, trajectory: Dict[str, Any], seed_tags: Dict[str, Any]
    ) -> str:
        criteria = seed_tags.get("evaluation_criteria", [])
        criteria_text = "\n".join(
            [
                f"{i+1}. {c['dimension'] if isinstance(c, dict) else c}"
                for i, c in enumerate(criteria)
            ]
        )

        turns_text = ""
        for turn in trajectory.get("turns", []):
            reasoning = turn.get("reasoning", "").strip()
            tc = turn.get("tool_call")
            if reasoning:
                turns_text += f"\n【思考】{reasoning}\n"
            if tc:
                turns_text += (
                    f"【工具调用】{tc['tool_name']}: {json.dumps(tc['parameters'], ensure_ascii=False)}\n"
                )

        return f"""请评估以下金融分析回答的质量。

【用户问题】
{seed_tags.get('content', '')}

【模型思考与工具调用轨迹】
{turns_text}

【模型最终回答】
{trajectory.get('final_answer', '')}

【评估维度】
{criteria_text}

请对每个维度给出 0-10 的评分，并返回 JSON 格式：
{{
  "scores": {{
    "维度1": 8,
    "维度2": 7,
    ...
  }},
  "reasoning": "简要说明评分理由"
}}
"""

    async def pairwise_compare(
        self,
        trajectory_a: Dict[str, Any],
        trajectory_b: Dict[str, Any],
        seed_tags: Dict[str, Any],
    ) -> int:
        """
        成对比较两个轨迹

        Returns:
            1: A 更好
            0: 平局
            -1: B 更好
        """
        if self.client is None:
            return 0

        prompt = f"""请比较以下两个回答的质量。

【用户问题】
{seed_tags.get('content', '')}

【回答 A】
{trajectory_a.get('final_answer', '')}

【回答 B】
{trajectory_b.get('final_answer', '')}

【评估维度】
{json.dumps(seed_tags.get('evaluation_criteria', []), ensure_ascii=False)}

请判断哪个回答更好，返回 JSON：
{{
  "winner": "A" | "B" | "tie",
  "reasoning": "简要说明理由"
}}
"""

        try:
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": "你是一个严格的评判专家。",
                    },
                    {"role": "user", "content": prompt},
                ],
                temperature=0.0,
                response_format={"type": "json_object"},
            )
            result = json.loads(response.choices[0].message.content)
        except Exception:
            return 0

        winner = result.get("winner", "tie")
        if winner == "A":
            return 1
        elif winner == "B":
            return -1
        return 0
