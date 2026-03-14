# MCP Client API 文档

## MCPClient 类

### 构造函数

```python
MCPClient(
    server_command: List[str],
    timeout: float = 30.0
)
```

**参数说明：**

| 参数 | 类型 | 必需 | 默认值 | 说明 |
|------|------|------|--------|------|
| `server_command` | List[str] | 是 | - | 启动 MCP Server 的命令列表 |
| `timeout` | float | 否 | 30.0 | 连接和操作超时时间（秒） |

**示例：**

```python
from backend.app.mcp_client.client import MCPClient

client = MCPClient(
    server_command=["python", "-m", "backend.app.mcp_server.server"],
    timeout=30.0
)
```

### 属性

#### `connected`

```python
@property
def connected(self) -> bool
```

返回客户端是否已连接到 MCP Server。

**返回值：** `bool` - 连接状态

**示例：**

```python
if client.connected:
    result = await client.call_tool("get_quote", {"symbol": "AAPL"})
```

### 方法

#### `connect()`

```python
async def connect(self) -> bool
```

连接到 MCP Server。

**返回值：** `bool` - 连接是否成功

**异常：**
- `ConnectionError`: 连接失败
- `TimeoutError`: 连接超时

**示例：**

```python
try:
    success = await client.connect()
    if success:
        print("Connected to MCP Server")
except Exception as e:
    print(f"Connection failed: {e}")
```

#### `disconnect()`

```python
async def disconnect(self) -> None
```

断开与 MCP Server 的连接并清理资源。

**示例：**

```python
await client.disconnect()
print("Disconnected from MCP Server")
```

#### `discover_tools()`

```python
async def discover_tools(self) -> List[Dict[str, Any]]
```

发现并返回 MCP Server 提供的所有工具。

**返回值：** `List[Dict[str, Any]]` - 工具列表

每个工具字典包含：
- `name`: 工具名称
- `description`: 工具描述
- `inputSchema`: 输入参数 JSON Schema

**异常：**
- `ConnectionError`: 未连接时调用
- `DiscoveryError`: 工具发现失败

**示例：**

```python
tools = await client.discover_tools()
for tool in tools:
    print(f"Tool: {tool['name']}")
    print(f"Description: {tool['description']}")
```

#### `call_tool()`

```python
async def call_tool(
    self,
    tool_name: str,
    arguments: Dict[str, Any]
) -> Any
```

调用指定的 MCP 工具。

**参数：**

| 参数 | 类型 | 必需 | 说明 |
|------|------|------|------|
| `tool_name` | str | 是 | 工具名称 |
| `arguments` | Dict[str, Any] | 是 | 工具参数 |

**返回值：** `Any` - 工具调用结果

**异常：**
- `ConnectionError`: 未连接时调用
- `ToolError`: 工具调用失败
- `TimeoutError`: 调用超时

**示例：**

```python
# 调用 get_quote 工具
result = await client.call_tool(
    "get_quote",
    {"symbol": "AAPL"}
)
print(f"Price: {result['price']}")
```

#### `health_check()`

```python
async def health_check(self) -> bool
```

检查 MCP Server 健康状态。

**返回值：** `bool` - 是否健康

**示例：**

```python
if await client.health_check():
    print("MCP Server is healthy")
else:
    print("MCP Server is not responding")
```

---

## ToolAdapter 类

### 构造函数

```python
ToolAdapter(
    stock_service: StockService,
    mcp_client: Optional[MCPClient] = None,
    use_mcp: bool = True
)
```

**参数说明：**

| 参数 | 类型 | 必需 | 默认值 | 说明 |
|------|------|------|--------|------|
| `stock_service` | StockService | 是 | - | 股票服务实例 |
| `mcp_client` | MCPClient | 否 | None | MCP 客户端实例 |
| `use_mcp` | bool | 否 | True | 是否优先使用 MCP |

**示例：**

```python
from backend.app.mcp_client.adapter import ToolAdapter
from backend.app.service.stock_service import StockService

stock_service = StockService()
adapter = ToolAdapter(
    stock_service=stock_service,
    mcp_client=mcp_client,
    use_mcp=True
)
```

### 方法

#### `get_quote()`

```python
async def get_quote(
    self,
    symbol: str,
    exchange: Optional[str] = None
) -> Dict[str, Any]
```

获取股票实时报价。

**参数：**

| 参数 | 类型 | 必需 | 默认值 | 说明 |
|------|------|------|--------|------|
| `symbol` | str | 是 | - | 股票代码 |
| `exchange` | str | 否 | None | 交易所代码 |

**返回值：** `Dict[str, Any]` - 报价数据

包含字段：
- `symbol`: 股票代码
- `price`: 当前价格
- `change`: 涨跌额
- `change_percent`: 涨跌幅
- `volume`: 成交量
- `timestamp`: 时间戳

**示例：**

```python
quote = await adapter.get_quote("AAPL")
print(f"AAPL Price: ${quote['price']}")
print(f"Change: {quote['change_percent']}%")
```

#### `get_history()`

