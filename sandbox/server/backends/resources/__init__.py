"""
Stateful resource backend module - 金融研投助手专用

Provides heavyweight backends that require session management.

Backend types:
- UnifiedFinanceBackend - 金融研投助手统一入口 Backend

Directory layout:
```
backends/
├── resources/           # Stateful backends (heavyweight, require sessions)
│   ├── __init__.py
│   └── unified_finance.py        # 统一金融 Backend (唯一入口)
│
└── tools/               # Stateless tools (lightweight, no sessions)
    ├── __init__.py
    └── base_tool.py
```

Usage example:
```python
from sandbox.server import HTTPServiceServer
from sandbox.server.backends.resources import UnifiedFinanceBackend

server = HTTPServiceServer()
server.load_backend(UnifiedFinanceBackend())
server.run()
```

Config example:
```json
{
  "resources": {
    "unified_finance": {
      "enabled": true,
      "backend_class": "sandbox.server.backends.resources.unified_finance.UnifiedFinanceBackend",
      "config": {}
    }
  }
}
```

工具调用方式：
- 统一入口: unified_finance:execute_skill_tool
- 参数: {"skill_name": "xxx", "tool_name": "xxx", "arguments": {...}}
"""

# 统一金融 Backend - 唯一入口
from .unified_finance import UnifiedFinanceBackend

__all__ = [
    "UnifiedFinanceBackend",
]
