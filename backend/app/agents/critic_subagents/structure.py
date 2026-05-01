from app.agents.critic_subagents._base_scorer import _BaseScorer


class StructureScorer(_BaseScorer):
    name = "StructureScorer"
    dimension = "structure"
    state_field = "structure_score"
    rubric = (
        "10 = 章节清晰、引用恰当、markdown 格式正确;9-7 = 多数 OK;"
        "6-4 = 章节模糊;3-1 = 杂乱无章;0 = 无结构。"
    )
