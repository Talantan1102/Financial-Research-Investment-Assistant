# MCP Client 集成方案设计文档

## 概述

基于DeepResearch V2.0架构分析，设计MCP Client集成方案，使现有Agent能够通过MCP协议调用外部工具，同时保持向后兼容。

## 架构分析

### 当前架构特点

1. **无显式ReAct控制器**：工具调用直接内嵌在各Agent中（scout.py、data_analyst.py等）
2. **LangGraph状态机**：通过ResearchState共享全局状态
3. **流式输出**：使用asyncio.Queue实现实时SSE推送
4. **现有工具调用**：直接调用StockService等服务类

### 集成目标

1. **无缝集成**：Agent无需大规模改造即可使用MCP工具
2. **向后兼容**：失败时自动回退到原有实现
3. **性能优化**：避免不必要的进程通信开销
4. **可观测性**：完整的日志和错误追踪

---

## 1. MCPClient 类设计

### 文件位置
`backend/app/mcp_client/client.py`

### 类接口设计

```python
from typing import Dict, Any, List, Optional, AsyncContextManager
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
import logging
import asyncio


class MCPClient:
    """
    MCP 客户端封装

    使用 mcp Python SDK 连接到 MCP Server，提供工具发现和调用能力。
    支持连接生命周期管理和自动重连。
    """

    def __init__(
        self,
        server_script_path: str,
        python_path: str = "python",
        auto_connect: bool = False,
        max_retries: int = 3,
        retry_delay: float = 1.0
    ):
        """
        初始化 MCP Client

        Args:
            server_script_path: MCP Server 启动脚本路径
            python_path: Python 解释器路径
            auto_connect: 是否自动连接
            max_retries: 最大重试次数
            retry_delay: 重试延迟（秒）
        """
        self.server_script_path = server_script_path
        self.python_path = python_path
        self.max_retries = max_retries
        self.retry_delay = retry_delay

        self.session: Optional[ClientSession] = None
        self.stdio_transport: Optional[AsyncContextManager] = None
        self._connected = False
        self._tools_cache: Optional[List[Dict[str, Any]]] = None
        self._lock = asyncio.Lock()

        self.logger = logging.getLogger("MCPClient")

        if auto_connect:
            asyncio.create_task(self.connect())

    async def connect(self) -> bool:
        """
        连接到 MCP Server

        Returns:
            是否连接成功
        """
        if self._connected:
            self.logger.info("Already connected to MCP Server")
            return True

        async with self._lock:
            try:
                server_params = StdioServerParameters(
                    command=self.python_path,
                    args=[self.server_script_path],
                    env=None
                )

                # 创建 stdio 传输
                self.stdio_transport = stdio_client(server_params)
                read_stream, write_stream = await self.stdio_transport.__aenter__()

                # 创建会话
                self.session = ClientSession(read_stream, write_stream)
                await self.session.initialize()

                self._connected = True
                self.logger.info("Successfully connected to MCP Server")

                # 预加载工具列表
                await self._refresh_tools_cache()

                return True

            except Exception as e:
                self.logger.error(f"Failed to connect to MCP Server: {e}")
                self._connected = False
                return False

    async def disconnect(self) -> None:
        """断开连接"""
        async with self._lock:
            if self.stdio_transport:
                try:
                    await self.stdio_transport.__aexit__(None, None, None)
                except Exception as e:
                    self.logger.warning(f"Error during disconnect: {e}")
                finally:
                    self.stdio_transport = None
                    self.session = None
                    self._connected = False
                    self._tools_cache = None
                    self.logger.info("Disconnected from MCP Server")

    async def list_tools(self, refresh: bool = False) -> List[Dict[str, Any]]:
        """
        列出所有可用工具

        Args:
            refresh: 是否刷新缓存

        Returns:
            工具列表 [{"name": "skill.tool", "description": "...", "inputSchema": {...}}]
        """
        if not self._connected:
            await self.connect()

        if not self._connected:
            raise RuntimeError("Not connected to MCP Server")

        if not refresh and self._tools_cache is not None:
            return self._tools_cache

        await self._refresh_tools_cache()
        return self._tools_cache or []

    async def _refresh_tools_cache(self) -> None:
        """刷新工具缓存"""
        try:
            response = await self.session.list_tools()
            self._tools_cache = [
                {
                    "name": tool.name,
                    "description": tool.description,
                    "inputSchema": tool.inputSchema
                }
                for tool in response.tools
            ]
            self.logger.info(f"Cached {len(self._tools_cache)} tools")
        except Exception as e:
            self.logger.error(f"Failed to refresh tools cache: {e}")
            self._tools_cache = []

    async def call_tool(
        self,
        name: str,
        arguments: Dict[str, Any],
        retry: bool = True
    ) -> Dict[str, Any]:
        """
        调用工具

        Args:
            name: 工具名称 (格式: skill_name.tool_name)
            arguments: 工具参数
            retry: 失败时是否重试

        Returns:
            工具执行结果 {"success": bool, "data": Any, "error": str}
        """
        if not self._connected:
            await self.connect()

        if not self._connected:
            return {
                "success": False,
                "error": "Not connected to MCP Server",
                "data": None
            }

        retries = self.max_retries if retry else 1
        last_error = None

        for attempt in range(retries):
            try:
                self.logger.info(f"Calling tool: {name} (attempt {attempt + 1}/{retries})")

                response = await self.session.call_tool(name, arguments)

                # 解析响应
                if response.content and len(response.content) > 0:
                    content = response.content[0]
                    if hasattr(content, 'text'):
                        import json
                        result = json.loads(content.text)
                        self.logger.info(f"Tool {name} returned: success={result.get('success')}")
                        return result

                return {
                    "success": False,
                    "error": "Invalid response format",
                    "data": None
                }

            except Exception as e:
                last_error = str(e)
                self.logger.warning(f"Tool call failed (attempt {attempt + 1}): {e}")

                if attempt < retries - 1:
                    await asyncio.sleep(self.retry_delay)
                    # 尝试重连
                    if not self._connected:
                        await self.connect()

        return {
            "success": False,
            "error": f"Tool call failed after {retries} attempts: {last_error}",
            "data": None
        }

    async def has_tool(self, tool_name: str) -> bool:
        """
        检查工具是否存在

        Args:
            tool_name: 工具名称

        Returns:
            是否存在
        """
        tools = await self.list_tools()
        return any(t["name"] == tool_name for t in tools)

    @property
    def is_connected(self) -> bool:
        """是否已连接"""
        return self._connected

    async def __aenter__(self):
        """异步上下文管理器入口"""
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """异步上下文管理器出口"""
        await self.disconnect()


# 单例模式
_mcp_client_instance: Optional[MCPClient] = None


def get_mcp_client(
    server_script_path: str = None,
    auto_connect: bool = True
) -> MCPClient:
    """
    获取 MCP Client 单例

    Args:
        server_script_path: MCP Server 脚本路径（首次调用时必须提供）
        auto_connect: 是否自动连接

    Returns:
        MCPClient 实例
    """
    global _mcp_client_instance

    if _mcp_client_instance is None:
        if server_script_path is None:
            raise ValueError("server_script_path must be provided on first call")

        _mcp_client_instance = MCPClient(
            server_script_path=server_script_path,
            auto_connect=auto_connect
        )

    return _mcp_client_instance
```

