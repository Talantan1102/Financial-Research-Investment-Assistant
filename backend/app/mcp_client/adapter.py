"""
Tool Adapter - MCP Client 统一封装

纯粹的 MCP 工具调用封装，无降级逻辑。
通过 MCP Client 统一调用所有 Skills 的工具。
"""

from typing import Any, Dict, List, Optional


class ToolAdapter:
    """
    MCP Tool 适配器（纯净版）

    纯粹的 MCP Client 封装，提供统一的工具调用接口。
    所有工具调用都通过 MCP Server 执行，无降级逻辑。

    使用示例：
        adapter = ToolAdapter(mcp_client=mcp_client)
        # 股票查询
        result = await adapter.get_stock_by_code("600519")
        # 网络搜索
        result = await adapter.web_search("新能源汽车市场")
        # 数据分析
        result = await adapter.analyze_data(data_list)
    """

    def __init__(self, mcp_client):
        """
        初始化 ToolAdapter

        Args:
            mcp_client: MCPClient 实例（必需）
        """
        if mcp_client is None:
            raise ValueError("MCP Client 是必需的，不能为 None")

        self.mcp_client = mcp_client

    async def _call_tool(self, tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """
        调用 MCP 工具

        通过渐进式披露机制调用：
        1. 解析 skill_name 和 tool_name
        2. 调用 execute_skill_tool 执行具体工具

        Args:
            tool_name: MCP 工具名（格式：skill_name.tool_name）
            arguments: 工具参数

        Returns:
            Dict[str, Any]: 调用结果
        """
        if not self.mcp_client or not self.mcp_client.is_connected:
            raise RuntimeError(f"MCP Client 未连接，无法调用工具: {tool_name}")

        # 解析 skill_name 和 tool_name
        if "." not in tool_name:
            raise ValueError(f"工具名格式错误，应为 'skill_name.tool_name': {tool_name}")

        parts = tool_name.split(".", 1)
        skill_name = parts[0]
        actual_tool_name = parts[1]

        # 通过 execute_skill_tool 调用
        return await self.mcp_client.call_tool(
            "execute_skill_tool",
            {
                "skill_name": skill_name,
                "tool_name": actual_tool_name,
                "arguments": arguments
            }
        )

    # ========== Market Data 工具 ==========

    async def get_stock_by_code(self, stock_code: str) -> Dict[str, Any]:
        """获取股票行情数据"""
        return await self._call_tool(
            "market_data.get_quote",
            {"symbol": stock_code}
        )

    async def search_stock(self, keyword: str) -> Dict[str, Any]:
        """搜索股票"""
        return await self._call_tool(
            "market_data.search_stock",
            {"keyword": keyword}
        )

    # ========== Web Research 工具 ==========

    async def web_search(
        self,
        query: str,
        count: int = 5,
        freshness: Optional[str] = None
    ) -> Dict[str, Any]:
        """网络搜索"""
        arguments = {"query": query, "count": count}
        if freshness:
            arguments["freshness"] = freshness

        return await self._call_tool("web_research.web_search", arguments)

    async def knowledge_search(
        self,
        query: str,
        kb_name: str = "",
        top_k: int = 5
    ) -> Dict[str, Any]:
        """知识库搜索"""
        arguments = {"query": query, "top_k": top_k}
        if kb_name:
            arguments["kb_name"] = kb_name

        return await self._call_tool("web_research.knowledge_search", arguments)

    async def deep_search(
        self,
        query: str,
        sub_queries: Optional[List[str]] = None,
        max_depth: int = 2,
        cross_verify: bool = True
    ) -> Dict[str, Any]:
        """深度搜索"""
        arguments = {
            "query": query,
            "max_depth": max_depth,
            "cross_verify": cross_verify
        }
        if sub_queries:
            arguments["sub_queries"] = sub_queries

        return await self._call_tool("web_research.deep_search", arguments)

    async def batch_search(
        self,
        queries: List[Dict],
        search_type: str = "web"
    ) -> Dict[str, Any]:
        """批量搜索"""
        return await self._call_tool(
            "web_research.batch_search",
            {"queries": queries, "search_type": search_type}
        )

    async def extract_webpage(
        self,
        url: str,
        extract_type: str = "article"
    ) -> Dict[str, Any]:
        """提取网页内容"""
        return await self._call_tool(
            "web_research.extract_webpage",
            {"url": url, "extract_type": extract_type}
        )

    # ========== Data Analysis 工具 ==========

    async def analyze_data(
        self,
        data: List[Dict],
        analysis_type: str = "auto",
        context: str = ""
    ) -> Dict[str, Any]:
        """智能数据分析"""
        arguments = {"data": data, "analysis_type": analysis_type}
        if context:
            arguments["context"] = context

        return await self._call_tool("data_analysis.analyze_data", arguments)

    async def generate_chart(
        self,
        data: Dict,
        chart_type: str = "bar",
        title: str = "数据图表",
        options: Optional[Dict] = None
    ) -> Dict[str, Any]:
        """生成图表配置"""
        arguments = {"data": data, "chart_type": chart_type, "title": title}
        if options:
            arguments["options"] = options

        return await self._call_tool("data_analysis.generate_chart", arguments)

    async def text_to_sql(
        self,
        question: str,
        intent: str = "stats",
        table_hints: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """自然语言转 SQL"""
        arguments = {"question": question, "intent": intent}
        if table_hints:
            arguments["table_hints"] = table_hints

        return await self._call_tool("data_analysis.text_to_sql", arguments)

    async def calculate_metrics(
        self,
        data: List[Dict],
        metrics: List[str],
        value_field: str = "value",
        time_field: str = "time"
    ) -> Dict[str, Any]:
        """计算金融指标"""
        return await self._call_tool(
            "data_analysis.calculate_metrics",
            {
                "data": data,
                "metrics": metrics,
                "value_field": value_field,
                "time_field": time_field
            }
        )

    # ========== Financial Analysis 工具 ==========

    async def analyze_financial_report(
        self,
        symbol: str,
        report_type: str = "income"
    ) -> Dict[str, Any]:
        """分析财务报表"""
        return await self._call_tool(
            "financial_analysis.analyze_report",
            {"symbol": symbol, "report_type": report_type}
        )

    async def calculate_financial_ratios(self, symbol: str) -> Dict[str, Any]:
        """计算财务比率"""
        return await self._call_tool(
            "financial_analysis.calculate_ratios",
            {"symbol": symbol}
        )

    async def analyze_business(self, symbol: str) -> Dict[str, Any]:
        """分析经营情况"""
        return await self._call_tool(
            "financial_analysis.analyze_business",
            {"symbol": symbol}
        )

    # ========== Risk Assessment 工具 ==========

    async def assess_risk(self, symbol: str) -> Dict[str, Any]:
        """风险评估"""
        return await self._call_tool(
            "risk_assessment.assess",
            {"symbol": symbol}
        )

    async def predict_risk(self, symbol: str, days: int = 30) -> Dict[str, Any]:
        """风险预测"""
        return await self._call_tool(
            "risk_assessment.predict",
            {"symbol": symbol, "days": days}
        )

    async def monitor_risk(self, symbol: str) -> Dict[str, Any]:
        """风险监控"""
        return await self._call_tool(
            "risk_assessment.monitor",
            {"symbol": symbol}
        )

    # ========== Deep Research 工具 ==========

    async def research_plan(self, query: str) -> Dict[str, Any]:
        """研究规划"""
        return await self._call_tool(
            "deep_research.plan",
            {"query": query}
        )

    async def research_search(self, session_id: str) -> Dict[str, Any]:
        """研究搜索"""
        return await self._call_tool(
            "deep_research.search",
            {"session_id": session_id}
        )

    async def research_analyze(self, session_id: str) -> Dict[str, Any]:
        """研究分析"""
        return await self._call_tool(
            "deep_research.analyze",
            {"session_id": session_id}
        )

    async def research_write(self, session_id: str) -> Dict[str, Any]:
        """研究报告撰写"""
        return await self._call_tool(
            "deep_research.write",
            {"session_id": session_id}
        )

    # ========== 状态检查 ==========

    @property
    def is_connected(self) -> bool:
        """检查 MCP Client 是否已连接"""
        return self.mcp_client is not None and self.mcp_client.is_connected
