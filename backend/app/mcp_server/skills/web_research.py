# Copyright © 2026 深圳市深维智见教育科技有限公司 版权所有
# 未经授权，禁止转售或仿制。

"""WebResearch Skill - 网络搜索工具

提供网络信息搜索功能，获取新闻、公告、研报等外部信息。
"""

from typing import Dict, Any, Optional, List
from app.mcp_server.skills.base import BaseSkill, ToolParameter, ToolResult


class WebResearchSkill(BaseSkill):
    """
    网络搜索 Skill

    提供网络信息搜索，获取新闻、公告、研报等外部信息。
    """

    name = "web_research"
    description = "网络信息搜索，获取新闻、公告、研报等外部信息"

    def __init__(self):
        super().__init__()

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
                    required=True
                ),
                ToolParameter(
                    name="days",
                    type="integer",
                    description="搜索最近几天的新闻",
                    required=False,
                    default=7
                ),
                ToolParameter(
                    name="limit",
                    type="integer",
                    description="返回新闻数量",
                    required=False,
                    default=10
                )
            ]
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
                    required=True
                ),
                ToolParameter(
                    name="category",
                    type="string",
                    description="公告类型：all(全部), report(定期报告), major(重大事项), disclosure(信息披露)",
                    required=False,
                    default="all"
                ),
                ToolParameter(
                    name="limit",
                    type="integer",
                    description="返回公告数量",
                    required=False,
                    default=10
                )
            ]
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
                    required=True
                ),
                ToolParameter(
                    name="days",
                    type="integer",
                    description="搜索最近几天的新闻",
                    required=False,
                    default=7
                ),
                ToolParameter(
                    name="limit",
                    type="integer",
                    description="返回新闻数量",
                    required=False,
                    default=10
                )
            ]
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
                    required=True
                ),
                ToolParameter(
                    name="report_type",
                    type="string",
                    description="研报类型：all(全部), rating(评级), earnings(盈利预测), industry(行业)",
                    required=False,
                    default="all"
                ),
                ToolParameter(
                    name="limit",
                    type="integer",
                    description="返回研报数量",
                    required=False,
                    default=5
                )
            ]
        )

    async def search_stock_news(self, ts_code: str, days: int = 7, limit: int = 10) -> ToolResult:
        """搜索股票新闻"""
        if not ts_code:
            return ToolResult(success=False, error="股票代码不能为空")

        try:
            # 模拟新闻数据（实际实现需要接入新闻API）
            # 这里返回模拟数据作为示例
            mock_news = [
                {
                    "title": f"{ts_code}发布最新财报，业绩稳健增长",
                    "source": "证券时报",
                    "date": "2026-03-18",
                    "url": f"https://example.com/news/{ts_code}/1",
                    "summary": "公司发布2025年年报，营收同比增长15%，净利润增长12%..."
                },
                {
                    "title": f"{ts_code}获多家机构增持，看好长期发展",
                    "source": "中国证券报",
                    "date": "2026-03-15",
                    "url": f"https://example.com/news/{ts_code}/2",
                    "summary": "北向资金连续5日净流入，机构看好公司长期发展前景..."
                },
                {
                    "title": f"{ts_code}新品发布会成功举办",
                    "source": "新浪财经",
                    "date": "2026-03-12",
                    "url": f"https://example.com/news/{ts_code}/3",
                    "summary": "公司发布新一代产品，市场反响热烈..."
                }
            ]

            return ToolResult(success=True, data={
                "ts_code": ts_code,
                "news": mock_news[:limit],
                "count": len(mock_news[:limit]),
                "search_period": f"最近{days}天"
            })

        except Exception as e:
            return ToolResult(success=False, error=f"搜索股票新闻失败: {str(e)}")

    async def search_company_announcements(self, ts_code: str, category: str = "all", limit: int = 10) -> ToolResult:
        """搜索公司公告"""
        if not ts_code:
            return ToolResult(success=False, error="股票代码不能为空")

        try:
            # 模拟公告数据
            mock_announcements = [
                {
                    "title": "2025年年度报告",
                    "category": "report",
                    "date": "2026-03-20",
                    "url": f"https://example.com/announcement/{ts_code}/1"
                },
                {
                    "title": "关于召开2025年度股东大会的通知",
                    "category": "disclosure",
                    "date": "2026-03-18",
                    "url": f"https://example.com/announcement/{ts_code}/2"
                },
                {
                    "title": "关于重大合同的公告",
                    "category": "major",
                    "date": "2026-03-15",
                    "url": f"https://example.com/announcement/{ts_code}/3"
                },
                {
                    "title": "2025年第三季度报告",
                    "category": "report",
                    "date": "2025-10-30",
                    "url": f"https://example.com/announcement/{ts_code}/4"
                }
            ]

            # 按类别筛选
            if category != "all":
                filtered = [a for a in mock_announcements if a["category"] == category]
            else:
                filtered = mock_announcements

            return ToolResult(success=True, data={
                "ts_code": ts_code,
                "category": category,
                "announcements": filtered[:limit],
                "count": len(filtered[:limit])
            })

        except Exception as e:
            return ToolResult(success=False, error=f"搜索公司公告失败: {str(e)}")

    async def search_industry_news(self, industry: str, days: int = 7, limit: int = 10) -> ToolResult:
        """搜索行业新闻"""
        if not industry:
            return ToolResult(success=False, error="行业名称不能为空")

        try:
            # 模拟行业新闻数据
            mock_news = [
                {
                    "title": f"{industry}行业迎来政策利好",
                    "source": "经济日报",
                    "date": "2026-03-19",
                    "url": f"https://example.com/industry/{industry}/1",
                    "summary": f"国家发改委发布{industry}行业支持政策，预计将带动行业发展..."
                },
                {
                    "title": f"{industry}行业景气度持续提升",
                    "source": "财新网",
                    "date": "2026-03-16",
                    "url": f"https://example.com/industry/{industry}/2",
                    "summary": f"最新数据显示，{industry}行业景气指数连续三月上升..."
                },
                {
                    "title": f"{industry}行业龙头企业扩产",
                    "source": "21世纪经济报道",
                    "date": "2026-03-14",
                    "url": f"https://example.com/industry/{industry}/3",
                    "summary": f"多家{industry}龙头企业宣布扩产计划，行业前景看好..."
                }
            ]

            return ToolResult(success=True, data={
                "industry": industry,
                "news": mock_news[:limit],
                "count": len(mock_news[:limit]),
                "search_period": f"最近{days}天"
            })

        except Exception as e:
            return ToolResult(success=False, error=f"搜索行业新闻失败: {str(e)}")

    async def search_research_reports(self, keyword: str, report_type: str = "all", limit: int = 5) -> ToolResult:
        """搜索研报"""
        if not keyword:
            return ToolResult(success=False, error="搜索关键词不能为空")

        try:
            # 模拟研报数据
            mock_reports = [
                {
                    "title": f"{keyword}深度研究：业绩稳健，估值合理",
                    "institution": "中信证券",
                    "author": "张三",
                    "date": "2026-03-18",
                    "rating": "买入",
                    "target_price": "185.00",
                    "summary": "公司基本面稳健，盈利能力持续提升，维持买入评级..."
                },
                {
                    "title": f"{keyword}行业分析报告",
                    "institution": "国泰君安",
                    "author": "李四",
                    "date": "2026-03-15",
                    "rating": "增持",
                    "target_price": "178.00",
                    "summary": "行业景气度回升，公司作为龙头将充分受益..."
                },
                {
                    "title": f"{keyword}2025年年报点评",
                    "institution": "海通证券",
                    "author": "王五",
                    "date": "2026-03-12",
                    "rating": "买入",
                    "target_price": "190.00",
                    "summary": "业绩超预期，分红比例提升，长期价值凸显..."
                }
            ]

            return ToolResult(success=True, data={
                "keyword": keyword,
                "report_type": report_type,
                "reports": mock_reports[:limit],
                "count": len(mock_reports[:limit])
            })

        except Exception as e:
            return ToolResult(success=False, error=f"搜索研报失败: {str(e)}")