### 错误处理策略

1. **连接失败**：记录日志，返回错误状态，不抛出异常
2. **工具调用失败**：支持可配置的重试机制（默认3次）
3. **超时处理**：使用 asyncio.wait_for 设置超时
4. **资源清理**：使用异步上下文管理器确保连接正确释放

---

## 2. Agent 适配层设计

### 文件位置
`backend/app/mcp_client/adapter.py`

### 类接口设计

```python
from typing import Dict, Any, Optional, Callable, Awaitable
from app.mcp_client.client import MCPClient
import logging


class ToolAdapter:
    """
    工具适配器 - 为现有 Agent 提供向后兼容的工具调用接口

    设计原则：
    1. 优先使用 MCP Client 调用工具
    2. 失败时自动回退到原有实现（fallback）
    3. 提供统一的调用接口，屏蔽底层差异
    """

    def __init__(
        self,
        mcp_client: Optional[MCPClient] = None,
        enable_fallback: bool = True
    ):
        """
        初始化工具适配器

        Args:
            mcp_client: MCP Client 实例
            enable_fallback: 是否启用回退机制
        """
        self.mcp_client = mcp_client
        self.enable_fallback = enable_fallback
        self.logger = logging.getLogger("ToolAdapter")

        # 注册的回退处理器 {tool_name: fallback_handler}
        self._fallback_handlers: Dict[str, Callable] = {}

    def register_fallback(
        self,
        tool_name: str,
        handler: Callable[..., Awaitable[Dict[str, Any]]]
    ):
        """
        注册回退处理器

        Args:
            tool_name: 工具名称 (格式: skill.tool)
            handler: 回退处理函数（async）
        """
        self._fallback_handlers[tool_name] = handler
        self.logger.info(f"Registered fallback for tool: {tool_name}")

    async def call_tool(
        self,
        tool_name: str,
        arguments: Dict[str, Any],
        force_fallback: bool = False
    ) -> Dict[str, Any]:
        """
        调用工具（带自动回退）

        Args:
            tool_name: 工具名称 (skill.tool)
            arguments: 工具参数
            force_fallback: 是否强制使用回退

        Returns:
            {"success": bool, "data": Any, "error": str, "source": "mcp"|"fallback"}
        """
        # 强制回退
        if force_fallback:
            return await self._call_fallback(tool_name, arguments)

        # 尝试 MCP 调用
        if self.mcp_client and self.mcp_client.is_connected:
            try:
                result = await self.mcp_client.call_tool(tool_name, arguments)

                if result["success"]:
                    result["source"] = "mcp"
                    self.logger.info(f"Tool {tool_name} called via MCP successfully")
                    return result
                else:
                    self.logger.warning(f"MCP tool call failed: {result.get('error')}")

            except Exception as e:
                self.logger.error(f"MCP tool call exception: {e}")

        # MCP 失败，尝试回退
        if self.enable_fallback:
            self.logger.info(f"Falling back to legacy implementation for {tool_name}")
            return await self._call_fallback(tool_name, arguments)

        return {
            "success": False,
            "error": "MCP call failed and fallback disabled",
            "data": None,
            "source": "none"
        }

    async def _call_fallback(
        self,
        tool_name: str,
        arguments: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        调用回退处理器

        Args:
            tool_name: 工具名称
            arguments: 参数

        Returns:
            工具执行结果
        """
        handler = self._fallback_handlers.get(tool_name)

        if handler is None:
            return {
                "success": False,
                "error": f"No fallback handler registered for {tool_name}",
                "data": None,
                "source": "fallback"
            }

        try:
            result = await handler(**arguments)

            # 标准化返回格式
            if isinstance(result, dict):
                result["source"] = "fallback"
                return result
            else:
                return {
                    "success": True,
                    "data": result,
                    "source": "fallback"
                }

        except Exception as e:
            self.logger.error(f"Fallback handler error: {e}")
            return {
                "success": False,
                "error": f"Fallback execution failed: {str(e)}",
                "data": None,
                "source": "fallback"
            }

    async def has_tool(self, tool_name: str) -> bool:
        """
        检查工具是否可用（MCP 或 fallback）

        Args:
            tool_name: 工具名称

        Returns:
            是否可用
        """
        # 检查 MCP
        if self.mcp_client and self.mcp_client.is_connected:
            if await self.mcp_client.has_tool(tool_name):
                return True

        # 检查 fallback
        return tool_name in self._fallback_handlers


# 便捷函数：创建预配置的适配器
async def create_stock_adapter(mcp_client: MCPClient) -> ToolAdapter:
    """
    创建股票数据适配器（预注册 fallback）

    Args:
        mcp_client: MCP Client 实例

    Returns:
        配置好的 ToolAdapter
    """
    from app.service.stock_service import get_stock_service

    adapter = ToolAdapter(mcp_client=mcp_client, enable_fallback=True)

    # 注册 fallback handlers
    stock_service = get_stock_service()

    adapter.register_fallback(
        "market_data.get_stock_quote",
        stock_service.get_stock_by_code
    )

    adapter.register_fallback(
        "market_data.search_stock",
        stock_service.search_stock
    )

    return adapter
```