```python
async def get_history(
    self,
    symbol: str,
    period: str = "1mo",
    interval: str = "1d"
) -> List[Dict[str, Any]]
```

获取股票历史数据。

**参数：**

| 参数 | 类型 | 必需 | 默认值 | 说明 |
|------|------|------|--------|------|
| `symbol` | str | 是 | - | 股票代码 |
| `period` | str | 否 | "1mo" | 时间周期（1d, 5d, 1mo, 3mo, 6mo, 1y, 2y, 5y, 10y, ytd, max） |
| `interval` | str | 否 | "1d" | 数据间隔（1m, 2m, 5m, 15m, 30m, 60m, 90m, 1h, 1d, 5d, 1wk, 1mo, 3mo） |

**返回值：** `List[Dict[str, Any]]` - 历史数据列表

每条记录包含：
- `date`: 日期
- `open`: 开盘价
- `high`: 最高价
- `low`: 最低价
- `close`: 收盘价
- `volume`: 成交量

**示例：**

```python
history = await adapter.get_history("AAPL", period="1mo", interval="1d")
for day in history:
    print(f"{day['date']}: Open ${day['open']}, Close ${day['close']}")
```

#### `search_symbol()`

```python
async def search_symbol(
    self,
    query: str,
    limit: int = 10
) -> List[Dict[str, Any]]
```

搜索股票代码。

**参数：**

| 参数 | 类型 | 必需 | 默认值 | 说明 |
|------|------|------|--------|------|
| `query` | str | 是 | - | 搜索关键词 |
| `limit` | int | 否 | 10 | 返回结果数量限制 |

**返回值：** `List[Dict[str, Any]]` - 搜索结果

每条结果包含：
- `symbol`: 股票代码
- `name`: 公司名称
- `exchange`: 交易所
- `type`: 证券类型

**示例：**

```python
results = await adapter.search_symbol("Apple", limit=5)
for stock in results:
    print(f"{stock['symbol']}: {stock['name']} ({stock['exchange']})")
```

---

## 配置参数

### MCPClient 配置

```python
# 默认配置
DEFAULT_TIMEOUT = 30.0
DEFAULT_BUFFER_SIZE = 8192
```

| 参数 | 环境变量 | 默认值 | 说明 |
|------|----------|--------|------|
| `timeout` | `MCP_TIMEOUT` | 30.0 | 连接和调用超时 |
| `buffer_size` | `MCP_BUFFER_SIZE` | 8192 | 缓冲区大小 |
| `server_command` | `MCP_SERVER_COMMAND` | - | MCP Server 启动命令 |

### ToolAdapter 配置

| 参数 | 环境变量 | 默认值 | 说明 |
|------|----------|--------|------|
| `use_mcp` | `USE_MCP` | True | 是否优先使用 MCP |
| `fallback_enabled` | `MCP_FALLBACK_ENABLED` | True | 是否启用降级 |

---

## 错误码

### MCPClient 错误

| 错误类型 | 错误码 | 说明 | 处理建议 |
|----------|--------|------|----------|
| `ConnectionError` | 1001 | 连接失败 | 检查 MCP Server 是否运行 |
| `TimeoutError` | 1002 | 操作超时 | 增加 timeout 参数或检查网络 |
| `ToolError` | 1003 | 工具调用失败 | 检查参数是否正确 |
| `DiscoveryError` | 1004 | 工具发现失败 | 检查 MCP Server 配置 |
| `SerializationError` | 1005 | 序列化失败 | 检查数据格式 |

### ToolAdapter 错误

| 错误类型 | 错误码 | 说明 | 处理建议 |
|----------|--------|------|----------|
| `ServiceUnavailableError` | 2001 | 服务不可用 | 检查 MCP 和 StockService 状态 |
| `InvalidSymbolError` | 2002 | 无效的股票代码 | 检查 symbol 格式 |
| `RateLimitError` | 2003 | 请求频率限制 | 降低请求频率 |

---

## 使用示例

### 完整示例

```python
import asyncio
from backend.app.mcp_client.client import MCPClient
from backend.app.mcp_client.adapter import ToolAdapter
from backend.app.service.stock_service import StockService

async def main():
    # 创建 MCP Client
    mcp_client = MCPClient(
        server_command=["python", "-m", "backend.app.mcp_server.server"],
        timeout=30.0
    )
    
    try:
        # 连接 MCP Server
        await mcp_client.connect()
        
        # 发现可用工具
        tools = await mcp_client.discover_tools()
        print(f"Available tools: {[t['name'] for t in tools]}")
        
        # 创建 ToolAdapter
        stock_service = StockService()
        adapter = ToolAdapter(
            stock_service=stock_service,
            mcp_client=mcp_client,
            use_mcp=True
        )
        
        # 获取股票报价
        quote = await adapter.get_quote("AAPL")
        print(f"AAPL: ${quote['price']} ({quote['change_percent']}%)")
        
        # 获取历史数据
        history = await adapter.get_history("AAPL", period="1mo")
        print(f"Got {len(history)} days of history")
        
    finally:
        # 断开连接
        await mcp_client.disconnect()

if __name__ == "__main__":
    asyncio.run(main())
```
