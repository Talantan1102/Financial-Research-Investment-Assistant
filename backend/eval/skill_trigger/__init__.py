"""技能触发离线评测(Task 6.2)。

CLI 入口 ``eval_runner`` 与 ``eval.tool_selection`` 共享同一评测核心
(``eval.tool_selection._core``)—— golden schema 同构,只是默认 golden 路径
与桶集不同,核心逻辑零重复。
"""
