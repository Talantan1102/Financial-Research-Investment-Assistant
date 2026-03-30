"""
金融研投助手 MCP Server 模块 - 金融研投助手模式

架构设计（符合金融研投助手 MCP Server）：
- Round 1: select_skill(skill_name, reason) 选择合适的 Skill
- Round 2: get_skill_tools(name) 获取指定 Skill 的工具列表
- Round 3: execute_skill_tool(skill_name, tool_name, arguments) 执行具体工具

工具调用方式（金融研投助手模式）：
1. select_skill(skill_name, reason) -> 根据用户意图选择合适的 Skill
2. get_skill_tools(name) -> 获取该 Skill 的所有可用工具
3. execute_skill_tool(skill_name, tool_name, arguments) -> 执行具体工具

注意：此版本与金融研投助手 MCP Server 完全一致。

Directory layout:
```
backends/
├── resources/           # Stateful backends (heavyweight, require sessions)
│   ├── __init__.py
│   └── finance_research.py        # 金融研投助手 Backend 实现
│
└── tools/               # Stateless tools (lightweight, no sessions)
    ├── __init__.py
    └── base_tool.py
```

Usage example:
```python
from mcp.server.stdio import stdio_server
from sandbox.server.backends.resources import FinanceResearchBackend

backend = FinanceResearchBackend()
await backend.warmup()

# 使用 backend.get_server() 获取 MCP Server 实例运行
```
"""

# 原生 MCP Server
from .finance_research import FinanceResearchBackend

__all__ = ["FinanceResearchBackend"]
