"""
HTTP Service Server - FastAPI Application with MCP Native Support

Server 核心容器，支持两种后端：
1. 传统 Backend（使用 @tool 装饰器）
2. MCP Native Backend（直接暴露原生 MCP 方法）

Usage examples:

1. Load MCP Native Backend（推荐）:
```python
from sandbox.server import HTTPServiceServer
from sandbox.server.backends.resources import UnifiedFinanceMCPBackend

server = HTTPServiceServer(host="0.0.0.0", port=8080)
server.load_mcp_backend(UnifiedFinanceMCPBackend())
server.run()
```

2. Load traditional Backend:
```python
from sandbox.server import HTTPServiceServer
from sandbox.server.backends.resources import VMBackend

server = HTTPServiceServer(host="0.0.0.0", port=8080)
server.load_backend(VMBackend())
server.run()
```
"""

import asyncio
import logging
from typing import Dict, Any, Optional, Callable, List, TYPE_CHECKING, Union
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .core import ResourceRouter, ToolExecutor, scan_tools
from .backends.base import Backend, BackendConfig
from .backends.mcp_native_base import MCPNativeBackend, MCPBackendConfig
from .routes import register_routes

if TYPE_CHECKING:
    from .backends.mcp_native_base import MCPResource, MCPTool

logger = logging.getLogger("HTTPServiceServer")


