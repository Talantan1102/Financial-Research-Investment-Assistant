"""Chat-loop agent 评估体系(行为×难度 成绩单)。

设计稿:docs/superpowers/specs/2026-06-08-chatloop-eval-blueprint-design.md
实施计划:docs/superpowers/plans/2026-06-08-chatloop-eval-blueprint.md

脊柱 = 6 个被评行为(路由/工具选择/克制弃答/grounding/任务终态/可靠性);
①②③ 复用 eval.tool_selection 确定性 scorer,④ 复用 eval.memory.faithful_answer,
⑥ pass^k wrapper。SUT-runner 修了现有 tool_selection --live 的 MCP 跨任务 cancel-scope bug。
"""
