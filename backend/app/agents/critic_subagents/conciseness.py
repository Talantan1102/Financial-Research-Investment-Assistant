from app.agents.critic_subagents._base_scorer import _BaseScorer


class ConcisenessScorer(_BaseScorer):
    name = "ConcisenessScorer"
    dimension = "conciseness"
    state_field = "conciseness_score"
    rubric = "10 = 长度合理无冗余;9-7 = 略有重复;6-4 = 啰嗦;3-1 = 严重冗余;0 = 全篇水文。"
