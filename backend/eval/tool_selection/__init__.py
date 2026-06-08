"""工具选择 + 技能触发离线评测(Task 6.2)。

本包提供两个评测入口的共享核心(``_core``)与 tool_selection CLI。
技能触发 CLI 在姊妹包 ``eval.skill_trigger``,共享同一核心(薄封装)。

评测靶子是 chatloop 的 **首轮工具选择**(spec § 5.2 评测换靶):
不走 LLM-as-Judge —— 直接比对 ChatLoopAgent SUTOutput.tool_calls 的首选工具,
比 Judge 更便宜、更确定。指标见 ``_core`` docstring。
"""
