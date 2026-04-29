# Copyright © 2026 深圳市深维智见教育科技有限公司 版权所有
# 未经授权，禁止转售或仿制。

"""WebResearch Skill - 网络搜索工具

基于博查AI开放平台 API，提供真实的网络信息搜索功能。
博查API文档: https://open.bochaai.com/
"""

import os
from typing import Any, Literal

import aiohttp

from app.mcp_server.skills.base import BaseSkill, ToolParameter, ToolResult


class WebResearchSkill(BaseSkill):
    """
    网络搜索 Skill

    基于博查AI开放平台 API，提供真实的网络信息搜索，
    获取新闻、公告、研报等外部信息。
    """

    name = "web_research"
    description = "网络信息搜索，基于博查AI开放平台获取真实新闻、公告、研报等外部信息"

    def __init__(self):
        super().__init__()
        self.api_key = os.getenv("BOCHA_API_KEY", "")
        self.base_url = "https://api.bochaai.com/v1/web-search"
        self.use_mock = os.getenv("USE_MOCK_BOCHA", "false").lower() == "true"

    def _register_tools(self):
        """注册 WebResearch 相关工具"""

        # 1. 搜索股票新闻
        self.register_tool(
            name="search_stock_news",
            handler=self.search_stock_news,
            description="搜索指定股票的最新新闻",
            parameters=[
                ToolParameter(
                    name="ts_code",
                    type="string",
                    description="TS股票代码，如 600519.SH",
                    required=True,
                ),
                ToolParameter(
                    name="days",
                    type="integer",
                    description="搜索最近几天的新闻",
                    required=False,
                    default=7,
                ),
                ToolParameter(
                    name="limit",
                    type="integer",
                    description="返回新闻数量",
                    required=False,
                    default=10,
                ),
            ],
        )

        # 2. 搜索公司公告
        self.register_tool(
            name="search_company_announcements",
            handler=self.search_company_announcements,
            description="搜索指定公司的公告",
            parameters=[
                ToolParameter(
                    name="ts_code",
                    type="string",
                    description="TS股票代码，如 600519.SH",
                    required=True,
                ),
                ToolParameter(
                    name="category",
                    type="string",
                    description="公告类型：all(全部), report(定期报告), major(重大事项), disclosure(信息披露)",
                    required=False,
                    default="all",
                ),
                ToolParameter(
                    name="limit",
                    type="integer",
                    description="返回公告数量",
                    required=False,
                    default=10,
                ),
            ],
        )

        # 3. 搜索行业新闻
        self.register_tool(
            name="search_industry_news",
            handler=self.search_industry_news,
            description="搜索指定行业的最新新闻",
            parameters=[
                ToolParameter(
                    name="industry",
                    type="string",
                    description="行业名称，如'白酒'、'新能源'",
                    required=True,
                ),
                ToolParameter(
                    name="days",
                    type="integer",
                    description="搜索最近几天的新闻",
                    required=False,
                    default=7,
                ),
                ToolParameter(
                    name="limit",
                    type="integer",
                    description="返回新闻数量",
                    required=False,
                    default=10,
                ),
            ],
        )

        # 4. 搜索研报
        self.register_tool(
            name="search_research_reports",
            handler=self.search_research_reports,
            description="搜索指定股票或行业的研究报告",
            parameters=[
                ToolParameter(
                    name="keyword",
                    type="string",
                    description="搜索关键词，可以是股票名称或行业名称",
                    required=True,
                ),
                ToolParameter(
                    name="report_type",
                    type="string",
                    description="研报类型：all(全部), rating(评级), earnings(盈利预测), industry(行业)",
                    required=False,
                    default="all",
                ),
                ToolParameter(
                    name="limit",
                    type="integer",
                    description="返回研报数量",
                    required=False,
                    default=5,
                ),
            ],
        )

    def _extract_stock_name(self, ts_code: str) -> str:
        """从股票代码提取股票名称（简化版，实际应从数据库查询）"""
        stock_names = {
            "600519.SH": "贵州茅台",
            "000858.SZ": "五粮液",
            "600809.SH": "山西汾酒",
            "300750.SZ": "宁德时代",
            "688981.SH": "中芯国际",
            "600036.SH": "招商银行",
            "000001.SZ": "平安银行",
        }
        return stock_names.get(ts_code, ts_code)

    async def _call_bocha_api(
        self, query: str, freshness: str = "Month", count: int = 10
    ) -> dict[str, Any]:
        """
        调用博查AI搜索API或使用Mock服务

        Args:
            query: 搜索查询
            freshness: 时间范围 (Day, Week, Month, Year)
            count: 返回结果数量

        Returns:
            API响应数据
        """
        # 如果启用mock，调用mock服务
        if self.use_mock:
            return await self._call_mock_bocha(query, freshness, count)

        if not self.api_key:
            return {"success": False, "error": "BOCHA_API_KEY 未配置，请在环境变量中设置"}

        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}

        payload = {
            "query": query,
            "freshness": freshness,
            "count": min(count, 10),  # API限制最大10条
            "summary": True,  # 启用AI摘要
        }

        try:
            async with (
                aiohttp.ClientSession() as session,
                session.post(
                    self.base_url,
                    headers=headers,
                    json=payload,
                    timeout=aiohttp.ClientTimeout(total=30),
                ) as response,
            ):
                if response.status == 200:
                    data = await response.json()
                    return {"success": True, "data": data}
                else:
                    error_text = await response.text()
                    return {
                        "success": False,
                        "error": f"API请求失败 (状态码: {response.status}): {error_text}",
                    }
        except aiohttp.ClientTimeout:
            return {"success": False, "error": "请求超时"}
        except Exception as e:
            return {"success": False, "error": f"请求异常: {str(e)}"}

    def _infer_search_type(
        self, query: str
    ) -> Literal["news", "announcement", "industry", "report"]:
        """
        从查询字符串推断搜索类型

        Args:
            query: 搜索查询

        Returns:
            搜索类型
        """
        query_lower = query.lower()

        # 检查公告特征
        if any(
            kw in query_lower
            for kw in [
                "公告",
                "年报",
                "季报",
                "site:cninfo.com.cn",
                "site:szse.cn",
                "site:sse.com.cn",
            ]
        ):
            return "announcement"

        # 检查研报特征
        if any(kw in query_lower for kw in ["研报", "研究报告", "评级", "买入", "增持"]):
            return "report"

        # 检查行业特征（行业+新闻，且没有具体股票代码格式）
        if "行业" in query and "新闻" in query and "." not in query:
            return "industry"

        # 默认为新闻
        return "news"

    async def _call_mock_bocha(self, query: str, freshness: str, count: int) -> dict[str, Any]:
        """
        调用mock服务生成搜索结果

        Args:
            query: 搜索查询
            freshness: 时间范围
            count: 返回结果数量

        Returns:
            Mock API响应数据

        Raises:
            Exception: 异常直接抛出，不做降级处理
        """
        from app.service.mock_bocha_service import MockBochaService

        mock_service = MockBochaService()
        search_type = self._infer_search_type(query)

        results = await mock_service.generate_search_results(
            query=query, search_type=search_type, count=min(count, 10), freshness=freshness
        )

        return {"success": True, "data": results}

    def _parse_bocha_results(self, api_response: dict, limit: int) -> list[dict]:
        """解析博查API返回结果"""
        results = []

        if not api_response.get("success"):
            return results

        # 处理嵌套结构: response -> data -> webPages -> value
        outer_data = api_response.get("data", {})
        # 可能是直接的 SearchResponse 或嵌套在 data 中
        search_response = outer_data if "webPages" in outer_data else outer_data.get("data", {})

        web_pages = search_response.get("webPages", {})
        items = web_pages.get("value", [])

        for item in items[:limit]:
            results.append(
                {
                    "title": item.get("name", ""),
                    "url": item.get("url", ""),
                    "source": item.get("siteName", ""),
                    "date": item.get("datePublished", ""),
                    "summary": item.get("summary", item.get("snippet", "")),
                }
            )

        return results

    async def search_stock_news(self, ts_code: str, days: int = 7, limit: int = 10) -> ToolResult:
        """
        搜索股票新闻 - 使用博查AI API或Mock服务

        Args:
            ts_code: 股票代码
            days: 搜索最近几天
            limit: 返回数量

        Returns:
            ToolResult: 搜索结果
        """
        if not ts_code:
            return ToolResult(success=False, error="股票代码不能为空")

        try:
            stock_name = self._extract_stock_name(ts_code)

            # 构建搜索查询
            query = f"{stock_name} {ts_code.split('.')[0]} 新闻"

            # 根据days设置freshness
            if days <= 1:
                freshness = "Day"
            elif days <= 7:
                freshness = "Week"
            elif days <= 30:
                freshness = "Month"
            else:
                freshness = "Year"

            # 调用博查API或Mock服务
            api_result = await self._call_bocha_api(query, freshness, limit)

            if not api_result["success"]:
                return ToolResult(
                    success=False, error=f"搜索失败: {api_result.get('error', '未知错误')}"
                )

            # 解析结果
            news_list = self._parse_bocha_results(api_result, limit)

            data_source = "Mock博查服务" if self.use_mock else "博查AI开放平台"

            return ToolResult(
                success=True,
                data={
                    "ts_code": ts_code,
                    "news": news_list,
                    "count": len(news_list),
                    "search_period": f"最近{days}天",
                    "data_source": data_source,
                },
            )

        except Exception as e:
            return ToolResult(success=False, error=f"搜索股票新闻失败: {str(e)}")

    async def search_company_announcements(
        self, ts_code: str, category: str = "all", limit: int = 10
    ) -> ToolResult:
        """
        搜索公司公告 - 使用博查AI API

        Args:
            ts_code: 股票代码
            category: 公告类型
            limit: 返回数量

        Returns:
            ToolResult: 搜索结果
        """
        if not ts_code:
            return ToolResult(success=False, error="股票代码不能为空")

        try:
            stock_name = self._extract_stock_name(ts_code)

            # 根据类别构建查询
            category_keywords = {
                "report": "年报 季报 定期报告",
                "major": "重大事项 重大合同",
                "disclosure": "信息披露 公告",
                "all": "公告",
            }
            keyword = category_keywords.get(category, "公告")

            query = f"{stock_name} {ts_code.split('.')[0]} {keyword} site:cninfo.com.cn OR site:szse.cn OR site:sse.com.cn"

            # 调用博查API
            api_result = await self._call_bocha_api(query, "Month", limit)

            if not api_result["success"]:
                return ToolResult(
                    success=False, error=f"搜索失败: {api_result.get('error', '未知错误')}"
                )

            # 解析结果
            announcements = self._parse_bocha_results(api_result, limit)

            # 标记类别（简化处理）
            for item in announcements:
                title = item.get("title", "")
                if "年报" in title or "季报" in title:
                    item["category"] = "report"
                elif "重大" in title:
                    item["category"] = "major"
                else:
                    item["category"] = "disclosure"

            data_source = "Mock博查服务" if self.use_mock else "博查AI开放平台"

            return ToolResult(
                success=True,
                data={
                    "ts_code": ts_code,
                    "category": category,
                    "announcements": announcements,
                    "count": len(announcements),
                    "data_source": data_source,
                },
            )

        except Exception as e:
            return ToolResult(success=False, error=f"搜索公司公告失败: {str(e)}")

    async def search_industry_news(
        self, industry: str, days: int = 7, limit: int = 10
    ) -> ToolResult:
        """
        搜索行业新闻 - 使用博查AI API

        Args:
            industry: 行业名称
            days: 搜索最近几天
            limit: 返回数量

        Returns:
            ToolResult: 搜索结果
        """
        if not industry:
            return ToolResult(success=False, error="行业名称不能为空")

        try:
            # 构建搜索查询
            query = f"{industry}行业 新闻 动态"

            # 根据days设置freshness
            if days <= 1:
                freshness = "Day"
            elif days <= 7:
                freshness = "Week"
            elif days <= 30:
                freshness = "Month"
            else:
                freshness = "Year"

            # 调用博查API
            api_result = await self._call_bocha_api(query, freshness, limit)

            if not api_result["success"]:
                return ToolResult(
                    success=False, error=f"搜索失败: {api_result.get('error', '未知错误')}"
                )

            # 解析结果
            news_list = self._parse_bocha_results(api_result, limit)

            data_source = "Mock博查服务" if self.use_mock else "博查AI开放平台"

            return ToolResult(
                success=True,
                data={
                    "industry": industry,
                    "news": news_list,
                    "count": len(news_list),
                    "search_period": f"最近{days}天",
                    "data_source": data_source,
                },
            )

        except Exception as e:
            return ToolResult(success=False, error=f"搜索行业新闻失败: {str(e)}")

    async def search_research_reports(
        self, keyword: str, report_type: str = "all", limit: int = 5
    ) -> ToolResult:
        """
        搜索研报 - 使用博查AI API

        Args:
            keyword: 搜索关键词
            report_type: 研报类型
            limit: 返回数量

        Returns:
            ToolResult: 搜索结果
        """
        if not keyword:
            return ToolResult(success=False, error="搜索关键词不能为空")

        try:
            # 根据类型构建查询
            type_keywords = {
                "rating": "研报 评级 买入 增持",
                "earnings": "研报 盈利预测 业绩",
                "industry": "研报 行业分析",
                "all": "研报 研究报告",
            }
            type_keyword = type_keywords.get(report_type, "研报")

            query = f"{keyword} {type_keyword}"

            # 调用博查API
            api_result = await self._call_bocha_api(query, "Month", limit)

            if not api_result["success"]:
                return ToolResult(
                    success=False, error=f"搜索失败: {api_result.get('error', '未知错误')}"
                )

            # 解析结果
            reports = self._parse_bocha_results(api_result, limit)

            # 尝试提取评级和目标价（从标题和摘要中）
            for item in reports:
                title = item.get("title", "")
                summary = item.get("summary", "")
                combined = title + " " + summary

                # 简单提取评级
                if "买入" in combined:
                    item["rating"] = "买入"
                elif "增持" in combined:
                    item["rating"] = "增持"
                elif "中性" in combined:
                    item["rating"] = "中性"
                elif "卖出" in combined:
                    item["rating"] = "卖出"
                else:
                    item["rating"] = "未评级"

            data_source = "Mock博查服务" if self.use_mock else "博查AI开放平台"

            return ToolResult(
                success=True,
                data={
                    "keyword": keyword,
                    "report_type": report_type,
                    "reports": reports,
                    "count": len(reports),
                    "data_source": data_source,
                },
            )

        except Exception as e:
            return ToolResult(success=False, error=f"搜索研报失败: {str(e)}")
