"""
Finance Research Assistant Backend for AgentFlow

将金融研投助手的工具集成到 AgentFlow 框架中
复用现有的 ToolExecutor 实现
"""

import os
import sys
import json
import asyncio
import logging
from typing import Dict, Any, List, Optional
from pathlib import Path

# 添加金融研投助手到路径
FRA_BACKEND_PATH = Path(__file__).parent.parent.parent / "financial-research-assistant" / "backend" / "app" / "service"
sys.path.insert(0, str(FRA_BACKEND_PATH.parent.parent))

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("FinanceResearchBackend")


class FinanceResearchBackendConfig:
    """金融研投助手 Backend 配置"""
    
    def __init__(self, config: Dict[str, Any] = None):
        config = config or {}
        
        # API Keys
        self.search_api_key = config.get('search_api_key', os.getenv('SEARCH_API_KEY', ''))
        self.llm_api_key = config.get('llm_api_key', os.getenv('LLM_API_KEY', ''))
        self.llm_base_url = config.get('llm_base_url', os.getenv('LLM_BASE_URL', 'https://api.openai.com/v1'))
        self.db_connection_string = config.get('db_connection_string', os.getenv('DB_CONNECTION_STRING', ''))
        
        # RAG 配置
        self.rag_kb_name = config.get('rag_kb_name', 'default')
        
        # 缓存配置
        self.cache_ttl = config.get('cache_ttl', 3600)
        self.enable_cache = config.get('enable_cache', True)