class HTTPServiceServer:
    """
    HTTP Service Server - 支持传统 Backend 和 MCP Native Backend
    """
    
    def __init__(
        self,
        host: str = "0.0.0.0",
        port: int = 8080,
        title: str = "HTTP Service Server",
        description: str = "Independent HTTP Service with JSON protocol",
        version: str = "1.0.0",
        enable_cors: bool = True,
        session_ttl: int = 300,
        warmup_resources: Optional[List[str]] = None
    ):
        self.host = host
        self.port = port
        self.title = title
        self.description = description
        self.version = version
        self.enable_cors = enable_cors
        self.warmup_resources = warmup_resources or []
        self.session_ttl = session_ttl

        # ====================================================================
        # 传统 Backend 数据 structures
        # ====================================================================
        self._tools: Dict[str, Callable] = {}
        self._tool_name_index: Dict[str, List[str]] = {}
        self._tool_resource_types: Dict[str, str] = {}
        
        # ====================================================================
        # MCP Native Backend 存储
        # ====================================================================
        self._mcp_backends: Dict[str, MCPNativeBackend] = {}
        
        # ====================================================================
        # 传统 Backend 存储
        # ====================================================================
        self._backends: Dict[str, Backend] = {}
        
        # ====================================================================
        # 核心组件
        # ====================================================================
        self.resource_router = ResourceRouter(session_ttl=session_ttl)
        self._executor = ToolExecutor(
            tools=self._tools,
            tool_name_index=self._tool_name_index,
            tool_resource_types=self._tool_resource_types,
            resource_router=self.resource_router,
            warmup_callback=lambda backend_name: self.ensure_backend_warmed_up(backend_name)
        )
        
        # Warmup 状态
        self._warmed_up_backends: Dict[str, bool] = {}
        self._warmed_up_mcp_backends: Dict[str, bool] = {}
        self._warmup_lock = asyncio.Lock()
        
        # FastAPI
        self._app: Optional[FastAPI] = None
        self._cleanup_task: Optional[asyncio.Task] = None
    
    # ========================================================================
    # MCP Native Backend 加载
    # ========================================================================
    
    def load_mcp_backend(self, backend) -> str:
        """
        加载 MCP Native Backend（支持金融研投助手模式的 FinanceResearchBackend）
        
        Args:
            backend: MCP Backend 实例（FinanceResearchBackend 或 MCPNativeBackend）
            
        Returns:
            Backend 名称
        """
        # 获取 backend 名称
        backend_name = getattr(backend, 'name', backend.__class__.__name__)
        
        # 绑定 server（如果支持）
        if hasattr(backend, 'bind_server'):
            backend.bind_server(self)
        
        self._mcp_backends[backend_name] = backend
        
        # 注册 MCP 工具（与金融研投助手对齐）
        # Round 1: Skill 选择
        self.register_tool("skill", backend.skill)
        self.register_tool("select_skill", backend.select_skill)  # 向后兼容
        
        # Round 2: 获取工具列表
        self.register_tool("get_skill_tools", backend.get_skill_tools)
        
        # Round 3: 执行具体工具
        self.register_tool("execute_skill_tool", backend.execute_skill_tool)
        
        # 尝试同步 warmup（如果 warmup 是同步的或已经执行过）
        if hasattr(backend, 'skills') and backend.skills:
            # skills 已存在，直接注册具体工具
            registered_count = 0
            for skill_name, skill in backend.skills.items():
                if hasattr(skill, 'discover_tools_json'):
                    tools = skill.discover_tools_json()
                    for tool in tools:
                        tool_name = tool.get('name')
                        if tool_name:
                            full_name = f"{skill_name}.{tool_name}"
                            # 创建一个闭包来捕获 skill_name 和 tool_name
                            def make_tool_executor(sn, tn, be=backend):
                                async def tool_executor(*args, worker_id=None, timeout=None, trace_id=None, session_id=None, session_info=None, **kwargs):
                                    # 过滤掉执行器注入的参数，只保留原始工具参数
                                    clean_args = {k: v for k, v in kwargs.items() if k not in ['worker_id', 'timeout', 'trace_id', 'session_id', 'session_info']}
                                    return await be.execute_skill_tool(sn, tn, clean_args)
                                return tool_executor
                            self.register_tool(full_name, make_tool_executor(skill_name, tool_name))
                            registered_count += 1
            logger.info(f"✅ MCP Backend loaded: {backend_name} (registered: skill + {registered_count} specific tools)")
        else:
            # skills 不存在，标记为需要延迟注册
            logger.info(f"✅ MCP Backend loaded: {backend_name} (registered: 4 core tools, specific tools will be registered after warmup)")
        
        return backend_name
    
    def get_mcp_backend(self, name: str) -> Optional[MCPNativeBackend]:
        """获取 MCP Backend"""
        return self._mcp_backends.get(name)
    
    def list_mcp_backends(self) -> List[str]:
        """列出所有 MCP Backend"""
        return list(self._mcp_backends.keys())
    
    async def warmup_mcp_backend(self, backend_name: str) -> bool:
        """Warmup MCP Backend - 注册具体工具"""
        async with self._warmup_lock:
            if self._warmed_up_mcp_backends.get(backend_name):
                return True
            
            backend = self._mcp_backends.get(backend_name)
            if not backend:
                logger.warning(f"MCP Backend not found: {backend_name}")
                return False
            
            try:
                logger.info(f"🔥 Warming up MCP backend: {backend_name}")
                await backend.warmup()
                self._warmed_up_mcp_backends[backend_name] = True
                logger.info(f"✅ MCP Backend warmed up: {backend_name}")
                
                # warmup 后注册所有具体工具
                if hasattr(backend, 'skills') and backend.skills:
                    registered_count = 0
                    for skill_name, skill in backend.skills.items():
                        if hasattr(skill, 'discover_tools_json'):
                            tools = skill.discover_tools_json()
                            for tool in tools:
                                tool_name = tool.get('name')
                                if tool_name:
                                    full_name = f"{skill_name}.{tool_name}"
                                    # 检查是否已注册
                                    if full_name not in self._tools:
                                        def make_tool_executor(sn, tn):
                                            async def tool_executor(*args, worker_id=None, timeout=None, trace_id=None, session_id=None, session_info=None, **kwargs):
                                                # 过滤掉执行器注入的参数
                                                clean_args = {k: v for k, v in kwargs.items() if k not in ['worker_id', 'timeout', 'trace_id', 'session_id', 'session_info']}
                                                return await backend.execute_skill_tool(sn, tn, clean_args)
                                            return tool_executor
                                        self.register_tool(full_name, make_tool_executor(skill_name, tool_name))
                                        registered_count += 1
                    logger.info(f"✅ Registered {registered_count} specific tools from {backend_name}")
                
                return True
            except Exception as e:
                logger.error(f"❌ MCP Backend warmup failed: {backend_name}: {e}")
                return False
    
    # ========================================================================
    # MCP 端点处理 - 金融研投助手模式（3个工具）
    # ========================================================================
    
    async def _handle_mcp_select_skill(
        self, 
        backend_name: str,
        skill_name: str,
        reason: str
    ) -> Dict[str, Any]:
        """处理 select_skill 请求 - 金融研投助手模式"""
        backend = self._mcp_backends.get(backend_name)
        if not backend:
            return {"error": f"MCP Backend '{backend_name}' not found"}
        
        await self.warmup_mcp_backend(backend_name)
        
        try:
            result = await backend.select_skill(skill_name, reason)
            return result
        except Exception as e:
            logger.error(f"select_skill error: {e}")
            return {"success": False, "error": str(e)}
    
    async def _handle_mcp_get_skill_tools(
        self, 
        backend_name: str,
        name: str
    ) -> Dict[str, Any]:
        """处理 get_skill_tools 请求 - 金融研投助手模式"""
        backend = self._mcp_backends.get(backend_name)
        if not backend:
            return {"error": f"MCP Backend '{backend_name}' not found"}
        
        await self.warmup_mcp_backend(backend_name)
        
        try:
            result = await backend.get_skill_tools(name)
            return result
        except Exception as e:
            logger.error(f"get_skill_tools error: {e}")
            return {"success": False, "error": str(e)}
    
    async def _handle_mcp_execute_skill_tool(
        self, 
        backend_name: str,
        skill_name: str,
        tool_name: str,
        arguments: Dict[str, Any]
    ) -> Dict[str, Any]:
        """处理 execute_skill_tool 请求 - 金融研投助手模式"""
        backend = self._mcp_backends.get(backend_name)
        if not backend:
            return {"error": f"MCP Backend '{backend_name}' not found"}
        
        await self.warmup_mcp_backend(backend_name)
        
        try:
            result = await backend.execute_skill_tool(skill_name, tool_name, arguments)
            return result
        except Exception as e:
            logger.error(f"execute_skill_tool error: {e}")
            return {"success": False, "error": str(e)}
            return {"success": False, "error": str(e)}
    
    # ========================================================================
    # 传统 Backend 方法（保留）
    # ========================================================================
    
    def load_backend(self, backend: Backend) -> List[str]:
        """加载 Backend（自动检测是否是 MCP-style Backend）"""
        # 检测是否是 MCP-style Backend（有 select_skill, get_skill_tools, execute_skill_tool 方法）
        is_mcp_backend = (
            hasattr(backend, 'select_skill') and
            hasattr(backend, 'get_skill_tools') and
            hasattr(backend, 'execute_skill_tool')
        )
        
        if is_mcp_backend:
            # 使用 MCP Backend 加载逻辑
            self.load_mcp_backend(backend)
            # 返回空列表（MCP tools 通过不同方式统计）
            return []
        
        # 传统 Backend 加载逻辑
        backend.bind_server(self)
        self._backends[backend.name] = backend
        
        self.register_resource_type(
            resource_type=backend.name,
            initializer=backend.initialize,
            cleaner=backend.cleanup,
            default_config=backend.get_default_config()
        )
        
        registered = self.scan_and_register(backend, prefix=backend.name)
        logger.info(f"✅ Backend loaded: {backend.name} ({len(registered)} tools)")
        return registered
    
    def register_tool(self, name: str, func: Callable, resource_type: Optional[str] = None):
        """注册工具"""
        simple_name = name
        actual_resource_type = resource_type
        
        if ":" in name:
            parts = name.split(":", 1)
            actual_resource_type = parts[0]
            simple_name = parts[1]
        
        if actual_resource_type:
            full_name = f"{actual_resource_type}:{simple_name}"
        else:
            full_name = simple_name
        
        self._tools[full_name] = func
        
        if simple_name not in self._tool_name_index:
            self._tool_name_index[simple_name] = []
        if full_name not in self._tool_name_index[simple_name]:
            self._tool_name_index[simple_name].append(full_name)
        
        if actual_resource_type:
            self._tool_resource_types[full_name] = actual_resource_type
    
    def scan_and_register(self, obj: Any, prefix: Optional[str] = None) -> List[str]:
        """扫描并注册工具"""
        registered = []
        tools = scan_tools(obj, prefix)
        
        for tool_info in tools:
            name = tool_info["name"]
            func = tool_info["func"]
            resource_type = tool_info.get("resource_type")
            self.register_tool(name, func, resource_type=resource_type)
            registered.append(name)
        
        return registered

    def list_tools(self, include_hidden: bool = False) -> List[Dict[str, Any]]:
        """列出所有可用工具（包含 MCP 工具）"""
        tools = []
        print(f"[DEBUG] list_tools called, _tools has {len(self._tools)} items")
        print(f"[DEBUG] _tools keys: {list(self._tools.keys())}")

        # 系统内部工具，不应暴露给 LLM
        # 这些工具由编排层自动调用，LLM 不应直接调用
        INTERNAL_TOOLS = {"get_skill_tools", "execute_skill_tool", "select_skill"}

        for full_name, func in self._tools.items():
            if not include_hidden and full_name.startswith("_"):
                continue

            # 过滤系统内部工具（LLM 不应直接调用）
            tool_base_name = full_name.split(":")[-1]  # 处理 "resource:tool_name" 格式
            if tool_base_name in INTERNAL_TOOLS:
                print(f"[DEBUG] Filtering out internal tool: {full_name}")
                continue

            # 获取工具描述
            doc = getattr(func, "__doc__", "") or ""
            # 提取第一行作为简短描述
            short_desc = doc.strip().split("\n")[0] if doc else ""

            tools.append({
                "name": full_name,
                "full_name": full_name,
                "description": short_desc,
            })
        return tools
    
    async def execute(self, action: str, params: Dict[str, Any], **kwargs) -> Dict[str, Any]:
        """执行工具 - 支持与金融研投助手一致的直接工具调用"""
        # 支持直接工具调用格式: skill_name.tool_name
        if "." in action and action not in self._tools:
            # 尝试解析为 execute_skill_tool 调用
            parts = action.split(".", 1)
            if len(parts) == 2:
                skill_name, tool_name = parts
                # 转换为 execute_skill_tool 调用
                converted_params = {
                    "skill_name": skill_name,
                    "tool_name": tool_name,
                    "arguments": params
                }
                return await self._executor.execute("execute_skill_tool", converted_params, **kwargs)
        
        # 标准工具调用
        return await self._executor.execute(action, params, **kwargs)
    
    async def ensure_backend_warmed_up(self, backend_name: str) -> bool:
        """确保 Backend 已 warmup"""
        if self._warmed_up_backends.get(backend_name):
            return True
        
        backend = self._backends.get(backend_name)
        if not backend:
            return False
        
        async with self._warmup_lock:
            if self._warmed_up_backends.get(backend_name):
                return True
            
            try:
                await backend.warmup()
                self._warmed_up_backends[backend_name] = True
                return True
            except Exception as e:
                logger.error(f"Warmup failed: {backend_name}: {e}")
                return False
    
    def register_resource_type(self, resource_type: str, **kwargs):
        """注册资源类型"""
        self.resource_router.register_resource_type(resource_type, **kwargs)
    
    # ========================================================================
    # FastAPI Application
    # ========================================================================
    
    def create_app(self) -> FastAPI:
        """创建 FastAPI 应用"""
        
        @asynccontextmanager
        async def lifespan(app: FastAPI):
            logger.info("HTTP Service Server starting...")
            
            # Warmup MCP Backends
            for name in self._mcp_backends.keys():
                await self.warmup_mcp_backend(name)
            
            # Warmup 传统 Backends
            for name in self.warmup_resources or []:
                if name in self._backends:
                    await self.ensure_backend_warmed_up(name)
            
            print("=" * 80)
            print("✅ Server ready!")
            print(f"🌐 Access URL: http://{self.host}:{self.port}")
            print(f"📖 API Docs: http://{self.host}:{self.port}/docs")
            print("=" * 80)
            
            yield
            
            logger.info("Server shutting down...")
            # Shutdown MCP Backends
            for backend in self._mcp_backends.values():
                try:
                    await backend.shutdown()
                except Exception as e:
                    logger.error(f"Shutdown error: {e}")
            
            # Shutdown 传统 Backends
            for backend in self._backends.values():
                try:
                    await backend.shutdown()
                except Exception as e:
                    logger.error(f"Shutdown error: {e}")
        
        app = FastAPI(
            title=self.title,
            description=self.description,
            version=self.version,
            lifespan=lifespan
        )
        
        if self.enable_cors:
            app.add_middleware(
                CORSMiddleware,
                allow_origins=["*"],
                allow_credentials=True,
                allow_methods=["*"],
                allow_headers=["*"],
            )
        
        # 注册传统路由
        register_routes(app, self)
        
        # 注册 MCP 路由
        self._register_mcp_routes(app)
        
        self._app = app
        return app
    
    def _register_mcp_routes(self, app: FastAPI):
        """注册 MCP 端点"""
        
        # MCP 元信息端点
        @app.get("/mcp/backends")
        async def list_mcp_backends():
            """列出所有 MCP Backends"""
            return {
                "backends": [
                    {
                        "name": name,
                        "description": backend.description,
                        "version": backend.version
                    }
                    for name, backend in self._mcp_backends.items()
                ]
            }
        
        # ==================== 金融研投助手模式端点 ====================
        
        # select_skill 端点
        @app.post("/mcp/{backend_name}/skills/select")
        async def mcp_select_skill(
            backend_name: str,
            request: Dict[str, Any]
        ):
            """MCP: select_skill - 金融研投助手模式"""
            skill_name = request.get("skill_name")
            reason = request.get("reason", "")
            
            if not skill_name:
                return JSONResponse(
                    status_code=400, 
                    content={"success": False, "error": "Missing 'skill_name' field"}
                )
            
            result = await self._handle_mcp_select_skill(backend_name, skill_name, reason)
            return result
        
        # get_skill_tools 端点
        @app.get("/mcp/{backend_name}/skills/{skill_name}/tools")
        async def mcp_get_skill_tools(
            backend_name: str,
            skill_name: str
        ):
            """MCP: get_skill_tools - 金融研投助手模式"""
            result = await self._handle_mcp_get_skill_tools(backend_name, skill_name)
            return result
        
        # execute_skill_tool 端点
        @app.post("/mcp/{backend_name}/tools/execute")
        async def mcp_execute_skill_tool(
            backend_name: str,
            request: Dict[str, Any]
        ):
            """MCP: execute_skill_tool - 金融研投助手模式"""
            skill_name = request.get("skill_name")
            tool_name = request.get("tool_name")
            arguments = request.get("arguments", {})
            
            if not skill_name or not tool_name:
                return JSONResponse(
                    status_code=400, 
                    content={"success": False, "error": "Missing 'skill_name' or 'tool_name' field"}
                )
            
            result = await self._handle_mcp_execute_skill_tool(
                backend_name, skill_name, tool_name, arguments
            )
            return result
            
            if not name:
                return JSONResponse(
                    status_code=400, 
                    content={"error": "Missing 'name' field"}
                )
            
    def run(self, **kwargs):
        """启动服务器"""
        import uvicorn
        app = self.create_app()
        logger.info(f"Starting server on {self.host}:{self.port}")
        uvicorn.run(app, host=self.host, port=self.port, **kwargs)
