from app.agents.critic_subagents._base_scorer import _BaseScorer


class InsightScorer(_BaseScorer):
    name = "InsightScorer"
    dimension = "insight"
    state_field = "insight_score"
    rubric = (
        "10 = 深度分析,有非显然结论;9-7 = 有分析;6-4 = 表层分析;3-1 = 数据流水账;0 = 无任何分析。"
    )
