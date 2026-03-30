"""
后端模块 - 金融研投助手模式

提供金融研投助手风格的 MCP 后端：

1. MCP Native Backend（金融研投助手模式）
   - 直接作为 MCP Server 运行
   - 暴露 3 个工具：select_skill / get_skill_tools / execute_skill_tool
   - 与金融研投助手 MCP Server 完全一致的交互流程
   - 位置：backends/resources/
   - 示例：FinanceResearchBackend

2. Resource Backend（有状态后端，重量级 - 旧架构）
   - 需要初始化的资源
   - 使用 @tool 装饰器注册工具
   - 提供完整生命周期：warmup → initialize → cleanup → shutdown
   - 位置：backends/resources/
   - 示例：VM、RAG

3. API Tools（无状态工具，轻量级）
   - 不需要初始化和 session
   - 使用 @register_api_tool 装饰器注册
   - 位置：backends/tools/
   - 示例：WebSearch（search、visit、image_search）

目录结构:
```
backends/
├── __init__.py          # 导出基类
├── base.py              # Backend 基类定义
├── mcp_native_base.py   # MCP Native Backend 基类（金融研投助手模式）
│
├── resources/           # 有状态后端（重量级，需要 session）
│   ├── __init__.py      #   导出所有后端类
│   ├── finance_research.py     #   金融研投助手 Backend
│   ├── vm.py            #   VM 后端（桌面自动化）
│   └── rag.py           #   RAG 后端（文档检索）
│
└── tools/               # 无状态工具（轻量级，无需 session）
    ├── __init__.py      #   @register_api_tool 装饰器
    └── websearch.py     #   WebSearch 工具
```

使用示例 - MCP Native Backend（金融研投助手模式）:

```python
from sandbox.server import HTTPServiceServer
from sandbox.server.backends import MCPNativeBackend, MCPBackendConfig

# 示例: 金融研投助手模式 Backend
class MyBackend(MCPNativeBackend):
    name = "my_backend"
    
    async def select_skill(self, skill_name: str, reason: str) -> dict:
        # 选择合适的 Skill
        return {"success": True, "skill_name": skill_name}
    
    async def get_skill_tools(self, name: str) -> dict:
        # 获取 Skill 的工具列表
        return {"tools": [...]}
    
    async def execute_skill_tool(self, skill_name: str, tool_name: str, arguments: dict) -> dict:
        # 执行具体工具
        return {"result": "..."}

server = HTTPServiceServer()
server.load_mcp_backend(MyBackend())
server.run()
```
"""

from .base import Backend, BackendConfig
from .mcp_native_base import (
    MCPNativeBackend,
    MCPBackendConfig,
    MCPResource,
    MCPTool
)

__all__ = [
    # 旧 Backend 基类
    "Backend",
    "BackendConfig",
    # MCP Native Backend 基类 ⭐
    "MCPNativeBackend",
    "MCPBackendConfig",
    "MCPResource",
    "MCPTool",
]
