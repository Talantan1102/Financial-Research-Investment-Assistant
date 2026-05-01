from app.agents.critic_subagents._base_scorer import _BaseScorer


class CoverageScorer(_BaseScorer):
    name = "CoverageScorer"
    dimension = "coverage"
    state_field = "coverage_score"
    rubric = "10 = 所有 subtask 都覆盖;9-7 = 大部分;6-4 = 覆盖一半左右;3-1 = 覆盖少;0 = 完全偏题。"