### 向后兼容方案

1. **透明调用**：Agent代码无需感知底层是MCP还是直接调用
2. **自动回退**：MCP失败时自动使用原有StockService
3. **渐进式迁移**：可以逐个工具迁移，不影响已有功能

---

## 3. DeepScout 改造方案

### 修改文件
`backend/app/service/deep_research_v2/agents/scout.py`

### 改造步骤

#### 3.1 注入 ToolAdapter

```python
# scout.py 开头添加导入
from typing import Optional
from app.mcp_client.adapter import ToolAdapter

class DeepScout(BaseAgent):
    """深度侦探 Agent"""

    def __init__(
        self,
        llm_api_key: str,
        llm_base_url: str,
        search_api_key: str = None,
        model: str = None,
        tool_adapter: Optional[ToolAdapter] = None  # 新增参数
    ):
        super().__init__(llm_api_key, llm_base_url, model)
        self.name = "DeepScout"
        self.search_api_key = search_api_key
        self.tool_adapter = tool_adapter  # 存储适配器
```

#### 3.2 改造 `_fetch_stock_data_if_relevant` 方法

```python
async def _fetch_stock_data_if_relevant(self, state: ResearchState) -> None:
    """
    自动识别查询中的上市公司，获取实时股票数据

    改造点：优先使用 MCP Client 调用，失败时自动回退到 StockService
    """
    try:
        # 导入股票映射工具
        try:
            from config.stock_mapping import find_company_in_query
        except ImportError:
            from app.config.stock_mapping import find_company_in_query

        query = state.get("query", "")
        found_companies = find_company_in_query(query)

        if not found_companies:
            return

        # 处理每个检测到的公司
        for company_name, stock_code in found_companies[:2]:  # 最多查询2只股票
            self.logger.info(f"检测到上市公司: {company_name} ({stock_code})")

            # 尝试通过 ToolAdapter 调用（MCP 优先，自动回退）
            if self.tool_adapter:
                result = await self.tool_adapter.call_tool(
                    tool_name="market_data.get_stock_quote",
                    arguments={"stock_code": stock_code}
                )

                # 记录调用来源
                source = result.get("source", "unknown")
                self.logger.info(f"Stock data fetched via {source}")
            else:
                # 没有配置 ToolAdapter，使用原有方式
                from app.service.stock_service import get_stock_service
                stock_service = get_stock_service()
                result = await stock_service.get_stock_by_code(stock_code)

            # 处理结果（无论来源）
            if result.get("success"):
                data = result["data"]

                # 添加到 data_points（保持原有逻辑）
                state["data_points"].append({
                    "id": f"stock_{stock_code}",
                    "name": f"{company_name}股价",
                    "value": data.get("nowPri", ""),
                    "unit": "元",
                    "year": None,
                    "source": f"实时行情（{stock_code}）",
                    "confidence": 1.0,
                    "metadata": {
                        "increase": data.get("increase", ""),
                        "increPer": data.get("increPer", ""),
                        "todayMax": data.get("todayMax", ""),
                        "todayMin": data.get("todayMin", ""),
                    }
                })

                # 添加到 facts
                state["facts"].append({
                    "id": f"stock_fact_{stock_code}",
                    "content": f"{company_name}（{stock_code}）当前股价{data.get('nowPri')}元，涨跌幅{data.get('increPer')}",
                    "source_url": f"realtime_stock_{stock_code}",
                    "source_name": "实时股票行情",
                    "source_type": "official",
                    "credibility_score": 1.0,
                    "timestamp": datetime.now().isoformat(),
                    "related_sections": [],
                    "verified": True
                })

                self.logger.info(f"已添加股票数据: {company_name} ({stock_code})")
            else:
                self.logger.warning(f"获取股票数据失败: {result.get('error')}")

    except Exception as e:
        self.logger.error(f"股票数据获取异常: {e}")
        # 不影响主流程，继续执行
```

