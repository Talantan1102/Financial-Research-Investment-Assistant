from app.agents.critic_subagents._base_scorer import _BaseScorer


class FactualityScorer(_BaseScorer):
    name = "FactualityScorer"
    dimension = "factuality"
    state_field = "factuality_score"
    rubric = "10 = 所有数据点准确;9-7 = 多数准确;6-4 = 部分准确;3-1 = 多处错误;0 = 严重失实。"