class FinanceResearchBackend:
    """
    金融研投助手 Backend for AgentFlow
    
    提供与金融研投助手完全一致的工具接口，用于 GRPO 训练数据合成
    
    支持的工具:
    - web_search: 网络搜索
    - knowledge_search: 本地知识库搜索
    - text2sql: SQL 查询
    - data_analyzer: 数据分析
    - chart_generator: 图表生成
    - stock_query: 股票查询
    - bidding_search: 招投标搜索
    - finish: 完成任务
    """
    
    config_class = FinanceResearchBackendConfig
    
    def __init__(self):
        self.config: Optional[FinanceResearchBackendConfig] = None
        self.tool_executor = None
        self.react_context = None
    
    async def initialize(self, config: Dict[str, Any] = None):
        """初始化 Backend"""
        self.config = FinanceResearchBackendConfig(config)
        
        # 延迟导入，避免循环依赖
        try:
            from service.tool_executor import ToolExecutor, ReActContext
            from service.react_controller import ToolType
            
            self.ToolType = ToolType
            self.ReActContext = ReActContext
            
            # 创建工具执行器
            self.tool_executor = ToolExecutor(
                search_api_key=self.config.search_api_key,
                llm_api_key=self.config.llm_api_key,
                llm_base_url=self.config.llm_base_url,
                db_connection_string=self.config.db_connection_string
            )
            
            logger.info("FinanceResearchBackend initialized successfully")
            
        except ImportError as e:
            logger.error(f"Failed to import financial research assistant modules: {e}")
            raise
    
    # ============ 工具方法 ============
    
    async def action_web_search(self, query: str, count: int = 5) -> Dict[str, Any]:
        """
        网络搜索
        
        Args:
            query: 搜索关键词
            count: 返回结果数量
            
        Returns:
            {
                "success": True,
                "results": [
                    {
                        "url": "...",
                        "name": "...",
                        "summary": "...",
                        "source": "web"
                    }
                ]
            }
        """
        self._ensure_context()
        
        result = await self.tool_executor.execute(
            tool_name=self.ToolType.WEB_SEARCH.value,
            params={"query": query, "count": count},
            context=self.react_context
        )
        
        return {
            "success": True,
            "results": result if isinstance(result, list) else [],
            "query": query
        }
    
    async def action_knowledge_search(self, query: str, kb_name: str = None, top_k: int = 5) -> Dict[str, Any]:
        """
        本地知识库搜索
        
        Args:
            query: 搜索关键词
            kb_name: 知识库名称
            top_k: 返回结果数量
            
        Returns:
            {
                "success": True,
                "results": [
                    {
                        "url": "local://...",
                        "name": "...",
                        "summary": "...",
                        "source": "local"
                    }
                ]
            }
        """
        self._ensure_context()
        
        kb_name = kb_name or self.config.rag_kb_name
        
        result = await self.tool_executor.execute(
            tool_name=self.ToolType.KNOWLEDGE_SEARCH.value,
            params={"query": query, "kb_name": kb_name, "top_k": top_k},
            context=self.react_context
        )
        
        return {
            "success": True,
            "results": result if isinstance(result, list) else [],
            "kb_name": kb_name
        }
    
    async def action_text2sql(self, question: str, intent: str = "stats") -> Dict[str, Any]:
        """
        自然语言转 SQL 查询
        
        Args:
            question: 自然语言问题
            intent: 查询意图 (stats/query/chart)
            
        Returns:
            {
                "success": True,
                "sql": "SELECT ...",
                "data": [...],
                "columns": [...]
            }
        """
        self._ensure_context()
        
        result = await self.tool_executor.execute(
            tool_name=self.ToolType.TEXT2SQL.value,
            params={"question": question, "intent": intent},
            context=self.react_context
        )
        
        return result if isinstance(result, dict) else {
            "success": False,
            "error": "Invalid result format",
            "data": []
        }
    
    async def action_data_analyzer(self, data: List = None, analysis_type: str = "auto") -> Dict[str, Any]:
        """
        智能数据分析
        
        Args:
            data: 要分析的数据（如果为 None，使用上下文中收集的数据）
            analysis_type: 分析类型 (auto/trend/comparison/summary)
            
        Returns:
            {
                "success": True,
                "insights": ["..."],
                "statistics": {...},
                "visualization_hint": "bar"
            }
        """
        self._ensure_context()
        
        result = await self.tool_executor.execute(
            tool_name=self.ToolType.DATA_ANALYZER.value,
            params={"data": data, "analysis_type": analysis_type},
            context=self.react_context
        )
        
        return result if isinstance(result, dict) else {
            "success": False,
            "error": "Invalid result format",
            "insights": [],
            "statistics": {}
        }
    
    async def action_chart_generator(self, data: Any, chart_type: str = "bar", title: str = "数据分析") -> Dict[str, Any]:
        """
        生成图表配置
        
        Args:
            data: 图表数据
            chart_type: 图表类型 (bar/line/pie/scatter)
            title: 图表标题
            
        Returns:
            {
                "type": "bar",
                "title": "...",
                "data": {...},
                "options": {...}
            }
        """
        self._ensure_context()
        
        result = await self.tool_executor.execute(
            tool_name=self.ToolType.CHART_GENERATOR.value,
            params={"data": data, "chart_type": chart_type, "title": title},
            context=self.react_context
        )
        
        return result if isinstance(result, dict) else {
            "type": chart_type,
            "title": title,
            "data": {},
            "options": {}
        }
    
    async def action_stock_query(self, stock_code: str = "", keyword: str = "") -> Dict[str, Any]:
        """
        股票信息查询
        
        Args:
            stock_code: 股票代码 (如 "000001.SZ")
            keyword: 搜索关键词（如果没有提供代码）
            
        Returns:
            {
                "success": True,
                "data": {
                    "code": "000001.SZ",
                    "name": "平安银行",
                    "price": 10.5,
                    "change": 0.02,
                    ...
                }
            }
        """
        self._ensure_context()
        
        result = await self.tool_executor.execute(
            tool_name=self.ToolType.STOCK_QUERY.value,
            params={"stock_code": stock_code, "keyword": keyword},
            context=self.react_context
        )
        
        return result if isinstance(result, dict) else {
            "success": False,
            "error": "Invalid result format",
            "data": None
        }
    
    async def action_bidding_search(self, keyword: str, category: str = None, region: str = None, page: int = 1) -> Dict[str, Any]:
        """
        招投标信息搜索
        
        Args:
            keyword: 搜索关键词
            category: 类别 (招标/中标/采购)
            region: 地区
            page: 页码
            
        Returns:
            {
                "success": True,
                "results": [...],
                "total": 100
            }
        """
        self._ensure_context()
        
        result = await self.tool_executor.execute(
            tool_name=self.ToolType.BIDDING_SEARCH.value,
            params={"keyword": keyword, "category": category, "region": region, "page": page},
            context=self.react_context
        )
        
        return result if isinstance(result, dict) else {
            "success": False,
            "error": "Invalid result format",
            "results": [],
            "total": 0
        }
    
    async def action_finish(self, summary: str = "") -> Dict[str, Any]:
        """
        完成任务
        
        Args:
            summary: 任务总结
            
        Returns:
            {
                "status": "finished",
                "summary": "...",
                "total_data_collected": 10
            }
        """
        self._ensure_context()
        
        result = await self.tool_executor.execute(
            tool_name=self.ToolType.FINISH.value,
            params={"summary": summary},
            context=self.react_context
        )
        
        return result if isinstance(result, dict) else {
            "status": "finished",
            "summary": summary,
            "total_data_collected": len(self.react_context.collected_data) if self.react_context else 0
        }
    
    # ============ 辅助方法 ============
    
    def _ensure_context(self):
        """确保 ReActContext 已创建"""
        if self.react_context is None:
            self.react_context = self.ReActContext(query="agentflow_session")
    
    def reset_context(self, query: str = ""):
        """重置上下文（用于新会话）"""
        self.react_context = self.ReActContext(query=query or "agentflow_session")
        logger.info(f"Context reset with query: {query}")
    
    def get_collected_data(self) -> List[Dict]:
        """获取收集的数据"""
        if self.react_context:
            return self.react_context.collected_data
        return []
    
    def get_insights(self) -> List[str]:
        """获取洞察"""
        if self.react_context:
            return self.react_context.insights
        return []


# ============ AgentFlow 集成 ============