### 代码改造对比

**改造前**（直接调用StockService）：
```python
from service.stock_service import get_stock_service

stock_service = get_stock_service()
result = await stock_service.get_stock_by_code(stock_code)
```

**改造后**（通过ToolAdapter，支持MCP + fallback）：
```python
if self.tool_adapter:
    result = await self.tool_adapter.call_tool(
        tool_name="market_data.get_stock_quote",
        arguments={"stock_code": stock_code}
    )
else:
    # 兼容没有配置 ToolAdapter 的情况
    from app.service.stock_service import get_stock_service
    stock_service = get_stock_service()
    result = await stock_service.get_stock_by_code(stock_code)
```

**优势**：
1. 代码侵入性小，只改动调用部分
2. 保持原有错误处理逻辑
3. 完全向后兼容（tool_adapter为None时使用原实现）

---

## 4. Graph 层改造方案

### 修改文件
`backend/app/service/deep_research_v2/graph.py`

### 改造内容

#### 4.1 初始化时创建 MCP Client 和 ToolAdapter

```python
# graph.py 导入
import os
from app.mcp_client.client import get_mcp_client
from app.mcp_client.adapter import create_stock_adapter

class DeepResearchGraph:
    """DeepResearch V2.0 工作流图"""

    def __init__(
        self,
        llm_api_key: str = None,
        llm_base_url: str = None,
        search_api_key: str = None,
        model: str = None,
        max_iterations: int = None,
        enable_mcp: bool = True  # 新增：是否启用 MCP
    ):
        """初始化工作流"""
        # ... 现有配置代码 ...

        # 初始化 MCP Client（如果启用）
        self.mcp_client = None
        self.tool_adapter = None

        if enable_mcp:
            try:
                server_script = os.path.join(
                    os.path.dirname(__file__),
                    "../../mcp_server/server.py"
                )

                self.mcp_client = get_mcp_client(
                    server_script_path=server_script,
                    auto_connect=False  # 延迟连接，在 run() 时连接
                )

                logger.info("MCP Client initialized (not yet connected)")

            except Exception as e:
                logger.warning(f"Failed to initialize MCP Client: {e}")
                logger.warning("Will use legacy service implementations")

        # 初始化各个 Agent（传入 tool_adapter）
        self.architect = ChiefArchitect(...)

        self.scout = DeepScout(
            self.llm_api_key,
            self.llm_base_url,
            self.search_api_key,
            config.agents.scout.model,
            tool_adapter=None  # 稍后在 run() 中设置
        )

        # ... 其他 Agent 初始化 ...
```

