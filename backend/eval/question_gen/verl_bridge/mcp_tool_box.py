"""McpToolBox —— verl RL 工具面对齐 SFT/生产(Path A)的同款 MCP 工具界面。

替代旧 ToolBox(原子 6 件子集),消除 train/serve skew(详见
docs/superpowers/plans/2026-06-27-verl-mcp-tool-alignment-plan.md,T2)。

界面 = 生产渐进披露同款:
  - schemas(): 对 TOOL_DOCS 全表出 thin_schema(瘦条目,必填参数+brief)+ 殿后 search_tools
    —— 与生产 ToolHub.schemas_for_llm 同源(tool_docs.py),模型看到的与 SFT 采轨逐字节一致。
  - exec():
    · search_tools → search_docs(纯函数检索 TOOL_DOCS,零服务依赖)
    · run_python → CodeInterpreterTool(沙箱)
    · 数据工具(财报/估值/快照/价格/trade_cal/compare/指数/基金/板块)→ 同一份 MCP
      handle()(单源,_load_tool_registry("chat_tools")),逐调用注入 as_of(T1 ContextVar)
    · 重依赖辅助工具(memory/kb/web/news/portfolio/技能/控制)→ stub 占位
      (它们要 Milvus/PG/Bocha,RL 训练环境不起;且非 reward 必需。决策见 plan T3)

as_of:逐调用 `set_eval_as_of`(ContextVar,task-local),并发不串(见 _as_of T1 + 端到端 AC3)。
"""

from __future__ import annotations

import json
from typing import Any

from app.mcp_server._as_of import set_eval_as_of
from app.tools.base import ToolError

# 重依赖/非数据工具 → stub(界面在、调用返占位,不碰 Milvus/PG/Bocha)。
# get_news/web_search/kb_search 虽在 MCP registry,但 handle 要 Bocha/Milvus → 也 stub。
_STUB_TOOLS = frozenset(
    {
        "get_news",
        "web_search",
        "kb_search",
        "memory_search",
        "memory_write",
        "get_portfolio_positions",
        "load_skill",
        "run_skill_script",
        "offer_deep_research",
        "read_cached_result",
        "dispatch_subagents",
    }
)

_SEARCH_TOOLS_NAME = "search_tools"
_SEARCH_TOOLS_K = 3


def _search_tools_schema() -> dict[str, Any]:
    """search_tools schema(与 tool_hub._search_tools_schema 同形)。"""
    return {
        "type": "function",
        "function": {
            "name": _SEARCH_TOOLS_NAME,
            "description": (
                "检索某个工具的完整使用文档(参数 schema/硬约束/示例/何时用)。"
                "裸调延迟工具参数报错时,先用本工具拿到目标工具的参数文档。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "工具名或自然语言描述(如 'compare_stocks' / '对比多只股票')",
                    }
                },
                "required": ["query"],
            },
        },
    }


class _StubState:
    """CodeInterpreterTool.run_with_state 仅在 data_refs 时读 state;本服务不用 refs。"""

    user_id = "verl-rollout"


class McpToolBox:
    """对齐 MCP chat_tools 界面的 verl 工具盒(drop-in 替换旧 ToolBox)。"""

    def __init__(
        self, *, tushare: Any = None, skills_root: str, workdir_root: str, timeout_s: int = 30
    ) -> None:
        import os

        from app.chatloop.code_interpreter_tool import CodeInterpreterTool
        from app.mcp_server.server import _load_tool_registry
        from app.skills.executor_backend import SkillExecutorBackend
        from app.skills.skill_executor import SkillExecutor

        # 单源:MCP chat_tools 的 {name: module(TOOL_DEF+handle)}(数据工具走真 handle)。
        self._registry = _load_tool_registry("chat_tools")

        # run_python 沙箱(同旧 ToolBox)。
        os.makedirs(skills_root, exist_ok=True)
        os.makedirs(workdir_root, exist_ok=True)
        executor = SkillExecutor(skills_root=skills_root, workdir_root=workdir_root)
        self._run_python = CodeInterpreterTool(
            backend=SkillExecutorBackend(executor), cache=None, timeout_s=timeout_s
        )
        self._state = _StubState()

    def schemas(self) -> list[dict[str, Any]]:
        """生产渐进披露同款:TOOL_DOCS 全表 thin_schema + 殿后 search_tools。"""
        from app.chatloop.tool_docs import TOOL_DOCS, thin_schema

        out = [thin_schema(doc) for doc in TOOL_DOCS.values()]
        out.append(_search_tools_schema())
        return out

    async def exec(
        self, tool_name: str, args: dict[str, Any], *, as_of: str | None = None
    ) -> dict[str, Any]:
        # 1. search_tools:纯函数检索 TOOL_DOCS(零服务依赖),返 {"docs":[{name,doc}]}。
        if tool_name == _SEARCH_TOOLS_NAME:
            from app.chatloop.tool_docs import search_docs

            query = args.get("query")
            if not isinstance(query, str) or not query.strip():
                raise ToolError("search_tools 需要 query(string),传工具名或自然语言描述。")
            hits = search_docs(query, k=_SEARCH_TOOLS_K)
            return {"docs": [{"name": d.name, "doc": d.doc} for d in hits]}

        # 2. run_python:沙箱(run_with_state)。
        if tool_name == "run_python":
            validated = self._run_python.args_schema.model_validate(args)
            return await self._run_python.run_with_state(validated, self._state)

        # 3. stub(重依赖/非数据工具):界面在,返占位,不碰重服务。
        if tool_name in _STUB_TOOLS:
            return {"note": f"{tool_name} 在 RL 训练环境为占位工具,本次无结果(非 reward 必需)。"}

        # 4. 数据工具:同一份 MCP handle();逐调用注入 as_of(ContextVar,并发安全)。
        mod = self._registry.get(tool_name)
        if mod is None:
            raise KeyError(tool_name)
        token = set_eval_as_of(as_of)
        try:
            tc_list = await mod.handle(args)
        finally:
            from app.mcp_server._as_of import _ASOF_VAR

            _ASOF_VAR.reset(token)
        return _adapt_textcontent(tc_list)


def _adapt_textcontent(tc_list: Any) -> dict[str, Any]:
    """MCP handle() 返 list[TextContent](text=JSON 串)→ dict(verl 侧吃 dict)。"""
    if not tc_list:
        return {}
    text = getattr(tc_list[0], "text", None)
    if text is None:
        return {"result": str(tc_list)}
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return {"text": text}


__all__ = ["McpToolBox"]