class AgentFlowFinanceBackend:
    """
    AgentFlow 兼容的 Backend 包装器
    
    提供 AgentFlow 所需的接口:
    - initialize(): 初始化
    - action_*(): 工具方法
    """
    
    def __init__(self):
        self.backend = FinanceResearchBackend()
    
    async def initialize(self, config: Dict[str, Any] = None):
        """AgentFlow 初始化接口"""
        await self.backend.initialize(config)
    
    # 代理所有 action 方法到 backend
    async def action_web_search(self, **kwargs):
        return await self.backend.action_web_search(**kwargs)
    
    async def action_knowledge_search(self, **kwargs):
        return await self.backend.action_knowledge_search(**kwargs)
    
    async def action_text2sql(self, **kwargs):
        return await self.backend.action_text2sql(**kwargs)
    
    async def action_data_analyzer(self, **kwargs):
        return await self.backend.action_data_analyzer(**kwargs)
    
    async def action_chart_generator(self, **kwargs):
        return await self.backend.action_chart_generator(**kwargs)
    
    async def action_stock_query(self, **kwargs):
        return await self.backend.action_stock_query(**kwargs)
    
    async def action_bidding_search(self, **kwargs):
        return await self.backend.action_bidding_search(**kwargs)
    
    async def action_finish(self, **kwargs):
        return await self.backend.action_finish(**kwargs)


# ============ 工具定义导出 ============

def get_tool_definitions() -> List[Dict[str, Any]]:
    """
    获取工具定义列表（用于 AgentFlow 配置）
    
    Returns:
        工具定义列表，与金融研投助手完全一致
    """
    return [
        {
            "name": "web_search",
            "description": "执行网络搜索，获取网页信息。适用于获取最新的行业新闻、市场动态、公司公告等信息。",
            "parameters": {
                "query": {
                    "type": "string",
                    "description": "搜索关键词"
                },
                "count": {
                    "type": "integer",
                    "description": "返回结果数量（默认5）",
                    "default": 5
                }
            }
        },
        {
            "name": "knowledge_search",
            "description": "搜索本地知识库（研报、公告等）。适用于查询历史研究报告、公司公告等信息。",
            "parameters": {
                "query": {
                    "type": "string",
                    "description": "搜索关键词"
                },
                "kb_name": {
                    "type": "string",
                    "description": "知识库名称（默认使用配置中的知识库）"
                },
                "top_k": {
                    "type": "integer",
                    "description": "返回结果数量（默认5）",
                    "default": 5
                }
            }
        },
        {
            "name": "text2sql",
            "description": "将自然语言问题转换为 SQL 查询并执行。适用于查询结构化数据（如财务数据库）。",
            "parameters": {
                "question": {
                    "type": "string",
                    "description": "自然语言问题"
                },
                "intent": {
                    "type": "string",
                    "description": "查询意图（stats/query/chart）",
                    "default": "stats"
                }
            }
        },
        {
            "name": "data_analyzer",
            "description": "对收集的数据进行智能分析，提取洞察和统计信息。",
            "parameters": {
                "data": {
                    "type": "array",
                    "description": "要分析的数据（可选，默认使用已收集的数据）"
                },
                "analysis_type": {
                    "type": "string",
                    "description": "分析类型（auto/trend/comparison/summary）",
                    "default": "auto"
                }
            }
        },
        {
            "name": "chart_generator",
            "description": "根据数据生成图表配置（ECharts 格式）。",
            "parameters": {
                "data": {
                    "type": "object",
                    "description": "图表数据"
                },
                "chart_type": {
                    "type": "string",
                    "description": "图表类型（bar/line/pie/scatter）",
                    "default": "bar"
                },
                "title": {
                    "type": "string",
                    "description": "图表标题",
                    "default": "数据分析"
                }
            }
        },
        {
            "name": "stock_query",
            "description": "查询股票实时行情和基本信息。",
            "parameters": {
                "stock_code": {
                    "type": "string",
                    "description": "股票代码（如 000001.SZ）"
                },
                "keyword": {
                    "type": "string",
                    "description": "搜索关键词（如果没有提供代码）"
                }
            }
        },
        {
            "name": "bidding_search",
            "description": "搜索招投标信息。",
            "parameters": {
                "keyword": {
                    "type": "string",
                    "description": "搜索关键词"
                },
                "category": {
                    "type": "string",
                    "description": "类别（招标/中标/采购）"
                },
                "region": {
                    "type": "string",
                    "description": "地区"
                },
                "page": {
                    "type": "integer",
                    "description": "页码",
                    "default": 1
                }
            }
        },
        {
            "name": "finish",
            "description": "完成任务，返回研究总结。",
            "parameters": {
                "summary": {
                    "type": "string",
                    "description": "任务总结"
                }
            }
        }
    ]


if __name__ == "__main__":
    # 测试代码
    async def test():
        backend = FinanceResearchBackend()
        await backend.initialize({
            'search_api_key': os.getenv('SEARCH_API_KEY', ''),
            'llm_api_key': os.getenv('LLM_API_KEY', ''),
            'llm_base_url': os.getenv('LLM_BASE_URL', '')
        })
        
        # 测试 web_search
        result = await backend.action_web_search(query="保险行业 2024年发展趋势", count=3)
        print(json.dumps(result, indent=2, ensure_ascii=False))
    
    asyncio.run(test())