#### 4.2 在 run() 方法中管理连接生命周期

```python
async def run(
    self,
    query: str,
    session_id: str,
    resume: bool = False,
    user_id: str = None,
    search_web: bool = True,
    search_local: bool = False
) -> AsyncGenerator[Dict[str, Any], None]:
    """执行研究流程（流式输出）"""

    # MCP Client 连接（如果启用）
    if self.mcp_client:
        try:
            connected = await self.mcp_client.connect()
            if connected:
                # 创建 ToolAdapter 并注入到 Scout
                self.tool_adapter = await create_stock_adapter(self.mcp_client)
                self.scout.tool_adapter = self.tool_adapter

                logger.info("MCP Client connected, tools ready")

                # 可选：输出可用工具列表
                tools = await self.mcp_client.list_tools()
                logger.info(f"Available MCP tools: {[t['name'] for t in tools]}")
        except Exception as e:
            logger.warning(f"MCP Client connection failed: {e}")
            logger.warning("Falling back to legacy implementations")

    try:
        # ... 现有的研究流程代码 ...

        async for event in self._run_simplified(state):
            yield event

    finally:
        # 断开 MCP 连接
        if self.mcp_client:
            await self.mcp_client.disconnect()
            logger.info("MCP Client disconnected")
```

### 生命周期管理

```
Graph 启动 (run)
    ↓
连接 MCP Client
    ↓
创建 ToolAdapter
    ↓
注入到各个 Agent
    ↓
执行研究流程
    ↓
断开 MCP Client (finally)
```

**优势**：
1. 连接在需要时建立，避免资源浪费
2. 使用 try-finally 确保连接正确释放
3. 失败时优雅降级，不影响主流程

---

## 5. 配置管理

### 新增配置文件
`backend/app/config/mcp_config.py`

