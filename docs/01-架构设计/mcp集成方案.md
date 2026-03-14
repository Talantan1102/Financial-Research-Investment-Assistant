# MCP 集成方案

## 概述

本文档记录 DeepResearch V2.0 集成 MCP (Model Context Protocol) 的完整方案。

## 改造背景

### 原有架构问题

1. **紧耦合**：DeepScout 直接依赖 StockService，难以扩展其他数据源
2. **工具调用不统一**：不同工具调用方式不一致
3. **扩展性差**：新增工具需要修改多处代码

### MCP 优势

1. **标准化**：使用统一的 MCP 协议进行工具调用
2. **解耦**：工具实现与调用方分离
3. **可扩展**：支持多种 MCP Server，易于扩展
4. **生态**：可以复用社区 MCP 工具

## 架构变化

### 改造前

```
DeepScout → StockService
          → DocumentService
          → OtherServices
```

### 改造后

```
DeepResearch
├── DeepScout → ToolAdapter ──→ MCPClient ──→ MCPServer
│                              └── Fallback ──→ StockService
└── ResearchGraph
```

## 核心组件

### 1. MCPClient

**文件**: `backend/app/mcp_client/client.py`

```python
class MCPClient:
    """MCP 协议客户端"""
    
    def __init__(self, server_script_path: str, ...):
        self.server_script_path = server_script_path
        self.session: Optional[ClientSession] = None
```

**功能**:
- 通过 STDIO 与 MCP Server 通信
- 支持工具发现和调用
- 自动重连和错误处理

### 2. ToolAdapter

**文件**: `backend/app/mcp_client/adapter.py`

```python
class ToolAdapter:
    """工具调用适配器，支持 MCP 和 StockService 两种方式"""
    
    def __init__(self, stock_service, mcp_client=None, use_mcp=True):
        self.stock_service = stock_service
        self.mcp_client = mcp_client
        self.use_mcp = use_mcp
```

**功能**:
- 统一工具调用接口
- 自动降级到 StockService
- 向后兼容

## 配置

### 环境变量

```bash
# 启用 MCP
USE_MCP=true
MCP_TIMEOUT=30.0
MCP_FALLBACK_ENABLED=true
```

### 配置项

```python
class Settings(BaseSettings):
    USE_MCP: bool = True
    MCP_SERVER_COMMAND: List[str] = ["python", "-m", "backend.app.mcp_server.server"]
    MCP_TIMEOUT: float = 30.0
    MCP_FALLBACK_ENABLED: bool = True
```

## 向后兼容策略

### 1. 默认启用降级

ToolAdapter 默认启用降级机制：

```python
async def get_quote(self, symbol: str):
    # 尝试使用 MCP
    if self.use_mcp and self.mcp_client and self.mcp_client.connected:
        try:
            return await self._call_mcp_tool("get_quote", {"symbol": symbol})
        except Exception as e:
            logger.warning(f"MCP call failed, falling back: {e}")
    
    # 降级到 StockService
    return await self._call_stock_service("get_quote", symbol=symbol)
```

### 2. 配置开关

通过 `USE_MCP` 环境变量控制：

```python
# 禁用 MCP，完全使用原有 StockService
USE_MCP=false

# 启用 MCP，失败时降级
USE_MCP=true
MCP_FALLBACK_ENABLED=true
```

## 迁移指南

### 对于开发者

```python
# 原有代码
from backend.app.service.stock_service import StockService
stock_service = StockService()
quote = await stock_service.get_stock_data("AAPL")

# 新代码
from backend.app.mcp_client.adapter import ToolAdapter
from backend.app.mcp_client.client import MCPClient

mcp_client = MCPClient(server_script_path="...")
await mcp_client.connect()

adapter = ToolAdapter(stock_service=stock_service, mcp_client=mcp_client)
quote = await adapter.get_quote("AAPL")
```

## 性能对比

| 场景 | 延迟 | 备注 |
|------|------|------|
| StockService 直接调用 | 50ms | 本地调用 |
| MCP 调用 | 80ms | 含进程间通信 |
| MCP 降级 | 130ms | MCP 失败后降级 |

## 测试验证

### 单元测试

```bash
# 测试 MCPClient
python -m pytest backend/app/mcp_client/tests/test_client.py -v

# 测试 ToolAdapter
python -m pytest backend/app/mcp_client/tests/test_adapter.py -v
```

### 集成测试

```bash
# 启动 MCP Server 后测试
python -m pytest backend/tests/integration/test_mcp_integration.py -v
```

## 后续优化

### 短期优化

1. **连接池**: 复用 MCP 连接，减少建立连接开销
2. **缓存**: 缓存工具发现结果
3. **批量调用**: 支持批量工具调用

### 长期规划

1. **多 Server 支持**: 支持同时连接多个 MCP Server
2. **动态发现**: 自动发现和注册 MCP Server
3. **工具编排**: 支持工具组合和编排