```python
"""MCP Client 配置"""
import os
from typing import Optional
from pydantic import BaseModel, Field


class MCPConfig(BaseModel):
    """MCP 配置"""

    enabled: bool = Field(
        default=True,
        description="是否启用 MCP Client"
    )

    server_script: str = Field(
        default="backend/app/mcp_server/server.py",
        description="MCP Server 脚本路径"
    )

    python_path: str = Field(
        default="python",
        description="Python 解释器路径"
    )

    max_retries: int = Field(
        default=3,
        description="工具调用最大重试次数"
    )

    retry_delay: float = Field(
        default=1.0,
        description="重试延迟（秒）"
    )

    enable_fallback: bool = Field(
        default=True,
        description="是否启用回退机制"
    )

    connection_timeout: int = Field(
        default=10,
        description="连接超时（秒）"
    )

    call_timeout: int = Field(
        default=30,
        description="工具调用超时（秒）"
    )


def get_mcp_config() -> MCPConfig:
    """获取 MCP 配置（支持环境变量覆盖）"""
    return MCPConfig(
        enabled=os.getenv("MCP_ENABLED", "true").lower() == "true",
        server_script=os.getenv("MCP_SERVER_SCRIPT", "backend/app/mcp_server/server.py"),
        python_path=os.getenv("MCP_PYTHON_PATH", "python"),
        max_retries=int(os.getenv("MCP_MAX_RETRIES", "3")),
        retry_delay=float(os.getenv("MCP_RETRY_DELAY", "1.0")),
        enable_fallback=os.getenv("MCP_ENABLE_FALLBACK", "true").lower() == "true",
    )
```

---

## 6. 错误处理策略

### 错误分类

| 错误类型 | 处理策略 | 是否中断流程 |
|---------|---------|-------------|
| MCP 连接失败 | 记录日志，使用 fallback | 否 |
| 工具调用超时 | 重试 3 次，失败后 fallback | 否 |
| 工具不存在 | 使用 fallback（如果有） | 否 |
| 参数校验失败 | 记录错误，返回失败结果 | 否 |
| Fallback 失败 | 记录错误，继续流程 | 否 |
| JSON 解析失败 | 记录错误，返回原始响应 | 否 |

### 日志级别

```python
# 正常流程
logger.info("MCP tool called successfully")

# 可恢复错误
logger.warning("MCP call failed, using fallback")

# 严重错误（不影响主流程）
logger.error("Both MCP and fallback failed")
```

---

## 7. 测试策略

### 单元测试

```python
# tests/test_mcp_client.py
import pytest
from app.mcp_client.client import MCPClient

@pytest.mark.asyncio
async def test_mcp_client_connect():
    """测试 MCP Client 连接"""
    client = MCPClient(server_script_path="backend/app/mcp_server/server.py")
    assert await client.connect()
    assert client.is_connected
    await client.disconnect()

@pytest.mark.asyncio
async def test_mcp_client_call_tool():
    """测试工具调用"""
    async with MCPClient(server_script_path="...") as client:
        result = await client.call_tool(
            "market_data.get_stock_quote",
            {"stock_code": "sh600519"}
        )
        assert result["success"]
        assert "data" in result

@pytest.mark.asyncio
async def test_tool_adapter_fallback():
    """测试回退机制"""
    from app.mcp_client.adapter import ToolAdapter
    from app.service.stock_service import get_stock_service

    adapter = ToolAdapter(mcp_client=None, enable_fallback=True)

    # 注册 fallback
    stock_service = get_stock_service()
    adapter.register_fallback(
        "market_data.get_stock_quote",
        stock_service.get_stock_by_code
    )

    # 调用（应使用 fallback）
    result = await adapter.call_tool(
        "market_data.get_stock_quote",
        {"stock_code": "sh600519"}
    )

    assert result["success"]
    assert result["source"] == "fallback"
```

### 集成测试

```python
# tests/test_scout_mcp_integration.py
import pytest
from app.service.deep_research_v2.graph import create_research_graph

@pytest.mark.asyncio
async def test_scout_with_mcp():
    """测试 Scout Agent 使用 MCP 获取股票数据"""
    graph = create_research_graph(enable_mcp=True)

    events = []
    async for event in graph.run(
        query="茅台股价怎么样",
        session_id="test_session"
    ):
        events.append(event)

    # 验证是否获取了股票数据
    final_event = events[-1]
    assert final_event["type"] == "research_complete"
    assert final_event["facts_count"] > 0
```

---

## 8. 改造步骤清单

### Phase 1: 基础设施搭建（2-3小时）

- [ ] 创建 `backend/app/mcp_client/__init__.py`
- [ ] 实现 `backend/app/mcp_client/client.py` (MCPClient 类)
- [ ] 实现 `backend/app/mcp_client/adapter.py` (ToolAdapter 类)
- [ ] 创建 `backend/app/config/mcp_config.py`
- [ ] 编写单元测试 `tests/test_mcp_client.py`

### Phase 2: Agent 改造（1-2小时）

- [ ] 修改 `scout.py` 构造函数，添加 `tool_adapter` 参数
- [ ] 改造 `scout.py` 的 `_fetch_stock_data_if_relevant` 方法
- [ ] 修改 `graph.py` 的 `__init__` 方法，初始化 MCP Client
- [ ] 修改 `graph.py` 的 `run` 方法，管理连接生命周期

### Phase 3: 测试验证（1-2小时）

- [ ] 运行单元测试
- [ ] 集成测试：启动完整流程，验证 MCP 调用
- [ ] 回退测试：关闭 MCP Server，验证 fallback 机制
- [ ] 性能测试：对比 MCP vs 直接调用的性能差异

### Phase 4: 文档和监控（1小时）

- [ ] 更新 README.md，说明 MCP 集成
- [ ] 添加配置示例和环境变量说明
- [ ] 添加日志监控指标（MCP 调用成功率、fallback 使用率）
- [ ] 编写故障排查指南

---

## 9. 性能优化建议

### 9.1 连接池

```python
# 未来优化：支持连接池
class MCPClientPool:
    """MCP Client 连接池"""

    def __init__(self, pool_size: int = 3):
        self.pool_size = pool_size
        self.clients: List[MCPClient] = []

    async def get_client(self) -> MCPClient:
        """获取空闲的 Client"""
        # ... 连接池逻辑 ...
```

### 9.2 工具调用缓存

```python
# 为幂等工具添加缓存
class CachedToolAdapter(ToolAdapter):
    """带缓存的工具适配器"""

    def __init__(self, *args, cache_ttl: int = 60, **kwargs):
        super().__init__(*args, **kwargs)
        self.cache = {}
        self.cache_ttl = cache_ttl
```

### 9.3 批量调用优化

```python
# 批量获取多个股票数据
async def batch_call_tools(
    adapter: ToolAdapter,
    tool_name: str,
    arguments_list: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    """批量调用工具"""
    tasks = [
        adapter.call_tool(tool_name, args)
        for args in arguments_list
    ]
    return await asyncio.gather(*tasks)
```

---

## 10. 监控指标

### 关键指标

| 指标名称 | 说明 | 告警阈值 |
|---------|------|---------|
| mcp_connection_success_rate | MCP 连接成功率 | < 95% |
| mcp_call_success_rate | 工具调用成功率 | < 90% |
| mcp_call_latency_p99 | 调用延迟 P99 | > 3s |
| fallback_usage_rate | Fallback 使用率 | > 20% |
| tool_call_timeout_rate | 超时率 | > 5% |

### 日志示例

```python
logger.info(
    "MCP tool call stats",
    extra={
        "tool_name": "market_data.get_stock_quote",
        "success": True,
        "source": "mcp",
        "latency_ms": 234,
        "attempt": 1
    }
)
```

---

## 11. 总结

### 核心优势

1. **无缝集成**：现有 Agent 代码改动最小化
2. **向后兼容**：完整的 fallback 机制，零风险
3. **渐进式迁移**：可以逐个工具迁移到 MCP
4. **可观测性**：完整的日志和监控体系
5. **高可用性**：连接失败不影响主流程

### 技术亮点

1. **适配器模式**：ToolAdapter 屏蔽底层差异
2. **异步上下文管理器**：自动管理连接生命周期
3. **单例模式**：避免重复创建 MCP Client
4. **工具缓存**：减少重复的工具发现调用
5. **错误隔离**：MCP 错误不影响主流程

### 预期改进

1. **统一工具管理**：所有工具通过 MCP 统一管理
2. **热更新能力**：无需重启即可添加新工具
3. **多语言支持**：未来可接入其他语言实现的工具
4. **安全隔离**：工具执行在独立进程中，更安全

### 下一步计划

1. 完成 Phase 1-4 改造
2. 迁移更多工具到 MCP（WebSearch、NewsCollection等）
3. 实现连接池和缓存优化
4. 添加监控面板
5. 编写最佳实践文档
